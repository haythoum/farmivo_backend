"""The farm's cash box (caisse, /v1/cash): the money the farm works with.

The owner puts in the starting capital (e.g. 15 000 TND); anyone who works on the farm can add money later
(a top-up: 1 000 TND more makes 16 000); then every expense recorded in Finance (feed, vet, purchases of animals
...) takes money from the box and every income (sales, milk ...) puts money in, by itself. Money taken out of the
box for something else than the farm is an ``out`` movement.

- GET /v1/cash (managers, owner): balance and the movements; counted from the first money put in (``since``):
  income and expenses dated before it are not counted.
- /v1/cash/moves: POST by workers and above (put money in; a worker cannot take money out nor see the box),
  GET / PATCH / DELETE by managers and the owner.
"""
from __future__ import annotations

from flask import Blueprint

from app.deps import Ctx, get_ctx
from app.errors import ApiError
from app.permissions import can_see_finance
from app.routers.crud import build_crud_blueprint, path_of
from app.schemas import CashBoxOut, CashMoveBase, CashMoveOut, CashMoveUpdate
from app.web import out

bp = Blueprint("cash", __name__)

MOVES = "cash_moves"


def _member_name(ctx: Ctx) -> str | None:
    me = ctx.repo.get(path_of(ctx, "members"), ctx.uid) if ctx.uid else None
    return (me or {}).get("name") or (me or {}).get("email")


def _before_create(ctx: Ctx, data: dict) -> dict:
    if data.get("direction") == "out" and not can_see_finance(ctx.role):
        raise ApiError(403, "Only the owner and managers can take money out of the cash box", code="forbidden_role")
    data["by"] = _member_name(ctx)
    return data


moves = build_crud_blueprint(
    name="cash_moves", collection=MOVES, create_model=CashMoveBase, update_model=CashMoveUpdate,
    out_model=CashMoveOut, date_field="date", before_create=_before_create,
)
bp.register_blueprint(moves, url_prefix="/cash/moves")


def r2(v: float) -> float:
    """Rounded to the cent."""
    return round(v + 0.0, 2)


def cash_box(ctx: Ctx) -> dict:
    """The cash box: put in, taken out, income and expenses since the first money put in, and the balance."""
    farm = ctx.repo.get("farms", ctx.farm_id) or {}
    rows = sorted(ctx.repo.list(path_of(ctx, MOVES)), key=lambda m: (m.get("date") or "", m.get("created_at") or ""),
                  reverse=True)
    put_in = sum(float(m["amount"]) for m in rows if m.get("direction") == "in")
    taken_out = sum(float(m["amount"]) for m in rows if m.get("direction") == "out")
    since = min((m["date"] for m in rows if m.get("direction") == "in"), default=None)
    income = expenses = 0.0
    if since:
        for tx in ctx.repo.list(path_of(ctx, "transactions"), [("date", ">=", since)]):
            if tx.get("type") == "income":
                income += float(tx.get("amount") or 0)
            else:
                expenses += float(tx.get("amount") or 0)
    return {"currency": farm.get("currency") or "TND", "since": since, "put_in": r2(put_in), "taken_out": r2(taken_out),
            "income": r2(income), "expenses": r2(expenses), "balance": r2(put_in - taken_out + income - expenses),
            "moves": rows[:100]}


@bp.get("/cash")
def get_cash():
    """GET /v1/cash - the cash box (managers, owner)."""
    return out(CashBoxOut.model_validate(cash_box(get_ctx())))
