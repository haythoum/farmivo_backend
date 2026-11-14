"""What animals cost and what the herd is worth: per-animal costs (GET /v1/animals/<id>/costs) and the herd's
balance sheet (GET /v1/finance/bilan).

Rules (agreed with the farm, November 2026):

- Buying an animal is capital, not a loss: its purchase price (``purchase_price``, origin not born on the farm)
  goes to "purchases". The app still books a ``purchase_animal`` expense transaction for the cash view; the
  balance sheet never counts that transaction as an expense.
- An expense can be shared between animals (``animal_ids``, or ``animal_id`` for one): each animal carries an
  equal share. An expense of a barn with no animals, or of the whole farm, stays an operating expense.
- An animal still on the farm is worth its purchase price plus the expenses booked on it.
- An animal that died or was given away (deceased, sacrificed, donated, gifted) is lost: its purchase price moves
  from capital to expenses ("dead / given animals").
- profit = (cash in + herd value) - (capital + expenses).
"""
from __future__ import annotations

from app.repository import Repository, farm_path
from app.schemas import DEAD_STATUSES, ON_FARM_STATUSES

# Expense categories shown in the animal's health file.
HEALTH_CATEGORIES = {"veterinary", "medication"}
# Booked automatically from the animal (purchase) and from its sale: never operating expenses or "other income".
PURCHASE_CATEGORY = "purchase_animal"
SALE_CATEGORY = "animal_sale"
LOST_STATUSES = DEAD_STATUSES | {"donated", "gifted"}


def barn_species(barn: dict | None) -> list[str]:
    """The species a barn takes: its ``species_list``, or the single ``species`` of older records; [] = any."""
    if not barn:
        return []
    listed = barn.get("species_list")
    if listed:
        return list(listed)
    return [barn["species"]] if barn.get("species") else []


def tx_animals(tx: dict) -> list[str]:
    """The animals an expense is shared between."""
    ids = list(tx.get("animal_ids") or [])
    if not ids and tx.get("animal_id"):
        ids = [tx["animal_id"]]
    return ids


def share_of(tx: dict) -> float | None:
    """Amount per animal when the transaction is shared between animals, else None."""
    ids = tx_animals(tx)
    return round(float(tx["amount"]) / len(ids), 2) if ids else None


def _bought_price(animal: dict) -> float:
    if animal.get("origin") == "born_on_farm":
        return 0.0
    return float(animal.get("purchase_price") or 0)


def _is_shared_expense(tx: dict) -> bool:
    return tx.get("type") == "expense" and tx.get("category") != PURCHASE_CATEGORY


def animal_cost_lines(repo: Repository, farm_id: str, animal_id: str) -> list[dict]:
    """Every expense (not the purchase itself) that concerns the animal, with the animal's share, newest first."""
    lines = []
    for tx in repo.list(farm_path(farm_id, "transactions")):
        if not _is_shared_expense(tx):
            continue
        ids = tx_animals(tx)
        if animal_id not in ids:
            continue
        lines.append({
            "transaction_id": tx["id"], "date": tx["date"], "category": tx["category"],
            "description": tx.get("description"), "amount": round(float(tx["amount"]) / len(ids), 2),
            "total_amount": float(tx["amount"]), "shared_with": len(ids),
        })
    lines.sort(key=lambda line: line["date"], reverse=True)
    return lines


def animal_costs(repo: Repository, farm_id: str, animal: dict) -> dict:
    """Purchase, expenses, total and (once it left the farm) the result for one animal."""
    lines = animal_cost_lines(repo, farm_id, animal["id"])
    expenses = round(sum(line["amount"] for line in lines), 2)
    health = round(sum(line["amount"] for line in lines if line["category"] in HEALTH_CATEGORIES), 2)
    purchase = _bought_price(animal)
    total = round(purchase + expenses, 2)
    result = None
    if animal.get("status") == "sold":
        result = round(float(animal.get("sale_price") or 0) - total, 2)
    elif animal.get("status") in LOST_STATUSES:
        result = -total
    return {
        "purchase_price": purchase,
        "purchase_date": animal.get("date_added") if purchase else None,
        "lines": lines, "expenses_total": expenses, "health_total": health, "total_cost": total,
        "sale_price": animal.get("sale_price") if animal.get("status") == "sold" else None,
        "result": result,
    }


def _in_barn(animal: dict, barn_id: str) -> bool:
    """The animal is in the barn, or was in it when it left the farm."""
    return animal.get("barn_id") == barn_id or (not animal.get("barn_id") and animal.get("last_barn_id") == barn_id)


def bilan(repo: Repository, farm_id: str, barn_id: str | None = None) -> dict:
    """The herd's balance sheet for the whole farm or one barn (all dates). See the module docstring."""
    animals = repo.list(farm_path(farm_id, "animals"))
    if barn_id:
        animals = [a for a in animals if _in_barn(a, barn_id)]
    by_id = {a["id"]: a for a in animals}

    purchases_total = lost_purchases = 0.0
    purchases_count = lost_count = herd_count = 0
    herd_value = 0.0
    animal_expenses: dict[str, float] = {}
    for a in animals:
        price = _bought_price(a)
        if price > 0:
            purchases_total += price
            purchases_count += 1
        if a.get("status") in LOST_STATUSES:
            lost_count += 1
            lost_purchases += price

    expenses_by: dict[str, float] = {}
    sales_total = other_income = 0.0
    sold_ids: set[str] = set()
    for tx in repo.list(farm_path(farm_id, "transactions")):
        amount = float(tx["amount"])
        ids = tx_animals(tx)
        if tx.get("type") == "income":
            if tx.get("category") == SALE_CATEGORY and ids:
                if any(i in by_id for i in ids):
                    sales_total += amount
                    sold_ids.update(i for i in ids if i in by_id)
            elif not barn_id or tx.get("barn_id") == barn_id or any(i in by_id for i in ids):
                other_income += amount
            continue
        if tx.get("category") == PURCHASE_CATEGORY:
            continue  # the purchase is capital, counted from the animals
        if ids:
            share = amount / len(ids)
            mine = [i for i in ids if i in by_id] if barn_id else ids
            if not mine:
                continue
            part = share * len(mine)
            for i in mine:
                animal_expenses[i] = animal_expenses.get(i, 0.0) + share
        elif barn_id and tx.get("barn_id") != barn_id:
            continue
        else:
            part = amount
        expenses_by[tx["category"]] = expenses_by.get(tx["category"], 0.0) + part

    for a in animals:
        if a.get("status") in ON_FARM_STATUSES:
            herd_count += 1
            herd_value += _bought_price(a) + animal_expenses.get(a["id"], 0.0)

    operating = sum(expenses_by.values())
    capital = purchases_total - lost_purchases
    expenses_total = operating + lost_purchases
    cash_in = sales_total + other_income
    r = lambda v: round(v, 2)  # noqa: E731
    return {
        "barn_id": barn_id,
        "purchases_total": r(purchases_total), "purchases_count": purchases_count,
        "lost_purchases": r(lost_purchases), "capital": r(capital),
        "expenses_by_category": {k: r(v) for k, v in sorted(expenses_by.items())},
        "operating_expenses": r(operating), "lost_count": lost_count, "expenses_total": r(expenses_total),
        "sales_total": r(sales_total), "sales_count": len(sold_ids), "other_income": r(other_income),
        "cash_in": r(cash_in),
        "herd_count": herd_count, "herd_value": r(herd_value),
        "profit": r(cash_in + herd_value - capital - expenses_total),
    }
