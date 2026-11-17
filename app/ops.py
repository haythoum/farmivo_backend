"""What the admin dashboard watches (app/admin/views.py): the problems log, which app version each user runs, and
the farms' activity week by week.

- **Problems** (``problems`` collection): server errors (an unexpected exception: HTTP 500 / 503), emails that
  could not be sent (Mailjet refused or unreachable) and pushes that failed. :func:`report` never raises: a
  problem while recording a problem must not break the request. Entries older than ``KEEP_DAYS`` are removed
  now and then.
- **Apps** (fields on ``users/<uid>``): the apps send ``X-Farmivo-Platform`` (android / ios),
  ``X-Farmivo-Version`` ("1.6.0 (16)"), ``X-Farmivo-OS`` ("Android 14", "iOS 17.5") and ``X-Farmivo-Device``
  ("Samsung SM-A155F") with every request; :func:`record_client` keeps the last ones with ``last_seen`` (written
  at most once an hour per user unless something changed) and the account's email (for support: resending the
  verification code).
- **Activity**: :func:`weekly_activity` counts, for each of the last weeks, the new accounts, the new farms and
  the farms where something was recorded (any record created or changed that week); :func:`stopped_farms` lists
  the farms that recorded things before but nothing for a while.
"""
from __future__ import annotations

import logging
import random
import re
import traceback
from datetime import date, datetime, timedelta, timezone

from app.repository import Repository, farm_path

log = logging.getLogger("farmivo.ops")

PROBLEMS = "problems"
KEEP_DAYS = 90
KINDS = ("server_error", "email_failed", "push_failed")
SEEN_EVERY = timedelta(hours=1)
# What the people of a farm record themselves (not notifications, members or counters the server writes).
ACTIVITY_COLLECTIONS = (
    "animals", "barns", "vaccinations", "treatments", "vet_visits", "illnesses", "breedings", "weights",
    "production", "feedings", "transactions", "feed_items", "feed_moves",
)
CLIENT_HEADERS = {
    "app_platform": "X-Farmivo-Platform", "app_version": "X-Farmivo-Version",
    "os_version": "X-Farmivo-OS", "device_model": "X-Farmivo-Device",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _short(value: object, limit: int = 300) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def report(kind: str, message: str, repo: Repository | None = None, **details: object) -> None:
    """Record one problem (``kind`` in KINDS). Without ``repo`` the request's repository is used (nothing is
    recorded outside a request, only logged). Never raises."""
    try:
        if repo is None:
            from flask import has_app_context

            if not has_app_context():
                return
            from app.deps import get_repo

            repo = get_repo()
        entry = {"kind": kind, "message": _short(message), "at": _now().isoformat(timespec="seconds"),
                 **{k: _short(v, 2000 if k == "trace" else 300) for k, v in details.items() if v is not None}}
        repo.create(PROBLEMS, entry)
        if random.random() < 0.05:  # now and then: forget old problems
            prune(repo)
    except Exception:  # noqa: BLE001 - recording a problem must never cause one
        log.exception("Could not record a %s problem", kind)


def report_exception(exc: BaseException, method: str, path: str, uid: str | None = None) -> None:
    """Record an unexpected exception of a request (the last lines of its traceback)."""
    trace = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)[-6:])
    report("server_error", f"{type(exc).__name__}: {exc}", method=method, path=path, uid=uid, trace=trace)


def prune(repo: Repository, keep_days: int = KEEP_DAYS) -> int:
    """Delete the problems older than ``keep_days``; returns how many."""
    limit = (_now() - timedelta(days=keep_days)).isoformat(timespec="seconds")
    old = repo.list(PROBLEMS, [("at", "<", limit)])
    for p in old:
        repo.delete(PROBLEMS, p["id"])
    return len(old)


def problems(repo: Repository, kind: str | None = None, days: int = 30) -> list[dict]:
    """The problems of the last ``days`` days, newest first (one kind or all)."""
    since = (_now() - timedelta(days=days)).isoformat(timespec="seconds")
    filters = [("at", ">=", since)] + ([("kind", "==", kind)] if kind else [])
    return sorted(repo.list(PROBLEMS, filters), key=lambda p: p.get("at") or "", reverse=True)


# --------------------------------------------------------------------------- apps
def client_info(headers) -> dict:
    """The app's platform, version, OS and phone model from the request headers (empty when not an app)."""
    info = {field: _short(headers.get(name), 60) for field, name in CLIENT_HEADERS.items() if headers.get(name)}
    if "app_platform" in info:
        info["app_platform"] = info["app_platform"].lower()
    return info


