"""
Auto-Applier — Playwright-based form submission for multiple ATS platforms.

Supports:
  - LinkedIn Easy Apply
  - Greenhouse (boards.greenhouse.io)
  - Lever (jobs.lever.co)
"""

import asyncio
import os
from pathlib import Path

from playwright.async_api import async_playwright, Page, Browser

from config import CANDIDATE_PROFILE, ANTHROPIC_API_KEY
import anthropic

# Extract contact info from profile for form filling
_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def extract_profile_field(field: str) -> str:
    """Use simple string parsing to pull fields from CANDIDATE_PROFILE."""
    lines = CANDIDATE_PROFILE.strip().split("\n")
    for line in lines:
        if line.lower().startswith(field.lower()):
            return line.split(":", 1)[-1].strip().strip("[]")
    return ""


APPLICANT = {
    "name":       extract_profile_field("Name"),
    "email":      extract_profile_field("Email"),
    "phone":      extract_profile_field("Phone"),
    "linkedin":   extract_profile_field("LinkedIn"),
    "location":   extract_profile_field("Location"),
    "first_name": extract_profile_field("Name").split()[0] if extract_profile_field("Name") else "",
    "last_name":  " ".join(extract_profile_field("Name").split()[1:]) if extract_profile_field("Name") else "",
}


# ── AI Form Field Resolver ─────────────────────────────────────────────────────

async def ai_fill_field(label: str, options: list[str] = None) -> str:
    """
    Ask Claude what to answer for an unusual form field.
    Used for custom questions like "Why do you want to work here?"
    """
    prompt = f"""You are filling out a job application form on behalf of this candidate:

{CANDIDATE_PROFILE}

Form field label: "{label}"
{f'Options: {options}' if options else ''}

Provide the best answer for this field. Be concise and genuine.
If it's a dropdown/multiple choice, return exactly one of the provided options.
Otherwise return a short text answer (under 100 words).
Output ONLY the answer, nothing else.
"""
    response = _client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=150,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text.strip()


# ── Generic helpers ────────────────────────────────────────────────────────────

async def safe_fill(page: Page, selector: str, value: str, timeout: int = 3000):
    try:
        el = await page.wait_for_selector(selector, timeout=timeout)
        await el.fill(value)
        return True
    except Exception:
        return False


async def safe_click(page: Page, selector: str, timeout: int = 3000):
    try:
        el = await page.wait_for_selector(selector, timeout=timeout)
        await el.click()
        return True
    except Exception:
        return False


async def upload_file(page: Page, selector: str, file_path: str):
    try:
        el = await page.wait_for_selector(selector, timeout=5000)
        await el.set_input_files(file_path)
        return True
    except Exception as e:
        print(f"    ⚠️  File upload failed: {e}")
        return False


# ── Greenhouse Applier ─────────────────────────────────────────────────────────

async def apply_greenhouse(page: Page, job: dict, cv_path: str, cover_letter_path: str) -> bool:
    """
    Apply via Greenhouse embedded application form.
    """
    print(f"  🌿 Greenhouse apply: {job['url']}")
    try:
        await page.goto(job["url"], timeout=30000)
        await page.wait_for_timeout(2000)

        # Standard Greenhouse fields
        await safe_fill(page, "#first_name", APPLICANT["first_name"])
        await safe_fill(page, "#last_name", APPLICANT["last_name"])
        await safe_fill(page, "#email", APPLICANT["email"])
        await safe_fill(page, "#phone", APPLICANT["phone"])

        # LinkedIn URL (optional)
        await safe_fill(page, "input[name*='linkedin']", APPLICANT["linkedin"])

        # Resume upload
        await upload_file(page, "input[type='file'][name*='resume']", cv_path)
        await page.wait_for_timeout(1000)

        # Cover letter upload (if field exists)
        cl_input = await page.query_selector("input[type='file'][name*='cover']")
        if cl_input:
            await cl_input.set_input_files(cover_letter_path)

        # Handle custom questions
        custom_fields = await page.query_selector_all(".field")
        for field in custom_fields:
            label_el = await field.query_selector("label")
            label = (await label_el.inner_text()).strip() if label_el else ""

            # Skip already-filled standard fields
            if any(kw in label.lower() for kw in ["name", "email", "phone", "resume", "cover"]):
                continue

            # Dropdowns
            select_el = await field.query_selector("select")
            if select_el:
                options = await select_el.inner_text()
                option_list = [o.strip() for o in options.split("\n") if o.strip()]
                answer = await ai_fill_field(label, option_list)
                await select_el.select_option(label=answer)
                continue

            # Text areas / inputs
            input_el = await field.query_selector("textarea, input[type='text']")
            if input_el:
                answer = await ai_fill_field(label)
                await input_el.fill(answer)

        # Submit
        await safe_click(page, "#submit_app, button[type='submit']")
        await page.wait_for_timeout(3000)

        # Check for success
        content = await page.content()
        if any(kw in content.lower() for kw in ["thank you", "submitted", "application received"]):
            print(f"  ✅ Greenhouse application submitted!")
            return True
        else:
            print(f"  ⚠️  Submit confirmation unclear — check manually")
            return False

    except Exception as e:
        print(f"  ❌ Greenhouse apply failed: {e}")
        return False


