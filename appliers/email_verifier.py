"""
Email verification code extractor for Greenhouse ATS.

Greenhouse sends a security code to the applicant's email after form submission.
This module reads the code via IMAP and returns it for auto-entry.

Requires:
  - GMAIL_APP_PASSWORD secret (16-char Google App Password)
  - Email address from CANDIDATE_PROFILE
"""

import asyncio
import email
import imaplib
import os
import re
from datetime import datetime, timedelta, timezone


GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")


def is_configured() -> bool:
    """Check if email verification is available."""
    return bool(GMAIL_APP_PASSWORD)


def _fetch_greenhouse_code(email_address: str, max_age_minutes: int = 10) -> str | None:
    """
    Connect to Gmail via IMAP and find the latest Greenhouse security code.

    Searches for emails from Greenhouse received within the last max_age_minutes,
    extracts the verification code, and returns it.
    """
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(email_address, GMAIL_APP_PASSWORD)
        mail.select("INBOX")

        # Search for recent Greenhouse verification emails
        since_date = (datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)).strftime("%d-%b-%Y")
        # Search by sender and recency
        _, msg_ids = mail.search(
            None,
            f'(FROM "no-reply@us.greenhouse-mail.io" SINCE "{since_date}")'
        )

        if not msg_ids[0]:
            # Try alternative Greenhouse sender
            _, msg_ids = mail.search(
                None,
                f'(FROM "greenhouse" SUBJECT "security code" SINCE "{since_date}")'
            )

        if not msg_ids[0]:
            mail.logout()
            return None

        # Get the most recent matching email
        latest_id = msg_ids[0].split()[-1]
        _, msg_data = mail.fetch(latest_id, "(RFC822)")
        mail.logout()

        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email)

        # Extract body text
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

        # Extract the security code — Greenhouse uses alphanumeric codes
        # Pattern: "Copy and paste this code into the security code field"
        # followed by the code on the next line (or in a styled element)
        # The code is typically 6-10 alphanumeric characters
        patterns = [
            # Plain text: code on its own line after "code" mention
            r"security code field[^:]*:\s*\n?\s*([A-Za-z0-9]{6,10})",
            # HTML: code in bold/span element
            r"<(?:strong|b|span)[^>]*>\s*([A-Za-z0-9]{6,10})\s*</(?:strong|b|span)>",
            # Fallback: any standalone alphanumeric code near "security code"
            r"(?:security|verification)\s*code[^A-Za-z0-9]*([A-Za-z0-9]{6,10})",
            # Very broad fallback: isolated alphanumeric token in email body
            r"\n\s*([A-Za-z0-9]{6,10})\s*\n",
        ]

        for pattern in patterns:
            match = re.search(pattern, body, re.IGNORECASE)
            if match:
                return match.group(1)

        return None

    except Exception as e:
        print(f"    ⚠️  Email fetch error: {e}")
        return None


async def fetch_verification_code(email_address: str, max_wait: int = 60, poll_interval: int = 5) -> str | None:
    """
    Poll Gmail for a Greenhouse verification code.

    Waits up to max_wait seconds, checking every poll_interval seconds.
    Returns the code string, or None if not found in time.
    """
    if not is_configured():
        print("    ⚠️  GMAIL_APP_PASSWORD not set — cannot fetch verification code")
        return None

    print(f"    📧 Waiting for Greenhouse verification email...")
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
