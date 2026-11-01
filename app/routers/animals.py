"""Animal profiles: CRUD, status changes, photo upload and family tree (/v1/animals...)."""

from __future__ import annotations

from flask import Blueprint, request

from app.config import get_settings
from app.deps import Ctx, get_ctx, get_photo_store
from app.errors import ApiError
from app.routers.crud import get_animal_or_404, path_of
from app.schemas import (
    ON_FARM_STATUSES,
    AnimalCreate,
    AnimalOut,
    AnimalStatus,
    AnimalUpdate,
    FamilyOut,
    StatusChange,
)
from app.services.photos import ALLOWED_TYPES
from app.utils import age_parts, parse_date
from app.web import body, no_content, out, q_int, q_str

bp = Blueprint("animals", __name__)

# Collections holding records that reference an animal via ``animal_id``.
RELATED_COLLECTIONS = ["vaccinations", "treatments", "vet_visits", "illnesses", "weights", "production", "feedings", "reminders"]


def render_animal(record: dict) -> AnimalOut:
    """Convert a stored animal into AnimalOut, adding age_days, age_months and age_label."""
    dob = parse_date(record.get("date_of_birth"))
    until = parse_date(record.get("status_date")) if record.get("status") == "deceased" else None
    days, months, label = age_parts(dob, until)
    return AnimalOut.model_validate({**record, "age_days": days, "age_months": months, "age_label": label})


def ear_tag_taken(ctx: Ctx, ear_tag: str, exclude_id: str | None = None) -> bool:
    """True if another animal of this farm already uses the ear tag."""
    matches = ctx.repo.list(path_of(ctx, "animals"), [("ear_tag", "==", ear_tag)])
    return any(m["id"] != exclude_id for m in matches)


def check_parents(ctx: Ctx, data: dict, animal_id: str | None = None) -> None:
    """Validate mother_id/father_id: must exist, have the right sex and not be the animal itself (404/422)."""
    for field, expected_sex in (("mother_id", "female"), ("father_id", "male")):
        parent_id = data.get(field)
        if not parent_id:
            continue
        if parent_id == animal_id:
            raise ApiError(422, f"{field} cannot be the animal itself")
        parent = ctx.repo.get(path_of(ctx, "animals"), parent_id)
        if not parent:
            raise ApiError(404, f"{field} animal not found")
        if parent.get("sex") != expected_sex:
            raise ApiError(422, f"{field} must reference a {expected_sex} animal")


@bp.get("/animals")
def list_animals():
    """GET /v1/animals - list the farm's animals, filtered by status/species/sex and searched by q."""
    ctx = get_ctx()
    status_ = q_str("status")  # a status, or 'on_farm' for active+sick+quarantine
    species, sex = q_str("species"), q_str("sex")
    q = q_str("q")  # search ear tag, name or breed
    limit = q_int("limit", 500, ge=1, le=2000)
    filters: list[tuple[str, str, object]] = []
    if status_ == "on_farm":
        filters.append(("status", "in", sorted(ON_FARM_STATUSES)))
    elif status_:
        filters.append(("status", "==", status_))
    if species:
        filters.append(("species", "==", species))
    if sex:
        filters.append(("sex", "==", sex))
    rows = ctx.repo.list(path_of(ctx, "animals"), filters, order_by="ear_tag")
    if q:
        needle = q.lower()
        rows = [
            r for r in rows if any(needle in (r.get(f) or "").lower() for f in ("ear_tag", "name", "breed"))
        ]
    return out([render_animal(r) for r in rows[:limit]])


@bp.post("/animals")
def create_animal():
    """POST /v1/animals - create an animal (409 if the ear tag is taken)."""
    ctx = get_ctx()
    animal = body(AnimalCreate)
    if ear_tag_taken(ctx, animal.ear_tag):
        raise ApiError(409, f"Ear tag '{animal.ear_tag}' is already used on this farm")
    data = animal.model_dump(mode="json")
    check_parents(ctx, data)
    if data["status"] in ("sold", "deceased"):
        data["status_date"] = animal.date_added.isoformat()
    return out(render_animal(ctx.repo.create(path_of(ctx, "animals"), data)), 201)


@bp.get("/animals/<animal_id>")
def get_animal(animal_id: str):
    """GET /v1/animals/<id> - one animal (404 if missing)."""
    return out(render_animal(get_animal_or_404(get_ctx(), animal_id)))


@bp.patch("/animals/<animal_id>")
def update_animal(animal_id: str):
    """PATCH /v1/animals/<id> - change some fields of an animal."""
    ctx = get_ctx()
    existing = get_animal_or_404(ctx, animal_id)
    patch = body(AnimalUpdate).model_dump(mode="json", exclude_unset=True)
    if "ear_tag" in patch:
        if patch["ear_tag"] is None:
            raise ApiError(422, "ear_tag cannot be null")
        if ear_tag_taken(ctx, patch["ear_tag"], exclude_id=animal_id):
            raise ApiError(409, f"Ear tag '{patch['ear_tag']}' is already used on this farm")
    for required in ("species", "sex"):
        if required in patch and patch[required] is None:
            raise ApiError(422, f"{required} cannot be null")
    check_parents(ctx, patch, animal_id)
    updated = ctx.repo.update(path_of(ctx, "animals"), animal_id, patch)
    return out(render_animal(updated or existing))


