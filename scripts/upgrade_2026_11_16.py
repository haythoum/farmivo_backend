"""One-off upgrade for the 16 November 2026 release (safe to run more than once):

    cd /home/ubuntu/farmivo/farmivo_backend
    /home/ubuntu/farmivo/venvfarmivo/bin/python -m scripts.upgrade_2026_11_16

Animals sold together in one finance entry (an "Animal sale" income that names its animals) stayed on the farm
until now. They are sold now with their entry (app/sales.py): status "sold" on the entry's date, each at its share
of the price (the average), out of their barn. Animals already marked "sold" by hand without a price get their
price from the entry. Animals that left the farm otherwise (dead, sold alone with a price, or in an earlier sale
entry) are left as they are; --check lists animals named in several sale entries (their money counted twice).

    ... -m scripts.upgrade_2026_11_16 --check

only shows what it finds (database, farms, each sale entry and the state of its animals) and changes nothing.
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


def check(repo: Repository) -> list[str]:
    """What the upgrade would look at, as lines to print (no passwords, nothing changed)."""
    lines = []
    farms = repo.list("farms")
    lines.append(f"farms: {len(farms)}")
    for farm in farms:
        txs = repo.list(farm_path(farm["id"], "transactions"))
        animals = {a["id"]: a for a in repo.list(farm_path(farm["id"], "animals"))}
        lines.append(f"farm {farm.get('name')!r}: {len(animals)} animals, {len(txs)} entries, "
                     f"{sum(1 for t in txs if t.get('type') == 'income')} income entries")
        for tx in txs:
            if tx.get("type") != "income":
                continue
            ids = sales.costs.tx_animals(tx)
            lines.append(f"  {tx.get('date')} {tx.get('category')!r} {tx.get('amount')} {tx.get('description')!r}: "
                         f"{len(ids)} animal(s) named, barn={tx.get('barn_id')!r}, whole_barn={tx.get('whole_barn')!r}")
            for animal_id in ids:
                a = animals.get(animal_id)
                lines.append(f"    - {animal_id}: " + ("deleted" if not a else
                             f"{a.get('farm_code') or a.get('ear_tag')} status={a.get('status')!r} "
                             f"sale_tx_id={a.get('sale_tx_id')!r} sale_price={a.get('sale_price')!r}"))
        named: dict[str, list[dict]] = {}
        for tx in txs:
            if sales.is_sale(tx):
                for animal_id in sales.costs.tx_animals(tx):
                    named.setdefault(animal_id, []).append(tx)
        for animal_id, in_sales in named.items():
            if len(in_sales) > 1:
                a = animals.get(animal_id) or {}
                lines.append(f"  ! {a.get('farm_code') or a.get('ear_tag') or animal_id} is in {len(in_sales)} sale entries: "
                             + ", ".join(f"{t.get('date')} {t.get('amount')} {t.get('description')!r}" for t in in_sales)
                             + " -> its money is counted in each; take it out of the wrong entries in the app")
    return lines


def main() -> None:
    from flask import Flask

    from app.config import get_settings
    from app.deps import _mongo_db
    from app.repository import MongoRepository

    settings = get_settings()
    with Flask(__name__).app_context():
        repo = MongoRepository(_mongo_db(), settings.mongo_prefix)
        if "--check" in sys.argv:
            print(f"database: {settings.mongo_db!r} on {settings.mongo_host}:{settings.mongo_port}, "
                  f"user {'set' if settings.mongo_user or settings.mongo_uri else 'NOT set'}, "
                  f"collection prefix {settings.mongo_prefix!r}")
            print("\n".join(check(repo)))
            return
        print(f"animals sold with their sale entry: {upgrade(repo)}")


if __name__ == "__main__":
    main()
