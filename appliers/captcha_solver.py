"""
CAPTCHA Solver — Free reCAPTCHA solving using the recognizer library.

Uses YOLO + CLIP AI models to solve reCAPTCHA v2 image challenges locally.
No paid API keys required — all solving runs on-device.

Strategy for tough environments (CI/datacenter IPs):
  - Multiple attempts with increasing timeouts
  - Page reload between attempts to get a fresh/easier challenge
  - Longer waits to let reCAPTCHA fully load before solving
"""

import asyncio
from recognizer.agents.playwright import AsyncChallenger

# Escalating timeout strategy: start fast, get more patient
_ATTEMPT_CONFIGS = [
    {"click_timeout": 1500, "pre_wait": 1000},   # Quick first try
    {"click_timeout": 3000, "pre_wait": 2000},   # Slower, let it load
    {"click_timeout": 5000, "pre_wait": 3000},   # Patient
    {"click_timeout": 8000, "pre_wait": 5000},   # Very patient (after reload)
]


async def _is_captcha_present(page) -> bool:
    """Check if a reCAPTCHA element exists on the page."""
    el = await page.query_selector(
        ".g-recaptcha, [data-sitekey], iframe[src*='recaptcha']"
    )
    return el is not None


async def _try_solve(page, click_timeout: int) -> bool:
    """Single solve attempt. Returns True on success, raises on failure."""
    challenger = AsyncChallenger(page, click_timeout=click_timeout)
    await challenger.solve_recaptcha()
    return True


async def detect_and_solve(page, allow_reload: bool = True) -> bool:
    """
    Attempt to solve any reCAPTCHA on the current page.

    Uses multiple attempts with escalating timeouts. On the 3rd+ attempt,
    reloads the page to get a fresh challenge (often easier).

    Args:
        page: Patchright page object
        allow_reload: If True, reload the page on later attempts for a fresh challenge

    Returns True if no CAPTCHA or CAPTCHA was solved, False if blocked.
    """
    if not await _is_captcha_present(page):
        return True  # No CAPTCHA — all clear

    print("    🔐 reCAPTCHA detected — solving with AI (YOLO + CLIP)...")

    for i, cfg in enumerate(_ATTEMPT_CONFIGS):
        attempt_num = i + 1

        # Reload page on attempt 3+ to get a fresh challenge
        if i >= 2 and allow_reload:
            print(f"    🔄 Reloading page for fresh challenge...")
            current_url = page.url
            try:
                await page.reload(timeout=15000)
                await page.wait_for_timeout(3000)
                if not await _is_captcha_present(page):
                    print("    ✅ CAPTCHA gone after reload!")
                    return True
            except Exception:
                pass  # Reload failed, try solving anyway

        # Wait for CAPTCHA to fully render
        await page.wait_for_timeout(cfg["pre_wait"])

        try:
            await _try_solve(page, cfg["click_timeout"])
            print(f"    ✅ reCAPTCHA solved! (attempt {attempt_num})")
            return True
        except Exception as e:
            err_str = str(e).lower()
            if "no" in err_str and ("found" in err_str or "captcha" in err_str):
                # No actual CAPTCHA present (false positive from selector)
                return True
            print(f"    ❌ Attempt {attempt_num}/{len(_ATTEMPT_CONFIGS)} failed: {e}")

            # Brief pause between attempts
            if i < len(_ATTEMPT_CONFIGS) - 1:
                await asyncio.sleep(2)

    print("    🚫 All CAPTCHA solve attempts exhausted")
    return False


def is_configured() -> bool:
    """Return True — recognizer CAPTCHA solving requires no API keys."""
    return True
