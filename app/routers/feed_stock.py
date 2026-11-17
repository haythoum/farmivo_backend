"""Feed stock: the feeds kept (barley, bran, hay ...) counted in sacks, and the sacks coming in and going out
(/v1/feed-stock, /v1/feed-stock/items, /v1/feed-stock/moves).

- Sacks **in** with a price per sack book the feed expense in Finance by themselves (category ``feed``, shared by
  the animals on the farm like any feed expense; ``transaction_id`` links them). Changing or deleting the movement
  changes or deletes that expense; deleting the expense in Finance only unlinks the movement.
  Prices are money: only managers and the owner may send ``unit_price`` (workers record sacks only), and
  ``unit_price`` / ``amount`` are hidden from workers and viewers.
- Sacks **out** cannot be more than the stock (422 "Not enough in stock").
- **Low stock**: when sacks going out bring a feed to its ``low_at`` or below, the farm's managers get a
  notification (once, when it crosses the line) and the save answers ``notice`` for the app to show.
- Deleting a feed deletes its movements (the expenses stay in Finance: the money was spent).
"""
from __future__ import annotations

from flask import Blueprint, g, request

from app import costs
from app.deps import Ctx, get_ctx, get_notifier
from app.errors import ApiError
from app.i18n import request_lang, t
from app.permissions import can_see_finance
from app.routers.crud import build_crud_blueprint, path_of
from app.schemas import FeedItemBase, FeedItemOut, FeedItemUpdate, FeedMoveBase, FeedMoveOut, FeedMoveUpdate
from app.services.reminders import notify_farm
from app.web import out

bp = Blueprint("feed_stock", __name__)

ITEMS = "feed_items"
MOVES = "feed_moves"


def r2(value: float) -> float:
    """Rounded to 2 decimals, without a useless ".0"."""
    rounded = round(float(value), 2)
    return int(rounded) if rounded == int(rounded) else rounded


def balance(ctx: Ctx, feed_id: str, without: str | None = None) -> float:
    """Sacks of the feed in stock (in minus out), leaving out the movement ``without`` (being edited)."""
    total = 0.0
    for m in ctx.repo.list(path_of(ctx, MOVES), [("feed_id", "==", feed_id)]):
        if m["id"] != without:
            total += m["sacks"] if m.get("direction") == "in" else -m["sacks"]
    return round(total, 3)


def _feed(ctx: Ctx, feed_id: str) -> dict:
    feed = ctx.repo.get(path_of(ctx, ITEMS), feed_id)
    if not feed:
        raise ApiError(404, "Feed not found")
    return feed


# ------------------------------------------------------------------------ feeds
def _item_view(record: dict) -> dict:
    ctx = get_ctx()
    moves = ctx.repo.list(path_of(ctx, MOVES), [("feed_id", "==", record["id"])])
    left = round(sum(m["sacks"] if m.get("direction") == "in" else -m["sacks"] for m in moves), 3)
    return {**record, "balance": r2(left), "low": left <= float(record.get("low_at") or 0),
            "last_move": max((m.get("date") for m in moves), default=None)}


def _after_item_delete(ctx: Ctx, record: dict) -> None:
    for m in ctx.repo.list(path_of(ctx, MOVES), [("feed_id", "==", record["id"])]):
        ctx.repo.delete(path_of(ctx, MOVES), m["id"])


items = build_crud_blueprint(
    name="feed_items", collection=ITEMS, create_model=FeedItemBase, update_model=FeedItemUpdate,
    out_model=FeedItemOut, enrich=_item_view, after_delete=_after_item_delete,
)
bp.register_blueprint(items, url_prefix="/feed-stock/items")


# -------------------------------------------------------------------- movements
def _check(ctx: Ctx, data: dict, move_id: str | None = None) -> dict:
    feed = _feed(ctx, data["feed_id"])
    if data["direction"] == "out":
        data["unit_price"] = None
        data["supplier"] = None
        left = balance(ctx, feed["id"], without=move_id)
        if data["sacks"] > left + 1e-9:
            raise ApiError(422, f"Not enough in stock: {r2(max(left, 0))} sacks left")
    elif not can_see_finance(ctx.role) and "unit_price" in (request.get_json(silent=True) or {}):
        ctx.require("manager")  # 403: a price books an expense, which is finance
    g.feed_before = balance(ctx, feed["id"], without=move_id)
    return data


def _before_move_create(ctx: Ctx, data: dict) -> dict:
    return _check(ctx, data)


def _before_move_update(ctx: Ctx, existing: dict, merged: dict) -> dict:
    if not can_see_finance(ctx.role) and existing.get("unit_price") is not None:
        merged["unit_price"] = existing["unit_price"]  # a worker never sees the price: keep it
    merged = _check(ctx, merged, existing["id"])
    merged["transaction_id"] = existing.get("transaction_id")
    return merged


