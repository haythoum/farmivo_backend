from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status

from app.config import get_settings
from app.deps import Ctx, get_ctx, get_photo_store
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
from app.services.photos import ALLOWED_TYPES, PhotoStore
from app.utils import age_parts, parse_date

router = APIRouter(prefix="/animals", tags=["Animals"])

# Collections holding records that reference an animal via ``animal_id``.
RELATED_COLLECTIONS = ["vaccinations", "treatments", "vet_visits", "illnesses", "weights", "production", "feedings", "reminders"]


def render_animal(record: dict) -> AnimalOut:
    dob = parse_date(record.get("date_of_birth"))
    until = parse_date(record.get("status_date")) if record.get("status") == "deceased" else None
    days, months, label = age_parts(dob, until)
    return AnimalOut.model_validate({**record, "age_days": days, "age_months": months, "age_label": label})


def ear_tag_taken(ctx: Ctx, ear_tag: str, exclude_id: str | None = None) -> bool:
    matches = ctx.repo.list(path_of(ctx, "animals"), [("ear_tag", "==", ear_tag)])
    return any(m["id"] != exclude_id for m in matches)


def check_parents(ctx: Ctx, data: dict, animal_id: str | None = None) -> None:
    for field, expected_sex in (("mother_id", "female"), ("father_id", "male")):
        parent_id = data.get(field)
        if not parent_id:
            continue
        if parent_id == animal_id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{field} cannot be the animal itself")
        parent = ctx.repo.get(path_of(ctx, "animals"), parent_id)
        if not parent:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"{field} animal not found")
        if parent.get("sex") != expected_sex:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{field} must reference a {expected_sex} animal")


@router.get("", response_model=list[AnimalOut])
def list_animals(
    status_: str | None = Query(None, alias="status", description="a status, or 'on_farm' for active+sick+quarantine"),
    species: str | None = None,
    sex: str | None = None,
    q: str | None = Query(None, description="search ear tag, name or breed"),
    limit: int = Query(500, ge=1, le=2000),
    ctx: Ctx = Depends(get_ctx),
):
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
    return [render_animal(r) for r in rows[:limit]]


@router.post("", response_model=AnimalOut, status_code=status.HTTP_201_CREATED)
def create_animal(body: AnimalCreate, ctx: Ctx = Depends(get_ctx)):
    if ear_tag_taken(ctx, body.ear_tag):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Ear tag '{body.ear_tag}' is already used on this farm")
    data = body.model_dump(mode="json")
    check_parents(ctx, data)
    if data["status"] in ("sold", "deceased"):
        data["status_date"] = body.date_added.isoformat()
    return render_animal(ctx.repo.create(path_of(ctx, "animals"), data))


@router.get("/{animal_id}", response_model=AnimalOut)
def get_animal(animal_id: str, ctx: Ctx = Depends(get_ctx)):
    return render_animal(get_animal_or_404(ctx, animal_id))


@router.patch("/{animal_id}", response_model=AnimalOut)
def update_animal(animal_id: str, body: AnimalUpdate, ctx: Ctx = Depends(get_ctx)):  # type: ignore[valid-type]
    existing = get_animal_or_404(ctx, animal_id)
    patch = body.model_dump(mode="json", exclude_unset=True)
    if "ear_tag" in patch:
        if patch["ear_tag"] is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "ear_tag cannot be null")
        if ear_tag_taken(ctx, patch["ear_tag"], exclude_id=animal_id):
            raise HTTPException(status.HTTP_409_CONFLICT, f"Ear tag '{patch['ear_tag']}' is already used on this farm")
    for required in ("species", "sex"):
        if required in patch and patch[required] is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{required} cannot be null")
    check_parents(ctx, patch, animal_id)
    updated = ctx.repo.update(path_of(ctx, "animals"), animal_id, patch)
    return render_animal(updated or existing)


