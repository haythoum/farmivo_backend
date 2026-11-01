"""Email verification with a 6-digit code, sent after sign-up and required before creating or joining a farm.

Storage: ``email_codes/<uid>`` (Mongo collection ``email_codes``) keeps only a hash of the current code, when it
expires, how many wrong attempts were made, and when codes were sent (for the 60 s cooldown and the hourly
limit). The plain code exists only in the email. ``users/<uid>.email_verified`` records success.

A user counts as verified if that flag is set, if Firebase already says the email is verified (token claim), or
if they are already an active farm member (accounts from before verification existed); the last two are saved
to ``users/<uid>`` the first time they are seen.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from app.errors import ApiError
from app.repository import Repository
from app.services.mailer import MailError, Mailer
from app.services.membership import Identity, Membership

CODE_LENGTH = 6
CODE_TTL = timedelta(minutes=15)
RESEND_AFTER = timedelta(seconds=60)
MAX_SENDS_PER_HOUR = 5
MAX_ATTEMPTS = 5


def now() -> datetime:
    """Current UTC time (a function so the tests can move the clock)."""
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


def _parse(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text) if text else None


def hash_code(uid: str, code: str, secret: str) -> str:
    """HMAC-SHA256 of the code, keyed with the server secret and the uid, so a stored hash is useless elsewhere."""
    return hmac.new(f"{secret}:{uid}".encode(), code.encode(), hashlib.sha256).hexdigest()


def is_verified(repo: Repository, identity: Identity, membership: Membership | None = None) -> bool:
    """True if the user's email counts as verified (see the module docstring). Persists the flag when it was
    only implied by the token claim or an active membership."""
    user = repo.get("users", identity.uid) or {}
    if user.get("email_verified"):
        return True
    if identity.email_verified or (membership is not None and membership.status == "active"):
        mark_verified(repo, identity.uid)
        return True
    return False


def mark_verified(repo: Repository, uid: str) -> None:
    """Set ``users/<uid>.email_verified`` (keeping the farm fields already stored there)."""
    user = {k: v for k, v in (repo.get("users", uid) or {}).items()
            if k not in ("id", "created_at", "updated_at")}
    repo.set("users", uid, {**user, "email_verified": True, "email_verified_at": _iso(now())})


def send_code(repo: Repository, mailer: Mailer, identity: Identity, secret: str) -> dict:
    """Create a new code, store its hash and email it. Returns the body of POST /v1/me/verification/send.

    409 already_verified, 400 no_email, 429 too_soon (60 s between codes) or too_many_codes (5 per hour),
    502 email_failed when the mail server refuses.
    """
    if is_verified(repo, identity):
        raise ApiError(409, "Your email is already verified", code="already_verified")
    if not identity.email:
        raise ApiError(400, "Your account has no email address", code="no_email")
    current = now()
    record = repo.get("email_codes", identity.uid) or {}
    last_sent = _parse(record.get("last_sent_at"))
    if last_sent and current - last_sent < RESEND_AFTER:
        wait = int((RESEND_AFTER - (current - last_sent)).total_seconds()) + 1
        raise ApiError(429, f"Please wait {wait} seconds before asking for a new code", code="too_soon",
                       extra={"retry_after": wait})
    recent = [t for t in record.get("sent_at", []) if current - _parse(t) < timedelta(hours=1)]
    if len(recent) >= MAX_SENDS_PER_HOUR:
        raise ApiError(429, "Too many codes requested. Try again in an hour", code="too_many_codes")

    code = "".join(secrets.choice("0123456789") for _ in range(CODE_LENGTH))
    minutes = int(CODE_TTL.total_seconds() // 60)
    try:
        mailer.send_code(identity.email, code, minutes)
    except MailError as exc:
        raise ApiError(502, "We could not send the email. Try again later", code="email_failed") from exc
    repo.set("email_codes", identity.uid, {
        "email": identity.email,
        "code_hash": hash_code(identity.uid, code, secret),
        "expires_at": _iso(current + CODE_TTL),
        "attempts": 0,
        "last_sent_at": _iso(current),
        "sent_at": recent + [_iso(current)],
    })
    return {
        "sent_to": identity.email,
        "resend_after_seconds": int(RESEND_AFTER.total_seconds()),
        "expires_in_seconds": int(CODE_TTL.total_seconds()),
    }


def verify_code(repo: Repository, identity: Identity, code: str, secret: str) -> None:
    """Check the code typed in the app; on success mark the email verified and delete the code.

    400 wrong_code (with the attempts left), 429 too_many_attempts (the code is burnt after 5 wrong tries),
    410 code_expired (expired, burnt or never sent). Already verified users succeed without a code check.
    """
    if is_verified(repo, identity):
        return
    record = repo.get("email_codes", identity.uid)
    expires = _parse((record or {}).get("expires_at"))
    if not record or not record.get("code_hash") or not expires or now() >= expires:
        raise ApiError(410, "The code has expired. Ask for a new one", code="code_expired")
    typed = "".join((code or "").split())
    if hmac.compare_digest(hash_code(identity.uid, typed, secret), record["code_hash"]):
        repo.delete("email_codes", identity.uid)
        mark_verified(repo, identity.uid)
        return
    attempts = int(record.get("attempts", 0)) + 1
    if attempts >= MAX_ATTEMPTS:
        repo.update("email_codes", identity.uid, {"attempts": attempts, "code_hash": None})
        raise ApiError(429, "Too many wrong attempts. Ask for a new code", code="too_many_attempts")
    repo.update("email_codes", identity.uid, {"attempts": attempts})
    left = MAX_ATTEMPTS - attempts
    raise ApiError(400, f"Wrong code. {left} attempt{'s' if left != 1 else ''} left", code="wrong_code")
