"""Animal profiles: CRUD, status changes, photo upload and family tree (/v1/animals...)."""

from __future__ import annotations

from flask import Blueprint, current_app, request
from pydantic import ValidationError

from app.config import get_settings
from app.deps import Ctx, get_ctx, get_photo_store
from app.errors import ApiError, validation_error
from app.routers.crud import clean, get_animal_or_404, path_of
from app import age_classes
from app.i18n import request_lang
from app.schemas import (
    DEAD_STATUSES,
    LEFT_STATUSES,
    ON_FARM_STATUSES,
    AnimalBase,
    AnimalCreate,
    AnimalOut,
    AnimalStatus,
    AnimalUpdate,
    FamilyOut,
    StatusChange,
)
from app.services.photos import ALLOWED_TYPES
from app.utils import age_parts, parse_date, today
from app.web import body, no_content, out, q_int, q_str

bp = Blueprint("animals", __name__)

# Collections holding records that reference an animal via ``animal_id``.
RELATED_COLLECTIONS = ["vaccinations", "treatments", "vet_visits", "illnesses", "weights", "production", "feedings", "reminders"]


def barn_names(ctx: Ctx) -> dict[str, str]:
    """Barn id -> name for the current farm (one query, used when rendering many animals)."""
    return {b["id"]: b.get("name", "") for b in ctx.repo.list(path_of(ctx, "barns"))}


def render_animal(record: dict, barns: dict[str, str] | None = None) -> AnimalOut:
    """Convert a stored animal into AnimalOut, adding the age fields, the age class label (in the request's
    language) and the barn name. ``barns`` = barn_names(ctx); when omitted the barn name is left empty."""
    dob = parse_date(record.get("date_of_birth"))
    until = parse_date(record.get("status_date")) if record.get("status") in DEAD_STATUSES else None
    days, months, label = age_parts(dob, until)
    extra = {"age_days": days, "age_months": months, "age_label": label,
             "age_class_label": age_classes.label(record.get("species"), record.get("age_class"), request_lang())}
    if barns is not None and record.get("barn_id"):
        extra["barn_name"] = barns.get(record["barn_id"])
    return AnimalOut.model_validate({**record, **extra})


def render_one(ctx: Ctx, record: dict) -> AnimalOut:
    """render_animal for a single animal, with its barn name."""
    barn = ctx.repo.get(path_of(ctx, "barns"), record["barn_id"]) if record.get("barn_id") else None
    return render_animal(record, {barn["id"]: barn.get("name", "")} if barn else {})


def ear_tag_taken(ctx: Ctx, ear_tag: str, species: str | None, exclude_id: str | None = None) -> bool:
    """True if another animal of the same species on this farm already uses the ear tag. The same number may
    be used once per species (goat 001 and dog 001)."""
    matches = ctx.repo.list(path_of(ctx, "animals"), [("ear_tag", "==", ear_tag)])
    return any(m["id"] != exclude_id and m.get("species") == species for m in matches)


def tag_conflict(tag: str, species: str | None) -> ApiError:
    """409 for an ear tag already used by an animal of the same species."""
    return ApiError(409, f"Ear tag '{tag}' is already used for another {species or 'animal'} on this farm")


def check_barn(ctx: Ctx, barn_id: str | None, species: str | None) -> None:
    """The barn must exist on this farm and, when it is reserved to one species, match the animal's (404/422)."""
    if not barn_id:
        return
    barn = ctx.repo.get(path_of(ctx, "barns"), barn_id)
    if not barn:
        raise ApiError(404, "Barn not found")
    if barn.get("species") and species and barn["species"] != species:
        raise ApiError(422, f"Barn '{barn.get('name')}' is for {barn['species']}, not {species}")


