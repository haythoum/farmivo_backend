"""Generic farm-scoped CRUD blueprint factory plus shared helpers."""

from typing import Any, Callable

from flask import Blueprint
from pydantic import BaseModel, ValidationError

from app.deps import Ctx, get_ctx
from app.errors import ApiError, validation_error
from app.repository import farm_path
from app.web import body, no_content, out, q_date, q_int, q_str

Hook = Callable[..., Any]


def path_of(ctx: Ctx, collection: str) -> str:
    """Path of one of the current farm's collections."""
    return farm_path(ctx.farm_id, collection)


def get_animal_or_404(ctx: Ctx, animal_id: str) -> dict:
    """Load an animal of the current farm or raise ApiError 404."""
    animal = ctx.repo.get(path_of(ctx, "animals"), animal_id)
    if not animal:
        raise ApiError(404, "Animal not found")
    return animal


def clean(record: dict, model: type[BaseModel]) -> dict:
    """Keep only the keys that belong to ``model`` (drops id and timestamps)."""
    return {k: v for k, v in record.items() if k in model.model_fields}


def build_crud_blueprint(
    *,
    name: str,
    collection: str,
    create_model: type[BaseModel],
    update_model: type[BaseModel],
    out_model: type[BaseModel],
    date_field: str | None = None,
    before_create: Hook | None = None,
    before_update: Hook | None = None,
    after_write: Hook | None = None,
    after_delete: Hook | None = None,
    enrich: Callable[[dict], dict] | None = None,
) -> Blueprint:
    """Build a Blueprint with list/create/get/update/delete routes for one farm collection, with optional hooks."""
    bp = Blueprint(name, __name__)

    def render(record: dict) -> Any:
        return out_model.model_validate(enrich(record) if enrich else record)

    def check_animal(ctx: Ctx, data: dict) -> None:
        if data.get("animal_id"):
            get_animal_or_404(ctx, data["animal_id"])

    @bp.get("")
    def list_records():
        ctx = get_ctx()
        animal_id = q_str("animal_id")
        date_from, date_to = q_date("date_from"), q_date("date_to")
        limit = q_int("limit", 200, ge=1, le=1000)
        filters: list[tuple[str, str, Any]] = []
        if animal_id:
            filters.append(("animal_id", "==", animal_id))
        if date_field and date_from:
            filters.append((date_field, ">=", date_from.isoformat()))
        if date_field and date_to:
            filters.append((date_field, "<=", date_to.isoformat()))
        rows = ctx.repo.list(
            path_of(ctx, collection), filters, order_by=date_field or "created_at", desc=True, limit=limit
        )
        return out([render(r) for r in rows])

    @bp.post("")
    def create_record():
        ctx = get_ctx()
        model = body(create_model)
        data = model.model_dump(mode="json")
        check_animal(ctx, data)
        if before_create:
            data = before_create(ctx, data)
        record = ctx.repo.create(path_of(ctx, collection), data)
        if after_write:
            after_write(ctx, record)
        return out(render(record), 201)

    @bp.get("/<record_id>")
    def get_record(record_id: str):
        ctx = get_ctx()
        record = ctx.repo.get(path_of(ctx, collection), record_id)
        if not record:
            raise ApiError(404, "Record not found")
        return out(render(record))

    @bp.patch("/<record_id>")
    def update_record(record_id: str):
        ctx = get_ctx()
        existing = ctx.repo.get(path_of(ctx, collection), record_id)
        if not existing:
            raise ApiError(404, "Record not found")
        patch = body(update_model).model_dump(mode="json", exclude_unset=True)
        check_animal(ctx, patch)
        try:  # re-validate the merged record so cross-field rules still hold
            merged = create_model.model_validate({**clean(existing, create_model), **patch}).model_dump(mode="json")
        except ValidationError as exc:
            raise validation_error(exc) from exc
        if before_update:
            merged = before_update(ctx, existing, merged)
        record = ctx.repo.update(path_of(ctx, collection), record_id, merged)
        if after_write:
            after_write(ctx, record)
        return out(render(record))

    @bp.delete("/<record_id>")
    def delete_record(record_id: str):
        ctx = get_ctx()
        record = ctx.repo.get(path_of(ctx, collection), record_id)
        if not record:
            raise ApiError(404, "Record not found")
        ctx.repo.delete(path_of(ctx, collection), record_id)
        if after_delete:
            after_delete(ctx, record)
        return no_content()

    return bp
