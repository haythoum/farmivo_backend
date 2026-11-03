"""Deleting a user's account (``DELETE /v1/me``), as the App Store and Google Play require.

What is deleted:

- always: the user's devices (push tokens), the ``users/<uid>`` record, a pending email code and the
  user's membership or join request, and the notifications about them (join requests) or only for them;
- if the user is the owner and nobody else is an active member: the whole farm, with every record
  (animals, health, breeding, growth, production, feeding, finance, reminders, notifications, members) and
  the animal photos. People who were waiting for approval lose their request;
- if the user is the owner and other active members exist: nothing; 409 ``owner_must_transfer``
  (transfer ownership first, so the farm is not lost for the others).

The Firebase sign-in account is deleted afterwards by the route (best effort).
"""
from __future__ import annotations

import logging

from app.errors import ApiError
from app.repository import Repository, farm_path
from app.services.membership import Identity, members_path, resolve, set_user

log = logging.getLogger("farmivo.account")

# Every collection that lives under farms/<farm_id>/ (see docs/DATA_MODEL.md).
FARM_COLLECTIONS = (
    "animals", "vaccinations", "treatments", "vet_visits", "illnesses", "reminders", "breedings",
    "weights", "production", "feedings", "transactions", "notifications", "members",
)


def delete_account(repo: Repository, photo_store, identity: Identity) -> dict:
    """Delete everything that belongs to the user. Returns {"farm_deleted": bool}.

    Raises ApiError 409 ``owner_must_transfer`` (before deleting anything) when the user owns a farm that
    has other active members.
    """
    uid = identity.uid
    current = resolve(repo, identity)
    farm_deleted = False
    if current.farm and current.status == "active" and current.role == "owner":
        others = [m for m in repo.list(members_path(current.farm["id"]))
                  if m.get("status") == "active" and m["id"] != uid]
        if others:
            raise ApiError(409, "Transfer ownership before deleting your account", code="owner_must_transfer")
        delete_farm(repo, photo_store, current.farm)
        farm_deleted = True
    elif current.farm:
        repo.delete(members_path(current.farm["id"]), uid)
    # also older rejected or pending records in other farms
    for member in repo.group_list("members", [("uid", "==", uid)]):
        repo.delete(members_path(member["parent_id"]), uid)
    # Notifications about the person (their join requests carry name and email) or only for them.
    for field in ("subject_uid", "for_uid"):
        for note in repo.group_list("notifications", [(field, "==", uid)]):
            if note.get("parent_id"):
                repo.delete(farm_path(note["parent_id"], "notifications"), note["id"])

    for device in repo.list(f"users/{uid}/devices"):
        repo.delete(f"users/{uid}/devices", device["id"])
    repo.delete("email_codes", uid)
    repo.delete("users", uid)
    return {"farm_deleted": farm_deleted}


def delete_farm(repo: Repository, photo_store, farm: dict) -> None:
    """Delete a farm with all its records and photos. Pending or rejected requesters are detached first."""
    farm_id = farm["id"]
    for member in repo.list(members_path(farm_id)):
        user = repo.get("users", member["id"]) or {}
        if user.get("farm_id") == farm_id:
            set_user(repo, member["id"], None, None)

    photo_urls = [a["photo_url"] for a in repo.list(farm_path(farm_id, "animals")) if a.get("photo_url")]
    for collection in FARM_COLLECTIONS:
        path = farm_path(farm_id, collection)
        for record in repo.list(path):
            repo.delete(path, record["id"])
    repo.delete("farms", farm_id)

    remover = getattr(photo_store, "delete_farm", None)
    if remover:
        try:
            remover(farm_id, photo_urls)
        except Exception as exc:  # noqa: BLE001 - photos are best effort; the records are already gone
            log.warning("Could not delete the photos of farm %s: %s", farm_id, exc)