def sync_purchase(ctx: Ctx, animal: dict) -> dict:
    """Keep the purchase expense in line with the animal: one "purchase_animal" expense of purchase_price on
    date_added while the origin is not born on the farm and the price is above 0; removed otherwise. The
    transaction id is kept on the animal (purchase_tx_id). Returns the animal (updated when the id changed)."""
    path = path_of(ctx, "transactions")
    price = animal.get("purchase_price") or 0
    tx_id = animal.get("purchase_tx_id")
    existing = ctx.repo.get(path, tx_id) if tx_id else None
    if price > 0 and animal.get("origin") != "born_on_farm":
        label = animal.get("name") or animal.get("ear_tag")
        fields = {"type": "expense", "category": "purchase_animal", "amount": float(price),
                  "date": (animal.get("date_added") or today().isoformat())[:10],
                  "description": f"Purchase of {label}", "animal_id": animal["id"]}
        if existing:
            ctx.repo.update(path, tx_id, fields)
            return animal
        tx = ctx.repo.create(path, fields)
        return ctx.repo.update(path_of(ctx, "animals"), animal["id"], {"purchase_tx_id": tx["id"]}) or animal
    if existing:
        ctx.repo.delete(path, tx_id)
    if tx_id:
        return ctx.repo.update(path_of(ctx, "animals"), animal["id"], {"purchase_tx_id": None}) or animal
    return animal


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
    barn = q_str("barn_id")  # a barn id, or 'none' for animals in no barn
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
    if barn and barn != "none":
        filters.append(("barn_id", "==", barn))
    rows = ctx.repo.list(path_of(ctx, "animals"), filters, order_by="ear_tag")
    if barn == "none":
        rows = [r for r in rows if not r.get("barn_id")]
    if q:
        needle = q.lower()
        rows = [
            r for r in rows if any(needle in (r.get(f) or "").lower() for f in ("ear_tag", "name", "breed"))
        ]
    barns = barn_names(ctx)
    return out([render_animal(r, barns) for r in rows[:limit]])


@bp.post("/animals")
def create_animal():
    """POST /v1/animals - create an animal (409 if the ear tag is taken)."""
    ctx = get_ctx()
    animal = body(AnimalCreate)
    if ear_tag_taken(ctx, animal.ear_tag, animal.species.value):
        raise tag_conflict(animal.ear_tag, animal.species.value)
    data = animal.model_dump(mode="json")
    data["photo_url"] = None  # photos only come from POST /animals/<id>/photo (no arbitrary outside URLs)
    check_parents(ctx, data)
    check_barn(ctx, data.get("barn_id"), data["species"])
    if data["status"] in LEFT_STATUSES:
        data["status_date"] = animal.date_added.isoformat()
    created = sync_purchase(ctx, ctx.repo.create(path_of(ctx, "animals"), data))
    return out(render_one(ctx, created), 201)


@bp.get("/animals/<animal_id>")
def get_animal(animal_id: str):
    """GET /v1/animals/<id> - one animal (404 if missing)."""
    ctx = get_ctx()
    return out(render_one(ctx, get_animal_or_404(ctx, animal_id)))


@bp.patch("/animals/<animal_id>")
def update_animal(animal_id: str):
    """PATCH /v1/animals/<id> - change some fields of an animal."""
    ctx = get_ctx()
    existing = get_animal_or_404(ctx, animal_id)
    patch = body(AnimalUpdate).model_dump(mode="json", exclude_unset=True)
    for required in ("ear_tag", "species", "sex"):
        if required in patch and patch[required] is None:
            raise ApiError(422, f"{required} cannot be null")
    merged = {**clean(existing, AnimalBase), **patch}
    if ("species" in patch and patch["species"] != existing.get("species")
            and existing.get("age_class") and "age_class" not in patch):
        # The old age class belongs to the old species: drop it instead of refusing the change.
        patch["age_class"] = None
        merged["age_class"] = None
    try:  # PATCH models drop validators: re-check the merged animal (e.g. date of birth not in the future)
        AnimalBase.model_validate(merged)
    except ValidationError as exc:
        raise validation_error(exc) from exc
    if ("ear_tag" in patch or "species" in patch) and ear_tag_taken(ctx, merged["ear_tag"], merged["species"],
                                                                     exclude_id=animal_id):
        raise tag_conflict(merged["ear_tag"], merged["species"])
    check_parents(ctx, patch, animal_id)
    if "barn_id" in patch or "species" in patch:
        check_barn(ctx, merged.get("barn_id"), merged["species"])
    updated = ctx.repo.update(path_of(ctx, "animals"), animal_id, patch) or existing
    if {"purchase_price", "origin", "date_added", "name", "ear_tag"} & patch.keys():
        updated = sync_purchase(ctx, updated)
    return out(render_one(ctx, updated))