@router.post("/{animal_id}/status", response_model=AnimalOut)
def change_status(animal_id: str, body: StatusChange, ctx: Ctx = Depends(get_ctx)):
    """Change the animal's status. Selling with a price records an income transaction."""
    animal = get_animal_or_404(ctx, animal_id)
    patch: dict = {"status": body.status.value, "status_date": body.date.isoformat()}
    if body.notes:
        patch["status_notes"] = body.notes
    if body.status == AnimalStatus.sold and body.buyer:
        patch["buyer"] = body.buyer
    updated = ctx.repo.update(path_of(ctx, "animals"), animal_id, patch)
    if body.status == AnimalStatus.sold and body.sale_price:
        label = animal.get("name") or animal.get("ear_tag")
        ctx.repo.create(
            path_of(ctx, "transactions"),
            {
                "type": "income",
                "category": "animal_sale",
                "amount": body.sale_price,
                "date": body.date.isoformat(),
                "description": f"Sale of {label}" + (f" to {body.buyer}" if body.buyer else ""),
                "animal_id": animal_id,
            },
        )
    if body.status in (AnimalStatus.sold, AnimalStatus.deceased):
        # Pending reminders for an animal that left the farm are no longer useful.
        for reminder in ctx.repo.list(path_of(ctx, "reminders"), [("animal_id", "==", animal_id), ("status", "==", "pending")]):
            ctx.repo.update(path_of(ctx, "reminders"), reminder["id"], {"status": "done"})
    return render_animal(updated or animal)


@router.delete("/{animal_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_animal(animal_id: str, ctx: Ctx = Depends(get_ctx)):
    """Delete an animal and every health, growth and production record attached to it."""
    get_animal_or_404(ctx, animal_id)
    for collection in RELATED_COLLECTIONS:
        for rec in ctx.repo.list(path_of(ctx, collection), [("animal_id", "==", animal_id)]):
            ctx.repo.delete(path_of(ctx, collection), rec["id"])
    for rec in ctx.repo.list(path_of(ctx, "breedings"), [("dam_id", "==", animal_id)]):
        ctx.repo.delete(path_of(ctx, "breedings"), rec["id"])
    # Children keep existing but lose the dangling parent link.
    for field in ("mother_id", "father_id"):
        for child in ctx.repo.list(path_of(ctx, "animals"), [(field, "==", animal_id)]):
            ctx.repo.update(path_of(ctx, "animals"), child["id"], {field: None})
    ctx.repo.delete(path_of(ctx, "animals"), animal_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{animal_id}/photo", response_model=AnimalOut)
async def upload_photo(
    animal_id: str,
    file: UploadFile = File(...),
    ctx: Ctx = Depends(get_ctx),
    store: PhotoStore = Depends(get_photo_store),
):
    get_animal_or_404(ctx, animal_id)
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Photo must be JPEG, PNG or WebP")
    limit = get_settings().max_photo_bytes
    content = await file.read(limit + 1)
    if len(content) > limit:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"Photo exceeds {limit // (1024 * 1024)} MB")
    if not content:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Empty file")
    url = store.save(ctx.farm_id, animal_id, content, file.content_type)
    updated = ctx.repo.update(path_of(ctx, "animals"), animal_id, {"photo_url": url})
    return render_animal(updated)  # type: ignore[arg-type]


@router.get("/{animal_id}/family", response_model=FamilyOut)
def get_family(animal_id: str, ctx: Ctx = Depends(get_ctx)):
    """Parents, siblings (same mother or father) and offspring of an animal."""
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
    return FamilyOut(
        animal=render_animal(animal),
        mother=render_animal(mother) if mother else None,
        father=render_animal(father) if father else None,
        siblings=[render_animal(r) for r in sorted(siblings.values(), key=lambda r: r["ear_tag"])],
        offspring=[render_animal(r) for r in sorted(offspring.values(), key=lambda r: r["ear_tag"])],
    )
