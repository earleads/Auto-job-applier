"""
Job Scrapers — LinkedIn, Indeed, Greenhouse, Lever.

Uses Playwright for JS-heavy pages and httpx for lightweight ATS APIs.
"""

import asyncio
import hashlib
import re
from datetime import datetime, timezone
from typing import Optional

import httpx
from playwright.async_api import async_playwright, Page

from config import (
    SEARCH_QUERIES, TARGET_COMPANIES, LOCATIONS, ENABLED_SOURCES,
    REQUIRED_KEYWORDS, EXCLUDE_KEYWORDS,
)
from database import upsert_job, is_first_scrape

US_STATE_HINTS = [
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA",
    "KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ",
    "NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT",
    "VA","WA","WV","WI","WY","United States","USA","Remote",
]

NON_US_HINTS = [
    "United Kingdom","London"," UK","Canada","Toronto","India","Bengaluru",
    "Singapore","Australia","Germany","France","Netherlands","Dublin","Poland",
]

def strip_html(text: str) -> str:
    """Strip HTML tags to get plain text for keyword matching and scoring."""
    if not text:
        return ""
    clean = re.sub(r"<[^>]+>", " ", text)
    clean = re.sub(r"&[a-zA-Z]+;", " ", clean)  # &amp; &nbsp; etc.
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


def is_usa_location(location: str) -> bool:
    """True if location appears to be US-based or remote."""
    if not location:
        return True  # unknown — let Claude's scoring decide
    loc = location.strip()
    if any(h.lower() in loc.lower() for h in NON_US_HINTS):
        return False
    return True  # default allow — scraper casts wide, scorer filters


def title_matches_compliance(title: str) -> bool:
    """Fast check: does the job title look compliance-related?
    Used to skip obviously irrelevant jobs (engineers, designers, etc.)
    before even looking at the description.

    We require BOTH:
    1. A compliance-domain keyword (what the job is about)
    2. An analyst-level role keyword (seniority check) — OR the domain
       keyword IS the role (e.g. "Compliance Analyst" has both)
    """
    t = title.lower()

    # Domain keywords — what the job is about
    DOMAIN_KEYWORDS = [
        "compliance", "aml", "bsa", "kyc", "financial crimes", "fincrime",
        "sanctions", "regulatory", "regtech",
        "anti-money laundering", "anti money laundering",
        "transaction monitoring", "suspicious activity",
        "ofac", "fincen", "due diligence", "cdd", "edd",
    ]

    # Role keywords — appropriate seniority level
    ROLE_KEYWORDS = [
        "analyst", "associate", "specialist", "coordinator", "officer",
        "advisor", "examiner", "investigator", "reviewer", "manager",
    ]

    # Title patterns that should NOT match even if they contain domain keywords
    TITLE_EXCLUDES = [
        "program manager", "product manager", "engineering manager",
        "software engineer", "machine learning", "data engineer",
        "designer", "counsel", "attorney", "lawyer", "recruiter",
        "sales", "marketing", "partner development",
    ]
    if any(ex in t for ex in TITLE_EXCLUDES):
        return False

    # Broader domain keywords that are OK even without a role keyword
    # (e.g. "AML Analyst" or just "Compliance" in the title)
    has_domain = any(kw in t for kw in DOMAIN_KEYWORDS)
    has_role = any(kw in t for kw in ROLE_KEYWORDS)

    # Also accept "fraud analyst", "risk analyst" but NOT "risk ops program manager"
    COMBO_KEYWORDS = [
        "fraud analyst", "fraud investigator", "fraud specialist",
        "risk analyst", "risk associate", "risk specialist",
        "trust and safety", "trust & safety",
    ]
    has_combo = any(kw in t for kw in COMBO_KEYWORDS)

    # Require domain + role, or a specific combo keyword
    # domain alone is not enough (e.g. "Product Manager, Compliance Platform" is not a compliance role)
    return (has_domain and has_role) or has_combo