@bp.post("/animals/<animal_id>/status")
def change_status(animal_id: str):
    """Change the animal's status. Selling with a price records an income transaction."""
    ctx = get_ctx()
    animal = get_animal_or_404(ctx, animal_id)
    change = body(StatusChange)
    patch: dict = {"status": change.status.value, "status_date": change.date.isoformat()}
    if change.notes:
        patch["status_notes"] = change.notes
    if change.status == AnimalStatus.sold and change.buyer:
        patch["buyer"] = change.buyer
    updated = ctx.repo.update(path_of(ctx, "animals"), animal_id, patch)
    if change.status == AnimalStatus.sold and change.sale_price:
        label = animal.get("name") or animal.get("ear_tag")
        ctx.repo.create(
            path_of(ctx, "transactions"),
            {
                "type": "income",
                "category": "animal_sale",
                "amount": change.sale_price,
                "date": change.date.isoformat(),
                "description": f"Sale of {label}" + (f" to {change.buyer}" if change.buyer else ""),
                "animal_id": animal_id,
            },
        )
    if change.status in (AnimalStatus.sold, AnimalStatus.deceased):
        # Pending reminders for an animal that left the farm are no longer useful.
        for reminder in ctx.repo.list(path_of(ctx, "reminders"), [("animal_id", "==", animal_id), ("status", "==", "pending")]):
            ctx.repo.update(path_of(ctx, "reminders"), reminder["id"], {"status": "done"})
    return out(render_animal(updated or animal))


@bp.delete("/animals/<animal_id>")
def delete_animal(animal_id: str):
    """Delete an animal and every health, growth and production record attached to it."""
    ctx = get_ctx()
    get_animal_or_404(ctx, animal_id)
    for collection in RELATED_COLLECTIONS:
        for rec in ctx.repo.list(path_of(ctx, collection), [("animal_id", "==", animal_id)]):
            ctx.repo.delete(path_of(ctx, collection), rec["id"])
    for rec in ctx.repo.list(path_of(ctx, "breedings"), [("dam_id", "==", animal_id)]):
        ctx.repo.delete(path_of(ctx, "breedings"), rec["id"])
    # Breedings where it was the sire stay (they belong to the dam) but lose the link.
    for rec in ctx.repo.list(path_of(ctx, "breedings"), [("sire_id", "==", animal_id)]):
        ctx.repo.update(path_of(ctx, "breedings"), rec["id"], {"sire_id": None})
    # Children keep existing but lose the dangling parent link.
    for field in ("mother_id", "father_id"):
        for child in ctx.repo.list(path_of(ctx, "animals"), [(field, "==", animal_id)]):
            ctx.repo.update(path_of(ctx, "animals"), child["id"], {field: None})
    ctx.repo.delete(path_of(ctx, "animals"), animal_id)
    return no_content()


@bp.post("/animals/<animal_id>/photo")
def upload_photo(animal_id: str):
    """POST /v1/animals/<id>/photo - store a JPEG/PNG/WebP (multipart field "file") and set photo_url."""
    ctx = get_ctx()
    store = get_photo_store()
    get_animal_or_404(ctx, animal_id)
    file = request.files.get("file")
    if file is None:
        raise ApiError(422, [{"loc": ["body", "file"], "msg": "Field required", "type": "missing"}])
    content_type = file.mimetype
    if content_type not in ALLOWED_TYPES:
        raise ApiError(415, "Photo must be JPEG, PNG or WebP")
    limit = get_settings().max_photo_bytes
    content = file.stream.read(limit + 1)
    if len(content) > limit:
        raise ApiError(413, f"Photo exceeds {limit // (1024 * 1024)} MB")
    if not content:
        raise ApiError(422, "Empty file")
    url = store.save(ctx.farm_id, animal_id, content, content_type)
    updated = ctx.repo.update(path_of(ctx, "animals"), animal_id, {"photo_url": url})
    return out(render_animal(updated))  # type: ignore[arg-type]


@bp.get("/animals/<animal_id>/family")
def get_family(animal_id: str):
    """Parents, siblings (same mother or father) and offspring of an animal."""
    ctx = get_ctx()
    animal = get_animal_or_404(ctx, animal_id)
    path = path_of(ctx, "animals")
    mother = ctx.repo.get(path, animal["mother_id"]) if animal.get("mother_id") else None
    father = ctx.repo.get(path, animal["father_id"]) if animal.get("father_id") else None
    offspring = {
        r["id"]: r
        for field in ("mother_id", "father_id")
        for r in ctx.repo.list(path, [(field, "==", animal_id)])
    }
    siblings: dict[str, dict] = {}
    for field, parent in (("mother_id", mother), ("father_id", father)):
        if parent:
            for r in ctx.repo.list(path, [(field, "==", parent["id"])]):
                if r["id"] != animal_id:
                    siblings[r["id"]] = r
    return out(FamilyOut(
        animal=render_animal(animal),
        mother=render_animal(mother) if mother else None,
        father=render_animal(father) if father else None,
        siblings=[render_animal(r) for r in sorted(siblings.values(), key=lambda r: r["ear_tag"])],
        offspring=[render_animal(r) for r in sorted(offspring.values(), key=lambda r: r["ear_tag"])],
    ))
