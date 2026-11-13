"""Calls made before signing in (/v1/auth/...): today only "Forgot password?"."""
from __future__ import annotations

from flask import Blueprint, current_app

from app.deps import get_mailer, get_repo
from app.i18n import request_lang
from app.schemas import PasswordResetIn
from app.services import password_reset
from app.web import body, no_content

bp = Blueprint("auth", __name__)


@bp.post("/auth/password-reset")
def request_password_reset():
    """POST /v1/auth/password-reset {"email"} - no sign-in needed. Emails a link to choose a new password, in the
    Accept-Language language, when the address has an account. Always 204 for a well-formed address (it does not
    reveal who is registered); 429 too_soon / too_many, 502 email_failed."""
    data = body(PasswordResetIn)
    fake = current_app.config.get("FARMIVO_OVERRIDES", {}).get("reset_link")  # tests
    make_link = fake or password_reset.firebase_link
    password_reset.send_reset(get_repo(), get_mailer(), data.email, request_lang(), make_link)
    return no_content()
