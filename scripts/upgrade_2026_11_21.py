"""One-off upgrade of 21 Nov 2026: every animal marked "sold" without a sale entry (sold at 0 or without a price)
gets its sale entry in Finance (amount = its sale price, 0 when none), so it shows in the operations and counts as
sold. Safe to run twice (an animal with an entry is left alone).

    cd /home/ubuntu/farmivo/farmivo_backend
    /home/ubuntu/farmivo/venvfarmivo/bin/python -m scripts.upgrade_2026_11_21
"""
from __future__ import annotations

from app.repository import Repository, farm_path


def upgrade(repo: Repository) -> int:
    """Returns how many sale entries were created."""
    made = 0
    for farm in repo.list("farms"):
        for a in repo.list(farm_path(farm["id"], "animals"), [("status", "==", "sold")]):
            if a.get("sale_tx_id") and repo.get(farm_path(farm["id"], "transactions"), a["sale_tx_id"]):
                continue
            label = a.get("name") or a.get("ear_tag")
            tx = repo.create(farm_path(farm["id"], "transactions"), {
                "type": "income", "category": "animal_sale", "amount": float(a.get("sale_price") or 0),
                "date": a.get("status_date") or (a.get("updated_at") or "")[:10],
                "description": f"Sale of {label}" + (f" to {a['buyer']}" if a.get("buyer") else ""),
                "animal_id": a["id"]})
            repo.update(farm_path(farm["id"], "animals"), a["id"], {"sale_tx_id": tx["id"]})
            made += 1
    return made


def main() -> None:
    from flask import Flask

    from app.config import get_settings
    from app.deps import _mongo_db
    from app.repository import MongoRepository

    with Flask(__name__).app_context():
        repo = MongoRepository(_mongo_db(), get_settings().mongo_prefix)
        print(f"sale entries created for animals sold without one: {upgrade(repo)}")


if __name__ == "__main__":
    main()
