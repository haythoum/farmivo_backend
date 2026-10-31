from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.config import get_settings
from app.deps import get_notifier, get_repo
from app.repository import Repository
from app.services.notifier import Notifier
from app.services.reminders import run_due_reminders

router = APIRouter(prefix="/internal", tags=["Internal"], include_in_schema=False)


@router.post("/reminders/run")
def run_reminders(
    x_cron_secret: str | None = Header(default=None),
    repo: Repository = Depends(get_repo),
    notifier: Notifier = Depends(get_notifier),
):
    """Called by Cloud Scheduler (e.g. daily at 07:00) to push due reminders."""
    secret = get_settings().cron_secret
    if not secret or not x_cron_secret or not hmac.compare_digest(secret, x_cron_secret):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Forbidden")
    return run_due_reminders(repo, notifier)
