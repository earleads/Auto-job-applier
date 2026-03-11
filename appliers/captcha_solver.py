"""
CAPTCHA Solver — CapSolver REST API integration for solving CAPTCHAs on ATS forms.

Supports:
  - hCaptcha (HCaptchaTaskProxyLess)
  - reCAPTCHA v2 (ReCaptchaV2TaskProxyLess)
  - reCAPTCHA v3 (ReCaptchaV3TaskProxyLess)
  - Cloudflare Turnstile (AntiTurnstileTaskProxyLess)
  - FunCaptcha / Arkose Labs (FunCaptchaTaskProxyLess)

Requires CAPSOLVER_API_KEY environment variable.
Pricing: ~$0.50-$2.00 per 1000 solves depending on CAPTCHA type.
"""

import asyncio
import os
import httpx
from playwright.async_api import Page


CAPSOLVER_API_KEY = os.getenv("CAPSOLVER_API_KEY", "")
CAPSOLVER_BASE = "https://api.capsolver.com"

# JavaScript to detect CAPTCHA type and sitekey on a page.
# Detection order matters: hCaptcha elements also have data-sitekey,
# so we check hCaptcha BEFORE reCAPTCHA.
DETECT_CAPTCHA_JS = """
() => {
    const r = {type: null, sitekey: null};

    // 1. hCaptcha (check FIRST — hCaptcha uses data-sitekey too)
    const hc = document.querySelector('.h-captcha, [data-hcaptcha-sitekey]');
    if (hc) {
        r.type = 'hcaptcha';
        r.sitekey = hc.dataset.sitekey || hc.dataset.hcaptchaSitekey;
    }
    if (!r.type) {
        const hcScript = document.querySelector('script[src*="hcaptcha.com"], iframe[src*="hcaptcha.com"]');
        if (hcScript) {
            const el = document.querySelector('[data-sitekey]');
            if (el) { r.type = 'hcaptcha'; r.sitekey = el.dataset.sitekey; }
        }
    }

    // 2. Cloudflare Turnstile
    if (!r.type) {
        const ts = document.querySelector('.cf-turnstile, [data-turnstile-sitekey]');
        if (ts) {
            r.type = 'turnstile';
            r.sitekey = ts.dataset.sitekey || ts.dataset.turnstileSitekey;
        }
        if (!r.type && document.querySelector('script[src*="turnstile"], iframe[src*="turnstile"]')) {
            const el = document.querySelector('[data-sitekey]');
            if (el) { r.type = 'turnstile'; r.sitekey = el.dataset.sitekey; }
        }
    }

    // 3. reCAPTCHA v3 (invisible, loaded via render= param)
    if (!r.type) {
        const s = document.querySelector('script[src*="recaptcha"][src*="render="]');
        if (s) {
            const m = s.src.match(/render=([^&]+)/);
            if (m && m[1] !== 'explicit') { r.type = 'recaptchav3'; r.sitekey = m[1]; }
        }
    }

    // 4. reCAPTCHA v2 (checkbox or invisible)
    if (!r.type) {
        const rc = document.querySelector('.g-recaptcha');
        if (rc) { r.type = 'recaptchav2'; r.sitekey = rc.dataset.sitekey; }
    }
    if (!r.type && document.querySelector('script[src*="recaptcha"]')) {
        const el = document.querySelector('[data-sitekey]');
        if (el) { r.type = 'recaptchav2'; r.sitekey = el.dataset.sitekey; }
    }

    // 5. FunCaptcha (Arkose Labs)
    if (!r.type) {
        const fc = document.querySelector('#FunCaptcha, [data-pkey], .funcaptcha');
        if (fc) { r.type = 'funcaptcha'; r.sitekey = fc.dataset.pkey; }
    }
    if (!r.type && document.querySelector('script[src*="arkoselabs"], script[src*="funcaptcha"]')) {
        const el = document.querySelector('[data-pkey]');
        if (el) { r.type = 'funcaptcha'; r.sitekey = el.dataset.pkey; }
    }

    return r;
}
"""

