"""
CAPTCHA Solver — Botright-powered free CAPTCHA solving for ATS forms.

Uses Botright's built-in AI models (YOLO + CLIP for reCAPTCHA, hcaptcha-challenger
for hCaptcha) to solve CAPTCHAs without any paid API keys.

Supports:
  - reCAPTCHA v2 (image classification via YOLO/CLIP)
  - hCaptcha (via hcaptcha-challenger)
  - GeeTest v3/v4 (slider + image)

No API keys required — all solving runs locally.
"""


async def detect_and_solve(page) -> bool:
    """
    Attempt to solve any CAPTCHA on the current page using Botright's built-in solvers.

    Botright pages have solve_recaptcha() and solve_hcaptcha() methods.
    Falls back gracefully if no CAPTCHA is present or solving fails.

    Returns True if no CAPTCHA or CAPTCHA was solved, False if blocked.
    """
    # Only Botright pages have these methods — regular Playwright pages don't
    if not hasattr(page, "solve_recaptcha"):
        return True

    # Try reCAPTCHA first (most common on Greenhouse/Lever)
    try:
        recaptcha_el = await page.query_selector(
            ".g-recaptcha, [data-sitekey], iframe[src*='recaptcha']"
        )
        if recaptcha_el:
            print("    🔐 reCAPTCHA detected — solving with Botright AI...")
            result = await page.solve_recaptcha()
            if result:
                print("    ✅ reCAPTCHA solved!")
                return True
            else:
                print("    ⚠️  reCAPTCHA solve returned falsy — retrying...")
                # One retry
                result = await page.solve_recaptcha()
                if result:
                    print("    ✅ reCAPTCHA solved on retry!")
                    return True
                print("    ❌ reCAPTCHA solve failed")
                return False
    except Exception as e:
        err_str = str(e).lower()
        # "no recaptcha found" is not an error — just means no CAPTCHA on page
        if "no" in err_str and ("found" in err_str or "captcha" in err_str):
            pass
        else:
            print(f"    ⚠️  reCAPTCHA solver error: {e}")

    # Try hCaptcha
    try:
        hcaptcha_el = await page.query_selector(
            ".h-captcha, [data-hcaptcha-sitekey], iframe[src*='hcaptcha']"
        )
        if hcaptcha_el:
            print("    🔐 hCaptcha detected — solving with Botright AI...")
            result = await page.solve_hcaptcha()
            if result:
                print("    ✅ hCaptcha solved!")
                return True
            else:
                print("    ❌ hCaptcha solve failed")
                return False
    except Exception as e:
        err_str = str(e).lower()
        if "no" in err_str and ("found" in err_str or "captcha" in err_str):
            pass
        else:
            print(f"    ⚠️  hCaptcha solver error: {e}")

    # Try GeeTest
    try:
        geetest_el = await page.query_selector(
            ".geetest_holder, .geetest_widget, [data-gt]"
        )
        if geetest_el:
            print("    🔐 GeeTest detected — solving with Botright AI...")
            result = await page.solve_geetest()
            if result:
                print("    ✅ GeeTest solved!")
                return True
            else:
                print("    ❌ GeeTest solve failed")
                return False
    except Exception as e:
        err_str = str(e).lower()
        if "not implemented" in err_str:
            print("    ⚠️  GeeTest solver not available in this Botright version")
        elif "no" in err_str and "found" in err_str:
            pass
        else:
            print(f"    ⚠️  GeeTest solver error: {e}")

    # No CAPTCHA found — all clear
    return True


def is_configured() -> bool:
    """Return True — Botright CAPTCHA solving requires no API keys."""
    return True
