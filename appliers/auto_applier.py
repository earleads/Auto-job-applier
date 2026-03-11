"""
Auto-Applier — Patchright-based form submission for multiple ATS platforms.

Supports:
  - LinkedIn Easy Apply
  - Greenhouse (boards.greenhouse.io) — with free AI CAPTCHA solving
  - Lever (jobs.lever.co) — with free AI CAPTCHA solving

Uses Patchright (stealth Playwright fork) for anti-detection browsing and
the recognizer library (YOLO + CLIP) for free reCAPTCHA solving.
No paid API keys required.
"""

import asyncio
import os
from pathlib import Path

from patchright.async_api import async_playwright, Page

from config import CANDIDATE_PROFILE, ANTHROPIC_API_KEY
import anthropic
from appliers.captcha_solver import detect_and_solve, is_configured as captcha_configured

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

async def ai_fill_field(label: str, options: list[str] = None) -> str | None:
    """
    Ask Claude what to answer for an unusual form field.
    Used for custom questions like "Why do you want to work here?"
    Returns None if the field should be skipped.
    """
    prompt = f"""You are filling out a job application form on behalf of this candidate:

{CANDIDATE_PROFILE}

Form field label: "{label}"
{f'Options: {options}' if options else ''}

Provide the best answer for this field. Be concise and genuine.
If it's a dropdown/multiple choice, return exactly one of the provided options.
Otherwise return a short text answer (under 100 words).

IMPORTANT: If you cannot answer because the field asks for something you don't have
(security codes, CAPTCHAs, verification codes, SSN, passwords, salary expectations
with no basis, etc.), respond with exactly: SKIP

Output ONLY the answer (or SKIP), nothing else.
"""
    response = _client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=150,
        messages=[{"role": "user", "content": prompt}]
    )
    answer = response.content[0].text.strip()

    # Detect refusals — Claude sometimes ignores SKIP and writes a paragraph
    REFUSAL_PHRASES = [
        "i cannot", "i can't", "i'm unable", "not available",
        "not included", "not provided", "don't have", "do not have",
        "cannot provide", "would typically be",
    ]
    answer_lower = answer.lower()
    is_refusal = any(phrase in answer_lower for phrase in REFUSAL_PHRASES)

    if answer == "SKIP" or is_refusal or len(answer) > 200:
        print(f"    ⏭️  AI declined field: {label[:50]}")
        return None
    return answer


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


async def greenhouse_upload_file(page: Page, field_name: str, file_path: str) -> bool:
    """Upload a file to Greenhouse's JS-based upload widget.

    Greenhouse forms don't use standard <input type='file'> in the HTML.
    Instead, clicking the 'Attach' button creates one dynamically via JS.
    We trigger the click, wait for the hidden input, then set the file.

    Falls back to the 'paste' textarea if file upload doesn't work.
    """
    try:
        # Strategy 1: Click "Attach" to trigger dynamic file input creation
        attach_btn = await page.query_selector(
            f"[data-field='{field_name}'] button[data-source='attach']"
        )
        if attach_btn:
            # Listen for the file input that JS will create
            async with page.expect_file_chooser(timeout=5000) as fc_info:
                await attach_btn.click()
            file_chooser = await fc_info.value
            await file_chooser.set_files(file_path)
            await page.wait_for_timeout(2000)
            # Check if filename appeared (upload success indicator)
            filename_el = await page.query_selector(f"#{field_name}_filename")
            if filename_el:
                name_text = await filename_el.inner_text()
                if name_text.strip():
                    print(f"    📎 Uploaded {field_name}: {name_text.strip()}")
                    return True

        # Strategy 2: Use the "paste" textarea as fallback
        paste_btn = await page.query_selector(
            f"[data-field='{field_name}'] button[data-source='paste']"
        )
        if paste_btn and file_path.endswith(('.txt', '.text')):
            await paste_btn.click()
            await page.wait_for_timeout(500)
            textarea = await page.query_selector(f"#{field_name}_text")
            if textarea:
                with open(file_path) as f:
                    text = f.read()
                await textarea.fill(text)
                print(f"    📝 Pasted {field_name} text")
                return True

        print(f"    ⚠️  Could not upload {field_name}")
        return False
    except Exception as e:
        print(f"    ⚠️  {field_name} upload error: {e}")
        return False


