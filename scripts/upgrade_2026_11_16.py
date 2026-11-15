"""One-off upgrade for the 16 November 2026 release (safe to run more than once):

    cd /home/ubuntu/farmivo/farmivo_backend
    /home/ubuntu/farmivo/venvfarmivo/bin/python -m scripts.upgrade_2026_11_16

Animals sold together in one finance entry (an "Animal sale" income that names its animals) stayed on the farm
until now. They are sold now with their entry (app/sales.py): status "sold" on the entry's date, each at its share
of the price (the average), out of their barn. Animals that left the farm otherwise (dead, sold alone) are left as
they are.
"""
from __future__ import annotations

import os
import sys

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import sales  # noqa: E402
from app.repository import Repository, farm_path  # noqa: E402


def upgrade(repo: Repository) -> int:
    """Returns how many animals were sold with their sale entry."""
    changed = 0
    for farm in repo.list("farms"):
        for tx in repo.list(farm_path(farm["id"], "transactions")):
            if sales.is_sale(tx):
                changed += sales.sync(repo, farm["id"], tx)
    return changed


def main() -> None:
    from flask import Flask

    from app.config import get_settings
    from app.deps import _mongo_db
    from app.repository import MongoRepository

    with Flask(__name__).app_context():
        repo = MongoRepository(_mongo_db(), get_settings().mongo_prefix)
        print(f"animals sold with their sale entry: {upgrade(repo)}")


if __name__ == "__main__":
    main()
