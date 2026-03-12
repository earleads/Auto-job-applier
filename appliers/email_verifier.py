"""
Email verification code extractor for Greenhouse ATS.

Greenhouse sends a security code to the applicant's email after form submission.
This module reads the code via Gmail API (preferred) or IMAP (fallback).

Gmail API setup (recommended — no App Password needed):
  1. Run: python setup_gmail.py
  2. Add GMAIL_REFRESH_TOKEN, GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET as secrets

IMAP fallback:
  - GMAIL_APP_PASSWORD secret (16-char Google App Password)
"""

import asyncio
import base64
import email
import imaplib
import os
import re
from datetime import datetime, timedelta, timezone

# Gmail API credentials (preferred)
GMAIL_REFRESH_TOKEN = os.getenv("GMAIL_REFRESH_TOKEN", "")
GMAIL_CLIENT_ID = os.getenv("GMAIL_CLIENT_ID", "")
GMAIL_CLIENT_SECRET = os.getenv("GMAIL_CLIENT_SECRET", "")

# IMAP fallback
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")


def is_configured() -> bool:
    """Check if email verification is available via either method."""
    gmail_api_ok = all([GMAIL_REFRESH_TOKEN, GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET])
    imap_ok = bool(GMAIL_APP_PASSWORD)
    return gmail_api_ok or imap_ok


def _use_gmail_api() -> bool:
    return all([GMAIL_REFRESH_TOKEN, GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET])


# ---------- Code extraction ----------

CODE_PATTERNS = [
    r"security code field[^:]*:\s*\n?\s*([A-Za-z0-9]{6,10})",
    r"<(?:strong|b|span)[^>]*>\s*([A-Za-z0-9]{6,10})\s*</(?:strong|b|span)>",
    r"(?:security|verification)\s*code[^A-Za-z0-9]*([A-Za-z0-9]{6,10})",
    r"\n\s*([A-Za-z0-9]{6,10})\s*\n",
]


def _extract_code(body: str) -> str | None:
    for pattern in CODE_PATTERNS:
        match = re.search(pattern, body, re.IGNORECASE)
        if match:
            return match.group(1)
    return None


# ---------- Gmail API method ----------

_gmail_api_broken = False  # Set to True if refresh token is invalid (avoid repeated retries)


def _fetch_via_gmail_api(email_address: str, max_age_minutes: int = 10) -> str | None:
    """Fetch verification code using Gmail API with OAuth2 refresh token."""
    global _gmail_api_broken
    if _gmail_api_broken:
        return None

    try:
        import httpx
    except ImportError:
        print("    ⚠️  httpx not installed, cannot use Gmail API")
        return None

    try:
        # Exchange refresh token for access token
        token_resp = httpx.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": GMAIL_CLIENT_ID,
                "client_secret": GMAIL_CLIENT_SECRET,
                "refresh_token": GMAIL_REFRESH_TOKEN,
                "grant_type": "refresh_token",
            },
            timeout=10,
        )
        if token_resp.status_code != 200:
            resp_data = token_resp.json() if token_resp.headers.get("content-type", "").startswith("application/json") else {}
            error_code = resp_data.get("error", "")
            if error_code == "invalid_grant":
                _gmail_api_broken = True
                print("    ⚠️  Gmail refresh token expired or revoked (invalid_grant)")
                print("    ⚠️  If Google Cloud OAuth is in 'Testing' mode, tokens expire after 7 days")
                print("    ⚠️  Fix: re-run 'python setup_gmail.py' locally and update GMAIL_REFRESH_TOKEN secret")
                return None
            print(f"    ⚠️  Gmail API token error: {token_resp.text[:200]}")
            return None

        access_token = token_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {access_token}"}

        # Search for recent Greenhouse emails (searches ALL folders incl. spam)
        after_ts = int((datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)).timestamp())
        # Try multiple search queries from narrow to broad
        search_queries = [
            f"from:greenhouse-mail.io after:{after_ts}",
            f"from:greenhouse after:{after_ts}",
            f"subject:(security code) after:{after_ts}",
            f"subject:(verification code) after:{after_ts}",
        ]
        messages = []
        for query in search_queries:
            search_resp = httpx.get(
                "https://gmail.googleapis.com/gmail/v1/users/me/messages",
                params={"q": query, "maxResults": 3, "includeSpamTrash": True},
                headers=headers,
                timeout=10,
            )
            if search_resp.status_code != 200:
                print(f"    ⚠️  Gmail API search error: {search_resp.text[:200]}")
                continue
            messages = search_resp.json().get("messages", [])
            if messages:
                break

        if not messages:
            return None

        # Get the most recent message
        msg_id = messages[0]["id"]
        msg_resp = httpx.get(
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg_id}",
            params={"format": "full"},
            headers=headers,
            timeout=10,
        )
        if msg_resp.status_code != 200:
            return None

        msg_data = msg_resp.json()

        # Extract body from the message payload
        body = _extract_body_from_gmail_payload(msg_data.get("payload", {}))
        if body:
            return _extract_code(body)

        # Fallback: try snippet (short preview text)
        snippet = msg_data.get("snippet", "")
        if snippet:
            return _extract_code(snippet)

        return None

    except Exception as e:
        print(f"    ⚠️  Gmail API error: {e}")
        return None


