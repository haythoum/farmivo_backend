from __future__ import annotations

import csv
import io
from datetime import date, timedelta
from enum import Enum

from flask import Blueprint, Response

from app.deps import Ctx, get_ctx
from app.errors import ApiError
from app.routers.animals import render_animal
from app.routers.crud import path_of
from app.utils import today
from app.web import out, q_date, q_enum

bp = Blueprint("reports", __name__)


class ReportKind(str, Enum):
    herd = "herd"
    vaccinations = "vaccinations"
    financial = "financial"
    production = "production"


class ReportFormat(str, Enum):
    json = "json"
    csv = "csv"


def _range_filters(field: str, start: date, end: date) -> list[tuple[str, str, object]]:
    return [(field, ">=", start.isoformat()), (field, "<=", end.isoformat())]


def build_rows(ctx: Ctx, kind: ReportKind, start: date, end: date) -> tuple[list[str], list[dict]]:
    if kind == ReportKind.herd:
        columns = ["ear_tag", "name", "species", "breed", "sex", "date_of_birth", "age_label", "date_added", "status", "status_date"]
        rows = [render_animal(a).model_dump(mode="json") for a in ctx.repo.list(path_of(ctx, "animals"), order_by="ear_tag")]
        return columns, rows

    animals = {a["id"]: a for a in ctx.repo.list(path_of(ctx, "animals"))}

    def tag(animal_id: str | None) -> str:
        return (animals.get(animal_id or "") or {}).get("ear_tag", "")

    if kind == ReportKind.vaccinations:
        columns = ["ear_tag", "vaccine_name", "date_given", "next_due_date", "batch_number", "administered_by"]
        records = ctx.repo.list(path_of(ctx, "vaccinations"), _range_filters("date_given", start, end), order_by="date_given", desc=True)
        return columns, [{**r, "ear_tag": tag(r["animal_id"])} for r in records]

    if kind == ReportKind.financial:
        columns = ["date", "type", "category", "amount", "description", "ear_tag"]
        records = ctx.repo.list(path_of(ctx, "transactions"), _range_filters("date", start, end), order_by="date", desc=True)
        return columns, [{**r, "ear_tag": tag(r.get("animal_id"))} for r in records]

    columns = ["date", "product", "quantity", "unit", "ear_tag"]
    records = ctx.repo.list(path_of(ctx, "production"), _range_filters("date", start, end), order_by="date", desc=True)
    return columns, [{**r, "ear_tag": tag(r.get("animal_id"))} for r in records]


@bp.get("/reports/<kind>")
def report(kind: str):
    """Tabular reports as JSON or downloadable CSV. Date range defaults to the last 90 days (ignored for 'herd')."""
    ctx = get_ctx()
    try:
        kind = ReportKind(kind)  # type: ignore[assignment]
    except ValueError:
        raise ApiError(422, [{"loc": ["path", "kind"], "msg": "Input should be one of: herd, vaccinations, financial, production", "type": "enum"}]) from None
    format = q_enum("format", ReportFormat, ReportFormat.json)
    date_from, date_to = q_date("date_from"), q_date("date_to")
    end = date_to or today()
    start = date_from or end - timedelta(days=89)
    if start > end:
        raise ApiError(422, "date_from must not be after date_to")
    columns, rows = build_rows(ctx, kind, start, end)
    if format == ReportFormat.json:
        return out({
            "kind": kind.value,
            "date_from": start.isoformat(),
            "date_to": end.isoformat(),
            "columns": columns,
            "rows": [{c: r.get(c) for c in columns} for r in rows],
        })
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(columns)
    for r in rows:
        writer.writerow([_csv_safe(r.get(c)) for c in columns])
    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="farmivo-{kind.value}-{today().isoformat()}.csv"'},
    )


def _csv_safe(value: object) -> object:
    """Neutralise spreadsheet formula injection in user-entered text."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@"):
        return "'" + value
    return "" if value is None else value