def passes_keyword_filter(job: dict) -> bool:
    """
    Quick pre-filter before spending Claude tokens.
    The job TITLE must contain a compliance keyword — we don't match on
    description alone because every fintech's boilerplate mentions
    "compliance" / "risk" / "regulatory" regardless of the actual role.
    """
    title = job.get("title", "")
    if not title_matches_compliance(title):
        return False
    # Also reject titles that match exclude patterns (too senior, wrong industry)
    text = f"{title} {strip_html(job.get('description', ''))}".lower()
    is_excluded = any(kw.lower() in text for kw in EXCLUDE_KEYWORDS)
    return not is_excluded


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:12]


def detect_ats(url: str) -> Optional[str]:
    if "greenhouse.io" in url or "grnh.se" in url:
        return "greenhouse"
    if "lever.co" in url:
        return "lever"
    if "linkedin.com" in url:
        return "linkedin"
    if "workday" in url:
        return "workday"
    return "other"


# ── LinkedIn Scraper ───────────────────────────────────────────────────────────

async def scrape_linkedin(page: Page, query: str, location: str, first_run: bool = False) -> list[dict]:
    jobs = []
    # First run: search last 7 days; subsequent runs: last 24 hours
    time_filter = "r604800" if first_run else "r86400"
    url = (
        f"https://www.linkedin.com/jobs/search/?keywords={query.replace(' ', '%20')}"
        f"&location={location.replace(' ', '%20')}&f_TPR={time_filter}&sortBy=DD"
    )
    print(f"  🔍 LinkedIn: '{query}' in {location}")
    await page.goto(url, timeout=30000)
    await page.wait_for_timeout(3000)

    # Scroll to load more jobs
    for _ in range(3):
        await page.keyboard.press("End")
        await page.wait_for_timeout(1500)

    cards = await page.query_selector_all(".job-search-card")
    for card in cards[:25]:
        try:
            title_el = await card.query_selector(".base-search-card__title")
            company_el = await card.query_selector(".base-search-card__subtitle")
            location_el = await card.query_selector(".job-search-card__location")
            link_el = await card.query_selector("a.base-card__full-link")

            title = (await title_el.inner_text()).strip() if title_el else ""
            company = (await company_el.inner_text()).strip() if company_el else ""
            loc = (await location_el.inner_text()).strip() if location_el else ""
            job_url = await link_el.get_attribute("href") if link_el else ""

            if not job_url:
                continue

            # Clean LinkedIn tracking params
            job_url = job_url.split("?")[0]

            job = {
                "id": make_id(job_url),
                "title": title,
                "company": company,
                "location": loc,
                "url": job_url,
                "description": "",   # fetched separately
                "source": "linkedin",
                "posted_at": datetime.now(timezone.utc).isoformat(),
                "ats_type": "linkedin",
            }
            jobs.append(job)
        except Exception as e:
            print(f"    ⚠️  Card parse error: {e}")

    return jobs


async def fetch_linkedin_job_details(page: Page, job: dict) -> dict:
    """
    Fetch full JD from LinkedIn job page AND extract external apply URL.
    Updates the job dict in place with description, and if an external apply
    link is found, updates url and ats_type to route to the real ATS.
    """
    try:
        await page.goto(job["url"], timeout=20000)
        await page.wait_for_timeout(2000)

        # Try to expand "Show more"
        see_more = await page.query_selector("button.show-more-less-html__button")
        if see_more:
            await see_more.click()
            await page.wait_for_timeout(500)

        desc_el = await page.query_selector(".description__text")
        if desc_el:
            job["description"] = (await desc_el.inner_text()).strip()

        # Look for external apply link (not Easy Apply)
        # LinkedIn shows "Apply" button that links to the company's ATS
        apply_link = await page.query_selector(
            "a.apply-button[href*='greenhouse'], "
            "a.apply-button[href*='lever.co'], "
            "a[href*='boards.greenhouse.io'], "
            "a[href*='jobs.lever.co'], "
            "a.apply-button--offsite, "
            ".apply-button--offsite a, "
            "a[data-tracking-control-name='public_jobs_apply-link-offsite']"
        )
        if apply_link:
            external_url = await apply_link.get_attribute("href")
            if external_url:
                external_url = external_url.split("?")[0] if "linkedin.com" not in external_url else external_url
                ats_type = detect_ats(external_url)
                if ats_type in ("greenhouse", "lever"):
                    print(f"    🔗 External apply link found: {ats_type}")
                    job["apply_url"] = external_url
                    job["ats_type"] = ats_type

    except Exception as e:
        print(f"    ⚠️  Job detail fetch failed: {e}")

    return job


