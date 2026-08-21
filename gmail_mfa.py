"""
gmail_mfa.py — odbiera kod weryfikacyjny (MFA) wysyłany e-mailem przez Garmina,
żeby logowanie do Garmin Connect mogło przebiegać bez ręcznego wpisywania kodu.

Wymagania:
  - konto Gmail ustawione jako adres logowania w Garmin Connect
  - hasło aplikacji (App Password) do tego konta Gmail:
    https://myaccount.google.com/apppasswords
    (wymaga włączonej weryfikacji dwuetapowej na koncie Gmail)

Zmienne środowiskowe:
  GMAIL_IMAP_EMAIL         — adres Gmail (domyślnie taki sam jak GARMIN_EMAIL)
  GMAIL_IMAP_APP_PASSWORD  — hasło aplikacji Gmail (16 znaków, bez spacji)
"""

import email
import email.utils
import imaplib
import os
import re
import time
from datetime import datetime, timezone

IMAP_HOST = "imap.gmail.com"
CODE_RE = re.compile(r"\b(\d{6})\b")


def fetch_garmin_mfa_code(since: datetime, timeout: int = 120, poll_interval: int = 5) -> str:
    """
    Czeka na maila z kodem MFA od Garmina wysłanego po `since` i zwraca kod.
    Rzuca TimeoutError, jeśli kod nie przyjdzie w ciągu `timeout` sekund.
    """
    gmail_email = os.environ.get("GMAIL_IMAP_EMAIL") or os.environ["GARMIN_EMAIL"]
    app_password = os.environ["GMAIL_IMAP_APP_PASSWORD"]

    deadline = time.monotonic() + timeout
    while True:
        code = _check_inbox_once(gmail_email, app_password, since)
        if code:
            return code
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"Nie znaleziono maila z kodem MFA od Garmina w ciągu {timeout}s. "
                "Sprawdź czy GMAIL_IMAP_EMAIL/GMAIL_IMAP_APP_PASSWORD są poprawne "
                "i czy Garmin faktycznie wysyła kod na ten adres."
            )
        time.sleep(poll_interval)


def _check_inbox_once(gmail_email: str, app_password: str, since: datetime) -> str | None:
    with imaplib.IMAP4_SSL(IMAP_HOST) as imap:
        imap.login(gmail_email, app_password)
        imap.select("INBOX")

        status, data = imap.search(None, 'HEADER FROM "garmin.com"')
        if status != "OK" or not data or not data[0]:
            return None

        msg_ids = data[0].split()[-10:]  # ostatnie 10 maili od Garmina wystarczy
        candidates = []

        for msg_id in msg_ids:
            status, msg_data = imap.fetch(msg_id, "(RFC822)")
            if status != "OK" or not msg_data or not msg_data[0]:
                continue
            msg = email.message_from_bytes(msg_data[0][1])

            msg_date = _parse_email_date(msg.get("Date"))
            if msg_date is None or msg_date < since:
                continue

            code = _extract_code(msg)
            if code:
                candidates.append((msg_date, code))

        if not candidates:
            return None

        candidates.sort(key=lambda c: c[0])
        return candidates[-1][1]


def _parse_email_date(date_header: str | None) -> datetime | None:
    if not date_header:
        return None
    try:
        dt = email.utils.parsedate_to_datetime(date_header)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _extract_code(msg) -> str | None:
    subject = msg.get("Subject", "") or ""
    match = CODE_RE.search(subject)
    if match:
        return match.group(1)

    body = _get_text_body(msg)
    if body:
        match = CODE_RE.search(body)
        if match:
            return match.group(1)

    return None


def _get_text_body(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                try:
                    return part.get_payload(decode=True).decode(errors="replace")
                except Exception:
                    continue
        return ""
    try:
        return msg.get_payload(decode=True).decode(errors="replace")
    except Exception:
        return ""
