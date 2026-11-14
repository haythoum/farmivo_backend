"""Income and expenses: transactions CRUD and the finance summary (/v1/transactions, /v1/finance/summary)."""

from __future__ import annotations

from datetime import date, timedelta

import re

from flask import Blueprint

from app import costs
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


def _prepare(ctx: Ctx, data: dict) -> dict:
    """Check the barn and the animals of a transaction; for a whole barn, take its animals on the farm now.
    One animal (animal_id) and a list (animal_ids) are kept in step."""
    barn_id = data.get("barn_id")
    if barn_id and not ctx.repo.get(path_of(ctx, "barns"), barn_id):
        raise ApiError(404, "Barn not found")
    if data.get("whole_barn"):
        if not barn_id:
            raise ApiError(422, "Choose the barn")
        data["animal_ids"] = [a["id"] for a in ctx.repo.list(path_of(ctx, "animals"), [("barn_id", "==", barn_id)])
                              if a.get("status") in ON_FARM_STATUSES]
    ids = list(dict.fromkeys(data.get("animal_ids") or []))
    if not ids and data.get("animal_id"):
        ids = [data["animal_id"]]
    for animal_id in ids:
        get_animal_or_404(ctx, animal_id)
    data["animal_ids"] = ids
    data["animal_id"] = ids[0] if len(ids) == 1 else None
    return data


def _before_update(ctx: Ctx, existing: dict, merged: dict) -> dict:
    # A whole-barn expense keeps the animals it was shared between unless the barn changed.
    if merged.get("whole_barn") and merged.get("barn_id") == existing.get("barn_id") and existing.get("animal_ids"):
        merged = {**merged, "whole_barn": False, "animal_ids": existing["animal_ids"]}
        merged = _prepare(ctx, merged)
        merged["whole_barn"] = True
        return merged
    return _prepare(ctx, merged)


def _enrich(record: dict) -> dict:
    from app.deps import get_ctx as _ctx

    ctx = _ctx()
    barn = ctx.repo.get(path_of(ctx, "barns"), record["barn_id"]) if record.get("barn_id") else None
    return {**record, "label": tx_label(record, request_lang()), "barn_name": (barn or {}).get("name"),
            "share": costs.share_of(record) if len(costs.tx_animals(record)) > 1 else None}


transactions = build_crud_blueprint(
    name="transactions",
    collection="transactions",
    create_model=TransactionBase,
    update_model=TransactionUpdate,
    out_model=TransactionOut,
    date_field="date",
    before_create=_prepare,
    before_update=_before_update,
    enrich=_enrich,
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
