"""
Auto-Applier — Patchright-based form submission for multiple ATS platforms.

Supports:
  - LinkedIn Easy Apply
  - Greenhouse (boards.greenhouse.io) — with free AI CAPTCHA solving
  - Lever (jobs.lever.co) — with free AI CAPTCHA solving
  - Generic ATS (Workday, iCIMS, Ashby, Jobvite, SmartRecruiters, etc.)

Uses Patchright (stealth Playwright fork) for anti-detection browsing and
the recognizer library (YOLO + CLIP) for free reCAPTCHA solving.
No paid API keys required.
"""

import asyncio
import os
import re
from datetime import datetime
from pathlib import Path

from patchright.async_api import async_playwright, Page

from config import CANDIDATE_PROFILE, ANTHROPIC_API_KEY
import anthropic
from appliers.captcha_solver import detect_and_solve, is_configured as captcha_configured
from appliers.email_verifier import fetch_verification_code, is_configured as email_configured

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
(CAPTCHAs, SSN, passwords, salary expectations with no basis, etc.),
respond with exactly: SKIP
Note: Do NOT skip "Security Code" fields — those are handled separately.

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


# ── Screenshot helper ─────────────────────────────────────────────────────────

SCREENSHOTS_DIR = Path("screenshots")
SCREENSHOTS_DIR.mkdir(exist_ok=True)