# ── Indeed Scraper ─────────────────────────────────────────────────────────────

async def scrape_indeed(page: Page, query: str, location: str, first_run: bool = False) -> list[dict]:
    jobs = []
    # First run: search last 7 days; subsequent runs: last 24 hours
    days = 7 if first_run else 1
    url = f"https://www.indeed.com/jobs?q={query.replace(' ', '+')}&l={location.replace(' ', '+')}&fromage={days}&sort=date"
    print(f"  🔍 Indeed: '{query}' in {location}")

    try:
        await page.goto(url, timeout=30000)
        await page.wait_for_timeout(3000)

        cards = await page.query_selector_all("[data-testid='slider_item']")
        for card in cards[:20]:
            try:
                title_el = await card.query_selector("[data-testid='jobTitle']")
                company_el = await card.query_selector("[data-testid='company-name']")
                location_el = await card.query_selector("[data-testid='text-location']")
                link_el = await card.query_selector("a[data-testid='job-title-link']")

                title = (await title_el.inner_text()).strip() if title_el else ""
                company = (await company_el.inner_text()).strip() if company_el else ""
                loc = (await location_el.inner_text()).strip() if location_el else ""
                href = await link_el.get_attribute("href") if link_el else ""

                if not href:
                    continue
                job_url = f"https://www.indeed.com{href}" if href.startswith("/") else href

                jobs.append({
                    "id": make_id(job_url),
                    "title": title,
                    "company": company,
                    "location": loc,
                    "url": job_url,
                    "description": "",
                    "source": "indeed",
                    "posted_at": datetime.now(timezone.utc).isoformat(),
                    "ats_type": "other",
                })
            except Exception as e:
                print(f"    ⚠️  Indeed card error: {e}")
    except Exception as e:
        print(f"  ❌ Indeed scrape failed: {e}")

    return jobs


# ── Greenhouse ATS ─────────────────────────────────────────────────────────────

async def scrape_greenhouse(company_slug: str) -> list[dict]:
    """Fetch compliance-related roles from Greenhouse API (no auth needed).
    Filters by title first so we only process relevant jobs."""
    jobs = []
    url = f"https://boards-api.greenhouse.io/v1/boards/{company_slug}/jobs?content=true"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(url)
            if r.status_code == 200:
                data = r.json()
                total = len(data.get("jobs", []))
                matched = 0
                for j in data.get("jobs", []):
                    title = j.get("title", "")
                    # Skip jobs whose titles are clearly not compliance-related
                    if not title_matches_compliance(title):
                        continue
                    matched += 1
                    job_id = j.get("id", "")
                    job_url = j.get("absolute_url", "")
                    if not job_url and job_id:
                        # Construct URL from slug + job ID as fallback
                        job_url = f"https://boards.greenhouse.io/{company_slug}/jobs/{job_id}"
                    if not job_url:
                        print(f"    ⚠️  Skipping '{title}' — no URL available")
                        continue
                    raw_content = j.get("content", "")
                    jobs.append({
                        "id": make_id(job_url),
                        "title": title,
                        "company": company_slug.replace("-", " ").title(),
                        "location": ", ".join([l["name"] for l in j.get("offices", [])]),
                        "url": job_url,
                        "description": raw_content,
                        "description_text": strip_html(raw_content),
                        "source": "greenhouse",
                        "posted_at": j.get("updated_at", datetime.now(timezone.utc).isoformat()),
                        "ats_type": "greenhouse",
                    })
                print(f"  📋 Greenhouse {company_slug}: {matched} compliance roles / {total} total")
            elif r.status_code == 404:
                pass  # Board doesn't exist or slug is wrong — silent
            else:
                print(f"  ⚠️  Greenhouse {company_slug}: HTTP {r.status_code}")
    except Exception as e:
        print(f"  ⚠️  Greenhouse {company_slug} error: {e}")
    return jobs


# ── Lever ATS ──────────────────────────────────────────────────────────────────