@bp.post("/animals/<animal_id>/status")
def change_status(animal_id: str):
    """Change the animal's status: on the farm (active, sick, quarantine) or leaving it (sold, deceased, donated,
    gifted, sacrificed). Selling with a price books one income transaction (sale_tx_id on the animal); changing
    the status again, or the price, updates or removes that transaction so a sale is never counted twice."""
    ctx = get_ctx()
    animal = get_animal_or_404(ctx, animal_id)
    change = body(StatusChange)
    status = change.status.value
    patch: dict = {"status": status, "status_date": change.date.isoformat(), "status_notes": change.notes}
    patch["buyer"] = change.buyer if status == "sold" else None
    patch["sale_price"] = change.sale_price if status == "sold" else None
    patch["recipient"] = change.recipient if status in ("donated", "gifted") else None
    tx_path = path_of(ctx, "transactions")
    tx_id = animal.get("sale_tx_id")
    existing_tx = ctx.repo.get(tx_path, tx_id) if tx_id else None
    if status == "sold" and change.sale_price:
        label = animal.get("name") or animal.get("ear_tag")
        fields = {
            "type": "income",
            "category": "animal_sale",
            "amount": change.sale_price,
            "date": change.date.isoformat(),
            "description": f"Sale of {label}" + (f" to {change.buyer}" if change.buyer else ""),
            "animal_id": animal_id,
        }
        if existing_tx:
            ctx.repo.update(tx_path, tx_id, fields)
        else:
            patch["sale_tx_id"] = ctx.repo.create(tx_path, fields)["id"]
    else:
        if existing_tx:
            ctx.repo.delete(tx_path, tx_id)
        patch["sale_tx_id"] = None
    updated = ctx.repo.update(path_of(ctx, "animals"), animal_id, patch)
    if status in LEFT_STATUSES:
        # Pending reminders for an animal that left the farm are no longer useful.
        for reminder in ctx.repo.list(path_of(ctx, "reminders"), [("animal_id", "==", animal_id), ("status", "==", "pending")]):
            ctx.repo.update(path_of(ctx, "reminders"), reminder["id"], {"status": "done"})
    return out(render_one(ctx, updated or animal))


@bp.delete("/animals/<animal_id>")
def delete_animal(animal_id: str):
    """Delete an animal and every health, growth and production record attached to it."""
    ctx = get_ctx()
    animal = get_animal_or_404(ctx, animal_id)
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
    _delete_photo(animal.get("photo_url"))
    return no_content()


def _delete_photo(url: str | None) -> None:
    """Best effort: remove a photo that is no longer used (replaced, or its animal deleted)."""
    remover = getattr(get_photo_store(), "delete", None)
    if not url or remover is None:
        return
    try:
        remover(url)
    except Exception as exc:  # noqa: BLE001 - a leftover file must not fail the request
        current_app.logger.warning("Could not delete photo %s: %s", url, exc)


@bp.post("/animals/<animal_id>/photo")
def upload_photo(animal_id: str):
    """POST /v1/animals/<id>/photo - store a JPEG/PNG/WebP (multipart field "file") and set photo_url."""
    ctx = get_ctx()
    store = get_photo_store()
    animal = get_animal_or_404(ctx, animal_id)
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
    if animal.get("photo_url") and animal["photo_url"] != url:
        _delete_photo(animal["photo_url"])  # the previous photo is no longer reachable from the app
    return out(render_one(ctx, updated))  # type: ignore[arg-type]


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
    barns = barn_names(ctx)
    return out(FamilyOut(
        animal=render_animal(animal, barns),
        mother=render_animal(mother, barns) if mother else None,
        father=render_animal(father, barns) if father else None,
        siblings=[render_animal(r, barns) for r in sorted(siblings.values(), key=lambda r: r["ear_tag"])],
        offspring=[render_animal(r, barns) for r in sorted(offspring.values(), key=lambda r: r["ear_tag"])],
    ))
