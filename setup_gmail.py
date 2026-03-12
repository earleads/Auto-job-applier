#!/usr/bin/env python3
"""
One-time Gmail OAuth setup for email verification code fetching.

Supports two modes:
  - Auto mode (has browser): Opens a browser window for sign-in
  - Manual mode (headless/no browser): Prints a URL to visit, you paste back the auth code

Steps:
  1. Go to https://console.cloud.google.com/
  2. Create a new project (or use an existing one)
  3. Enable the Gmail API:  APIs & Services → Library → search "Gmail API" → Enable
  4. Create OAuth credentials:
     a. APIs & Services → Credentials → Create Credentials → OAuth client ID
     b. Application type: "Desktop app"
     c. Download the JSON file → save as 'credentials.json' in this directory
  5. Run this script:  python setup_gmail.py
  6. Follow the prompts (browser or manual URL)
  7. Copy the printed GMAIL_REFRESH_TOKEN, GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET
     values into your GitHub repository secrets

That's it! The bot will now use Gmail API to read verification codes.
"""

import json
import sys
from pathlib import Path
from urllib.parse import urlencode

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
CREDS_FILE = Path("credentials.json")
REDIRECT_URI = "urn:ietf:wg:oauth:2.0:oob"


def _load_client_config():
    """Load and return client_id and client_secret from credentials.json."""
    if not CREDS_FILE.exists():
        print(f"Error: {CREDS_FILE} not found.")
        print()
        print("Download your OAuth credentials from Google Cloud Console:")
        print("  1. Go to https://console.cloud.google.com/apis/credentials")
        print("  2. Click your OAuth 2.0 Client ID → Download JSON")
        print(f"  3. Save the file as '{CREDS_FILE}' in this directory")
        sys.exit(1)

    with open(CREDS_FILE) as f:
        client_config = json.load(f)
    client_info = client_config.get("installed") or client_config.get("web", {})
    return client_info["client_id"], client_info["client_secret"]


def _print_secrets(refresh_token, client_id, client_secret):
    print()
    print("=" * 60)
    print("SUCCESS! Add these as GitHub repository secrets:")
    print("=" * 60)
    print()
    print(f"  GMAIL_REFRESH_TOKEN  = {refresh_token}")
    print(f"  GMAIL_CLIENT_ID      = {client_id}")
    print(f"  GMAIL_CLIENT_SECRET  = {client_secret}")
    print()
    print("Go to: GitHub repo → Settings → Secrets → Actions")
    print("Add all three secrets above.")
    print()
    print("You can delete credentials.json now (the refresh token is all you need).")


def run_manual(client_id, client_secret):
    """Manual OAuth flow — prints URL, user pastes back the authorization code."""
    try:
        import httpx
    except ImportError:
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "httpx"])
        import httpx

    # Build authorization URL
    auth_params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
    }
    auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(auth_params)}"

    print()
    print("Open this URL in any browser and sign in with your Gmail account:")
    print()
    print(f"  {auth_url}")
    print()
    auth_code = input("Paste the authorization code here: ").strip()

    if not auth_code:
        print("No code entered. Aborting.")
        sys.exit(1)

    # Exchange authorization code for tokens
    token_resp = httpx.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": auth_code,
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI,
        },
        timeout=15,
    )

    if token_resp.status_code != 200:
        print(f"Error exchanging code for token: {token_resp.text}")
        sys.exit(1)

    tokens = token_resp.json()
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        print("Error: No refresh token in response. Make sure 'access_type=offline' and 'prompt=consent' are set.")
        print(f"Response: {tokens}")
        sys.exit(1)

    _print_secrets(refresh_token, client_id, client_secret)


def run_browser(client_id, client_secret):
    """Browser-based OAuth flow using google-auth-oauthlib."""
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("google-auth-oauthlib not installed. Falling back to manual mode.")
        print()
        return run_manual(client_id, client_secret)

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_FILE), SCOPES)
    creds = flow.run_local_server(port=0)
    _print_secrets(creds.refresh_token, client_id, client_secret)


def main():
    client_id, client_secret = _load_client_config()

    print()
    print("Gmail OAuth Setup")
    print("-" * 40)
    print("  1. Auto (opens browser window)")
    print("  2. Manual (copy-paste URL + code)")
    print()
    choice = input("Choose mode [1/2, default=2]: ").strip()

    if choice == "1":
        run_browser(client_id, client_secret)
    else:
        run_manual(client_id, client_secret)


if __name__ == "__main__":
    main()