def record_client(repo: Repository, uid: str, email: str | None, info: dict) -> bool:
    """Keep the user's app details and ``last_seen`` (and email). Writes only when something changed or the last
    write is older than an hour; returns True when it wrote. Never raises."""
    try:
        user = repo.get("users", uid)
        fields = {k: v for k, v in info.items() if (user or {}).get(k) != v}
        if email and (user or {}).get("email") != email:
            fields["email"] = email
        seen = (user or {}).get("last_seen")
        now = _now()
        stale = not seen or now - datetime.fromisoformat(seen) >= SEEN_EVERY
        if not fields and not stale:
            return False
        fields["last_seen"] = now.isoformat(timespec="seconds")
        if user is None:
            repo.set("users", uid, fields)
        else:
            repo.update("users", uid, fields)
        return True
    except Exception:  # noqa: BLE001
        log.exception("Could not record the app details of %s", uid)
        return False


def version_key(version: str | None) -> tuple:
    """Sortable form of "1.6.0 (16)": the build number first when there is one, then the dotted numbers."""
    text = version or ""
    build = re.search(r"\((\d+)\)", text)
    numbers = tuple(int(n) for n in re.findall(r"\d+", text.split("(")[0]))
    return (int(build.group(1)) if build else -1, numbers)


def app_versions(users: list[dict]) -> dict:
    """Platform split and versions in use: {"platforms": {android: n, ios: n, unknown: n}, "versions":
    [{platform, version, users, newest}], "latest": {platform: version}, "old": [user rows on an older version]}."""
    platforms: dict[str, int] = {}
    versions: dict[tuple[str, str], int] = {}
    latest: dict[str, str] = {}
    for u in users:
        platform = u.get("app_platform") or "unknown"
        platforms[platform] = platforms.get(platform, 0) + 1
        if platform == "unknown":
            continue
        version = u.get("app_version") or "?"
        versions[(platform, version)] = versions.get((platform, version), 0) + 1
        if platform not in latest or version_key(version) > version_key(latest[platform]):
            latest[platform] = version
    rows = [{"platform": p, "version": v, "users": n, "newest": latest.get(p) == v}
            for (p, v), n in sorted(versions.items(), key=lambda kv: (kv[0][0], version_key(kv[0][1])), reverse=True)]
    old = [u for u in users if u.get("app_platform") in latest
           and version_key(u.get("app_version")) < version_key(latest[u["app_platform"]])]
    old.sort(key=lambda u: u.get("last_seen") or "", reverse=True)
    return {"platforms": platforms, "versions": rows, "latest": latest, "old": old}


# ----------------------------------------------------------------------- activity
def week_start(day: date) -> date:
    """The Monday of ``day``'s week."""
    return day - timedelta(days=day.weekday())


def _day(stamp: str | None) -> date | None:
    try:
        return datetime.fromisoformat(stamp).date() if stamp else None
    except ValueError:
        return None


def farm_days(repo: Repository, farm_id: str, collections: tuple[str, ...]) -> set[date]:
    """The days on which something of the farm was created or changed."""
    days: set[date] = set()
    for collection in collections:
        for record in repo.list(farm_path(farm_id, collection)):
            for field in ("created_at", "updated_at"):
                d = _day(record.get(field))
                if d:
                    days.add(d)
    return days


def weekly_activity(repo: Repository, collections: tuple[str, ...], weeks: int = 12,
                    today: date | None = None) -> dict:
    """{"weeks": [{"week": "2026-11-16", "signups", "new_farms", "active_farms"}] oldest first,
    "farm_days": {farm_id: set of days}} for the last ``weeks`` weeks (the current one included)."""
    current = week_start(today or _now().date())
    starts = [current - timedelta(weeks=n) for n in range(weeks - 1, -1, -1)]
    rows = {s: {"week": s.isoformat(), "signups": 0, "new_farms": 0, "active_farms": 0} for s in starts}
    for u in repo.list("users"):
        d = _day(u.get("created_at"))
        if d and week_start(d) in rows:
            rows[week_start(d)]["signups"] += 1
    by_farm: dict[str, set[date]] = {}
    for f in repo.list("farms"):
        d = _day(f.get("created_at"))
        if d and week_start(d) in rows:
            rows[week_start(d)]["new_farms"] += 1
        by_farm[f["id"]] = farm_days(repo, f["id"], collections)
        for s in {week_start(day) for day in by_farm[f["id"]]}:
            if s in rows:
                rows[s]["active_farms"] += 1
    return {"weeks": [rows[s] for s in starts], "farm_days": by_farm}


def stopped_farms(farms: list[dict], farm_days_by_id: dict[str, set[date]], quiet_days: int = 21,
                  today: date | None = None) -> list[dict]:
    """Farms that recorded something on at least 2 different days but nothing in the last ``quiet_days`` days:
    [{"farm": farm, "last": date, "days_used": n, "quiet_for": days}], the most recently stopped first."""
    now = today or _now().date()
    out = []
    for f in farms:
        days = farm_days_by_id.get(f["id"]) or set()
        if len(days) < 2:
            continue
        last = max(days)
        if (now - last).days >= quiet_days:
            out.append({"farm": f, "last": last, "days_used": len(days), "quiet_for": (now - last).days})
    out.sort(key=lambda r: r["last"], reverse=True)
    return out
