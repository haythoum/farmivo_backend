"""What a vaccination, a treatment or a vet visit cost (``cost`` on the record): the money is booked in Finance by
itself, as an expense of that animal (since 21 Nov 2026).

- ``cost`` on a vaccination or a vet visit books a ``veterinary`` expense, on a treatment a ``medication``
  expense, carried by the record's animal (``transaction_id`` links them). Changing the cost or the date changes
  the expense; removing the cost or deleting the record deletes it; deleting the expense in Finance only unlinks it.
- A whole barn vaccinated at once (POST /vaccinations/bulk) with a ``cost`` books one expense for the whole
  vaccination, shared by the animals vaccinated.
- Money is finance: only managers and the owner may send ``cost`` (workers get 403 and never see it).
"""
from __future__ import annotations

from flask import request

from app.deps import Ctx, get_ctx
from app.permissions import can_see_finance
from app.repository import farm_path

# collection -> (expense category, date field, name field, description prefix)
KINDS: dict[str, tuple[str, str, str, str]] = {
    "vaccinations": ("veterinary", "date_given", "vaccine_name", "Vaccination"),
    "treatments": ("medication", "start_date", "name", "Treatment"),
    "vet_visits": ("veterinary", "visit_date", "reason", "Vet visit"),
}


def guard(ctx: Ctx) -> None:
    """403 when someone who may not see money sends a cost."""
    sent = request.get_json(silent=True) or {}
    if "cost" in sent and sent.get("cost") is not None and not can_see_finance(ctx.role):
        ctx.require("manager")


def description(collection: str, record: dict, animal_label: str | None) -> str:
    """"Vaccination: Enterotoxemia (03-0001)" (translated when shown, finance.tx_label)."""
    prefix = KINDS[collection][3]
    name = record.get(KINDS[collection][2]) or ""
    return f"{prefix}: {name} ({animal_label})" if animal_label else f"{prefix}: {name}"


def _label(ctx: Ctx, animal_id: str | None) -> str | None:
    animal = ctx.repo.get(farm_path(ctx.farm_id, "animals"), animal_id) if animal_id else None
    return (animal or {}).get("farm_code") or (animal or {}).get("ear_tag")


def sync(ctx: Ctx, collection: str, record: dict) -> str | None:
    """Create, update or delete the record's expense; returns the expense id (None without a cost)."""
    from app.routers.finance import _prepare

    category, date_field, _, _ = KINDS[collection]
    path = farm_path(ctx.farm_id, "transactions")
    tx_id = record.get("transaction_id")
    existing = ctx.repo.get(path, tx_id) if tx_id else None
    cost = float(record.get("cost") or 0)
    if cost <= 0:
        if existing:
            ctx.repo.delete(path, existing["id"])
        return None
    fields = {"amount": round(cost, 2), "date": record[date_field],
              "description": description(collection, record, _label(ctx, record.get("animal_id")))}
    if existing:
        ctx.repo.update(path, existing["id"], fields)
        return existing["id"]
    data = _prepare(ctx, {"type": "expense", "category": category, "barn_id": None, "whole_barn": False,
                          "animal_ids": [record["animal_id"]], "animal_id": record["animal_id"], **fields})
    return ctx.repo.create(path, data)["id"]


def hooks(collection: str, after_write=None, after_delete=None) -> dict:
    """The CRUD hooks of a health collection: cost guarded, expense kept in step, cost hidden from workers.
    ``after_write`` / ``after_delete`` = the collection's own hooks (reminders), run as well."""

    def before_create(ctx: Ctx, data: dict) -> dict:
        guard(ctx)
        return data

    def before_update(ctx: Ctx, existing: dict, merged: dict) -> dict:
        guard(ctx)
        if not can_see_finance(ctx.role):
            merged["cost"] = existing.get("cost")  # a worker never sees it: keep it
        merged["transaction_id"] = existing.get("transaction_id")
        return merged

    def write(ctx: Ctx, record: dict) -> None:
        tx_id = sync(ctx, collection, record)
        if tx_id != record.get("transaction_id"):
            ctx.repo.update(farm_path(ctx.farm_id, collection), record["id"], {"transaction_id": tx_id})
        record["transaction_id"] = tx_id
        if after_write:
            after_write(ctx, record)

    def delete(ctx: Ctx, record: dict) -> None:
        sync(ctx, collection, {**record, "cost": None})
        if after_delete:
            after_delete(ctx, record)

    def enrich(record: dict) -> dict:
        if can_see_finance(get_ctx().role):
            return record
        return {**record, "cost": None, "transaction_id": None}

    return {"before_create": before_create, "before_update": before_update, "after_write": write,
            "after_delete": delete, "enrich": enrich}


def unlink(ctx: Ctx, tx_id: str) -> None:
    """The expense was deleted in Finance: the health records keep their cost text but lose the link."""
    for collection in KINDS:
        for rec in ctx.repo.list(farm_path(ctx.farm_id, collection), [("transaction_id", "==", tx_id)]):
            ctx.repo.update(farm_path(ctx.farm_id, collection), rec["id"], {"transaction_id": None, "cost": None})


def book_bulk(ctx: Ctx, vaccine: str, date: str, cost: float, animal_ids: list[str]) -> str | None:
    """One expense for a whole vaccination of several animals, shared by them."""
    from app.routers.finance import _prepare

    if cost <= 0 or not animal_ids:
        return None
    data = _prepare(ctx, {"type": "expense", "category": "veterinary", "amount": round(cost, 2), "date": date,
                          "description": f"Vaccination: {vaccine} ({len(animal_ids)} animals)", "barn_id": None,
                          "whole_barn": False, "animal_ids": animal_ids, "animal_id": None})
    return ctx.repo.create(farm_path(ctx.farm_id, "transactions"), data)["id"]
