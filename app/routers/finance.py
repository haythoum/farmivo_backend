"""Income and expenses: transactions CRUD and the finance summary (/v1/transactions, /v1/finance/summary)."""

from __future__ import annotations

from datetime import date, timedelta

import re

from flask import Blueprint

from app import costs, sales
from app.deps import Ctx, get_ctx
from app.errors import ApiError
from app.i18n import request_lang, t
from app.repository import Repository, farm_path
from app.routers.crud import build_crud_blueprint, get_animal_or_404, path_of
from app.schemas import (
    ON_FARM_STATUSES,
    BilanOut,
    FinanceSummary,
    MonthlyFinance,
    TransactionBase,
    TransactionOut,
    TransactionUpdate,
)
from app.utils import today
from app.web import out, q_date, q_str

bp = Blueprint("finance", __name__)

# Descriptions the server writes itself (an animal's purchase or sale), shown in the reader's language.
_AUTO = [
    (re.compile(r"^Purchase of (?P<animal>.+)$"), "tx.purchase"),
    (re.compile(r"^Sale of (?P<animal>.+) to (?P<buyer>.+)$"), "tx.sale_to"),
    (re.compile(r"^Sale of (?P<animal>.+)$"), "tx.sale"),
]


def tx_label(tx: dict, lang: str) -> str | None:
    """The description in ``lang``: the app's own purchase / sale texts are translated, a typed one is kept."""
    text = tx.get("description")
    if not text:
        return None
    for pattern, key in _AUTO:
        m = pattern.match(text)
        if m and tx.get("category") in (costs.PURCHASE_CATEGORY, costs.SALE_CATEGORY):
            return t(key, lang, **m.groupdict())
    return text


def _snapshot(ctx: Ctx, barn_id: str | None) -> list[str]:
    """The animals on the farm now (in ``barn_id``, or anywhere): an expense saved for a barn or the farm is
    shared by the animals there when it is saved, and keeps them."""
    filters = [("barn_id", "==", barn_id)] if barn_id else None
    return [a["id"] for a in ctx.repo.list(path_of(ctx, "animals"), filters) if a.get("status") in ON_FARM_STATUSES]


def _shared(data: dict) -> bool:
    """An expense that its animals carry (not the purchase of an animal, never an income)."""
    return data.get("type") == "expense" and data.get("category") != costs.PURCHASE_CATEGORY


def _prepare(ctx: Ctx, data: dict, tx_id: str | None = None) -> dict:
    """Check the barn and the animals of a transaction. An expense is always carried by animals:
    - chosen animals (``animal_ids``; ``animal_id`` = one, kept in step);
    - the whole barn (``whole_barn``, or a barn and no animal): its animals on the farm;
    - the whole farm (no barn, no animal): every animal on the farm (``whole_farm``).
    With no animal to carry it, it stays a farm expense (operating). Feed is shared by age (``weights``).
    A sale of animals (app/sales.py) only takes animals on the farm (or already sold by this same entry,
    ``tx_id``)."""
    barn_id = data.get("barn_id")
    if barn_id and not ctx.repo.get(path_of(ctx, "barns"), barn_id):
        raise ApiError(404, "Barn not found")
    ids = list(dict.fromkeys(data.get("animal_ids") or []))
    if not ids and data.get("animal_id"):
        ids = [data["animal_id"]]
    data["whole_farm"] = False
    if data.get("whole_barn"):
        if not barn_id:
            raise ApiError(422, "Choose the barn")
        ids = _snapshot(ctx, barn_id)
    elif _shared(data) and not ids:
        if barn_id:
            data["whole_barn"] = True
        else:
            data["whole_farm"] = True
        ids = _snapshot(ctx, barn_id)
    if tx_id:
        # An entry saved before: animals deleted since are left out (their id made the entry impossible to edit).
        found = {i: ctx.repo.get(path_of(ctx, "animals"), i) for i in ids}
        ids = [i for i in ids if found[i]]
        animals = [found[i] for i in ids]
    else:
        animals = [get_animal_or_404(ctx, animal_id) for animal_id in ids]
    if sales.is_sale(data):
        gone = sales.cannot_sell(ctx.repo, ctx.farm_id, {"animal_ids": ids}, tx_id)
        if gone:
            raise ApiError(409, f"{gone.get('farm_code') or gone.get('ear_tag') or gone.get('name') or '?'} is no longer "
                                "on the farm: it cannot be sold. Take it out of this sale")
    data["animal_ids"] = ids
    data["animal_id"] = ids[0] if len(ids) == 1 else None
    data["weights"] = costs.feed_weights(animals, data["date"]) if _shared(data) and data.get("category") == "feed" \
        and len(ids) > 1 else []
    return data