# Map CAPTCHA type to CapSolver task type
TASK_TYPE_MAP = {
    "hcaptcha": "HCaptchaTaskProxyLess",
    "recaptchav2": "ReCaptchaV2TaskProxyLess",
    "recaptchav3": "ReCaptchaV3TaskProxyLess",
    "turnstile": "AntiTurnstileTaskProxyLess",
    "funcaptcha": "FunCaptchaTaskProxyLess",
}


def is_configured() -> bool:
    """Return True if CapSolver API key is set."""
    return bool(CAPSOLVER_API_KEY)


async def detect_captcha(page: Page) -> dict | None:
    """
    Detect CAPTCHA on the current page.
    Returns dict with 'type' and 'sitekey' if found, None otherwise.
    """
    try:
        result = await page.evaluate(DETECT_CAPTCHA_JS)
        if result and result.get("type") and result.get("sitekey"):
            print(f"    🔐 CAPTCHA detected: {result['type']} (sitekey: {result['sitekey'][:12]}...)")
            return result
        return None
    except Exception as e:
        print(f"    ⚠️  CAPTCHA detection error: {e}")
        return None


async def solve_captcha(page: Page, captcha_info: dict) -> str | None:
    """
    Solve a CAPTCHA using CapSolver REST API.

    Args:
        page: Playwright page (used to get the URL)
        captcha_info: dict with 'type' and 'sitekey'

    Returns:
        Solution token string, or None if solving failed.
    """
    if not CAPSOLVER_API_KEY:
        print("    ⚠️  CAPSOLVER_API_KEY not set — cannot solve CAPTCHA")
        return None

    captcha_type = captcha_info["type"]
    sitekey = captcha_info["sitekey"]
    page_url = page.url

    task_type = TASK_TYPE_MAP.get(captcha_type)
    if not task_type:
        print(f"    ⚠️  Unknown CAPTCHA type: {captcha_type}")
        return None

    # Build task object
    task = {
        "type": task_type,
        "websiteURL": page_url,
        "websiteKey": sitekey,
    }

    # reCAPTCHA v3 needs a pageAction
    if captcha_type == "recaptchav3":
        task["pageAction"] = "submit"

    print(f"    🧩 Sending {captcha_type} to CapSolver...")

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            # Step 1: Create task
            resp = await client.post(
                f"{CAPSOLVER_BASE}/createTask",
                json={
                    "clientKey": CAPSOLVER_API_KEY,
                    "task": task,
                },
            )
            data = resp.json()

            if data.get("errorId", 0) > 0:
                print(f"    ❌ CapSolver createTask error: {data.get('errorDescription', 'unknown')}")
                return None

            task_id = data.get("taskId")
            if not task_id:
                print(f"    ❌ CapSolver returned no taskId")
                return None

            # Step 2: Poll for result (max 120 seconds)
            for attempt in range(60):
                await asyncio.sleep(2)
                result_resp = await client.post(
                    f"{CAPSOLVER_BASE}/getTaskResult",
                    json={
                        "clientKey": CAPSOLVER_API_KEY,
                        "taskId": task_id,
                    },
                )
                result_data = result_resp.json()

                if result_data.get("errorId", 0) > 0:
                    print(f"    ❌ CapSolver poll error: {result_data.get('errorDescription', 'unknown')}")
                    return None

                status = result_data.get("status")
                if status == "ready":
                    solution = result_data.get("solution", {})
                    token = solution.get("gRecaptchaResponse") or solution.get("token")
                    if token:
                        print(f"    ✅ CAPTCHA solved (token: {token[:20]}...)")
                        return token
                    print(f"    ❌ CapSolver returned no token in solution")
                    return None
                elif status == "processing":
                    continue
                else:
                    print(f"    ❌ Unexpected CapSolver status: {status}")
                    return None

            print(f"    ❌ CapSolver timed out after 120s")
            return None

    except Exception as e:
        print(f"    ❌ CapSolver API error: {e}")
        return None