async def scrape_lever(company_slug: str) -> list[dict]:
    """Fetch compliance-related roles from Lever API.
    Filters by title first so we only process relevant jobs."""
    jobs = []
    url = f"https://api.lever.co/v0/postings/{company_slug}?mode=json"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(url)
            if r.status_code == 200:
                all_jobs = r.json()
                total = len(all_jobs)
                matched = 0
                for j in all_jobs:
                    title = j.get("text", "")
                    # Skip jobs whose titles are clearly not compliance-related
                    if not title_matches_compliance(title):
                        continue
                    matched += 1
                    job_url = j.get("hostedUrl", "")
                    if not job_url:
                        continue  # Skip jobs with no apply URL
                    desc_parts = [
                        j.get("description", ""),
                        *[l.get("content", "") for l in j.get("lists", [])],
                        j.get("additional", ""),
                    ]
                    raw_desc = "\n".join(filter(None, desc_parts))
                    jobs.append({
                        "id": make_id(job_url),
                        "title": title,
                        "company": company_slug.replace("-", " ").title(),
                        "location": j.get("categories", {}).get("location", ""),
                        "url": job_url,
                        "description": raw_desc,
                        "description_text": strip_html(raw_desc),
                        "source": "lever",
                        "posted_at": datetime.fromtimestamp(
                            j.get("createdAt", 0) / 1000
                        ).isoformat(),
                        "ats_type": "lever",
                    })
                print(f"  📋 Lever {company_slug}: {matched} compliance roles / {total} total")
            elif r.status_code == 404:
                pass  # Board doesn't exist
            else:
                print(f"  ⚠️  Lever {company_slug}: HTTP {r.status_code}")
    except Exception as e:
        print(f"  ⚠️  Lever {company_slug} error: {e}")
    return jobs


# ── Company slug maps ──────────────────────────────────────────────────────────

# Map company name → (ats, slug)
# Add your target companies here
COMPANY_ATS_MAP = {
    # Greenhouse companies
    "Stripe":           ("greenhouse", "stripe"),
    "Plaid":            ("greenhouse", "plaid"),
    "Chime":            ("greenhouse", "chime"),
    "Marqeta":          ("greenhouse", "marqeta"),
    "Brex":             ("greenhouse", "brex"),
    "Ramp":             ("greenhouse", "ramp"),
    "Coinbase":         ("greenhouse", "coinbase"),
    "Affirm":           ("greenhouse", "affirm"),
    "Robinhood":        ("greenhouse", "robinhood"),
    "SoFi":             ("greenhouse", "sofi"),
    "Blend":            ("greenhouse", "blend"),
    "Current":          ("greenhouse", "current"),
    "Alloy":            ("greenhouse", "alloy"),
    "Unit21":           ("greenhouse", "unit21"),
    "Socure":           ("greenhouse", "socure"),
    "Circle":           ("greenhouse", "circle"),
    "Paxos":            ("greenhouse", "paxos"),
    "Fireblocks":       ("greenhouse", "fireblocks"),
    "Chainalysis":      ("greenhouse", "chainalysis"),
    "Persona":          ("greenhouse", "persona"),
    "Middesk":          ("greenhouse", "middesk"),
    "Upstart":          ("greenhouse", "upstart"),
    "Figure":           ("greenhouse", "figure"),
    "Melio":            ("greenhouse", "melio"),
    "Column":           ("greenhouse", "column"),
    "Modern Treasury":  ("greenhouse", "moderntreasury"),
    "Lithic":           ("greenhouse", "lithic"),
    "Highnote":         ("greenhouse", "highnote"),
    "Orum":             ("greenhouse", "orum"),
    "MoneyLion":        ("greenhouse", "moneylion"),
    "Greenlight":       ("greenhouse", "greenlight"),
    # Lever companies
    "Sardine":          ("lever", "sardine"),
    "Anchorage Digital":("lever", "anchorage-digital"),
    "BitGo":            ("lever", "bitgo"),
    "Gemini":           ("lever", "gemini"),
    "Hummingbird":      ("lever", "hummingbird"),
    "Treasury Prime":   ("lever", "treasuryprime"),
    "Synctera":         ("lever", "synctera"),
    "Increase":         ("lever", "increase"),
    "ComplyAdvantage":  ("lever", "complyadvantage"),
    "Onfido":           ("lever", "onfido"),
}


