"""Health: vaccinations, treatments, vet visits, illnesses and reminders (/v1/vaccinations, ... /v1/reminders)."""

from __future__ import annotations

import re
from datetime import date, timedelta

from flask import Blueprint

from app.deps import Ctx, get_ctx
from app.errors import ApiError
from app.i18n import request_lang
from app.routers.crud import build_crud_blueprint, get_animal_or_404, path_of
from app.schemas import (
    IllnessBase,
    IllnessOut,
    IllnessUpdate,
    ReminderCreate,
    ReminderOut,
    TreatmentBase,
    TreatmentOut,
    TreatmentUpdate,
    VaccinationBase,
    VaccinationOut,
    VaccinationUpdate,
    VetVisitBase,
    VetVisitOut,
    VetVisitUpdate,
)
from app.services.reminders import animal_label, delete_reminder, reminder_title, source_title, sync_reminder
from app.utils import parse_date, today
from app.web import body, no_content, out, q_int, q_str

bp = Blueprint("health", __name__)


# ------------------------------------------------------------- vaccinations
def _sync_vaccination(ctx: Ctx, record: dict) -> None:
    """CRUD hook: keep the vacc_<id> reminder on the vaccination's next_due_date."""
    label = animal_label(ctx.repo, ctx.farm_id, record["animal_id"])
    title, key, params = source_title("vaccination", label, name=record["vaccine_name"])
    sync_reminder(
        ctx.repo,
        ctx.farm_id,
        f"vacc_{record['id']}",
        source_type="vaccination",
        source_id=record["id"],
        animal_id=record["animal_id"],
        title=title,
        title_key=key,
        title_params=params,
        due_date=record.get("next_due_date"),
    )


vaccinations = build_crud_blueprint(
    name="vaccinations",
    collection="vaccinations",
    create_model=VaccinationBase,
    update_model=VaccinationUpdate,
    out_model=VaccinationOut,
    date_field="date_given",
    after_write=_sync_vaccination,
    after_delete=lambda ctx, rec: delete_reminder(ctx.repo, ctx.farm_id, f"vacc_{rec['id']}"),
)
bp.register_blueprint(vaccinations, url_prefix="/vaccinations")

# ---------------------------------------------------------------- treatments
treatments = build_crud_blueprint(
    name="treatments",
    collection="treatments",
    create_model=TreatmentBase,
    update_model=TreatmentUpdate,
    out_model=TreatmentOut,
    date_field="start_date",
)
bp.register_blueprint(treatments, url_prefix="/treatments")


# --------------------------------------------------------------- vet visits
def _sync_vet_visit(ctx: Ctx, record: dict) -> None:
    """CRUD hook: keep the vet_<id> reminder on the vet visit's follow_up_date."""
    label = animal_label(ctx.repo, ctx.farm_id, record["animal_id"])
    title, key, params = source_title("vet", label, reason=record["reason"])
    sync_reminder(
        ctx.repo,
        ctx.farm_id,
        f"vet_{record['id']}",
        source_type="vet_visit",
        source_id=record["id"],
        animal_id=record["animal_id"],
        title=title,
        title_key=key,
        title_params=params,
        due_date=record.get("follow_up_date"),
    )


vet_visits = build_crud_blueprint(
    name="vet_visits",
    collection="vet_visits",
    create_model=VetVisitBase,
    update_model=VetVisitUpdate,
    out_model=VetVisitOut,
    date_field="visit_date",
    after_write=_sync_vet_visit,
    after_delete=lambda ctx, rec: delete_reminder(ctx.repo, ctx.farm_id, f"vet_{rec['id']}"),
)
bp.register_blueprint(vet_visits, url_prefix="/vet-visits")


# ------------------------------------------------------------------ illness
def _illness_status(record: dict) -> dict:
    """Add status "recovered" or "ongoing" depending on recovery_date."""
    return {**record, "status": "recovered" if record.get("recovery_date") else "ongoing"}


illnesses = build_crud_blueprint(
    name="illnesses",
    collection="illnesses",
    create_model=IllnessBase,
    update_model=IllnessUpdate,
    out_model=IllnessOut,
    date_field="start_date",
    enrich=_illness_status,
)
bp.register_blueprint(illnesses, url_prefix="/illnesses")


# ---------------------------------------------------------------- reminders
reminders_bp = Blueprint("reminders", __name__)


def _render_reminder(record: dict, as_of: date) -> ReminderOut:
    """Convert a stored reminder into ReminderOut with days_until counted from as_of."""
    due = parse_date(record["due_date"])
    return ReminderOut.model_validate({**record, "title": reminder_title(record, request_lang()),
                                       "days_until": (due - as_of).days if due else None})


@reminders_bp.get("/reminders")
def list_reminders():
    """GET /v1/reminders - reminders ordered by due date, filtered by status, animal, type or horizon."""
    ctx = get_ctx()
    status_ = q_str("status", "pending")
    if not re.fullmatch("pending|done|all", status_ or ""):
        raise ApiError(422, [{"loc": ["query", "status"], "msg": "String should match pattern '^(pending|done|all)$'", "type": "string_pattern_mismatch"}])
    within_days = q_int("within_days", None, ge=0, le=3650)  # only reminders due within N days (overdue included)
    animal_id, source_type = q_str("animal_id"), q_str("source_type")
    filters: list[tuple[str, str, object]] = []
    if status_ != "all":
        filters.append(("status", "==", status_))
    if animal_id:
        filters.append(("animal_id", "==", animal_id))
    if source_type:
        filters.append(("source_type", "==", source_type))
    if within_days is not None:
        filters.append(("due_date", "<=", (today() + timedelta(days=within_days)).isoformat()))
    rows = ctx.repo.list(path_of(ctx, "reminders"), filters, order_by="due_date")
    now = today()
    return out([_render_reminder(r, now) for r in rows])


@reminders_bp.post("/reminders")
def create_custom_reminder():
    """POST /v1/reminders - a reminder not tied to a record (source_type "custom")."""
    ctx = get_ctx()
    data = body(ReminderCreate)
    if data.animal_id:
        get_animal_or_404(ctx, data.animal_id)
    record = ctx.repo.create(
        path_of(ctx, "reminders"),
        {
            "source_type": "custom",
            "source_id": None,
            "animal_id": data.animal_id,
            "title": data.title,
            "due_date": data.due_date.isoformat(),
            "status": "pending",
            "notified_buckets": [],
        },
    )
    return out(_render_reminder(record, today()), 201)


@reminders_bp.post("/reminders/<reminder_id>/done")
def mark_reminder_done(reminder_id: str):
    """POST /v1/reminders/<id>/done - mark a reminder as done (no more pushes)."""
    ctx = get_ctx()
    record = ctx.repo.update(path_of(ctx, "reminders"), reminder_id, {"status": "done"})
    if not record:
        raise ApiError(404, "Reminder not found")
    return out(_render_reminder(record, today()))


@reminders_bp.delete("/reminders/<reminder_id>")
def delete_custom_reminder(reminder_id: str):
    """DELETE /v1/reminders/<id> - delete a reminder."""
    ctx = get_ctx()
    if not ctx.repo.delete(path_of(ctx, "reminders"), reminder_id):
        raise ApiError(404, "Reminder not found")
    return no_content()
