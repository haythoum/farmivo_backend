"""Barns of a farm (/v1/barns) and the age-by-teeth catalog (/v1/age-classes).

A farm can have several barns (sheepfold, stable for the horses, cow shed ...). A barn may be reserved to one
species; each animal can be placed in one barn (``barn_id`` on the animal). Everyone on the farm can read them;
workers and above create and edit them, managers and the owner delete them (the usual role policy).
"""
from __future__ import annotations

from flask import Blueprint
from pydantic import ValidationError

from app import age_classes
from app.deps import Ctx, get_ctx
from app.errors import ApiError, validation_error
from app.i18n import request_lang
from app.routers.crud import clean, path_of
from app.schemas import ON_FARM_STATUSES, BarnBase, BarnOut, BarnUpdate
from app.web import body, no_content, out

bp = Blueprint("barns", __name__)


def _render(barn: dict, animals: list[dict]) -> BarnOut:
    count = sum(1 for a in animals if a.get("barn_id") == barn["id"] and a.get("status") in ON_FARM_STATUSES)
    return BarnOut.model_validate({**clean(barn, BarnOut), "id": barn["id"], "animal_count": count})


def _get_or_404(ctx: Ctx, barn_id: str) -> dict:
    barn = ctx.repo.get(path_of(ctx, "barns"), barn_id)
    if not barn:
        raise ApiError(404, "Barn not found")
    return barn


def _check_name(ctx: Ctx, name: str, exclude_id: str | None = None) -> None:
    for other in ctx.repo.list(path_of(ctx, "barns")):
        if other["id"] != exclude_id and (other.get("name") or "").strip().lower() == name.strip().lower():
            raise ApiError(409, f"A barn named '{name}' already exists")


def _check_species(ctx: Ctx, barn_id: str, species: str | None) -> None:
    """A barn reserved to one species cannot already hold animals of another one (422)."""
    if not species:
        return
    others = [a for a in ctx.repo.list(path_of(ctx, "animals"), [("barn_id", "==", barn_id)])
              if a.get("species") != species and a.get("status") in ON_FARM_STATUSES]
    if others:
        raise ApiError(422, f"{len(others)} animals of another species are in this barn")


@bp.get("/barns")
def list_barns():
    """GET /v1/barns - the farm's barns by name, with the number of animals on the farm in each."""
    ctx = get_ctx()
    animals = ctx.repo.list(path_of(ctx, "animals"))
    barns = ctx.repo.list(path_of(ctx, "barns"), order_by="name")
    return out([_render(b, animals) for b in barns])


@bp.post("/barns")
def create_barn():
    """POST /v1/barns {name, species?, capacity?, notes?} - add a barn (409 if the name is taken)."""
    ctx = get_ctx()
    data = body(BarnBase).model_dump(mode="json")
    _check_name(ctx, data["name"])
    barn = ctx.repo.create(path_of(ctx, "barns"), data)
    return out(_render(barn, []), 201)


@bp.get("/barns/<barn_id>")
def get_barn(barn_id: str):
    """GET /v1/barns/<id> - one barn."""
    ctx = get_ctx()
    barn = _get_or_404(ctx, barn_id)
    return out(_render(barn, ctx.repo.list(path_of(ctx, "animals"), [("barn_id", "==", barn_id)])))


@bp.patch("/barns/<barn_id>")
def update_barn(barn_id: str):
    """PATCH /v1/barns/<id> - rename, change the species, capacity or notes."""
    ctx = get_ctx()
    existing = _get_or_404(ctx, barn_id)
    patch = body(BarnUpdate).model_dump(mode="json", exclude_unset=True)
    if "name" in patch and patch["name"] is None:
        raise ApiError(422, "name cannot be null")
    try:
        merged = BarnBase.model_validate({**clean(existing, BarnBase), **patch}).model_dump(mode="json")
    except ValidationError as exc:
        raise validation_error(exc) from exc
    if "name" in patch:
        _check_name(ctx, merged["name"], exclude_id=barn_id)
    if patch.get("species"):
        _check_species(ctx, barn_id, merged["species"])
    barn = ctx.repo.update(path_of(ctx, "barns"), barn_id, patch) or existing
    return out(_render(barn, ctx.repo.list(path_of(ctx, "animals"), [("barn_id", "==", barn_id)])))


@bp.delete("/barns/<barn_id>")
def delete_barn(barn_id: str):
    """DELETE /v1/barns/<id> - delete a barn; its animals stay on the farm without a barn."""
    ctx = get_ctx()
    _get_or_404(ctx, barn_id)
    for animal in ctx.repo.list(path_of(ctx, "animals"), [("barn_id", "==", barn_id)]):
        ctx.repo.update(path_of(ctx, "animals"), animal["id"], {"barn_id": None})
    ctx.repo.delete(path_of(ctx, "barns"), barn_id)
    return no_content()


@bp.get("/age-classes")
def list_age_classes():
    """GET /v1/age-classes - age by teeth: per species, the classes in order with label and hint in the
    request's language. Species not listed (pig, poultry, rabbit, other) are aged by date of birth only."""
    get_ctx()
    return out(age_classes.catalog(request_lang()))