# ── Lever Applier ──────────────────────────────────────────────────────────────

async def apply_lever(page: Page, job: dict, cv_path: str, cover_letter_path: str) -> bool:
    """Apply via Lever job posting page."""
    print(f"  🔧 Lever apply: {job['url']}")
    try:
        await page.goto(job["url"], timeout=30000)
        await page.wait_for_timeout(2000)

        # Click Apply button
        await safe_click(page, "a[href*='/apply'], .postings-btn")
        await page.wait_for_timeout(2000)

        # Fill fields
        await safe_fill(page, "input[name='name']", APPLICANT["name"])
        await safe_fill(page, "input[name='email']", APPLICANT["email"])
        await safe_fill(page, "input[name='phone']", APPLICANT["phone"])
        await safe_fill(page, "input[name='org']", "")  # Current company (optional)
        await safe_fill(page, "input[name*='linkedin']", APPLICANT["linkedin"])

        # Resume upload
        await upload_file(page, "input[type='file']", cv_path)
        await page.wait_for_timeout(1500)

        # Cover letter textarea (if present)
        cl_area = await page.query_selector("textarea[name*='cover'], textarea[placeholder*='cover']")
        if cl_area:
            with open(cover_letter_path) as f:
                cl_text = f.read()
            await cl_area.fill(cl_text)

        # Custom questions
        custom_inputs = await page.query_selector_all(".application-field")
        for field in custom_inputs:
            label_el = await field.query_selector("label")
            label = (await label_el.inner_text()).strip() if label_el else ""
            input_el = await field.query_selector("input[type='text'], textarea")
            if input_el and label:
                answer = await ai_fill_field(label)
                await input_el.fill(answer)

        # Submit
        await safe_click(page, "button[type='submit'], input[type='submit']")
        await page.wait_for_timeout(3000)

        content = await page.content()
        if any(kw in content.lower() for kw in ["thank you", "application received", "successfully"]):
            print(f"  ✅ Lever application submitted!")
            return True
        return False

    except Exception as e:
        print(f"  ❌ Lever apply failed: {e}")
        return False


# ── LinkedIn Easy Apply ────────────────────────────────────────────────────────

