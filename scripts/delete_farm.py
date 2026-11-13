"""Delete one farm and everything in it (admin tool, run on the server). For now the apps cannot delete a farm.

    cd /home/ubuntu/farmivo/farmivo_backend
    /home/ubuntu/farmivo/venvfarmivo/bin/python -m scripts.delete_farm                # list the farms
    /home/ubuntu/farmivo/venvfarmivo/bin/python -m scripts.delete_farm --find Bizerte # search by farm name or email
    /home/ubuntu/farmivo/venvfarmivo/bin/python -m scripts.delete_farm <farm_id>      # show what will go, then delete

Deleting shows what the farm holds and asks you to type the farm's name; nothing is deleted before that
(``--dry-run`` only shows). It removes the farm, every record under it (animals, barns, health, breeding,
growth, milk, feeding, finance, reminders, notifications, members) and the animal photos, the same way as when
an owner deletes their account in the app. The people of the farm keep their sign-in (Firebase) and their
``users`` record; they simply have no farm any more and the app offers them to create or join one.
There is no undo: take a backup first if in doubt (``mongodump``).
"""
from __future__ import annotations

import argparse
import sys

from app.repository import Repository, farm_path
from app.services.account import FARM_COLLECTIONS, delete_farm
from app.services.membership import members_path


def _owner(repo: Repository, farm_id: str) -> dict:
    for m in repo.list(members_path(farm_id)):
        if m.get("role") == "owner":
            return m
    return {}


def describe(repo: Repository, farm: dict) -> str:
    """One line per farm: id, name, owner, members, animals, creation date."""
    owner = _owner(repo, farm["id"])
    members = [m for m in repo.list(members_path(farm["id"])) if m.get("status") == "active"]
    animals = repo.list(farm_path(farm["id"], "animals"))
    return (f"{farm['id']}  {farm.get('name') or '(no name)'}  ·  owner {owner.get('email') or owner.get('name') or '?'}"
            f"  ·  {len(members)} members  ·  {len(animals)} animals  ·  created {str(farm.get('created_at', ''))[:10]}")


def find(repo: Repository, text: str = "") -> list[dict]:
    """Farms whose name, id, owner or member email contains ``text`` (all farms when empty)."""
    text = text.strip().lower()
    out = []
    for farm in repo.list("farms"):
        hay = [farm["id"], farm.get("name") or ""]
        hay += [(m.get("email") or "") + " " + (m.get("name") or "") for m in repo.list(members_path(farm["id"]))]
        if not text or any(text in h.lower() for h in hay):
            out.append(farm)
    return sorted(out, key=lambda f: str(f.get("created_at", "")))


def contents(repo: Repository, farm_id: str) -> dict[str, int]:
    """Number of records in each of the farm's collections (only the non-empty ones)."""
    counts = {c: len(repo.list(farm_path(farm_id, c))) for c in FARM_COLLECTIONS}
    return {c: n for c, n in counts.items() if n}


def run(repo: Repository, photo_store, argv: list[str], ask=input, say=print) -> int:
    """The command line; returns the exit code (``ask``/``say`` are replaceable for tests)."""
    p = argparse.ArgumentParser(prog="python -m scripts.delete_farm", description="Delete one farm and all its data.")
    p.add_argument("farm_id", nargs="?", help="the farm to delete (see the list)")
    p.add_argument("--find", default="", help="list only farms whose name, id or member email contains this")
    p.add_argument("--dry-run", action="store_true", help="show what would be deleted, delete nothing")
    a = p.parse_args(argv)

    if not a.farm_id:
        farms = find(repo, a.find)
        for farm in farms:
            say(describe(repo, farm))
        say(f"{len(farms)} farm(s). To delete one: python -m scripts.delete_farm <farm_id>")
        return 0

    farm = repo.get("farms", a.farm_id)
    if not farm:
        say(f"No farm with id {a.farm_id}.")
        return 1
    say(describe(repo, farm))
    for collection, n in contents(repo, farm["id"]).items():
        say(f"  {collection:<14} {n}")
    for m in repo.list(members_path(farm["id"])):
        say(f"  member: {m.get('email') or m.get('name') or m['id']} ({m.get('role')}, {m.get('status')})")
    if a.dry_run:
        say("Dry run: nothing deleted.")
        return 0
    name = farm.get("name") or farm["id"]
    if ask(f"This deletes the farm and all its data for good. Type the farm name ({name}) to confirm: ").strip() != name:
        say("Not confirmed: nothing deleted.")
        return 1
    delete_farm(repo, photo_store, farm)
    say(f"Farm {name} ({farm['id']}) deleted.")
    return 0


def main() -> None:
    from flask import Flask

    from app.config import get_settings
    from app.deps import _mongo_db, _photo_store
    from app.repository import MongoRepository

    with Flask(__name__).app_context():
        repo = MongoRepository(_mongo_db(), get_settings().mongo_prefix)
        try:
            photos = _photo_store()
        except Exception as exc:  # noqa: BLE001 - the records can still be deleted; say the photos stay
            print(f"Photo storage not reachable ({exc}); the photos will stay, the records are deleted.")
            photos = None
        sys.exit(run(repo, photos, sys.argv[1:]))


if __name__ == "__main__":
    main()