# ── Main scraper orchestrator ──────────────────────────────────────────────────

async def run_scrapers(test_mode: bool = False) -> tuple[int, dict[str, int]]:
    """Run all enabled scrapers. Returns (total_new, {source: count}).

    When test_mode=True, only scrapes 3 ATS companies and 2 LinkedIn queries
    in 1 location for a fast end-to-end validation (~2-5 minutes).
    """
    new_jobs = 0
    source_counts = {"greenhouse": 0, "lever": 0, "linkedin": 0, "indeed": 0}

    first_run = is_first_scrape()
    if first_run:
        print("\n📅 First run detected — searching last 7 days of job posts")

    companies = TARGET_COMPANIES
    if test_mode:
        # Pick first 3 companies that have ATS mappings for a quick check
        companies = [c for c in TARGET_COMPANIES if c in COMPANY_ATS_MAP][:3]
        print(f"\n🧪 TEST MODE: scraping only {len(companies)} ATS companies: {companies}")

    # 1. Direct ATS scrapes (no browser needed — most reliable)
    print("\n📡 Scraping company ATS pages...")
    for company in companies:
        if company in COMPANY_ATS_MAP:
            ats, slug = COMPANY_ATS_MAP[company]
            if ats == "greenhouse" and ENABLED_SOURCES.get("greenhouse"):
                jobs = await scrape_greenhouse(slug)
            elif ats == "lever" and ENABLED_SOURCES.get("lever"):
                jobs = await scrape_lever(slug)
            else:
                continue

            for job in jobs:
                if not is_usa_location(job.get("location", "")):
                    continue
                if not passes_keyword_filter(job):
                    continue
                # Store clean text description for scoring
                if "description_text" in job:
                    job["description"] = job.pop("description_text")
                if upsert_job(job):
                    new_jobs += 1
                    source_counts[ats] += 1
                    print(f"  ✅ NEW: {job['title']} @ {job['company']}")

    # 2. LinkedIn + Indeed (browser-based)
    if ENABLED_SOURCES.get("linkedin") or ENABLED_SOURCES.get("indeed"):
        if test_mode:
            print("\n🧪 TEST MODE: skipping browser scraping (LinkedIn/Indeed) for speed")
            print("   Use ATS results above to validate the pipeline.")
        else:
            print("\n🌐 Launching browser for job boards...")
        if not test_mode:
            try:
                async with async_playwright() as p:
                    browser = await p.chromium.launch(
                        headless=True,
                        args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
                    )
                    context = await browser.new_context(
                        user_agent=(
                            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/120.0.0.0 Safari/537.36"
                        ),
                        viewport={"width": 1280, "height": 800},
                    )
                    page = await context.new_page()

                    for query in SEARCH_QUERIES:
                        for location in LOCATIONS:
                            if ENABLED_SOURCES.get("linkedin"):
                                try:
                                    jobs = await scrape_linkedin(page, query, location, first_run=first_run)
                                    for job in jobs:
                                        job = await fetch_linkedin_job_details(page, job)
                                        if upsert_job(job):
                                            new_jobs += 1
                                            source_counts["linkedin"] += 1
                                            print(f"  ✅ NEW: {job['title']} @ {job['company']}")
                                        await asyncio.sleep(1)
                                except Exception as e:
                                    print(f"  ❌ LinkedIn scrape failed for '{query}' in {location}: {e}")

                            if ENABLED_SOURCES.get("indeed"):
                                try:
                                    jobs = await scrape_indeed(page, query, location, first_run=first_run)
                                    for job in jobs:
                                        if upsert_job(job):
                                            new_jobs += 1
                                            source_counts["indeed"] += 1
                                except Exception as e:
                                    print(f"  ❌ Indeed scrape failed for '{query}' in {location}: {e}")

                            await asyncio.sleep(2)

                    await browser.close()
            except Exception as e:
                print(f"  ❌ Browser launch failed: {e}")

    print(f"\n🎯 Scraping complete — {new_jobs} new jobs found")
    return new_jobs, source_counts
