"""Automatic reminders.

Reminders are derived from other records (vaccination ``next_due_date``, vet visit
``follow_up_date``, breeding ``expected_birth_date``). Each source record owns one
reminder with a deterministic id, so create/update/delete of the source keeps the
reminder in sync. ``run_due_reminders`` is called by the daily cron job and pushes
notifications when a reminder enters a new bucket: 7 days, 1 day, due today, overdue.
"""

from __future__ import annotations

import logging
from datetime import date

from app.i18n import DEFAULT, recipient_lang, ref, render
from app.repository import Repository, farm_path
from app.services.notifier import MEMBERS_CHANNEL, REMINDERS_CHANNEL, Notifier
from app.utils import parse_date, today

logger = logging.getLogger(__name__)

BUCKET_OVERDUE = -1


def reminder_bucket(days_until: int) -> int | None:
    """Notification bucket for a number of days until due: -1 overdue, 0 today, 1, 7, or None (not yet)."""
    if days_until < 0:
        return BUCKET_OVERDUE
    if days_until == 0:
        return 0
    if days_until <= 1:
        return 1
    if days_until <= 7:
        return 7
    return None


def animal_label(repo: Repository, farm_id: str, animal_id: str | None) -> str | None:
    """"Name (TAG)" of an animal, or whichever exists, or None."""
    if not animal_id:
        return None
    animal = repo.get(farm_path(farm_id, "animals"), animal_id)
    if not animal:
        return None
    name = animal.get("name")
    tag = animal.get("ear_tag")
    return f"{name} ({tag})" if name and tag else (name or tag)


def sync_reminder(
    repo: Repository,
    farm_id: str,
    reminder_id: str,
    *,
    source_type: str,
    source_id: str,
    animal_id: str | None,
    title: str,
    due_date: str | date | None,
    title_key: str | None = None,
    title_params: dict | None = None,
) -> None:
    """Create/update the reminder owned by a source record, or remove it if there is no date.

    ``title`` is the English text (fallback); ``title_key`` / ``title_params`` let readers get it in their
    own language (see ``reminder_title``).
    """
    path = farm_path(farm_id, "reminders")
    due = parse_date(due_date)
    existing = repo.get(path, reminder_id)
    if due is None:
        if existing:
            repo.delete(path, reminder_id)
        return
    same_date = existing is not None and existing.get("due_date") == due.isoformat()
    repo.set(
        path,
        reminder_id,
        {
            "source_type": source_type,
            "source_id": source_id,
            "animal_id": animal_id,
            "title": title,
            "title_key": title_key,
            "title_params": title_params or {},
            "due_date": due.isoformat(),
            "status": existing.get("status", "pending") if same_date else "pending",
            "notified_buckets": existing.get("notified_buckets", []) if same_date else [],
        },
    )


def reminder_title(record: dict, lang: str | None) -> str:
    """A reminder's title in ``lang`` (server-made reminders), or the stored text (custom reminders)."""
    if record.get("title_key"):
        return render(record["title_key"], lang, record.get("title_params"))
    return record.get("title", "")


def source_title(kind: str, animal: str | None, **params) -> tuple[str, str, dict]:
    """(English title, key, params) for a server-made reminder: kind is vaccination, vet or birth."""
    key = f"reminder.{kind}_animal" if animal else f"reminder.{kind}"
    if animal:
        params["animal"] = animal
    return render(key, DEFAULT, params), key, params


def delete_reminder(repo: Repository, farm_id: str, reminder_id: str) -> None:
    """Delete one reminder of a farm (no error if missing)."""
    repo.delete(farm_path(farm_id, "reminders"), reminder_id)


def farm_member_uids(repo: Repository, farm: dict, roles: set[str] | None = None) -> list[str]:
    """Uids of the farm's active members, optionally only those with one of ``roles``.

    Farms whose members were never resolved (accounts from before memberships) fall back to the farm's
    owner_uid / member_uids.
    """
    members = [m for m in repo.list(farm_path(farm["id"], "members")) if m.get("status") == "active"]
    if members:
        return [m["id"] for m in members if roles is None or m.get("role") in roles]
    legacy = set(farm.get("member_uids") or [])
    if farm.get("owner_uid"):
        legacy.add(farm["owner_uid"])
    if roles is not None and "owner" not in roles:
        return []
    return sorted(legacy)