async def upload_file(page: Page, selector: str, file_path: str):
    """Upload a file to a file input. Selector can be comma-separated alternatives."""
    # Try each selector individually if comma-separated
    selectors = [s.strip() for s in selector.split(",")]
    for sel in selectors:
        try:
            el = await page.wait_for_selector(sel, timeout=3000)
            if el:
                await el.set_input_files(file_path)
                return True
        except Exception:
            continue
    print(f"    ⚠️  File upload: no matching input found")
    return False


# ── Greenhouse Applier ─────────────────────────────────────────────────────────

async def apply_greenhouse(page: Page, job: dict, cv_path: str, cover_letter_path: str) -> bool:
    """
    Apply via Greenhouse embedded application form.
    URL format: https://boards.greenhouse.io/embed/job_app?for={slug}&token={job_id}
    """
    print(f"  🌿 Greenhouse apply: {job['url']}")
    try:
        await page.goto(job["url"], timeout=30000)
        await page.wait_for_timeout(3000)

        # Solve CAPTCHA if present on initial page load
        captcha_ok = await detect_and_solve(page)
        if not captcha_ok:
            print(f"  🚫 CAPTCHA blocked on Greenhouse page load")
            return "captcha_blocked"

        # Standard Greenhouse embed form fields
        await safe_fill(page, "#first_name", APPLICANT["first_name"])
        await safe_fill(page, "#last_name", APPLICANT["last_name"])
        await safe_fill(page, "#email", APPLICANT["email"])
        await safe_fill(page, "#phone", APPLICANT["phone"])

        # LinkedIn URL — try multiple selectors
        await safe_fill(page, "input[name*='linkedin']", APPLICANT["linkedin"])
        await safe_fill(page, "input[autocomplete='url']", APPLICANT["linkedin"])

        # Location (if asked)
        await safe_fill(page, "#job_application_location", APPLICANT["location"])

        # Resume upload — Greenhouse uses JS-based S3 upload, not <input type="file">
        await greenhouse_upload_file(page, "resume", cv_path)

        # Cover letter upload
        await greenhouse_upload_file(page, "cover_letter", cover_letter_path)

        # Handle custom questions — Greenhouse wraps each in a .field div
        custom_fields = await page.query_selector_all(".field")
        for field in custom_fields:
            label_el = await field.query_selector("label")
            label = (await label_el.inner_text()).strip() if label_el else ""

            # Skip empty labels and already-filled standard fields
            if not label:
                continue
            label_lower = label.lower()
            if any(kw in label_lower for kw in [
                "first name", "last name", "email", "phone",
                "resume", "cover letter", "attach",
            ]):
                continue

            # Skip fields we can't/shouldn't fill
            SKIP_FIELDS = [
                "security", "captcha", "verification", "verify",
                "password", "ssn", "social security", "eeoc",
                "gender", "race", "ethnicity", "veteran", "disability",
                "i-9", "w-4", "authorization code",
            ]
            if any(kw in label_lower for kw in SKIP_FIELDS):
                print(f"    ⏭️  Skipping field: {label}")
                continue

            # LinkedIn — fill directly
            if "linkedin" in label_lower:
                input_el = await field.query_selector("input[type='text']")
                if input_el:
                    await input_el.fill(APPLICANT["linkedin"])
                continue

            # Dropdowns (select elements)
            select_el = await field.query_selector("select")
            if select_el:
                options = await select_el.inner_text()
                option_list = [o.strip() for o in options.split("\n") if o.strip()]
                if option_list:
                    answer = await ai_fill_field(label, option_list)
                    if answer:
                        try:
                            await select_el.select_option(label=answer)
                        except Exception:
                            pass
                continue

            # Text inputs (skip hidden inputs, textareas for paste, etc.)
            input_el = await field.query_selector("input[type='text']:not([type='hidden']), input[type='url']")
            if input_el:
                # Skip if already filled or if it's a standard field
                input_id = await input_el.get_attribute("id") or ""
                if input_id in ("first_name", "last_name", "email", "phone", "dev-field-1"):
                    continue
                current_val = await input_el.input_value()
                if current_val:
                    continue
                answer = await ai_fill_field(label)
                if answer:
                    try:
                        await input_el.fill(answer, timeout=5000)
                    except Exception as e:
                        print(f"    ⚠️  Could not fill '{label[:40]}': {e}")
                else:
                    print(f"    ⏭️  AI skipped field: {label}")

        # Solve CAPTCHA before submitting (reCAPTCHA often appears near submit)
        captcha_ok = await detect_and_solve(page)
        if not captcha_ok:
            print(f"  🚫 CAPTCHA blocked before Greenhouse submit")
            return "captcha_blocked"

        # Submit
        submit_clicked = await safe_click(page, "#submit_app, button[type='submit'], input[type='submit']")
        if not submit_clicked:
            print(f"  ⚠️  Could not find submit button")
            return False

        await page.wait_for_timeout(5000)

        # Sometimes CAPTCHA triggers after submit click — solve if needed
        captcha_ok = await detect_and_solve(page)
        if not captcha_ok:
            print(f"  🚫 CAPTCHA blocked after Greenhouse submit click")
            return "captcha_blocked"

        # Check for success
        content = await page.content()
        if any(kw in content.lower() for kw in ["thank you", "submitted", "application received", "application has been"]):
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

        # Solve CAPTCHA if present after clicking Apply
        captcha_ok = await detect_and_solve(page)
        if not captcha_ok:
            print(f"  🚫 CAPTCHA blocked on Lever apply page")
            return "captcha_blocked"

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
                if answer:
                    await input_el.fill(answer)

        # Solve CAPTCHA before submitting
        captcha_ok = await detect_and_solve(page)
        if not captcha_ok:
            print(f"  🚫 CAPTCHA blocked before Lever submit")
            return "captcha_blocked"

        # Submit
        await safe_click(page, "button[type='submit'], input[type='submit']")
        await page.wait_for_timeout(3000)

        # Solve CAPTCHA if triggered after submit
        captcha_ok = await detect_and_solve(page)
        if not captcha_ok:
            print(f"  🚫 CAPTCHA blocked after Lever submit click")
            return "captcha_blocked"

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
                        if answer:
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

