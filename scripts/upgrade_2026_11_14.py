"""One-off upgrade for the 14 November 2026 release (safe to run more than once):

    cd /home/ubuntu/farmivo/farmivo_backend
    /home/ubuntu/farmivo/venvfarmivo/bin/python -m scripts.upgrade_2026_11_14

Animals that already left the farm (sold, dead, given ...) still sit in their barn: they leave it now, and the
barn is remembered as ``last_barn_id`` (it counts in that barn's balance sheet), like animals that leave from now on.
"""
from __future__ import annotations

import os
import sys

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.repository import Repository, farm_path  # noqa: E402
from app.schemas import LEFT_STATUSES  # noqa: E402


def upgrade(repo: Repository) -> int:
    """Returns how many animals left their barn."""
    moved = 0
    for farm in repo.list("farms"):
        path = farm_path(farm["id"], "animals")
        for a in repo.list(path):
            if a.get("status") in LEFT_STATUSES and a.get("barn_id"):
                repo.update(path, a["id"], {"last_barn_id": a["barn_id"], "barn_id": None})
                moved += 1
    return moved


def main() -> None:
    from flask import Flask

    from app.config import get_settings
    from app.deps import _mongo_db
    from app.repository import MongoRepository

    with Flask(__name__).app_context():
        repo = MongoRepository(_mongo_db(), get_settings().mongo_prefix)
        print(f"animals that had left the farm, taken out of their barn: {upgrade(repo)}")


if __name__ == "__main__":
    main()