def device_tokens(repo: Repository, uids: list[str]) -> list[tuple[str, str, str]]:
    """(uid, token, language) for every registered phone of these users. The language is the phone's,
    else the user's last request language, else English."""
    triples: list[tuple[str, str, str]] = []
    for uid in uids:
        user = repo.get("users", uid)
        for device in repo.list(f"users/{uid}/devices"):
            if device.get("token"):
                triples.append((uid, device["token"], recipient_lang(device, user)))
    return triples


def farm_device_tokens(repo: Repository, farm: dict, roles: set[str] | None = None) -> list[tuple[str, str, str]]:
    """(uid, token, language) for the farm's active members (optionally only some roles)."""
    return device_tokens(repo, farm_member_uids(repo, farm, roles))


def _send(repo: Repository, notifier: Notifier, devices: list[tuple[str, str, str]], title_key: str,
          body_key: str, params: dict, data: dict[str, str], channel: str) -> None:
    """Push to the given devices, each in its own language, and forget tokens FCM reports as invalid."""
    by_lang: dict[str, list[str]] = {}
    for _, token, lang in devices:
        by_lang.setdefault(lang, []).append(token)
    invalid: set[str] = set()
    for lang, tokens in by_lang.items():
        invalid |= set(notifier.send(tokens, render(title_key, lang, params), render(body_key, lang, params),
                                     data, channel))
    for uid, token, _ in devices:
        if token in invalid:
            for device in repo.list(f"users/{uid}/devices", [("token", "==", token)]):
                repo.delete(f"users/{uid}/devices", device["id"])


def push_to_users(repo: Repository, notifier: Notifier, uids: list[str], title_key: str, body_key: str,
                  params: dict, data: dict[str, str], channel: str = MEMBERS_CHANNEL) -> None:
    """Push to specific people (e.g. "your request was approved"), in each one's language; nothing is stored
    in a farm's notification list."""
    _send(repo, notifier, device_tokens(repo, uids), title_key, body_key, params, data, channel)


def notify_farm(
    repo: Repository,
    notifier: Notifier,
    farm: dict,
    *,
    title_key: str,
    body_key: str,
    params: dict | None = None,
    type_: str = "info",
    animal_id: str | None = None,
    reminder_id: str | None = None,
    roles: set[str] | None = None,
    channel: str = REMINDERS_CHANNEL,
    subject_uid: str | None = None,
    for_uid: str | None = None,
) -> dict:
    """Store an in-app notification and push it to the devices of the farm's active members.

    The stored record keeps the English text plus the keys and params, so GET /v1/notifications shows it in
    the reader's language; each phone gets the push in its own language. ``roles`` limits the push (not the
    stored notification) to members with those roles, e.g. {"owner", "manager"} for join requests.
    ``subject_uid`` is the person a join request is about (so approving/rejecting can resolve it);
    ``for_uid`` makes the notification personal: only that member sees it and only their phones get the push.
    The push data carries ``notification_id`` so the app can mark the record read when the push is tapped.
    Returns the stored record.
    """
    params = params or {}
    farm_id = farm["id"]
    record = repo.create(
        farm_path(farm_id, "notifications"),
        {
            "title": render(title_key, DEFAULT, params),
            "body": render(body_key, DEFAULT, params),
            "title_key": title_key,
            "body_key": body_key,
            "params": params,
            "type": type_,
            "animal_id": animal_id,
            "reminder_id": reminder_id,
            "subject_uid": subject_uid,
            "for_uid": for_uid,
            "read": False,
        },
    )
    data = {"type": type_, "farm_id": farm_id, "notification_id": record["id"]}
    if animal_id:
        data["animal_id"] = animal_id
    if reminder_id:
        data["reminder_id"] = reminder_id
    devices = device_tokens(repo, [for_uid]) if for_uid else farm_device_tokens(repo, farm, roles)
    _send(repo, notifier, devices, title_key, body_key, params, data, channel)
    return record


