"""Generic farm-scoped CRUD router factory plus shared helpers."""

import json
from datetime import date
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ValidationError

from app.deps import Ctx, get_ctx
from app.repository import farm_path

Hook = Callable[..., Any]


def path_of(ctx: Ctx, collection: str) -> str:
    return farm_path(ctx.farm_id, collection)


def get_animal_or_404(ctx: Ctx, animal_id: str) -> dict:
    animal = ctx.repo.get(path_of(ctx, "animals"), animal_id)
    if not animal:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Animal not found")
    return animal


def validation_error(exc: ValidationError) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, json.loads(exc.json(include_url=False)))


def clean(record: dict, model: type[BaseModel]) -> dict:
    """Keep only the keys that belong to ``model`` (drops id and timestamps)."""
    return {k: v for k, v in record.items() if k in model.model_fields}


def build_crud_router(
    *,
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
) -> APIRouter:
    router = APIRouter()

    def render(record: dict) -> Any:
        return out_model.model_validate(enrich(record) if enrich else record)

    def check_animal(ctx: Ctx, data: dict) -> None:
        if data.get("animal_id"):
            get_animal_or_404(ctx, data["animal_id"])

    @router.get("", response_model=list[out_model])  # type: ignore[valid-type]
    def list_records(
        animal_id: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        limit: int = Query(200, ge=1, le=1000),
        ctx: Ctx = Depends(get_ctx),
    ):
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
        return [render(r) for r in rows]

    @router.post("", response_model=out_model, status_code=status.HTTP_201_CREATED)  # type: ignore[valid-type]
    def create_record(body: create_model, ctx: Ctx = Depends(get_ctx)):  # type: ignore[valid-type]
        data = body.model_dump(mode="json")
        check_animal(ctx, data)
        if before_create:
            data = before_create(ctx, data)
        record = ctx.repo.create(path_of(ctx, collection), data)
        if after_write:
            after_write(ctx, record)
        return render(record)

    @router.get("/{record_id}", response_model=out_model)  # type: ignore[valid-type]
    def get_record(record_id: str, ctx: Ctx = Depends(get_ctx)):
        record = ctx.repo.get(path_of(ctx, collection), record_id)
        if not record:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Record not found")
        return render(record)

    @router.patch("/{record_id}", response_model=out_model)  # type: ignore[valid-type]
    def update_record(record_id: str, body: update_model, ctx: Ctx = Depends(get_ctx)):  # type: ignore[valid-type]
        existing = ctx.repo.get(path_of(ctx, collection), record_id)
        if not existing:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Record not found")
        patch = body.model_dump(mode="json", exclude_unset=True)
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
        return render(record)

    @router.delete("/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_record(record_id: str, ctx: Ctx = Depends(get_ctx)):
        record = ctx.repo.get(path_of(ctx, collection), record_id)
        if not record:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Record not found")
        ctx.repo.delete(path_of(ctx, collection), record_id)
        if after_delete:
            after_delete(ctx, record)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router