_NO_HAND_PURCHASE = ("Animals bought are added in Animals, with Add animal and their purchase price: they then "
                     "appear in the herd and their purchase is booked here by itself")


def _create(ctx: Ctx, data: dict) -> dict:
    """A purchase of animals is never typed here (it counted the animals twice and left them out of the herd)."""
    if data.get("category") == costs.PURCHASE_CATEGORY:
        raise ApiError(422, _NO_HAND_PURCHASE)
    return _prepare(ctx, data)


def _before_update(ctx: Ctx, existing: dict, merged: dict) -> dict:
    from flask import request

    if merged.get("category") == costs.PURCHASE_CATEGORY and existing.get("category") != costs.PURCHASE_CATEGORY:
        raise ApiError(422, _NO_HAND_PURCHASE)
    sent = request.get_json(silent=True) or {}
    if "animal_ids" in sent and "animal_id" not in sent:
        merged = {**merged, "animal_id": None}  # the list decides (an emptied list clears the one animal too)
    chose_animals = bool(sent.get("animal_ids") or sent.get("animal_id"))
    same_barn = merged.get("barn_id") == existing.get("barn_id") and merged.get("type") == existing.get("type")
    shared_by_all = existing.get("whole_barn") or existing.get("whole_farm")
    if not chose_animals and same_barn and not shared_by_all and not costs.tx_animals(existing) \
            and not merged.get("whole_barn"):
        # An expense saved before expenses were shared (no animal): it stays a farm expense when it is edited, so
        # earlier balance sheets do not change.
        return {**merged, "animal_ids": [], "animal_id": None}
    if shared_by_all and not chose_animals and same_barn and existing.get("animal_ids") \
            and bool(merged.get("whole_barn")) == bool(existing.get("whole_barn")):
        # Same barn (or farm): it keeps the animals it was shared by when it was saved; a new category or date
        # only weighs them again (feed by age).
        kept = {**merged, "animal_ids": existing["animal_ids"], "animal_id": existing.get("animal_id"),
                "whole_farm": existing.get("whole_farm", False)}
        if merged.get("category") == existing.get("category") and merged.get("date") == existing.get("date"):
            return {**kept, "weights": existing.get("weights") or []}
        animals = [ctx.repo.get(path_of(ctx, "animals"), i) or {} for i in kept["animal_ids"]]
        kept["weights"] = costs.feed_weights(animals, kept["date"]) \
            if _shared(kept) and kept.get("category") == "feed" and len(animals) > 1 else []
        return kept
    if shared_by_all and not chose_animals:
        merged = {**merged, "animal_ids": [], "animal_id": None}  # another barn: shared by its animals
    return _prepare(ctx, merged, existing["id"])


def _after_write(ctx: Ctx, record: dict) -> None:
    """A sale of animals: the animals are sold with it (app/sales.py)."""
    sales.sync(ctx.repo, ctx.farm_id, record)


def _after_delete(ctx: Ctx, record: dict) -> None:
    """A deleted sale: its animals are back on the farm."""
    sales.sync(ctx.repo, ctx.farm_id, record, deleted=True)


def _enrich(record: dict) -> dict:
    from app.deps import get_ctx as _ctx

    ctx = _ctx()
    barn = ctx.repo.get(path_of(ctx, "barns"), record["barn_id"]) if record.get("barn_id") else None
    return {**record, "label": tx_label(record, request_lang()), "barn_name": (barn or {}).get("name"),
            "share": costs.share_of(record) if len(costs.tx_animals(record)) > 1 else None}


