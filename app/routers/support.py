"""The announcements the admin broadcasts (/v1/announcements): a signed-in account, no farm needed.

Announcements: written in the admin dashboard (/admin/broadcast) in English, French and/or Arabic; sent as a push
to every phone and listed here for 30 days so the apps show each one once (in a dialog) even when the push was
missed. Each user reads it in their language (English when that language was left empty).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from flask import Blueprint

from app.deps import get_identity, get_repo
from app.i18n import normalize, request_lang
from app.web import out

bp = Blueprint("support", __name__)

ANNOUNCEMENTS = "announcements"
SHOW_DAYS = 30


def announcement_text(record: dict, lang: str) -> tuple[str, str]:
    """(title, body) of an announcement in ``lang`` (English, then any filled language, when it is empty)."""
    order = [lang, "en", "fr", "ar"]
    for code in order:
        if (record.get(f"body_{code}") or "").strip():
            return (record.get(f"title_{code}") or "Farmivo").strip(), record[f"body_{code}"].strip()
    return "Farmivo", ""


@bp.get("/announcements")
def list_announcements():
    """GET /v1/announcements - the admin's announcements of the last 30 days, newest first:
    [{"id", "title", "body", "sent_at"}] in the user's language. The apps show each id once."""
    identity = get_identity()
    repo = get_repo()
    user = repo.get("users", identity.uid) or {}
    lang = normalize(user.get("lang")) or request_lang()
    since = (datetime.now(timezone.utc) - timedelta(days=SHOW_DAYS)).isoformat(timespec="seconds")
    rows = sorted((a for a in repo.list(ANNOUNCEMENTS) if (a.get("created_at") or "") >= since),
                  key=lambda a: a.get("created_at") or "", reverse=True)
    result = []
    for a in rows:
        title, text = announcement_text(a, lang)
        if text:
            result.append({"id": a["id"], "title": title, "body": text, "sent_at": a.get("created_at")})
    return out(result)