MANAGER_ONLY_TYPES = {"join_request"}


def visible_notifications(rows: list[dict], role: str | None, uid: str | None = None) -> list[dict]:
    """The notifications this reader may see: join requests only for managers and the owner, personal ones
    (``for_uid``) only for that person."""
    from app.permissions import at_least

    manager = at_least(role, "manager")
    return [r for r in rows
            if (manager or r.get("type") not in MANAGER_ONLY_TYPES)
            and (not r.get("for_uid") or r.get("for_uid") == uid)]


def is_visible(record: dict | None, role: str | None, uid: str | None) -> bool:
    """True if this reader may see (and mark or delete) the notification."""
    return bool(record) and bool(visible_notifications([record], role, uid))


def resolve_join_requests(repo: Repository, farm_id: str, uid: str) -> None:
    """Mark the "X wants to join" notifications about ``uid`` read once the request is decided (approved,
    rejected, cancelled or removed), so they don't stay unread for the other managers."""
    path = farm_path(farm_id, "notifications")
    for n in repo.list(path, [("type", "==", "join_request"), ("subject_uid", "==", uid)]):
        if not n.get("read") or not n.get("resolved"):
            repo.update(path, n["id"], {"read": True, "resolved": True})


def notification_text(record: dict, lang: str | None) -> dict:
    """A stored notification with title and body in ``lang`` (records from before translations keep theirs)."""
    if record.get("title_key"):
        record = {**record,
                  "title": render(record["title_key"], lang, record.get("params")),
                  "body": render(record.get("body_key", ""), lang, record.get("params"))}
    return record


def when_ref(days: int) -> dict:
    """The translatable "due in N days / tomorrow / today / overdue" part of a reminder push."""
    if days < -1:
        return ref("when.overdue", days=-days)
    if days == -1:
        return ref("when.overdue_one")
    if days == 0:
        return ref("when.today")
    if days == 1:
        return ref("when.tomorrow")
    return ref("when.in_days", days=days)


def run_due_reminders(repo: Repository, notifier: Notifier, as_of: date | None = None) -> dict[str, int]:
    """Send notifications for reminders that entered a new bucket. Returns counters."""
    current = as_of or today()
    stats = {"farms": 0, "notified": 0, "failed_farms": 0}
    for farm in repo.list("farms"):
        stats["farms"] += 1
        try:  # one broken farm (bad record, push error) must not stop the reminders of all the others
            stats["notified"] += _run_farm(repo, notifier, farm, current)
        except Exception:  # noqa: BLE001
            stats["failed_farms"] += 1
            logger.exception("Reminder job failed for farm %s", farm.get("id"))
    return stats


def _run_farm(repo: Repository, notifier: Notifier, farm: dict, current: date) -> int:
    """Push the due reminders of one farm; returns how many were sent."""
    sent = 0
    path = farm_path(farm["id"], "reminders")
    for reminder in repo.list(path, [("status", "==", "pending")]):
        due = parse_date(reminder.get("due_date"))
        if due is None:
            continue
        days = (due - current).days
        bucket = reminder_bucket(days)
        notified = list(reminder.get("notified_buckets") or [])
        if bucket is None or bucket in notified:
            continue
        # The reminder title already names the animal, so the body is just "<title> - <when>".
        if reminder.get("title_key"):
            title = ref(reminder["title_key"], **(reminder.get("title_params") or {}))
        else:
            title = reminder.get("title", "")
        notify_farm(
            repo,
            notifier,
            farm,
            title_key="push.reminder.title",
            body_key="push.reminder.body",
            params={"title": title, "when": when_ref(days)},
            type_=reminder.get("source_type", "reminder"),
            animal_id=reminder.get("animal_id"),
            reminder_id=reminder["id"],
        )
        repo.update(path, reminder["id"], {"notified_buckets": notified + [bucket]})
        sent += 1
    return sent
