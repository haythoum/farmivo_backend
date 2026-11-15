"""What animals cost and what the herd is worth: per-animal costs (GET /v1/animals/<id>/costs) and the herd's
balance sheet (GET /v1/finance/bilan).

Rules (agreed with the farm, November 2026):

- Buying an animal is capital, not a loss: its purchase price (``purchase_price``, origin not born on the farm)
  goes to "purchases". The server books a ``purchase_animal`` expense transaction for it (the animal's
  ``purchase_tx_id``) for the cash view; the balance sheet counts the animal's price, never that transaction.
- A ``purchase_animal`` expense entered by hand (20 sheep bought in one go, or the purchase of an animal deleted
  since) is capital too: it goes to "purchases", shared between its animals when it names them.
- An expense is carried by animals (``animal_ids``, or ``animal_id`` for one): chosen animals, else the barn's
  animals, else every animal on the farm (app/routers/finance.py). Each carries an equal share, except feed, shared
  by age (``weights``: 0-6 months 0.5, 6-12 months 1, 1 year and older 1.5). With no animal to carry it (an empty
  farm or barn) it stays an operating expense.
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


def feed_weights(animals: list[dict], on_date: str) -> list[float]:
    """Feed is eaten by age: 0-6 months 0.5, 6-12 months 1, 1 year and older 1.5 (unknown age: grown, 1.5).
    One weight per animal, in order."""
    from app.utils import age_parts, parse_date

    out = []
    for a in animals:
        _, months, _ = age_parts(parse_date(a.get("date_of_birth")), parse_date(on_date))
        out.append(1.5 if months is None or months >= 12 else 1.0 if months >= 6 else 0.5)
    return out


def shares(tx: dict) -> dict[str, float]:
    """What each animal of the transaction carries: equal parts, or by ``weights`` (feed by age)."""
    ids = tx_animals(tx)
    if not ids:
        return {}
    amount = float(tx["amount"])
    weights = tx.get("weights") or []
    if len(weights) != len(ids) or sum(weights) <= 0:
        weights = [1.0] * len(ids)
    total = sum(weights)
    out: dict[str, float] = {}
    for animal_id, w in zip(ids, weights):
        out[animal_id] = out.get(animal_id, 0.0) + amount * w / total
    return out


def share_of(tx: dict) -> float | None:
    """Amount per animal when the transaction is shared equally between animals, else None (by age: each
    animal's file shows its own part)."""
    ids = tx_animals(tx)
    if not ids or len(set(tx.get("weights") or [1])) > 1:
        return None
    return round(float(tx["amount"]) / len(ids), 2)


def _bought_price(animal: dict) -> float:
    if animal.get("origin") == "born_on_farm":
        return 0.0
    return float(animal.get("purchase_price") or 0)


def auto_purchase_ids(animals: list[dict]) -> set[str]:
    """The purchase expenses the server booked from the animals' prices (counted from the animals instead)."""
    return {a["purchase_tx_id"] for a in animals if a.get("purchase_tx_id")}


def animal_cost_lines(repo: Repository, farm_id: str, animal_id: str, skip: set[str] | None = None) -> list[dict]:
    """Every expense that concerns the animal, with the animal's share, newest first; ``skip`` = the purchase
    expenses booked from animal prices (the animal's own price is shown apart)."""
    skip = skip or set()
    lines = []
    for tx in repo.list(farm_path(farm_id, "transactions")):
        if tx.get("type") != "expense" or tx["id"] in skip:
            continue
        ids = tx_animals(tx)
        if animal_id not in ids:
            continue
        lines.append({
            "transaction_id": tx["id"], "date": tx["date"], "category": tx["category"],
            "description": tx.get("description"), "amount": round(shares(tx)[animal_id], 2),
            "total_amount": float(tx["amount"]), "shared_with": len(ids),
        })
    lines.sort(key=lambda line: line["date"], reverse=True)
    return lines


def animal_costs(repo: Repository, farm_id: str, animal: dict) -> dict:
    """Purchase, expenses, total and (once it left the farm) the result for one animal."""
    skip = auto_purchase_ids(repo.list(farm_path(farm_id, "animals")))
    if animal.get("purchase_tx_id"):
        skip.add(animal["purchase_tx_id"])
    every = animal_cost_lines(repo, farm_id, animal["id"], skip)
    # A purchase entered by hand that names the animal is part of what it cost to buy, not an expense on it.
    bought_by_hand = sum(line["amount"] for line in every if line["category"] == PURCHASE_CATEGORY)
    lines = [line for line in every if line["category"] != PURCHASE_CATEGORY]
    expenses = round(sum(line["amount"] for line in lines), 2)
    health = round(sum(line["amount"] for line in lines if line["category"] in HEALTH_CATEGORIES), 2)
    purchase = round(_bought_price(animal) + bought_by_hand, 2)
    total = round(purchase + expenses, 2)
    result = None
    if animal.get("status") == "sold":
        result = round(float(animal.get("sale_price") or 0) - total, 2)
    elif animal.get("status") in LOST_STATUSES:
        result = -total
    direct = round(sum(line["amount"] for line in lines if line["shared_with"] <= 1), 2)
    on_farm = animal.get("status") in ON_FARM_STATUSES
    return {
        "purchase_price": purchase,
        "purchase_date": animal.get("date_added") if purchase else None,
        "lines": lines, "expenses_total": expenses, "health_total": health, "total_cost": total,
        # direct = booked on this animal alone; shared = its share of expenses split between several animals
        "direct_total": direct, "shared_total": round(expenses - direct, 2),
        # the lowest price it can be sold at without a loss (while it is on the farm)
        "break_even": total if on_farm else None,
        "sale_price": animal.get("sale_price") if animal.get("status") == "sold" else None,
        "sale_date": animal.get("status_date") if animal.get("status") == "sold" else None,
        "result": result,
    }


def r2(value: float) -> float:
    return round(value, 2)


def _in_barn(animal: dict, barn_id: str) -> bool:
    """The animal is in the barn, or was in it when it left the farm."""
    return animal.get("barn_id") == barn_id or (not animal.get("barn_id") and animal.get("last_barn_id") == barn_id)


def bilan(repo: Repository, farm_id: str, barn_id: str | None = None) -> dict:
    """The herd's balance sheet for the whole farm or one barn (all dates). See the module docstring."""
    animals = repo.list(farm_path(farm_id, "animals"))
    booked = auto_purchase_ids(animals)  # purchases counted from the animals' prices
    if barn_id:
        animals = [a for a in animals if _in_barn(a, barn_id)]
    by_id = {a["id"]: a for a in animals}

    purchases_total = lost_purchases = 0.0
    purchases_count = lost_count = herd_count = 0
    herd_value = 0.0
    animal_expenses: dict[str, float] = {}
    hand_bought: dict[str, float] = {}  # share of purchase expenses entered by hand, per animal
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
    sale_txs: dict[str, dict] = {}
    for tx in repo.list(farm_path(farm_id, "transactions")):
        amount = float(tx["amount"])
        ids = tx_animals(tx)
        if tx.get("type") == "income":
            if tx.get("category") == SALE_CATEGORY:
                sale_txs[tx["id"]] = tx
            if tx.get("category") == SALE_CATEGORY and ids:
                if not barn_id or any(i in by_id for i in ids):
                    # Whole farm: a sale stays counted even when the animal was deleted since.
                    sales_total += amount
                    sold_ids.update(i for i in ids if i in by_id or not barn_id)
            elif not barn_id or tx.get("barn_id") == barn_id or any(i in by_id for i in ids):
                other_income += amount
            continue
        if tx.get("category") == PURCHASE_CATEGORY:
            if tx["id"] in booked:
                continue  # counted from the animal's price
            # Entered by hand: capital, shared between its animals when it names them.
            if ids:
                parts = shares(tx)
                mine = [i for i in parts if i in by_id] if barn_id else list(parts)
                if not mine:
                    continue
                purchases_total += sum(parts[i] for i in mine)
                purchases_count += len(mine)
                for i in mine:
                    hand_bought[i] = hand_bought.get(i, 0.0) + parts[i]
            elif not barn_id or tx.get("barn_id") == barn_id:
                purchases_total += amount
            continue
        if ids:
            parts = shares(tx)
            mine = [i for i in parts if i in by_id] if barn_id else list(parts)
            if not mine:
                continue
            part = sum(parts[i] for i in mine)
            for i in mine:
                animal_expenses[i] = animal_expenses.get(i, 0.0) + parts[i]
        elif barn_id and tx.get("barn_id") != barn_id:
            continue
        else:
            part = amount
        expenses_by[tx["category"]] = expenses_by.get(tx["category"], 0.0) + part

    for a in animals:
        if a.get("status") in ON_FARM_STATUSES:
            herd_count += 1
            herd_value += _bought_price(a) + hand_bought.get(a["id"], 0.0) + animal_expenses.get(a["id"], 0.0)
        elif a.get("status") in LOST_STATUSES:
            lost_purchases += hand_bought.get(a["id"], 0.0)

    # Every sold animal still on record: what it cost (purchase + its expenses), what it was sold for (its share of
    # a sale of several animals: the average price), the gain or loss.
    sold = []
    for a in animals:
        if a.get("status") != "sold":
            continue
        bought = _bought_price(a) + hand_bought.get(a["id"], 0.0)
        spent = animal_expenses.get(a["id"], 0.0)
        price = float(a.get("sale_price") or 0)
        sold.append({"id": a["id"], "ear_tag": a.get("ear_tag"), "farm_code": a.get("farm_code"), "name": a.get("name"),
                     "species": a.get("species"), "date": a.get("status_date"), "sale_price": round(price, 2),
                     "purchase_price": round(bought, 2), "expenses": round(spent, 2),
                     "total_cost": round(bought + spent, 2), "result": round(price - bought - spent, 2),
                     "transaction_id": a.get("sale_tx_id")})
    sold.sort(key=lambda x: x["date"] or "", reverse=True)

    # The same animals by sale: one entry per sale (several animals sold together for one price are one sale).
    by_sale: dict[str, dict] = {}
    for item in sold:
        key = item["transaction_id"] or item["id"]
        tx = sale_txs.get(item["transaction_id"] or "", {})
        sale = by_sale.setdefault(key, {
            "transaction_id": item["transaction_id"], "date": tx.get("date") or item["date"],
            "description": tx.get("description"), "category": SALE_CATEGORY, "amount": 0.0,
            "total_cost": 0.0, "result": 0.0, "animals": []})
        sale["animals"].append(item)
        sale["amount"] = r2(sale["amount"] + item["sale_price"])
        sale["total_cost"] = r2(sale["total_cost"] + item["total_cost"])
        sale["result"] = r2(sale["result"] + item["result"])
    sales_list = sorted(by_sale.values(), key=lambda s: s["date"] or "", reverse=True)
    for sale in sales_list:
        sale["count"] = len(sale["animals"])
        sale["average_price"] = r2(sale["amount"] / sale["count"])

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
        "sold": sold, "sales": sales_list, "sales_result": r(sum(x["result"] for x in sold)),
        "profit": r(cash_in + herd_value - capital - expenses_total),
    }