def _barn_filter(ctx: Ctx, rows: list[dict]) -> list[dict]:
    """?barn_id=: the entries of one barn: booked on it, or carried by its animals (now or when they left)."""
    barn_id = q_str("barn_id")
    if not barn_id:
        return rows
    mine = {a["id"] for a in ctx.repo.list(path_of(ctx, "animals"))
            if a.get("barn_id") == barn_id or (not a.get("barn_id") and a.get("last_barn_id") == barn_id)}
    return [r for r in rows if r.get("barn_id") == barn_id or any(i in mine for i in costs.tx_animals(r))]


transactions = build_crud_blueprint(
    name="transactions",
    collection="transactions",
    create_model=TransactionBase,
    update_model=TransactionUpdate,
    out_model=TransactionOut,
    date_field="date",
    before_create=_create,
    before_update=_before_update,
    after_write=_after_write,
    after_delete=_after_delete,
    enrich=_enrich,
    list_filter=_barn_filter,
)
bp.register_blueprint(transactions, url_prefix="/transactions")


def farm_currency(repo: Repository, farm_id: str) -> str:
    """The farm's currency code (USD if not set)."""
    farm = repo.get("farms", farm_id) or {}
    return farm.get("currency", "USD")


def compute_finance(repo: Repository, farm_id: str, start: date, end: date) -> FinanceSummary:
    """Income, expenses, net, per-category and per-month totals of a farm for a date range."""
    rows = repo.list(
        farm_path(farm_id, "transactions"),
        [("date", ">=", start.isoformat()), ("date", "<=", end.isoformat())],
    )
    income = expenses = 0.0
    income_by: dict[str, float] = {}
    expenses_by: dict[str, float] = {}
    monthly: dict[str, list[float]] = {}
    for r in rows:
        amount = float(r["amount"])
        bucket = monthly.setdefault(r["date"][:7], [0.0, 0.0])
        if r["type"] == "income":
            income += amount
            income_by[r["category"]] = income_by.get(r["category"], 0.0) + amount
            bucket[0] += amount
        else:
            expenses += amount
            expenses_by[r["category"]] = expenses_by.get(r["category"], 0.0) + amount
            bucket[1] += amount
    return FinanceSummary(
        date_from=start,
        date_to=end,
        currency=farm_currency(repo, farm_id),
        income=round(income, 2),
        expenses=round(expenses, 2),
        net=round(income - expenses, 2),
        income_by_category={k: round(v, 2) for k, v in sorted(income_by.items())},
        expenses_by_category={k: round(v, 2) for k, v in sorted(expenses_by.items())},
        monthly=[MonthlyFinance(month=m, income=round(v[0], 2), expenses=round(v[1], 2)) for m, v in sorted(monthly.items())],
    )


@bp.get("/finance/bilan")
def finance_bilan():
    """GET /v1/finance/bilan?barn_id= - the herd's balance sheet (all dates), for the farm or one barn:
    purchases (capital), expenses (with dead / given animals), sales, herd value and the real profit."""
    ctx = get_ctx()
    barn_id = q_str("barn_id") or None
    if barn_id and not ctx.repo.get(path_of(ctx, "barns"), barn_id):
        raise ApiError(404, "Barn not found")
    data = costs.bilan(ctx.repo, ctx.farm_id, barn_id)
    lang = request_lang()
    for sale in data["sales"]:
        sale["label"] = tx_label(sale, lang)
    return out(BilanOut.model_validate({**data, "currency": farm_currency(ctx.repo, ctx.farm_id)}))


@bp.get("/finance/summary")
def finance_summary():
    """Income, expenses and net for a period (defaults to the last 30 days), with category and monthly breakdowns."""
    ctx = get_ctx()
    date_from, date_to = q_date("date_from"), q_date("date_to")
    end = date_to or today()
    start = date_from or end - timedelta(days=29)
    if start > end:
        raise ApiError(422, "date_from must not be after date_to")
    return out(compute_finance(ctx.repo, ctx.farm_id, start, end))
