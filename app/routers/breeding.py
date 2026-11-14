"""Breeding and reproduction: matings, pregnancy, expected birth reminder and births (/v1/breedings...)."""

from __future__ import annotations

from app.deps import Ctx, get_ctx
from app.errors import ApiError
from app.routers.animals import ear_tag_taken, farm_code_for, render_one, tag_conflict
from app.routers.crud import build_crud_blueprint, path_of
from app.schemas import (
    ON_FARM_STATUSES,
    BirthOut,
    BirthRequest,
    BreedingBase,
    BreedingOut,
    BreedingUpdate,
)
from app.services.reminders import animal_label, delete_reminder, source_title, sync_reminder
from app.utils import expected_birth, parse_date, pregnancy_check, today
from app.web import body, out

# "pending" = mated, not checked yet; only "confirmed" counts as pregnant (dashboard, pregnant list).
ACTIVE_PREGNANCY = {"pending", "confirmed"}


def _validate_parents(ctx: Ctx, data: dict, new: bool = False) -> dict:
    """Check dam (female) and sire (male, same species as the dam; a cow is never mated with a ram), fill
    expected_birth_date from the gestation table; returns the dam. A new mating needs both animals on the farm."""
    dam = ctx.repo.get(path_of(ctx, "animals"), data["dam_id"])
    if not dam:
        raise ApiError(404, "Dam (female) not found")
    if dam.get("sex") != "female":
        raise ApiError(422, "dam_id must reference a female animal")
    if new and dam.get("status") not in ON_FARM_STATUSES:
        raise ApiError(422, f"Only animals on the farm can be mated ({dam.get('ear_tag')})")
    if data.get("sire_id"):
        sire = ctx.repo.get(path_of(ctx, "animals"), data["sire_id"])
        if not sire:
            raise ApiError(404, "Sire (male) not found")
        if sire.get("sex") != "male":
            raise ApiError(422, "sire_id must reference a male animal")
        if sire.get("species") != dam.get("species"):
            raise ApiError(422, f"The father must be of the same species as the mother ({dam.get('species')})")
        if new and sire.get("status") not in ON_FARM_STATUSES:
            raise ApiError(422, f"Only animals on the farm can be mated ({sire.get('ear_tag')})")
    if not data.get("expected_birth_date"):
        suggested = expected_birth(dam.get("species"), parse_date(data["mating_date"]))
        data["expected_birth_date"] = suggested.isoformat() if suggested else None
    if data.get("pregnancy_status") == "confirmed" and not data.get("pregnancy_confirmed_date"):
        data["pregnancy_confirmed_date"] = today().isoformat()
    return dam


def _before_create(ctx: Ctx, data: dict) -> dict:
    """CRUD hook: validate parents and start with no birth recorded."""
    if data.get("pregnancy_status") == "delivered":
        raise ApiError(422, "Record the birth to mark a pregnancy as delivered")
    _validate_parents(ctx, data, new=True)
    return {**data, "actual_birth_date": None, "offspring_ids": []}


def _before_update(ctx: Ctx, existing: dict, merged: dict) -> dict:
    """CRUD hook: re-validate parents on every update. "delivered" is only set by recording the birth
    (POST /breedings/<id>/births), which also creates the newborns. When the mating date moves and the expected
    birth was still the suggested one, the suggestion follows the new date."""
    if merged.get("pregnancy_status") == "delivered" and existing.get("pregnancy_status") != "delivered":
        raise ApiError(422, "Record the birth to mark a pregnancy as delivered")
    if merged.get("mating_date") != existing.get("mating_date") and existing.get("expected_birth_date"):
        dam = ctx.repo.get(path_of(ctx, "animals"), existing["dam_id"]) or {}
        old = expected_birth(dam.get("species"), parse_date(existing["mating_date"]))
        if old and merged.get("expected_birth_date") == old.isoformat():
            merged["expected_birth_date"] = None  # recomputed by _validate_parents
    if merged.get("pregnancy_status") == "pending":
        merged["pregnancy_confirmed_date"] = None  # not checked yet: no confirmation date
    _validate_parents(ctx, merged)
    return merged


def _sync(ctx: Ctx, record: dict) -> None:
    """CRUD hook: an unconfirmed mating (pending) gets a "Pregnancy check" reminder a few weeks after mating; a
    confirmed pregnancy gets the "Expected birth" reminder on expected_birth_date. Other states have neither."""
    status = record.get("pregnancy_status")
    label = animal_label(ctx.repo, ctx.farm_id, record["dam_id"])
    dam = ctx.repo.get(path_of(ctx, "animals"), record["dam_id"]) or {}
    check = pregnancy_check(dam.get("species"), parse_date(record["mating_date"])) if status == "pending" else None
    for kind, reminder_id, due in (
        ("pregnancy_check", f"check_{record['id']}", check.isoformat() if check else None),
        ("birth", f"birth_{record['id']}", record.get("expected_birth_date") if status == "confirmed" else None),
    ):
        title, key, params = source_title(kind, label)
        sync_reminder(
            ctx.repo,
            ctx.farm_id,
            reminder_id,
            source_type=kind,
            source_id=record["id"],
            animal_id=record["dam_id"],
            title=title,
            title_key=key,
            title_params=params,
            due_date=due,
        )


