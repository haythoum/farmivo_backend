"""Animal sales booked as finance entries (an ``animal_sale`` income that names its animals), e.g. 4 sheep sold
together to a butcher for one price.

The sale is the transaction; the animals follow it (since 16 Nov 2026):

- each animal of the sale leaves the farm as sold: ``status`` "sold", ``status_date`` = the sale's date,
  ``sale_price`` = its share of the price (the price divided by the number of animals: the average price),
  ``sale_tx_id`` = the transaction, and it leaves its barn (``last_barn_id`` keeps it for that barn's figures);
- changing the price or the date of the entry changes them on the animals; an animal taken out of the entry, or
  every animal of a deleted entry, comes back on the farm (into its old barn when it still exists);
- an animal that already left the farm (sold in another sale, dead, given) cannot be sold (checked before saving);
  an animal marked "sold" by hand without a price (no entry, or its own entry at 0) can: the sale gives it its
  price.

A single animal sold from its profile (POST /animals/<id>/status) books its own entry the same way
(``sale_tx_id``); editing that entry in the finance list keeps the animal in step too.
"""
from __future__ import annotations

from app import costs
from app.repository import Repository, farm_path
from app.schemas import ON_FARM_STATUSES


def is_sale(tx: dict) -> bool:
    """An income entry for animals sold."""
    return tx.get("type") == "income" and tx.get("category") == costs.SALE_CATEGORY


def prices(tx: dict) -> dict[str, float]:
    """Each animal's price in the sale: the total divided equally, to the cent (the first animals take the cents
    left over, so the prices add up to the total)."""
    ids = list(dict.fromkeys(costs.tx_animals(tx)))
    if not ids:
        return {}
    cents = round(float(tx["amount"]) * 100)
    base, extra = divmod(cents, len(ids))
    return {animal_id: (base + (1 if n < extra else 0)) / 100 for n, animal_id in enumerate(ids)}


def sold_without_price(animal: dict, repo: Repository | None = None, farm_id: str | None = None) -> bool:
    """Marked "sold" by hand without a price (no sale entry, or since 21 Nov its own entry at 0): a sale entry may
    still give it its price (its entry at 0 is then replaced)."""
    if animal.get("status") != "sold" or animal.get("sale_price"):
        return False
    if not animal.get("sale_tx_id"):
        return True
    own = repo.get(farm_path(farm_id, "transactions"), animal["sale_tx_id"]) if repo and farm_id else None
    return bool(own) and not float(own.get("amount") or 0) and costs.tx_animals(own) in ([], [animal["id"]])


def cannot_sell(repo: Repository, farm_id: str, tx: dict, tx_id: str | None = None) -> dict | None:
    """The first animal of the sale that already left the farm otherwise (not by this same entry), or None."""
    for animal_id in costs.tx_animals(tx):
        animal = repo.get(farm_path(farm_id, "animals"), animal_id)
        if not animal or animal.get("status") in ON_FARM_STATUSES or sold_without_price(animal, repo, farm_id):
            continue
        if tx_id and animal.get("sale_tx_id") == tx_id:
            continue
        return animal
    return None


def back_on_farm(repo: Repository, farm_id: str, animal: dict) -> None:
    """Undo a sale: the animal is on the farm again, in its old barn when that barn still exists."""
    back = animal.get("last_barn_id")
    barn = back if back and repo.get(farm_path(farm_id, "barns"), back) else None
    repo.update(farm_path(farm_id, "animals"), animal["id"], {
        "status": "active", "status_date": None, "sale_price": None, "buyer": None, "sale_tx_id": None,
        "barn_id": barn, "last_barn_id": None,
    })


def sync(repo: Repository, farm_id: str, tx: dict, deleted: bool = False) -> int:
    """Puts the animals in step with the sale entry ``tx`` (just saved, or ``deleted``); returns how many animals
    were sold or updated."""
    path = farm_path(farm_id, "animals")
    selling = prices(tx) if is_sale(tx) and not deleted else {}
    for animal in repo.list(path, [("sale_tx_id", "==", tx["id"])]):
        if animal["id"] not in selling:
            back_on_farm(repo, farm_id, animal)
    changed = 0
    for animal_id, price in selling.items():
        animal = repo.get(path, animal_id)
        if not animal:
            continue
        patch = {"status": "sold", "status_date": tx["date"], "sale_price": price, "sale_tx_id": tx["id"]}
        if animal.get("status") in ON_FARM_STATUSES:
            patch["last_barn_id"] = animal.get("barn_id") or animal.get("last_barn_id")
            patch["barn_id"] = None
            # Pending reminders for an animal that left the farm are no longer useful.
            for reminder in repo.list(farm_path(farm_id, "reminders"),
                                      [("animal_id", "==", animal_id), ("status", "==", "pending")]):
                repo.update(farm_path(farm_id, "reminders"), reminder["id"], {"status": "done"})
        elif animal.get("sale_tx_id") != tx["id"]:
            if not sold_without_price(animal, repo, farm_id):
                continue  # it left the farm otherwise (refused before saving; kept as it is for older entries)
            if animal.get("sale_tx_id"):  # its own entry at 0 gives way to this sale
                repo.delete(farm_path(farm_id, "transactions"), animal["sale_tx_id"])
        if any(animal.get(k) != v for k, v in patch.items()):
            repo.update(path, animal_id, patch)
            changed += 1
    return changed
