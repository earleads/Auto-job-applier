"""
CAPTCHA Solver — Free reCAPTCHA solving using the recognizer library.

Uses YOLO + CLIP AI models to solve reCAPTCHA v2 image challenges locally.
No paid API keys required — all solving runs on-device.

Supports:
  - reCAPTCHA v2 (image classification via YOLO/CLIP)
"""

from recognizer.agents.playwright import AsyncChallenger


async def detect_and_solve(page) -> bool:
    """
    Attempt to solve any reCAPTCHA on the current page.

    Uses the recognizer library's AsyncChallenger which handles detection,
    clicking the checkbox, solving image challenges, and submitting.

    Returns True if no CAPTCHA or CAPTCHA was solved, False if blocked.
    """
    # Check if there's a reCAPTCHA on the page
    recaptcha_el = await page.query_selector(
        ".g-recaptcha, [data-sitekey], iframe[src*='recaptcha']"
    )
    if not recaptcha_el:
        return True  # No CAPTCHA — all clear

    print("    🔐 reCAPTCHA detected — solving with AI (YOLO + CLIP)...")

    try:
        challenger = AsyncChallenger(page, click_timeout=1000)
        await challenger.solve_recaptcha()
        print("    ✅ reCAPTCHA solved!")
        return True
    except Exception as e:
        err_str = str(e).lower()
        if "no" in err_str and ("found" in err_str or "captcha" in err_str):
            # No actual CAPTCHA present (false positive from selector)
            return True
        print(f"    ❌ reCAPTCHA solve failed: {e}")

        # One retry
        try:
            print("    🔄 Retrying...")
            challenger = AsyncChallenger(page, click_timeout=1500)
            await challenger.solve_recaptcha()
            print("    ✅ reCAPTCHA solved on retry!")
            return True
        except Exception as e2:
            print(f"    ❌ Retry failed: {e2}")
            return False


def is_configured() -> bool:
    """Return True — recognizer CAPTCHA solving requires no API keys."""
    return True
