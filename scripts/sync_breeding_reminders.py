"""Bring the breeding reminders of every farm in line with the November 2026 rules (run once after deploying):

    /home/ubuntu/farmivo/venvfarmivo/bin/python -m scripts.sync_breeding_reminders   # the venv's Python 3, not "python" (2.7)

Before, a mating that was only "pending" (not checked) already had an "Expected birth" reminder. Now a pending
mating gets a "Pregnancy check" reminder instead, and only a confirmed pregnancy gets "Expected birth".
Safe to run more than once.
"""
from __future__ import annotations

from app.deps import Ctx
from app.repository import Repository, farm_path
from app.routers.breeding import _sync


def sync_all(repo: Repository) -> int:
    """Re-sync the reminders of every breeding of every farm; returns how many breedings were processed."""
    count = 0
    for farm in repo.list("farms"):
        ctx = Ctx(uid="script", farm_id=farm["id"], repo=repo)
        for breeding in repo.list(farm_path(farm["id"], "breedings")):
            _sync(ctx, breeding)
            count += 1
    return count


def main() -> None:
    from flask import Flask

    from app.config import get_settings
    from app.deps import _mongo_db
    from app.repository import MongoRepository

    with Flask(__name__).app_context():
        repo = MongoRepository(_mongo_db(), get_settings().mongo_prefix)
        print(f"breedings checked: {sync_all(repo)}")


if __name__ == "__main__":
    main()
