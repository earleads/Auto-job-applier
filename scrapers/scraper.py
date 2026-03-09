"""
Job Scrapers — LinkedIn, Indeed, Greenhouse, Lever.

Uses Playwright for JS-heavy pages and httpx for lightweight ATS APIs.
"""

import asyncio
import hashlib
import re
from datetime import datetime
from typing import Optional

import httpx
from playwright.async_api import async_playwright, Page

from config import (
    SEARCH_QUERIES, TARGET_COMPANIES, LOCATIONS, ENABLED_SOURCES,
    REQUIRED_KEYWORDS, EXCLUDE_KEYWORDS,
)
from database import upsert_job

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

def is_usa_location(location: str) -> bool:
    """True if location appears to be US-based or remote."""
    if not location:
        return True  # unknown — let Claude's scoring decide
    loc = location.strip()
    if any(h.lower() in loc.lower() for h in NON_US_HINTS):
        return False
    return True  # default allow — scraper casts wide, scorer filters


def passes_keyword_filter(job: dict) -> bool:
    """
    Quick pre-filter before spending Claude tokens:
    - Must contain at least one REQUIRED keyword in title or description
    - Must not match EXCLUDE keywords
    """
    text = f"{job.get('title', '')} {job.get('description', '')}".lower()
    has_required = any(kw.lower() in text for kw in REQUIRED_KEYWORDS)
    if not has_required:
        return False
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

async def scrape_linkedin(page: Page, query: str, location: str) -> list[dict]:
    jobs = []
    url = (
        f"https://www.linkedin.com/jobs/search/?keywords={query.replace(' ', '%20')}"
        f"&location={location.replace(' ', '%20')}&f_TPR=r86400&sortBy=DD"
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
                "posted_at": datetime.utcnow().isoformat(),
                "ats_type": "linkedin",
            }
            jobs.append(job)
        except Exception as e:
            print(f"    ⚠️  Card parse error: {e}")

    return jobs


async def fetch_linkedin_description(page: Page, job: dict) -> str:
    """Fetch full JD from LinkedIn job page."""
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
            return (await desc_el.inner_text()).strip()
    except Exception as e:
        print(f"    ⚠️  Description fetch failed: {e}")
    return ""


# ── Indeed Scraper ─────────────────────────────────────────────────────────────

async def scrape_indeed(page: Page, query: str, location: str) -> list[dict]:
    jobs = []
    url = f"https://www.indeed.com/jobs?q={query.replace(' ', '+')}&l={location.replace(' ', '+')}&fromage=1&sort=date"
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
                    "posted_at": datetime.utcnow().isoformat(),
                    "ats_type": "other",
                })
            except Exception as e:
                print(f"    ⚠️  Indeed card error: {e}")
    except Exception as e:
        print(f"  ❌ Indeed scrape failed: {e}")

    return jobs


# ── Greenhouse ATS ─────────────────────────────────────────────────────────────

async def scrape_greenhouse(company_slug: str) -> list[dict]:
    """Fetch all open roles from Greenhouse API (no auth needed)."""
    jobs = []
    url = f"https://boards-api.greenhouse.io/v1/boards/{company_slug}/jobs?content=true"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(url)
            if r.status_code == 200:
                data = r.json()
                for j in data.get("jobs", []):
                    job_url = j.get("absolute_url", "")
                    jobs.append({
                        "id": make_id(job_url),
                        "title": j.get("title", ""),
                        "company": company_slug.replace("-", " ").title(),
                        "location": ", ".join([l["name"] for l in j.get("offices", [])]),
                        "url": job_url,
                        "description": j.get("content", ""),
                        "source": "greenhouse",
                        "posted_at": j.get("updated_at", datetime.utcnow().isoformat()),
                        "ats_type": "greenhouse",
                    })
    except Exception as e:
        print(f"  ⚠️  Greenhouse {company_slug} error: {e}")
    return jobs


# ── Lever ATS ──────────────────────────────────────────────────────────────────

async def scrape_lever(company_slug: str) -> list[dict]:
    """Fetch all open roles from Lever API."""
    jobs = []
    url = f"https://api.lever.co/v0/postings/{company_slug}?mode=json"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(url)
            if r.status_code == 200:
                for j in r.json():
                    job_url = j.get("hostedUrl", "")
                    desc_parts = [
                        j.get("description", ""),
                        *[l.get("content", "") for l in j.get("lists", [])],
                        j.get("additional", ""),
                    ]
                    jobs.append({
                        "id": make_id(job_url),
                        "title": j.get("text", ""),
                        "company": company_slug.replace("-", " ").title(),
                        "location": j.get("categories", {}).get("location", ""),
                        "url": job_url,
                        "description": "\n".join(filter(None, desc_parts)),
                        "source": "lever",
                        "posted_at": datetime.fromtimestamp(
                            j.get("createdAt", 0) / 1000
                        ).isoformat(),
                        "ats_type": "lever",
                    })
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

async def run_scrapers() -> tuple[int, dict[str, int]]:
    """Run all enabled scrapers. Returns (total_new, {source: count})."""
    new_jobs = 0
    source_counts = {"greenhouse": 0, "lever": 0, "linkedin": 0, "indeed": 0}

    # 1. Direct ATS scrapes (no browser needed — most reliable)
    print("\n📡 Scraping company ATS pages...")
    for company in TARGET_COMPANIES:
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
                if upsert_job(job):
                    new_jobs += 1
                    source_counts[ats] += 1
                    print(f"  ✅ NEW: {job['title']} @ {job['company']}")

    # 2. LinkedIn + Indeed (browser-based)
    if ENABLED_SOURCES.get("linkedin") or ENABLED_SOURCES.get("indeed"):
        print("\n🌐 Launching browser for job boards...")
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
                                jobs = await scrape_linkedin(page, query, location)
                                for job in jobs[:5]:
                                    job["description"] = await fetch_linkedin_description(page, job)
                                    if upsert_job(job):
                                        new_jobs += 1
                                        source_counts["linkedin"] += 1
                                        print(f"  ✅ NEW: {job['title']} @ {job['company']}")
                            except Exception as e:
                                print(f"  ❌ LinkedIn scrape failed for '{query}' in {location}: {e}")

                        if ENABLED_SOURCES.get("indeed"):
                            try:
                                jobs = await scrape_indeed(page, query, location)
                                for job in jobs:
                                    if upsert_job(job):
                                        new_jobs += 1
                                        source_counts["indeed"] += 1
                            except Exception as e:
                                print(f"  ❌ Indeed scrape failed for '{query}' in {location}: {e}")

                        await asyncio.sleep(2)  # Be polite

                await browser.close()
        except Exception as e:
            print(f"  ❌ Browser launch failed: {e}")

    print(f"\n🎯 Scraping complete — {new_jobs} new jobs found")
    return new_jobs, source_counts