async def apply_linkedin(page: Page, job: dict, cv_path: str, cover_letter_path: str) -> bool:
    """
    Handle LinkedIn Easy Apply modal.
    NOTE: Requires being logged into LinkedIn via saved session.
    See README for session setup instructions.
    """
    print(f"  💼 LinkedIn Easy Apply: {job['url']}")
    try:
        await page.goto(job["url"], timeout=30000)
        await page.wait_for_timeout(3000)

        # Click Easy Apply button
        easy_apply_btn = await page.query_selector(
            "button.jobs-apply-button, .jobs-s-apply button"
        )
        if not easy_apply_btn:
            print("  ⏭️  No Easy Apply button — external application")
            return False

        await easy_apply_btn.click()
        await page.wait_for_timeout(2000)

        # Multi-step modal — iterate through pages
        max_steps = 8
        for step in range(max_steps):
            print(f"    Step {step + 1}...")

            # Upload resume if prompted
            file_input = await page.query_selector("input[type='file']")
            if file_input:
                await file_input.set_input_files(cv_path)
                await page.wait_for_timeout(1000)

            # Fill any visible text inputs using labels
            form_items = await page.query_selector_all(
                ".jobs-easy-apply-form-element, .fb-dash-form-element"
            )
            for item in form_items:
                label_el = await item.query_selector("label, span.visually-hidden")
                label = (await label_el.inner_text()).strip() if label_el else ""

                # Radio / Yes-No
                radios = await item.query_selector_all("input[type='radio']")
                if radios and label:
                    answer = await ai_fill_field(label, ["Yes", "No"])
                    for radio in radios:
                        val = await radio.get_attribute("value") or ""
                        if val.lower() == answer.lower():
                            await radio.click()
                            break
                    continue

                # Text / number inputs
                input_el = await item.query_selector("input[type='text'], input[type='number'], textarea")
                if input_el and label:
                    current = await input_el.input_value()
                    if not current:
                        answer = await ai_fill_field(label)
                        await input_el.fill(answer)

                # Dropdowns
                select_el = await item.query_selector("select")
                if select_el and label:
                    opts = await select_el.inner_text()
                    opt_list = [o.strip() for o in opts.split("\n") if o.strip()]
                    answer = await ai_fill_field(label, opt_list)
                    try:
                        await select_el.select_option(label=answer)
                    except Exception:
                        pass

            # Check buttons
            next_btn = await page.query_selector("button[aria-label='Continue to next step']")
            review_btn = await page.query_selector("button[aria-label='Review your application']")
            submit_btn = await page.query_selector("button[aria-label='Submit application']")

            if submit_btn:
                await submit_btn.click()
                await page.wait_for_timeout(2000)
                print(f"  ✅ LinkedIn Easy Apply submitted!")
                return True
            elif review_btn:
                await review_btn.click()
            elif next_btn:
                await next_btn.click()
            else:
                print(f"  ⚠️  No navigation button found at step {step + 1}")
                break

            await page.wait_for_timeout(1500)

        return False

    except Exception as e:
        print(f"  ❌ LinkedIn apply failed: {e}")
        return False


# ── Router ─────────────────────────────────────────────────────────────────────

async def apply_to_job(job: dict, cv_path: str, cover_letter_path: str, browser: Browser) -> bool:
    """Route application to correct ATS handler."""
    context = await browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
        )
    )

    # Load LinkedIn session cookies if available
    if job["ats_type"] == "linkedin":
        import json
        li_at = os.environ.get("LINKEDIN_LI_AT")
        cookies_path = "data/linkedin_cookies.json"
        if li_at:
            from save_linkedin_session import build_linkedin_cookies
            await context.add_cookies(build_linkedin_cookies(li_at))
        elif Path(cookies_path).exists():
            with open(cookies_path) as f:
                cookies = json.load(f)
            await context.add_cookies(cookies)

    page = await context.new_page()
    ats = job.get("ats_type", "other")

    try:
        if ats == "greenhouse":
            success = await apply_greenhouse(page, job, cv_path, cover_letter_path)
        elif ats == "lever":
            success = await apply_lever(page, job, cv_path, cover_letter_path)
        elif ats == "linkedin":
            success = await apply_linkedin(page, job, cv_path, cover_letter_path)
        else:
            print(f"  ⏭️  Unknown ATS type '{ats}' — skipping auto-apply")
            success = False
    finally:
        await context.close()

    return success


async def run_applications(jobs_with_docs: list[dict]) -> list[bool]:
    """
    Apply to all qualified jobs. Returns list of success/failure per job.
    """
    if not jobs_with_docs:
        return []

    results = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox"]
        )
        for item in jobs_with_docs:
            success = await apply_to_job(
                item["job"],
                item["cv_path"],
                item["cover_letter_path"],
                browser
            )
            results.append(success)
            await asyncio.sleep(5)  # Rate limiting between applications

        await browser.close()

    return results
