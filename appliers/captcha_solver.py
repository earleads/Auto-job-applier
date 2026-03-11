"""
CAPTCHA Solver — Two-tier reCAPTCHA solving:

1. Free: YOLO + CLIP AI models via the recognizer library (local, no API key)
2. Paid fallback: CapSolver API (requires CAPSOLVER_API_KEY env var)

If the free solver fails and CAPSOLVER_API_KEY is set, automatically falls back
to CapSolver's cloud-based solving which works reliably on CI/datacenter IPs.
"""

import asyncio
import httpx
from recognizer.agents.playwright import AsyncChallenger

from config import CAPSOLVER_API_KEY

CAPSOLVER_CREATE_URL = "https://api.capsolver.com/createTask"
CAPSOLVER_RESULT_URL = "https://api.capsolver.com/getTaskResult"


async def _solve_with_capsolver(page) -> bool:
    """
    Solve reCAPTCHA v2 using CapSolver's API.

    Steps:
    1. Extract the sitekey from the page
    2. Send a solve task to CapSolver
    3. Poll for the result token
    4. Inject the token into the page's reCAPTCHA response field
    """
    # Extract sitekey from the page
    sitekey = await page.evaluate("""() => {
        const el = document.querySelector('[data-sitekey]');
        if (el) return el.getAttribute('data-sitekey');
        const iframe = document.querySelector("iframe[src*='recaptcha']");
        if (iframe) {
            const match = iframe.src.match(/[?&]k=([^&]+)/);
            return match ? match[1] : null;
        }
        return null;
    }""")

    if not sitekey:
        print("    ⚠️  CapSolver: Could not find reCAPTCHA sitekey")
        return False

    page_url = page.url
    print(f"    🔑 CapSolver: Sending solve request (sitekey={sitekey[:12]}...)")

    async with httpx.AsyncClient(timeout=120) as client:
        # Create task
        resp = await client.post(CAPSOLVER_CREATE_URL, json={
            "clientKey": CAPSOLVER_API_KEY,
            "task": {
                "type": "ReCaptchaV2TaskProxyLess",
                "websiteURL": page_url,
                "websiteKey": sitekey,
            }
        })
        data = resp.json()

        if data.get("errorId", 0) != 0:
            print(f"    ❌ CapSolver create error: {data.get('errorDescription', data)}")
            return False

        task_id = data["taskId"]
        print(f"    ⏳ CapSolver: Waiting for solution (task={task_id[:12]}...)")

        # Poll for result (max ~120s)
        for _ in range(60):
            await asyncio.sleep(2)
            resp = await client.post(CAPSOLVER_RESULT_URL, json={
                "clientKey": CAPSOLVER_API_KEY,
                "taskId": task_id,
            })
            result = resp.json()

            if result.get("status") == "ready":
                token = result["solution"]["gRecaptchaResponse"]
                # Inject token into the page
                await page.evaluate(f"""(token) => {{
                    document.querySelector('#g-recaptcha-response').value = token;
                    // Also set in any hidden textareas (some forms use multiple)
                    document.querySelectorAll('textarea[name="g-recaptcha-response"]').forEach(
                        el => el.value = token
                    );
                    // Trigger callback if registered
                    if (typeof ___grecaptcha_cfg !== 'undefined') {{
                        const clients = ___grecaptcha_cfg.clients;
                        if (clients) {{
                            Object.keys(clients).forEach(key => {{
                                const client = clients[key];
                                // Walk the client object to find callback
                                const findCallback = (obj, depth) => {{
                                    if (depth > 5 || !obj) return;
                                    Object.keys(obj).forEach(k => {{
                                        if (typeof obj[k] === 'function') obj[k](token);
                                        else if (typeof obj[k] === 'object') findCallback(obj[k], depth + 1);
                                    }});
                                }};
                                findCallback(client, 0);
                            }});
                        }}
                    }}
                }}""", token)
                print("    ✅ CapSolver: Token injected!")
                return True

            if result.get("errorId", 0) != 0:
                print(f"    ❌ CapSolver solve error: {result.get('errorDescription', result)}")
                return False

        print("    ❌ CapSolver: Timed out waiting for solution")
        return False


async def detect_and_solve(page) -> bool:
    """
    Attempt to solve any reCAPTCHA on the current page.

    Strategy:
    1. Try the free YOLO+CLIP solver (recognizer library)
    2. If that fails and CAPSOLVER_API_KEY is set, fall back to CapSolver API

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

        # One retry with free solver
        try:
            print("    🔄 Retrying...")
            challenger = AsyncChallenger(page, click_timeout=1500)
            await challenger.solve_recaptcha()
            print("    ✅ reCAPTCHA solved on retry!")
            return True
        except Exception as e2:
            print(f"    ❌ Retry failed: {e2}")

    # Free solver failed — try CapSolver if configured
    if CAPSOLVER_API_KEY:
        print("    💳 Free solver failed — falling back to CapSolver API...")
        try:
            return await _solve_with_capsolver(page)
        except Exception as e:
            print(f"    ❌ CapSolver fallback failed: {e}")
            return False
    else:
        print("    💡 Tip: Set CAPSOLVER_API_KEY for reliable CAPTCHA solving on CI")
        return False


def is_configured() -> bool:
    """Return True — free recognizer solver requires no API keys. CapSolver is optional."""
    return True