def _extract_body_from_gmail_payload(payload: dict) -> str:
    """Recursively extract text body from Gmail API message payload."""
    mime_type = payload.get("mimeType", "")

    # Direct text part
    if mime_type in ("text/plain", "text/html"):
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

    # Multipart — recurse into parts, prefer text/plain
    parts = payload.get("parts", [])
    plain_body = ""
    html_body = ""
    for part in parts:
        part_mime = part.get("mimeType", "")
        if part_mime == "text/plain":
            data = part.get("body", {}).get("data", "")
            if data:
                plain_body = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        elif part_mime == "text/html":
            data = part.get("body", {}).get("data", "")
            if data:
                html_body = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        elif "multipart" in part_mime:
            nested = _extract_body_from_gmail_payload(part)
            if nested:
                return nested

    return plain_body or html_body


# ---------- IMAP method (fallback) ----------

def _fetch_via_imap(email_address: str, max_age_minutes: int = 10) -> str | None:
    """Fetch verification code via IMAP with App Password."""
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(email_address, GMAIL_APP_PASSWORD)
        mail.select("INBOX")

        since_date = (datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)).strftime("%d-%b-%Y")
        _, msg_ids = mail.search(
            None,
            f'(FROM "no-reply@us.greenhouse-mail.io" SINCE "{since_date}")'
        )

        if not msg_ids[0]:
            _, msg_ids = mail.search(
                None,
                f'(FROM "greenhouse" SUBJECT "security code" SINCE "{since_date}")'
            )

        if not msg_ids[0]:
            mail.logout()
            return None

        latest_id = msg_ids[0].split()[-1]
        _, msg_data = mail.fetch(latest_id, "(RFC822)")
        mail.logout()

        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email)

        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                if content_type == "text/plain":
                    body = part.get_payload(decode=True).decode("utf-8", errors="replace")
                    break
                elif content_type == "text/html" and not body:
                    body = part.get_payload(decode=True).decode("utf-8", errors="replace")
        else:
            body = msg.get_payload(decode=True).decode("utf-8", errors="replace")

        return _extract_code(body)

    except Exception as e:
        print(f"    ⚠️  Email fetch error: {e}")
        return None


# ---------- Public API ----------

def _fetch_greenhouse_code(email_address: str, max_age_minutes: int = 10) -> str | None:
    """Try Gmail API first, fall back to IMAP."""
    if _use_gmail_api():
        result = _fetch_via_gmail_api(email_address, max_age_minutes)
        if result:
            return result

    if GMAIL_APP_PASSWORD:
        return _fetch_via_imap(email_address, max_age_minutes)

    return None


async def fetch_verification_code(email_address: str, max_wait: int = 120, poll_interval: int = 8) -> str | None:
    """
    Poll Gmail for a Greenhouse verification code.

    Waits up to max_wait seconds, checking every poll_interval seconds.
    Returns the code string, or None if not found in time.
    """
    if not is_configured():
        print("    ⚠️  Gmail not configured — cannot fetch verification code")
        print("    ⚠️  Run 'python setup_gmail.py' to set up Gmail API access")
        return None

    method = "Gmail API" if _use_gmail_api() else "IMAP"
    print(f"    📧 Waiting for Greenhouse verification email... (via {method})")
    elapsed = 0
    while elapsed < max_wait:
        code = await asyncio.get_event_loop().run_in_executor(
            None, _fetch_greenhouse_code, email_address
        )
        if code:
            print(f"    📧 Got verification code: {code}")
            return code
        elapsed += poll_interval
        if elapsed < max_wait:
            await asyncio.sleep(poll_interval)

    print(f"    ⚠️  No verification email received within {max_wait}s")
    return None
