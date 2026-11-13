""""Forgot password?": email a link to choose a new password, sent by Farmivo through Mailjet.

Firebase's own reset email often never arrived (sent from a firebaseapp.com address that mail providers filter,
and the app showed "sent" even when Firebase refused). Now the server asks Firebase Admin for the reset link and
sends it in a branded email from the validated Farmivo sender, in the app's language, the same way as the
verification codes that do arrive.

The answer never says whether an account exists: unknown addresses get the same 204 (nothing is sent).
Limits per address: 60 seconds between emails and 5 per hour (``password_resets/<hash of the address>``).
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.errors import ApiError
from app.repository import Repository
from app.services.mailer import MailError, Mailer

log = logging.getLogger("farmivo.password_reset")

RESEND_AFTER = timedelta(seconds=60)
MAX_PER_HOUR = 5
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class NoSuchUser(Exception):
    """No Firebase account has this email."""


def now() -> datetime:
    """Current UTC time (a function so the tests can move the clock)."""
    return datetime.now(timezone.utc)


def _key(email: str) -> str:
    return hashlib.sha256(email.encode()).hexdigest()


def with_lang(link: str, lang: str) -> str:
    """The Firebase action link with ``lang`` set, so the "new password" page is in the app's language."""
    parts = urlsplit(link)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "lang"] + [("lang", lang)]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def firebase_link(email: str) -> str:
    """Ask Firebase Admin for a password reset link. Raises NoSuchUser for an unknown email."""
    from firebase_admin import auth

    from app.deps import _firebase_app

    _firebase_app()
    try:
        return auth.generate_password_reset_link(email)
    except auth.UserNotFoundError as exc:
        raise NoSuchUser(email) from exc


def send_reset(repo: Repository, mailer: Mailer, email: str, lang: str,
               make_link: Callable[[str], str] = firebase_link) -> None:
    """Email a reset link to ``email`` if it has an account. 422 invalid address, 429 too soon / too many,
    502 when the link or the email cannot be made (logged). Unknown addresses return normally."""
    address = (email or "").strip().lower()
    if not EMAIL_RE.match(address):
        raise ApiError(422, "Enter a valid email address", code="invalid_email")
    current = now()
    key = _key(address)
    record = repo.get("password_resets", key) or {}
    sent = [datetime.fromisoformat(t) for t in record.get("sent_at", [])]
    sent = [t for t in sent if current - t < timedelta(hours=1)]
    if sent and current - sent[-1] < RESEND_AFTER:
        wait = int((RESEND_AFTER - (current - sent[-1])).total_seconds()) + 1
        raise ApiError(429, f"Please wait {wait} seconds before asking again", code="too_soon",
                       extra={"retry_after": wait})
    if len(sent) >= MAX_PER_HOUR:
        raise ApiError(429, "Too many requests. Try again in an hour", code="too_many")
    # Count the attempt before anything else, so unknown and known addresses are limited the same way.
    repo.set("password_resets", key, {"sent_at": [t.isoformat(timespec="seconds") for t in sent + [current]]})
    try:
        link = make_link(address)
    except NoSuchUser:
        log.info("Password reset asked for an address without an account")
        return
    except Exception as exc:  # noqa: BLE001 - missing service-account key, Firebase unreachable
        log.error("Could not create a password reset link: %s", exc)
        raise ApiError(502, "We could not send the email. Try again later", code="email_failed") from exc
    try:
        mailer.send_password_reset(address, with_lang(link, lang), lang)
    except MailError as exc:
        log.error("Could not send the password reset email: %s", exc)
        raise ApiError(502, "We could not send the email. Try again later", code="email_failed") from exc