async def apply_to_job(job: dict, cv_path: str, cover_letter_path: str, browser) -> bool | str:
    """Route application to correct ATS handler."""
    context = await browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
        )
    )
    page = await context.new_page()
    ats = job.get("ats_type", "other")

    # For LinkedIn-sourced jobs with external apply URLs, use the external URL
    apply_url = job.get("apply_url", job["url"])
    job_for_apply = {**job, "url": apply_url}

    try:
        # Guard: never try to navigate to an empty or invalid URL
        if not job_for_apply.get("url") or not job_for_apply["url"].startswith("http"):
            print(f"  ⏭️  Skipping {job.get('title', '?')} — no valid apply URL")
            success = False
        elif ats == "greenhouse":
            success = await apply_greenhouse(page, job_for_apply, cv_path, cover_letter_path)
        elif ats == "lever":
            success = await apply_lever(page, job_for_apply, cv_path, cover_letter_path)
        elif ats == "linkedin":
            # No LinkedIn Easy Apply — skip jobs without external apply links
            print(f"  ⏭️  LinkedIn Easy Apply not available — no external link found for {job['title']}")
            success = False
        else:
            print(f"  ⏭️  Unknown ATS type '{ats}' — skipping auto-apply")
            success = False
    finally:
        await context.close()

    return success


async def run_applications(jobs_with_docs: list[dict]) -> list[bool | str]:
    """
    Apply to all qualified jobs. Returns list of True/False/"captcha_blocked" per job.

    Uses Botright for stealth browsing and free AI-powered CAPTCHA solving.
    No API keys required — all CAPTCHA solving runs locally.
    """
    if not jobs_with_docs:
        return []

    results = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]
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
