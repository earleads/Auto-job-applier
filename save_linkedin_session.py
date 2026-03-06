"""
Save LinkedIn Session — Cookie Import Helper

Since this runs in a headless/web environment (no GUI browser),
use one of these methods to provide your LinkedIn session cookies:

METHOD 1 — Browser DevTools (recommended):
    1. Log into LinkedIn in your normal browser
    2. Open DevTools (F12) → Application → Cookies → linkedin.com
    3. Copy the value of the "li_at" cookie (this is your session token)
    4. Run: python save_linkedin_session.py --token "YOUR_LI_AT_VALUE"

METHOD 2 — Cookie export extension:
    1. Install a cookie export extension (e.g. "EditThisCookie" or "Cookie-Editor")
    2. Go to linkedin.com while logged in
    3. Export cookies as JSON
    4. Save the file as data/linkedin_cookies.json

METHOD 3 — Interactive paste:
    1. Run: python save_linkedin_session.py
    2. Paste your li_at token when prompted
"""

import json
import os
import sys

COOKIES_PATH = "data/linkedin_cookies.json"


def build_linkedin_cookies(li_at_token: str) -> list[dict]:
    """Build a Playwright-compatible cookie list from the li_at session token."""
    return [
        {
            "name": "li_at",
            "value": li_at_token,
            "domain": ".linkedin.com",
            "path": "/",
            "httpOnly": True,
            "secure": True,
            "sameSite": "None",
        },
        {
            "name": "JSESSIONID",
            "value": "ajax:0000000000000000000",
            "domain": ".linkedin.com",
            "path": "/",
            "httpOnly": False,
            "secure": True,
            "sameSite": "None",
        },
    ]


def save_cookies(cookies: list[dict]):
    os.makedirs(os.path.dirname(COOKIES_PATH), exist_ok=True)
    with open(COOKIES_PATH, "w") as f:
        json.dump(cookies, f, indent=2)
    print(f"Saved {len(cookies)} cookies to {COOKIES_PATH}")


def main():
    # Method 1: --token flag
    if "--token" in sys.argv:
        idx = sys.argv.index("--token")
        if idx + 1 < len(sys.argv):
            token = sys.argv[idx + 1].strip().strip('"').strip("'")
        else:
            print("Error: --token requires a value")
            sys.exit(1)

    # Method 2: --file flag (import full cookie JSON)
    elif "--file" in sys.argv:
        idx = sys.argv.index("--file")
        if idx + 1 < len(sys.argv):
            with open(sys.argv[idx + 1]) as f:
                cookies = json.load(f)
            save_cookies(cookies)
            return
        else:
            print("Error: --file requires a path")
            sys.exit(1)

    # Method 3: interactive prompt
    else:
        print("LinkedIn Session Cookie Import")
        print("=" * 40)
        print()
        print("To get your li_at token:")
        print("  1. Log into LinkedIn in your browser")
        print("  2. Open DevTools (F12) -> Application -> Cookies -> linkedin.com")
        print("  3. Find the cookie named 'li_at' and copy its value")
        print()
        token = input("Paste your li_at cookie value: ").strip().strip('"').strip("'")

    if not token:
        print("Error: empty token")
        sys.exit(1)

    cookies = build_linkedin_cookies(token)
    save_cookies(cookies)
    print("LinkedIn session ready. The agent can now use LinkedIn Easy Apply.")


if __name__ == "__main__":
    main()
