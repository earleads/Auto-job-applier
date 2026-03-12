#!/usr/bin/env python3
"""
One-time Gmail OAuth setup for email verification code fetching.

Run this locally to generate a refresh token, then add it as a GitHub secret.

Steps:
  1. Go to https://console.cloud.google.com/
  2. Create a new project (or use an existing one)
  3. Enable the Gmail API:  APIs & Services → Library → search "Gmail API" → Enable
  4. Create OAuth credentials:
     a. APIs & Services → Credentials → Create Credentials → OAuth client ID
     b. Application type: "Desktop app"
     c. Download the JSON file → save as 'credentials.json' in this directory
  5. Run this script:  python setup_gmail.py
  6. A browser window opens — sign in with your Gmail account and grant access
  7. Copy the printed GMAIL_REFRESH_TOKEN, GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET
     values into your GitHub repository secrets

That's it! The bot will now use Gmail API to read verification codes.
"""

import json
import sys
from pathlib import Path

try:
    from google_auth_oauthlib.flow import InstalledAppFlow
except ImportError:
    print("Install required packages first:")
    print("  pip install google-auth-oauthlib google-api-python-client")
    sys.exit(1)

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
CREDS_FILE = Path("credentials.json")

def main():
    if not CREDS_FILE.exists():
        print(f"Error: {CREDS_FILE} not found.")
        print()
        print("Download your OAuth credentials from Google Cloud Console:")
        print("  1. Go to https://console.cloud.google.com/apis/credentials")
        print("  2. Click your OAuth 2.0 Client ID → Download JSON")
        print(f"  3. Save the file as '{CREDS_FILE}' in this directory")
        sys.exit(1)

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_FILE), SCOPES)
    creds = flow.run_local_server(port=0)

    # Read client ID and secret from credentials file
    with open(CREDS_FILE) as f:
        client_config = json.load(f)
    # Handle both "installed" and "web" credential types
    client_info = client_config.get("installed") or client_config.get("web", {})

    print()
    print("=" * 60)
    print("SUCCESS! Add these as GitHub repository secrets:")
    print("=" * 60)
    print()
    print(f"  GMAIL_REFRESH_TOKEN  = {creds.refresh_token}")
    print(f"  GMAIL_CLIENT_ID      = {client_info['client_id']}")
    print(f"  GMAIL_CLIENT_SECRET  = {client_info['client_secret']}")
    print()
    print("Go to: GitHub repo → Settings → Secrets → Actions")
    print("Add all three secrets above.")
    print()
    print("You can delete credentials.json now (the refresh token is all you need).")

if __name__ == "__main__":
    main()
