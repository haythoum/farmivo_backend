from __future__ import annotations

from fastapi import Depends, HTTPException, status

from app.deps import Ctx, get_ctx
from app.routers.animals import ear_tag_taken, render_animal
from app.routers.crud import build_crud_router, path_of
from app.schemas import (
    BirthOut,
    BirthRequest,
    BreedingBase,
    BreedingOut,
    BreedingUpdate,
)
from app.services.reminders import animal_label, delete_reminder, sync_reminder
from app.utils import expected_birth, parse_date, today

ACTIVE_PREGNANCY = {"pending", "confirmed"}


def _validate_parents(ctx: Ctx, data: dict) -> None:
    dam = ctx.repo.get(path_of(ctx, "animals"), data["dam_id"])
    if not dam:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dam (female) not found")
    if dam.get("sex") != "female":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "dam_id must reference a female animal")
    if data.get("sire_id"):
        sire = ctx.repo.get(path_of(ctx, "animals"), data["sire_id"])
        if not sire:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Sire (male) not found")
        if sire.get("sex") != "male":
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "sire_id must reference a male animal")
    if not data.get("expected_birth_date"):
        suggested = expected_birth(dam.get("species"), parse_date(data["mating_date"]))
        data["expected_birth_date"] = suggested.isoformat() if suggested else None


def _before_create(ctx: Ctx, data: dict) -> dict:
    _validate_parents(ctx, data)
    return {**data, "actual_birth_date": None, "offspring_ids": []}


def _before_update(ctx: Ctx, existing: dict, merged: dict) -> dict:
    _validate_parents(ctx, merged)
    return merged


def _sync(ctx: Ctx, record: dict) -> None:
    active = record.get("pregnancy_status") in ACTIVE_PREGNANCY
    label = animal_label(ctx.repo, ctx.farm_id, record["dam_id"])
    sync_reminder(
        ctx.repo,
        ctx.farm_id,
        f"birth_{record['id']}",
        source_type="birth",
        source_id=record["id"],
        animal_id=record["dam_id"],
        title="Expected birth" + (f": {label}" if label else ""),
        due_date=record.get("expected_birth_date") if active else None,
    )


router = build_crud_router(
    collection="breedings",
    create_model=BreedingBase,
    update_model=BreedingUpdate,
    out_model=BreedingOut,
    date_field="mating_date",
    before_create=_before_create,
    before_update=_before_update,
    after_write=_sync,
    after_delete=lambda ctx, rec: delete_reminder(ctx.repo, ctx.farm_id, f"birth_{rec['id']}"),
)


@router.post("/{breeding_id}/births", response_model=BirthOut, status_code=status.HTTP_201_CREATED)
def record_birth(breeding_id: str, body: BirthRequest, ctx: Ctx = Depends(get_ctx)):
    """Record a birth: creates the offspring as animals linked to their parents and closes the pregnancy."""
    breeding = ctx.repo.get(path_of(ctx, "breedings"), breeding_id)
    if not breeding:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Breeding record not found")
    if breeding.get("pregnancy_status") == "delivered":
        raise HTTPException(status.HTTP_409_CONFLICT, "A birth was already recorded for this breeding")
    if body.birth_date > today():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "birth_date cannot be in the future")
    if body.birth_date < parse_date(breeding["mating_date"]):  # type: ignore[operator]
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "birth_date cannot be before the mating date")

    tags = [o.ear_tag for o in body.offspring]
    if len(set(tags)) != len(tags):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Duplicate ear tags in request")
    for tag in tags:  # check everything first so a conflict creates nothing
        if ear_tag_taken(ctx, tag):
            raise HTTPException(status.HTTP_409_CONFLICT, f"Ear tag '{tag}' is already used on this farm")

    dam = ctx.repo.get(path_of(ctx, "animals"), breeding["dam_id"]) or {}
    created: list[dict] = []
    for kid in body.offspring:
        data = {
            "ear_tag": kid.ear_tag,
            "name": kid.name,
            "species": dam.get("species", "other"),
            "breed": dam.get("breed"),
            "sex": kid.sex.value,
            "date_of_birth": body.birth_date.isoformat(),
            "date_added": body.birth_date.isoformat(),
            "origin": "born_on_farm",
            "mother_id": breeding["dam_id"],
            "father_id": breeding.get("sire_id"),
            "notes": body.notes,
            "status": "deceased" if kid.stillborn else "active",
            "status_date": body.birth_date.isoformat() if kid.stillborn else None,
            "photo_url": None,
        }
        animal = ctx.repo.create(path_of(ctx, "animals"), data)
        created.append(animal)
        if kid.birth_weight_kg:
            ctx.repo.create(
                path_of(ctx, "weights"),
                {
                    "animal_id": animal["id"],
                    "date": body.birth_date.isoformat(),
                    "weight_kg": kid.birth_weight_kg,
                    "notes": "Birth weight",
                },
            )

    updated = ctx.repo.update(
        path_of(ctx, "breedings"),
        breeding_id,
        {
            "pregnancy_status": "delivered",
            "actual_birth_date": body.birth_date.isoformat(),
            "offspring_ids": [a["id"] for a in created],
        },
    )
    delete_reminder(ctx.repo, ctx.farm_id, f"birth_{breeding_id}")
    return BirthOut(
        breeding=BreedingOut.model_validate(updated),
        offspring=[render_animal(a) for a in created],
    )