async def inject_token(page: Page, captcha_info: dict, token: str) -> bool:
    """
    Inject a solved CAPTCHA token into the page so the form can be submitted.

    Different CAPTCHA types require different injection methods.
    """
    captcha_type = captcha_info["type"]

    try:
        if captcha_type in ("recaptchav2", "recaptchav3"):
            await page.evaluate(f"""
                (token) => {{
                    // Set all g-recaptcha-response textareas
                    document.querySelectorAll('[name="g-recaptcha-response"]').forEach(el => {{
                        el.value = token;
                        el.style.display = 'block';
                    }});
                    // Trigger callback if available
                    if (window.___grecaptcha_cfg) {{
                        const clients = window.___grecaptcha_cfg.clients;
                        if (clients) {{
                            for (const key of Object.keys(clients)) {{
                                const c = clients[key];
                                // Walk the client object to find the callback
                                const walk = (obj) => {{
                                    if (!obj || typeof obj !== 'object') return;
                                    if (typeof obj.callback === 'function') {{
                                        obj.callback(token);
                                        return;
                                    }}
                                    for (const k of Object.keys(obj)) walk(obj[k]);
                                }};
                                walk(c);
                            }}
                        }}
                    }}
                }}
            """, token)

        elif captcha_type == "hcaptcha":
            await page.evaluate(f"""
                (token) => {{
                    const ta = document.querySelector('[name="h-captcha-response"], textarea[name*="hcaptcha"]');
                    if (ta) ta.value = token;
                    document.querySelectorAll('iframe[data-hcaptcha-response]').forEach(
                        f => f.setAttribute('data-hcaptcha-response', token)
                    );
                    // Trigger hcaptcha callback
                    const cb = document.querySelector('[data-hcaptcha-widget-id]');
                    if (cb && window.hcaptcha) {{
                        try {{ window.hcaptcha.getResponse(cb.dataset.hcaptchaWidgetId); }} catch(e) {{}}
                    }}
                }}
            """, token)

        elif captcha_type == "turnstile":
            await page.evaluate(f"""
                (token) => {{
                    const inp = document.querySelector('[name="cf-turnstile-response"], input[name*="turnstile"]');
                    if (inp) inp.value = token;
                    // Trigger Turnstile callback
                    if (window.turnstile) {{
                        try {{ window.turnstile.getResponse(); }} catch(e) {{}}
                    }}
                }}
            """, token)

        elif captcha_type == "funcaptcha":
            await page.evaluate(f"""
                (token) => {{
                    const inp = document.querySelector('#FunCaptcha-Token, input[name="fc-token"]');
                    if (inp) inp.value = token;
                }}
            """, token)

        else:
            print(f"    ⚠️  No injection method for {captcha_type}")
            return False

        print(f"    💉 Token injected for {captcha_type}")
        return True

    except Exception as e:
        print(f"    ❌ Token injection failed: {e}")
        return False


async def detect_and_solve(page: Page) -> bool:
    """
    Full CAPTCHA handling flow: detect → solve → inject.

    Returns True if CAPTCHA was solved (or no CAPTCHA found), False if blocked.
    Call this after page load and before/after form submission.
    """
    if not is_configured():
        # No API key — check if there's a CAPTCHA; if so, we're blocked
        captcha = await detect_captcha(page)
        if captcha:
            print(f"    🚫 CAPTCHA detected but CAPSOLVER_API_KEY not set — blocked")
            return False
        return True  # No CAPTCHA, proceed normally

    captcha = await detect_captcha(page)
    if not captcha:
        return True  # No CAPTCHA on page

    token = await solve_captcha(page, captcha)
    if not token:
        return False  # Solving failed

    injected = await inject_token(page, captcha, token)
    if not injected:
        return False

    # Brief pause to let the page process the token
    await page.wait_for_timeout(1500)
    return True
