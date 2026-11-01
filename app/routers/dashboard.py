"""Farm dashboard: one call with herd, movements, health, breeding and finance figures (/v1/dashboard)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from flask import Blueprint

from app.deps import get_ctx
from app.routers.crud import path_of
from app.routers.finance import compute_finance
from app.schemas import ON_FARM_STATUSES, DashboardOut
from app.services.reminders import animal_label
from app.utils import parse_date, today
from app.web import out, q_int

bp = Blueprint("dashboard", __name__)


def _count_by(rows: list[dict], key: str) -> dict[str, int]:
    """Count rows per value of a field (missing values count as "unknown")."""
    counts: dict[str, int] = {}
    for r in rows:
        counts[r.get(key) or "unknown"] = counts.get(r.get(key) or "unknown", 0) + 1
    return dict(sorted(counts.items()))


@bp.get("/dashboard")
def dashboard():
    """GET /v1/dashboard - figures for the dashboard screen."""
    ctx = get_ctx()
    period_days = q_int("period_days", 30, ge=1, le=366)  # window for births/deaths/sales and finance
    upcoming_days = q_int("upcoming_days", 30, ge=1, le=365)
    now = today()
    start = now - timedelta(days=period_days - 1)
    start_iso, end_iso = start.isoformat(), now.isoformat()

    all_animals = ctx.repo.list(path_of(ctx, "animals"))
    on_farm = [a for a in all_animals if a.get("status") in ON_FARM_STATUSES]

    def in_period(value: str | None) -> bool:
        return bool(value) and start_iso <= value[:10] <= end_iso  # type: ignore[index]

    births = sum(1 for a in all_animals if a.get("origin") == "born_on_farm" and in_period(a.get("date_of_birth")))
    deaths = sum(1 for a in all_animals if a.get("status") == "deceased" and in_period(a.get("status_date")))
    sales = sum(1 for a in all_animals if a.get("status") == "sold" and in_period(a.get("status_date")))
    purchases = sum(1 for a in all_animals if a.get("origin") == "purchased" and in_period(a.get("date_added")))

    horizon = (now + timedelta(days=upcoming_days)).isoformat()
    pending = ctx.repo.list(path_of(ctx, "reminders"), [("status", "==", "pending")], order_by="due_date")
    vaccinations = [r for r in pending if r.get("source_type") == "vaccination"]
    upcoming_vacc = [r for r in vaccinations if now.isoformat() <= r["due_date"] <= horizon]
    overdue_vacc = [r for r in vaccinations if r["due_date"] < now.isoformat()]

    def item(r: dict) -> dict:
        due = parse_date(r["due_date"])
        return {
            "reminder_id": r["id"],
            "animal_id": r.get("animal_id"),
            "animal_label": animal_label(ctx.repo, ctx.farm_id, r.get("animal_id")),
            "title": r["title"],
            "due_date": r["due_date"],
            "days_until": (due - now).days,  # type: ignore[operator]
        }

    breedings = ctx.repo.list(path_of(ctx, "breedings"))
    pregnant = [b for b in breedings if b.get("pregnancy_status") in ("pending", "confirmed")]
    due_soon = sorted(
        (b for b in pregnant if b.get("expected_birth_date") and now.isoformat() <= b["expected_birth_date"] <= horizon),
        key=lambda b: b["expected_birth_date"],
    )

    finance = compute_finance(ctx.repo, ctx.farm_id, start, now)
    ongoing_illnesses = ctx.repo.list(path_of(ctx, "illnesses"))
    unread = len(ctx.repo.list(path_of(ctx, "notifications"), [("read", "==", False)]))

    return out(DashboardOut(
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        period_days=period_days,
        period_from=start,
        period_to=now,
        animals={
            "total": len(on_farm),
            "total_all_time": len(all_animals),
            "by_species": _count_by(on_farm, "species"),
            "by_sex": _count_by(on_farm, "sex"),
            "by_status": _count_by(all_animals, "status"),
        },
        movements={"births": births, "deaths": deaths, "sales": sales, "purchases": purchases},
        health={
            "upcoming_vaccinations": [item(r) for r in upcoming_vacc[:10]],
            "upcoming_vaccinations_count": len(upcoming_vacc),
            "overdue_vaccinations_count": len(overdue_vacc),
            "sick_animals": sum(1 for a in on_farm if a.get("status") in ("sick", "quarantine")),
            "ongoing_illnesses": len([i for i in ongoing_illnesses if not i.get("recovery_date")]),
        },
        breeding={
            "pregnant_count": len(pregnant),
            "due_soon": [
                {
                    "breeding_id": b["id"],
                    "dam_id": b["dam_id"],
                    "dam_label": animal_label(ctx.repo, ctx.farm_id, b["dam_id"]),
                    "expected_birth_date": b["expected_birth_date"],
                    "days_until": (parse_date(b["expected_birth_date"]) - now).days,  # type: ignore[operator]
                }
                for b in due_soon[:10]
            ],
        },
        finance={
            "currency": finance.currency,
            "income": finance.income,
            "expenses": finance.expenses,
            "net": finance.net,
        },
        unread_notifications=unread,
    ))