def _after_delete(ctx: Ctx, record: dict) -> None:
    delete_reminder(ctx.repo, ctx.farm_id, f"birth_{record['id']}")
    delete_reminder(ctx.repo, ctx.farm_id, f"check_{record['id']}")


bp = build_crud_blueprint(
    name="breedings",
    collection="breedings",
    create_model=BreedingBase,
    update_model=BreedingUpdate,
    out_model=BreedingOut,
    date_field="mating_date",
    before_create=_before_create,
    before_update=_before_update,
    after_write=_sync,
    after_delete=_after_delete,
)


@bp.post("/<breeding_id>/births")
def record_birth(breeding_id: str):
    """Record a birth: creates the offspring as animals linked to their parents and closes the pregnancy."""
    ctx = get_ctx()
    req = body(BirthRequest)
    breeding = ctx.repo.get(path_of(ctx, "breedings"), breeding_id)
    if not breeding:
        raise ApiError(404, "Breeding record not found")
    if breeding.get("pregnancy_status") == "delivered":
        raise ApiError(409, "A birth was already recorded for this breeding")
    if req.birth_date > today():
        raise ApiError(422, "birth_date cannot be in the future")
    if req.birth_date < parse_date(breeding["mating_date"]):  # type: ignore[operator]
        raise ApiError(422, "birth_date cannot be before the mating date")

    dam = ctx.repo.get(path_of(ctx, "animals"), breeding["dam_id"]) or {}
    species = dam.get("species", "other")
    tags = [o.ear_tag for o in req.offspring if o.ear_tag]  # empty: the newborn's farm number
    if len(set(tags)) != len(tags):
        raise ApiError(422, "Duplicate ear tags in request")
    for tag in tags:  # check everything first so a conflict creates nothing
        if ear_tag_taken(ctx, tag, species):
            raise tag_conflict(tag, species)

    # Claim the breeding first (compare-and-set), so two simultaneous requests cannot both create the newborns.
    claimed = ctx.repo.update_where(path_of(ctx, "breedings"), breeding_id,
                                    {"pregnancy_status": breeding.get("pregnancy_status")},
                                    {"pregnancy_status": "delivered", "actual_birth_date": req.birth_date.isoformat()})
    if claimed is None:
        raise ApiError(409, "A birth was already recorded for this breeding")

    created: list[dict] = []
    for kid in req.offspring:
        data = {
            "ear_tag": kid.ear_tag,
            "farm_code": None,
            "name": kid.name,
            "species": species,
            "breed": dam.get("breed"),
            "sex": kid.sex.value,
            "date_of_birth": req.birth_date.isoformat(),
            "date_added": req.birth_date.isoformat(),
            "origin": "born_on_farm",
            "mother_id": breeding["dam_id"],
            "father_id": breeding.get("sire_id"),
            "notes": req.notes,
            "status": "deceased" if kid.stillborn else "active",
            "status_date": req.birth_date.isoformat() if kid.stillborn else None,
            "photo_url": None,
            "barn_id": dam.get("barn_id"),  # newborns stay with their mother
        }
        # Its own farm number, of its birth year; the link to the mother is mother_id (family tracking).
        data["farm_code"] = farm_code_for(ctx, data)
        data["ear_tag"] = data["ear_tag"] or data["farm_code"]
        animal = ctx.repo.create(path_of(ctx, "animals"), data)
        created.append(animal)
        if kid.birth_weight_kg:
            ctx.repo.create(
                path_of(ctx, "weights"),
                {
                    "animal_id": animal["id"],
                    "date": req.birth_date.isoformat(),
                    "weight_kg": kid.birth_weight_kg,
                    "notes": "Birth weight",
                },
            )

    updated = ctx.repo.update(
        path_of(ctx, "breedings"),
        breeding_id,
        {
            "pregnancy_status": "delivered",
            "actual_birth_date": req.birth_date.isoformat(),
            "offspring_ids": [a["id"] for a in created],
        },
    )
    delete_reminder(ctx.repo, ctx.farm_id, f"birth_{breeding_id}")
    delete_reminder(ctx.repo, ctx.farm_id, f"check_{breeding_id}")
    return out(BirthOut(
        breeding=BreedingOut.model_validate(updated),
        offspring=[render_one(ctx, a) for a in created],
    ), 201)
