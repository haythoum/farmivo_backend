"""Automatic reminders.

Reminders are derived from other records (vaccination ``next_due_date``, vet visit
``follow_up_date``, breeding ``expected_birth_date``). Each source record owns one
reminder with a deterministic id, so create/update/delete of the source keeps the
reminder in sync. ``run_due_reminders`` is called by Cloud Scheduler and pushes
notifications when a reminder enters a new bucket: 7 days, 1 day, due today, overdue.
"""

from __future__ import annotations

import logging
from datetime import date

from app.repository import Repository, farm_path
from app.services.notifier import Notifier
from app.utils import parse_date, today

logger = logging.getLogger(__name__)

BUCKET_OVERDUE = -1


def reminder_bucket(days_until: int) -> int | None:
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
) -> None:
    """Create/update the reminder owned by a source record, or remove it if there is no date."""
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
            "due_date": due.isoformat(),
            "status": existing.get("status", "pending") if same_date else "pending",
            "notified_buckets": existing.get("notified_buckets", []) if same_date else [],
        },
    )


def delete_reminder(repo: Repository, farm_id: str, reminder_id: str) -> None:
    repo.delete(farm_path(farm_id, "reminders"), reminder_id)


def farm_device_tokens(repo: Repository, farm: dict) -> list[tuple[str, str]]:
    """Return (uid, token) pairs for every member of the farm."""
    members = set(farm.get("member_uids") or [])
    if farm.get("owner_uid"):
        members.add(farm["owner_uid"])
    pairs: list[tuple[str, str]] = []
    for uid in members:
        for device in repo.list(f"users/{uid}/devices"):
            if device.get("token"):
                pairs.append((uid, device["token"]))
    return pairs


def notify_farm(
    repo: Repository,
    notifier: Notifier,
    farm: dict,
    *,
    title: str,
    body: str,
    type_: str = "info",
    animal_id: str | None = None,
    reminder_id: str | None = None,
) -> None:
    """Store an in-app notification and push it to the farm's devices."""
    farm_id = farm["id"]
    repo.create(
        farm_path(farm_id, "notifications"),
        {
            "title": title,
            "body": body,
            "type": type_,
            "animal_id": animal_id,
            "reminder_id": reminder_id,
            "read": False,
        },
    )
    pairs = farm_device_tokens(repo, farm)
    data = {"type": type_}
    if animal_id:
        data["animal_id"] = animal_id
    if reminder_id:
        data["reminder_id"] = reminder_id
    invalid = set(notifier.send([t for _, t in pairs], title, body, data))
    if invalid:
        for uid, token in pairs:
            if token in invalid:
                for device in repo.list(f"users/{uid}/devices", [("token", "==", token)]):
                    repo.delete(f"users/{uid}/devices", device["id"])


def run_due_reminders(repo: Repository, notifier: Notifier, as_of: date | None = None) -> dict[str, int]:
    """Send notifications for reminders that entered a new bucket. Returns counters."""
    current = as_of or today()
    stats = {"farms": 0, "notified": 0}
    for farm in repo.list("farms"):
        stats["farms"] += 1
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
            label = animal_label(repo, farm["id"], reminder.get("animal_id"))
            if days < 0:
                when = f"overdue by {-days} day(s)"
            elif days == 0:
                when = "due today"
            elif days == 1:
                when = "due tomorrow"
            else:
                when = f"due in {days} days"
            title = reminder["title"]
            body = f"{label}: {title} is {when}" if label else f"{title} is {when}"
            notify_farm(
                repo,
                notifier,
                farm,
                title="Farmivo reminder",
                body=body,
                type_=reminder.get("source_type", "reminder"),
                animal_id=reminder.get("animal_id"),
                reminder_id=reminder["id"],
            )
            repo.update(path, reminder["id"], {"notified_buckets": notified + [bucket]})
            stats["notified"] += 1
    return stats
