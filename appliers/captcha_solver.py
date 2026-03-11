"""
CAPTCHA Solver — reCAPTCHA v2 solving with two strategies:

1. CapSolver API (primary, when CAPSOLVER_API_KEY is set) — reliable on CI/datacenter IPs
2. Free YOLO + CLIP via recognizer library (fallback, no API key needed)

When CAPSOLVER_API_KEY is configured, goes straight to CapSolver without
wasting attempts on the free solver (failed free attempts make reCAPTCHA harder).
"""

import asyncio
import httpx
from recognizer.agents.playwright import AsyncChallenger

from config import CAPSOLVER_API_KEY

CAPSOLVER_CREATE_URL = "https://api.capsolver.com/createTask"
CAPSOLVER_RESULT_URL = "https://api.capsolver.com/getTaskResult"

# Escalating timeout strategy for the free solver
_ATTEMPT_CONFIGS = [
    {"click_timeout": 1500, "pre_wait": 1000},
    {"click_timeout": 3000, "pre_wait": 2000},
    {"click_timeout": 5000, "pre_wait": 3000},
    {"click_timeout": 8000, "pre_wait": 5000},
]


async def _is_captcha_present(page) -> bool:
    """Check if a reCAPTCHA element exists on the page."""
    el = await page.query_selector(
        ".g-recaptcha, [data-sitekey], iframe[src*='recaptcha']"
    )
    return el is not None


async def _solve_with_capsolver(page) -> bool:
    """
    Solve reCAPTCHA v2 using CapSolver's API.

    Extracts the sitekey, sends a solve task, polls for the token,
    and injects it into the page's reCAPTCHA response field.
    """
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
    print(f"    🔑 CapSolver: Sending solve request...")

    async with httpx.AsyncClient(timeout=120) as client:
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
        print(f"    ⏳ CapSolver: Waiting for solution...")

        for _ in range(60):
            await asyncio.sleep(2)
            resp = await client.post(CAPSOLVER_RESULT_URL, json={
                "clientKey": CAPSOLVER_API_KEY,
                "taskId": task_id,
            })
            result = resp.json()

            if result.get("status") == "ready":
                token = result["solution"]["gRecaptchaResponse"]
                await page.evaluate("""(token) => {
                    // Set the response token
                    const el = document.querySelector('#g-recaptcha-response');
                    if (el) el.value = token;
                    document.querySelectorAll('textarea[name="g-recaptcha-response"]').forEach(
                        el => el.value = token
                    );
                    // Trigger reCAPTCHA callback if registered
                    if (typeof ___grecaptcha_cfg !== 'undefined') {
                        const clients = ___grecaptcha_cfg.clients;
                        if (clients) {
                            Object.keys(clients).forEach(key => {
                                const findCallback = (obj, depth) => {
                                    if (depth > 5 || !obj) return;
                                    Object.keys(obj).forEach(k => {
                                        if (typeof obj[k] === 'function') obj[k](token);
                                        else if (typeof obj[k] === 'object') findCallback(obj[k], depth + 1);
                                    });
                                };
                                findCallback(clients[key], 0);
                            });
                        }
                    }
                }""", token)
                print("    ✅ CapSolver: reCAPTCHA solved!")
                return True

            if result.get("errorId", 0) != 0:
                print(f"    ❌ CapSolver solve error: {result.get('errorDescription', result)}")
                return False

        print("    ❌ CapSolver: Timed out waiting for solution")
        return False


async def _solve_with_free(page, allow_reload: bool) -> bool:
    """Free YOLO+CLIP solver with escalating retries."""
    print("    🔐 Solving with AI (YOLO + CLIP)...")

    for i, cfg in enumerate(_ATTEMPT_CONFIGS):
        attempt_num = i + 1

        if i >= 2 and allow_reload:
            print("    🔄 Reloading page for fresh challenge...")
            try:
                await page.reload(timeout=15000)
                await page.wait_for_timeout(3000)
                if not await _is_captcha_present(page):
                    print("    ✅ CAPTCHA gone after reload!")
                    return True
            except Exception:
                pass

        await page.wait_for_timeout(cfg["pre_wait"])

        try:
            challenger = AsyncChallenger(page, click_timeout=cfg["click_timeout"])
            await challenger.solve_recaptcha()
            print(f"    ✅ reCAPTCHA solved! (attempt {attempt_num})")
            return True
        except Exception as e:
            err_str = str(e).lower()
            if "no" in err_str and ("found" in err_str or "captcha" in err_str):
                return True
            print(f"    ❌ Attempt {attempt_num}/{len(_ATTEMPT_CONFIGS)} failed: {e}")
            if i < len(_ATTEMPT_CONFIGS) - 1:
                await asyncio.sleep(2)

    print("    🚫 All free CAPTCHA solve attempts exhausted")
    return False


async def detect_and_solve(page, allow_reload: bool = True) -> bool:
    """
    Attempt to solve any reCAPTCHA on the current page.

    If CAPSOLVER_API_KEY is set, goes straight to CapSolver (no free attempts).
    Otherwise, uses the free YOLO+CLIP solver with escalating retries.

    Returns True if no CAPTCHA or CAPTCHA was solved, False if blocked.
    """
    if not await _is_captcha_present(page):
        return True

    print("    🔐 reCAPTCHA detected!")

    if CAPSOLVER_API_KEY:
        try:
            return await _solve_with_capsolver(page)
        except Exception as e:
            print(f"    ❌ CapSolver failed: {e}")
            return False
    else:
        return await _solve_with_free(page, allow_reload)


def is_configured() -> bool:
    """Return True — free solver needs no keys, CapSolver is optional."""
    return True