def expense_text(feed: dict, move: dict) -> str:
    """The feed expense's description: "Feed bought: Barley, 10 sacks (Supplier)"."""
    text = f"Feed bought: {feed.get('name')}, {r2(move['sacks'])} sacks"
    return f"{text} ({move['supplier']})" if move.get("supplier") else text


def sync_expense(ctx: Ctx, move: dict) -> str | None:
    """Create, update or delete the feed expense of a movement; returns the expense id (None without one)."""
    from app.routers.finance import _prepare

    path = path_of(ctx, "transactions")
    tx_id = move.get("transaction_id")
    existing = ctx.repo.get(path, tx_id) if tx_id else None
    wanted = move.get("direction") == "in" and float(move.get("unit_price") or 0) > 0
    if not wanted:
        if existing:
            ctx.repo.delete(path, existing["id"])
        return None
    feed = ctx.repo.get(path_of(ctx, ITEMS), move["feed_id"]) or {}
    fields = {"amount": round(float(move["sacks"]) * float(move["unit_price"]), 2), "date": move["date"],
              "description": expense_text(feed, move)}
    if existing:
        if existing.get("date") != fields["date"] and len(costs.tx_animals(existing)) > 1:
            animals = [ctx.repo.get(path_of(ctx, "animals"), i) or {} for i in costs.tx_animals(existing)]
            fields["weights"] = costs.feed_weights(animals, fields["date"])
        ctx.repo.update(path, existing["id"], fields)
        return existing["id"]
    data = _prepare(ctx, {"type": "expense", "category": "feed", "barn_id": None, "whole_barn": False,
                          "animal_ids": [], "animal_id": None, **fields})
    return ctx.repo.create(path, data)["id"]


def _after_move_write(ctx: Ctx, record: dict) -> None:
    tx_id = sync_expense(ctx, record)
    if tx_id != record.get("transaction_id"):
        ctx.repo.update(path_of(ctx, MOVES), record["id"], {"transaction_id": tx_id})
    record["transaction_id"] = tx_id
    feed = ctx.repo.get(path_of(ctx, ITEMS), record["feed_id"]) or {}
    left = balance(ctx, record["feed_id"])
    low_at = float(feed.get("low_at") or 0)
    if record.get("direction") == "out" and left <= low_at:
        g.feed_notice = t("msg.feed_low", request_lang(), feed=feed.get("name"), left=r2(left))
        if g.get("feed_before", left + 1) > low_at:  # it just crossed the line: tell the managers once
            notify_farm(ctx.repo, get_notifier(), ctx.farm or {"id": ctx.farm_id}, title_key="push.feed_low_title",
                        body_key="push.feed_low_body", params={"feed": feed.get("name"), "left": r2(left)},
                        type_="feed_low", roles={"owner", "manager"})


def _after_move_delete(ctx: Ctx, record: dict) -> None:
    sync_expense(ctx, {**record, "direction": "out"})  # its expense goes with it


def _move_view(record: dict) -> dict:
    ctx = get_ctx()
    feed = ctx.repo.get(path_of(ctx, ITEMS), record["feed_id"]) or {}
    view = {**record, "feed_name": feed.get("name"), "notice": g.get("feed_notice")}
    if record.get("direction") == "in" and record.get("unit_price") is not None:
        view["amount"] = round(float(record["sacks"]) * float(record["unit_price"]), 2)
    if not can_see_finance(ctx.role):
        view.update(unit_price=None, amount=None, transaction_id=None)
    return view


moves = build_crud_blueprint(
    name="feed_moves", collection=MOVES, create_model=FeedMoveBase, update_model=FeedMoveUpdate,
    out_model=FeedMoveOut, date_field="date", before_create=_before_move_create, before_update=_before_move_update,
    after_write=_after_move_write, after_delete=_after_move_delete, enrich=_move_view,
)
bp.register_blueprint(moves, url_prefix="/feed-stock/moves")


def unlink_expense(ctx: Ctx, tx_id: str) -> None:
    """The feed expense was deleted in Finance: its movement keeps its sacks, without the link."""
    for m in ctx.repo.list(path_of(ctx, MOVES), [("transaction_id", "==", tx_id)]):
        ctx.repo.update(path_of(ctx, MOVES), m["id"], {"transaction_id": None})


@bp.get("/feed-stock")
def stock():
    """GET /v1/feed-stock - every feed with its stock (``balance`` sacks, ``low``), the feeds running low first."""
    ctx = get_ctx()
    rows = [FeedItemOut.model_validate(_item_view(f)) for f in ctx.repo.list(path_of(ctx, ITEMS))]
    rows.sort(key=lambda f: (not f.low, (f.name or "").lower()))
    return out(rows)