async def capture_screenshot(page: Page, job: dict, status: str) -> str | None:
    """Capture a screenshot after an application attempt.

    Returns the screenshot file path, or None on failure.
    """
    try:
        title = re.sub(r'[^\w\s-]', '', job.get('title', 'unknown'))[:50].strip()
        company = re.sub(r'[^\w\s-]', '', job.get('company', 'unknown'))[:30].strip()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{ts}_{company}_{title}_{status}.png".replace(" ", "_")
        path = SCREENSHOTS_DIR / filename
        await page.screenshot(path=str(path), full_page=True)
        print(f"  📸 Screenshot saved: {path}")
        return str(path)
    except Exception as e:
        print(f"  ⚠️  Screenshot failed: {e}")
        return None


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

    Falls back to directly finding/creating a file input if the Attach flow hangs.
    """
    try:
        # Strategy 1: Find a hidden file input already in the DOM (some Greenhouse forms)
        file_input = await page.query_selector(
            f"[data-field='{field_name}'] input[type='file'], "
            f"input[type='file'][id*='{field_name}'], "
            f"input[type='file'][name*='{field_name}']"
        )
        if file_input:
            await file_input.set_input_files(file_path)
            await page.wait_for_timeout(2000)
            print(f"    📎 Uploaded {field_name} (direct input)")
            return True

        # Strategy 2: Click "Attach" to trigger dynamic file input creation
        attach_btn = await page.query_selector(
            f"[data-field='{field_name}'] button[data-source='attach']"
        )
        if attach_btn:
            try:
                async with page.expect_file_chooser(timeout=5000) as fc_info:
                    await attach_btn.click()
                file_chooser = await fc_info.value
                await file_chooser.set_files(file_path)
                await page.wait_for_timeout(2000)
                filename_el = await page.query_selector(f"#{field_name}_filename")
                if filename_el:
                    name_text = await filename_el.inner_text()
                    if name_text.strip():
                        print(f"    📎 Uploaded {field_name}: {name_text.strip()}")
                        return True
            except Exception:
                # file_chooser flow timed out — try finding the input JS created
                file_input = await page.query_selector(
                    f"[data-field='{field_name}'] input[type='file'], "
                    f"input[type='file'][id*='{field_name}']"
                )
                if file_input:
                    await file_input.set_input_files(file_path)
                    await page.wait_for_timeout(2000)
                    print(f"    📎 Uploaded {field_name} (fallback input)")
                    return True

        # Strategy 3: Any remaining file input on the page (last resort for cover letter)
        if field_name == "cover_letter":
            all_inputs = await page.query_selector_all("input[type='file']")
            # The first file input is usually resume; second is cover letter
            if len(all_inputs) >= 2:
                await all_inputs[1].set_input_files(file_path)
                await page.wait_for_timeout(2000)
                print(f"    📎 Uploaded {field_name} (2nd file input)")
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

        # Location (if asked) — Greenhouse uses autocomplete dropdown
        # The #job_application_location might be a <div> wrapper, so find the actual input inside
        loc_input = await page.query_selector(
            "#job_application_location input[type='text'], "
            "input#job_application_location, "
            "[data-field='job_application_location'] input[type='text'], "
            "input[name*='location']"
        )
        if loc_input:
            try:
                await loc_input.fill("")
                await loc_input.type(APPLICANT["location"].split("(")[0].strip(), delay=50)
                await page.wait_for_timeout(1500)
                # Select first autocomplete suggestion if dropdown appears
                suggestion = await page.query_selector(
                    ".autocomplete-results li, .location-autocomplete li, "
                    "[class*='autocomplete'] li, [role='option'], "
                    ".ui-menu-item, [class*='suggestion']"
                )
                if suggestion:
                    await suggestion.click()
                    await page.wait_for_timeout(500)
            except Exception as e:
                print(f"    ⚠️  Location fill failed, trying safe_fill: {e}")
                await safe_fill(page, "input[name*='location']", APPLICANT["location"])

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

            # Security Code field — handle specially (request code via email)
            if "security code" in label_lower:
                print(f"    🔐 Security Code field detected — requesting verification email...")
                if email_configured():
                    code = await fetch_verification_code(APPLICANT["email"], max_wait=120)
                    if code:
                        code_input = await field.query_selector(
                            "input[type='text'], input[type='number'], input:not([type='hidden'])"
                        )
                        if not code_input:
                            # Fallback: search the whole page for code input
                            code_input = await page.query_selector(
                                "input[name*='security'], input[name*='code'], "
                                "input[id*='security'], input[id*='code'], "
                                "input[placeholder*='code']"
                            )
                        if code_input:
                            try:
                                await code_input.scroll_into_view_if_needed(timeout=5000)
                            except Exception:
                                pass
                            try:
                                await code_input.fill(code, timeout=5000)
                            except Exception:
                                # Element not visible — use JS to set value directly
                                print(f"    ⚠️  fill() failed, using JS to set value...")
                                await code_input.evaluate(
                                    """(el, val) => {
                                        el.value = val;
                                        el.dispatchEvent(new Event('input', {bubbles: true}));
                                        el.dispatchEvent(new Event('change', {bubbles: true}));
                                    }""",
                                    code,
                                )
                            print(f"    📧 Entered security code: {code}")
                        else:
                            print(f"    ⚠️  Got code but could not find input in Security Code field")
                    else:
                        print(f"    ⚠️  Security code not received via email")
                else:
                    print(f"    ⚠️  Security Code required but Gmail not configured")
                continue

            # Skip fields we can't/shouldn't fill
            SKIP_FIELDS = [
                "captcha",
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

            # Checkboxes — e.g. "Select the countries you anticipate working in"
            checkboxes = await field.query_selector_all("input[type='checkbox']")
            if checkboxes:
                # Get all checkbox labels and ask AI which to select
                checkbox_options = []
                for cb in checkboxes:
                    cb_label = await cb.evaluate(
                        "el => (el.labels && el.labels[0] ? el.labels[0].innerText : el.value || '')"
                    )
                    if cb_label.strip():
                        checkbox_options.append(cb_label.strip())
                if checkbox_options:
                    answer = await ai_fill_field(label, checkbox_options)
                    if answer:
                        # AI may return one or comma-separated values
                        selections = [s.strip() for s in answer.split(",")]
                        for cb in checkboxes:
                            cb_label = await cb.evaluate(
                                "el => (el.labels && el.labels[0] ? el.labels[0].innerText : el.value || '')"
                            )
                            if cb_label.strip() in selections:
                                await cb.click()
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

        # Pre-submit screenshot for debugging (shows filled form before clicking submit)
        await capture_screenshot(page, job, "pre_submit")
        print(f"    📸 Pre-submit screenshot saved")

        # Solve CAPTCHA before submitting (reCAPTCHA often appears near submit)
        captcha_ok = await detect_and_solve(page)
        if not captcha_ok:
            print(f"  🚫 CAPTCHA blocked before Greenhouse submit")
            return "captcha_blocked"

        # Submit — scroll into view and use JS click as fallback for overlay issues
        submit_clicked = False
        for sel in ["#submit_app", "button[type='submit']", "input[type='submit']"]:
            el = await page.query_selector(sel)
            if el:
                try:
                    await el.scroll_into_view_if_needed()
                    await page.wait_for_timeout(500)
                    await el.click(timeout=5000)
                    submit_clicked = True
                    break
                except Exception:
                    # "subtree intercepts pointer events" — use JS click
                    try:
                        await el.evaluate("el => el.click()")
                        submit_clicked = True
                        break
                    except Exception:
                        continue
        if not submit_clicked:
            print(f"  ⚠️  Could not find submit button")
            return False

        await page.wait_for_timeout(5000)

        # Sometimes CAPTCHA triggers after submit click — solve if needed
        captcha_ok = await detect_and_solve(page)
        if not captcha_ok:
            print(f"  🚫 CAPTCHA blocked after Greenhouse submit click")
            return "captcha_blocked"

        # Check for Greenhouse email verification code prompt
        # Some companies require a security code sent to the applicant's email
        content_after_submit = (await page.content()).lower()
        needs_code = any(kw in content_after_submit for kw in [
            "security code", "verification code", "enter the code",
            "check your email", "code from your email",
        ])
        code_entered = False
        if needs_code and email_configured():
            code = await fetch_verification_code(APPLICANT["email"], max_wait=120)
            if code:
                # Find the security code input field and enter it
                code_input = await page.query_selector(
                    "input[name*='security'], input[name*='code'], "
                    "input[id*='security'], input[id*='code'], "
                    "input[placeholder*='code'], input[placeholder*='security'], "
                    "input[type='text']:not(#first_name):not(#last_name):not(#email):not(#phone)"
                )
                if code_input:
                    try:
                        await code_input.scroll_into_view_if_needed(timeout=5000)
                    except Exception:
                        pass
                    try:
                        await code_input.fill(code, timeout=5000)
                    except Exception:
                        print(f"    ⚠️  fill() failed, using JS to set value...")
                        await code_input.evaluate(
                            """(el, val) => {
                                el.value = val;
                                el.dispatchEvent(new Event('input', {bubbles: true}));
                                el.dispatchEvent(new Event('change', {bubbles: true}));
                            }""",
                            code,
                        )
                    print(f"    📧 Entered verification code: {code}")
                    await page.wait_for_timeout(1000)
                    # Re-submit with the code
                    for sel in ["#submit_app", "button[type='submit']", "input[type='submit']"]:
                        el = await page.query_selector(sel)
                        if el:
                            try:
                                await el.click(timeout=5000)
                            except Exception:
                                await el.evaluate("el => el.click()")
                            break
                    await page.wait_for_timeout(5000)
                    code_entered = True
                else:
                    print(f"    ⚠️  Got code but could not find input field")
            else:
                print(f"    ⚠️  Verification code required but not received")
        elif needs_code:
            print(f"    ⚠️  Verification code required but email verification not configured/working")

        # If verification code was needed but not entered, this is a failure
        if needs_code and not code_entered:
            await capture_screenshot(page, job, "needs_verification")
            print(f"  ❌ Application incomplete — verification code not entered")
            return False

        # Check for success — Greenhouse shows various confirmation messages
        content = (await page.content()).lower()
        current_url = page.url.lower()
        SUCCESS_KEYWORDS = [
            "thank you", "thanks for", "submitted", "application received",
            "application has been", "we have received", "successfully applied",
            "confirmation", "we'll be in touch", "we will review",
        ]
        # URL-based detection: Greenhouse redirects to a thank-you page
        url_success = any(kw in current_url for kw in ["thank", "confirm", "success"])
        content_success = any(kw in content for kw in SUCCESS_KEYWORDS)
        # Also check if the form itself is gone (replaced by confirmation)
        form_gone = not await page.query_selector("#submit_app")

        # Check for validation errors FIRST — they take priority over form_gone
        error_els = await page.query_selector_all(
            ".field-error, .error-message, #error_explanation, "
            "[class*='error'], .invalid-feedback, [aria-invalid='true']"
        )
        has_errors = False
        for error_el in error_els:
            error_text = (await error_el.inner_text()).strip()
            if error_text:
                has_errors = True
                print(f"  ❌ Greenhouse validation error: {error_text[:200]}")
                break

        # Also check for required fields that are still empty
        if not has_errors:
            required_inputs = await page.query_selector_all(
                "input[required], select[required], textarea[required]"
            )
            for inp in required_inputs:
                tag = await inp.evaluate("el => el.tagName.toLowerCase()")
                if tag == "select":
                    val = await inp.evaluate("el => el.value")
                else:
                    val = await inp.input_value()
                if not val or not val.strip():
                    label_text = await inp.evaluate(
                        "el => (el.labels && el.labels[0] ? el.labels[0].innerText : el.placeholder || el.name || 'unknown')"
                    )
                    has_errors = True
                    print(f"  ❌ Required field still empty: {label_text}")
                    break

        if has_errors:
            await capture_screenshot(page, job, "failed")
            return False
        elif content_success or url_success:
            await capture_screenshot(page, job, "success")
            print(f"  ✅ Greenhouse application submitted!")
            return True
        elif form_gone:
            # Form disappeared after submit with no errors — likely success
            await capture_screenshot(page, job, "success")
            print(f"  ✅ Greenhouse application submitted (form cleared)!")
            return True
        else:
            await capture_screenshot(page, job, "failed")
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
            await capture_screenshot(page, job, "success")
            print(f"  ✅ Lever application submitted!")
            return True
        await capture_screenshot(page, job, "failed")
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


# ── Generic ATS Applier ───────────────────────────────────────────────────────

async def apply_generic(page: Page, job: dict, cv_path: str, cover_letter_path: str) -> bool:
    """
    Generic applier for any ATS platform (Workday, iCIMS, Ashby, etc.).

    Strategy:
    1. Navigate to the apply URL
    2. Look for common "Apply" buttons to reach the application form
    3. Fill standard fields (name, email, phone, LinkedIn)
    4. Upload resume
    5. Use AI to handle custom fields
    6. Submit
    """
    ats = job.get("ats_type", "generic")
    print(f"  🌐 Generic apply ({ats}): {job['url'][:80]}")
    try:
        await page.goto(job["url"], timeout=30000)
        await page.wait_for_timeout(3000)

        # Solve CAPTCHA if present on initial page load
        captcha_ok = await detect_and_solve(page)
        if not captcha_ok:
            print(f"  🚫 CAPTCHA blocked on {ats} page load")
            return "captcha_blocked"

        # Step 1: Find and click "Apply" button (many ATS show job details first)
        apply_btn = await page.query_selector(
            "a[href*='apply'], "
            "button:has-text('Apply'), "
            "a:has-text('Apply Now'), "
            "a:has-text('Apply for this job'), "
            "button:has-text('Apply Now'), "
            "[data-automation-id='jobPostingApplyButton'], "  # Workday
            ".btn-apply, .apply-btn, .apply-button, "
            "#apply-button, #applyButton"
        )
        if apply_btn:
            try:
                await apply_btn.click(timeout=5000)
                await page.wait_for_timeout(3000)
            except Exception:
                # Try JS click if intercepted
                try:
                    await apply_btn.evaluate("el => el.click()")
                    await page.wait_for_timeout(3000)
                except Exception:
                    pass

        # Step 2: Fill standard form fields using common name/id/placeholder patterns
        FIELD_MAP = {
            "name":       (APPLICANT["name"],       ["input[name*='name' i]:not([name*='last']):not([name*='first'])", "input[autocomplete='name']"]),
            "first_name": (APPLICANT["first_name"], ["input[name*='first' i]", "input[name*='fname' i]", "input[autocomplete='given-name']", "input[id*='firstName' i]", "[data-automation-id='legalNameSection_firstName'] input"]),
            "last_name":  (APPLICANT["last_name"],  ["input[name*='last' i]", "input[name*='lname' i]", "input[autocomplete='family-name']", "input[id*='lastName' i]", "[data-automation-id='legalNameSection_lastName'] input"]),
            "email":      (APPLICANT["email"],      ["input[type='email']", "input[name*='email' i]", "input[autocomplete='email']", "input[id*='email' i]"]),
            "phone":      (APPLICANT["phone"],      ["input[type='tel']", "input[name*='phone' i]", "input[autocomplete='tel']", "input[id*='phone' i]"]),
            "linkedin":   (APPLICANT["linkedin"],   ["input[name*='linkedin' i]", "input[id*='linkedin' i]", "input[placeholder*='linkedin' i]"]),
        }

        filled_count = 0
        for field_name, (value, selectors) in FIELD_MAP.items():
            if not value:
                continue
            for sel in selectors:
                try:
                    el = await page.query_selector(sel)
                    if el:
                        current = await el.input_value()
                        if not current:
                            await el.fill(value)
                            filled_count += 1
                            break
                except Exception:
                    continue

        if filled_count == 0:
            print(f"  ⚠️  Could not fill any standard fields — form layout unrecognized")
            return False

        print(f"    📝 Filled {filled_count} standard fields")

        # Step 3: Upload resume
        file_input = await page.query_selector("input[type='file']")
        if file_input:
            await file_input.set_input_files(cv_path)
            await page.wait_for_timeout(2000)
            print(f"    📎 Resume uploaded")

        # Step 4: Handle custom fields with AI
        # Look for unfilled text inputs with labels
        all_fields = await page.query_selector_all("label")
        for label_el in all_fields:
            try:
                label = (await label_el.inner_text()).strip()
                if not label or len(label) > 200:
                    continue
                label_lower = label.lower()

                # Skip standard and sensitive fields
                SKIP_PATTERNS = [
                    "first name", "last name", "email", "phone", "resume",
                    "cover letter", "attach", "upload", "captcha", "password",
                    "ssn", "social security", "eeoc", "gender", "race",
                    "ethnicity", "veteran", "disability", "i-9", "w-4",
                    "linkedin",
                ]
                if any(p in label_lower for p in SKIP_PATTERNS):
                    continue

                # Find the associated input
                label_for = await label_el.get_attribute("for")
                if label_for:
                    input_el = await page.query_selector(f"#{label_for}")
                else:
                    # Try sibling/child input
                    parent = await label_el.evaluate_handle("el => el.closest('.field, .form-group, .form-field, [class*=field]') || el.parentElement")
                    input_el = await parent.as_element().query_selector("input[type='text'], textarea, select") if parent else None

                if not input_el:
                    continue

                tag = await input_el.evaluate("el => el.tagName.toLowerCase()")
                if tag == "select":
                    options_text = await input_el.inner_text()
                    option_list = [o.strip() for o in options_text.split("\n") if o.strip()]
                    if option_list:
                        answer = await ai_fill_field(label, option_list)
                        if answer:
                            try:
                                await input_el.select_option(label=answer)
                            except Exception:
                                pass
                else:
                    current = await input_el.input_value()
                    if not current:
                        answer = await ai_fill_field(label)
                        if answer:
                            try:
                                await input_el.fill(answer)
                            except Exception:
                                pass
            except Exception:
                continue

        # Step 5: Solve CAPTCHA before submit
        captcha_ok = await detect_and_solve(page)
        if not captcha_ok:
            print(f"  🚫 CAPTCHA blocked before {ats} submit")
            return "captcha_blocked"

        # Step 6: Submit
        submit_btn = await page.query_selector(
            "button[type='submit'], "
            "input[type='submit'], "
            "button:has-text('Submit'), "
            "button:has-text('Submit Application'), "
            "button:has-text('Apply'), "
            "[data-automation-id='bottom-navigation-next-button']"  # Workday
        )
        if submit_btn:
            try:
                await submit_btn.scroll_into_view_if_needed()
                await page.wait_for_timeout(500)
                await submit_btn.click(timeout=5000)
            except Exception:
                try:
                    await submit_btn.evaluate("el => el.click()")
                except Exception:
                    print(f"  ⚠️  Could not click submit button")
                    return False
        else:
            print(f"  ⚠️  No submit button found")
            return False

        await page.wait_for_timeout(5000)

        # Post-submit CAPTCHA
        captcha_ok = await detect_and_solve(page)

        # Check for validation errors first
        error_els = await page.query_selector_all(
            ".field-error, .error-message, #error_explanation, "
            "[class*='error'], .invalid-feedback, [aria-invalid='true']"
        )
        has_errors = False
        for error_el in error_els:
            error_text = (await error_el.inner_text()).strip()
            if error_text:
                has_errors = True
                print(f"  ❌ Validation error: {error_text[:200]}")
                break

        if has_errors:
            await capture_screenshot(page, job, "failed")
            return False

        # Check for success
        content = (await page.content()).lower()
        current_url = page.url.lower()
        SUCCESS_KEYWORDS = [
            "thank you", "thanks for", "submitted", "application received",
            "application has been", "we have received", "successfully applied",
            "confirmation", "we'll be in touch", "we will review",
        ]
        url_success = any(kw in current_url for kw in ["thank", "confirm", "success"])
        content_success = any(kw in content for kw in SUCCESS_KEYWORDS)

        if content_success or url_success:
            await capture_screenshot(page, job, "success")
            print(f"  ✅ {ats.title()} application submitted!")
            return True
        else:
            await capture_screenshot(page, job, "unclear")
            print(f"  ⚠️  {ats.title()} submit confirmation unclear — check manually")
            return False

    except Exception as e:
        print(f"  ❌ Generic apply failed ({ats}): {e}")
        return False


# ── Router ─────────────────────────────────────────────────────────────────────

# ATS types that can be handled by the generic applier
GENERIC_ATS_TYPES = {"workday", "icims", "ultipro", "jobvite", "ashby", "smartrecruiters", "generic"}

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
        elif ats in GENERIC_ATS_TYPES:
            success = await apply_generic(page, job_for_apply, cv_path, cover_letter_path)
        elif ats == "linkedin":
            # LinkedIn-sourced job without detected external ATS link.
            # Try the original LinkedIn URL with generic applier — some jobs
            # have an "Apply on company website" button we can follow at runtime.
            job_for_apply["url"] = job["url"]  # Use original LinkedIn URL
            print(f"  💼 LinkedIn job (no external link detected) — attempting to find apply link at runtime")
            try:
                await page.goto(job["url"], timeout=20000)
                await page.wait_for_timeout(3000)
                # Look for external apply button on the LinkedIn job page
                apply_btn = await page.query_selector(
                    "a.apply-button:not([href*='linkedin.com/login']), "
                    "a[data-tracking-control-name*='apply']:not([href*='linkedin.com/login']), "
                    ".top-card-layout__cta-container a:not([href*='linkedin.com/login']), "
                    "a[href*='boards.greenhouse.io'], "
                    "a[href*='jobs.lever.co'], "
                    "a[href*='myworkday'], "
                    "a[href*='careers']"
                )
                if apply_btn:
                    href = await apply_btn.get_attribute("href") or ""
                    if href and "linkedin.com" not in href and href.startswith("http"):
                        print(f"    🔗 Found external link at runtime: {href[:80]}")
                        job_for_apply["url"] = href
                        success = await apply_generic(page, job_for_apply, cv_path, cover_letter_path)
                    elif href:
                        # Try clicking and capturing the redirect
                        try:
                            await apply_btn.click(timeout=5000)
                            await page.wait_for_timeout(3000)
                            new_url = page.url
                            if "linkedin.com" not in new_url:
                                print(f"    🔗 Redirected to: {new_url[:80]}")
                                job_for_apply["url"] = new_url
                                success = await apply_generic(page, job_for_apply, cv_path, cover_letter_path)
                            else:
                                print(f"  ⏭️  Apply button stayed on LinkedIn — likely Easy Apply")
                                success = False
                        except Exception:
                            print(f"  ⏭️  Could not follow apply button")
                            success = False
                    else:
                        print(f"  ⏭️  No external apply link found for {job['title']}")
                        success = False
                else:
                    print(f"  ⏭️  No apply button found on LinkedIn page for {job['title']}")
                    success = False
            except Exception as e:
                print(f"  ❌ LinkedIn runtime apply failed: {e}")
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
