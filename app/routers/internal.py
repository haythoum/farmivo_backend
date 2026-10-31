from __future__ import annotations

import hmac

from flask import Blueprint, request

from app.config import get_settings
from app.deps import get_notifier, get_repo
from app.errors import ApiError
from app.services.reminders import run_due_reminders
from app.web import out

bp = Blueprint("internal", __name__)


@bp.post("/internal/reminders/run")
def run_reminders():
    """Called by a daily cron job (e.g. 07:00) to push due reminders. Needs the X-Cron-Secret header."""
    secret = get_settings().cron_secret
    provided = request.headers.get("X-Cron-Secret")
    if not secret or not provided or not hmac.compare_digest(secret, provided):
        raise ApiError(403, "Forbidden")
    return out(run_due_reminders(get_repo(), get_notifier()))
