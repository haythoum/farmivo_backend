from __future__ import annotations

from datetime import date, timedelta

from flask import Blueprint

from app.deps import get_ctx
from app.errors import ApiError
from app.repository import Repository, farm_path
from app.routers.crud import build_crud_blueprint
from app.schemas import (
    FinanceSummary,
    MonthlyFinance,
    TransactionBase,
    TransactionOut,
    TransactionUpdate,
)
from app.utils import today
from app.web import out, q_date

bp = Blueprint("finance", __name__)

transactions = build_crud_blueprint(
    name="transactions",
    collection="transactions",
    create_model=TransactionBase,
    update_model=TransactionUpdate,
    out_model=TransactionOut,
    date_field="date",
)
bp.register_blueprint(transactions, url_prefix="/transactions")


def farm_currency(repo: Repository, farm_id: str) -> str:
    farm = repo.get("farms", farm_id) or {}
    return farm.get("currency", "USD")


def compute_finance(repo: Repository, farm_id: str, start: date, end: date) -> FinanceSummary:
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
