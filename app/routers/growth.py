"""Growth and production: weights, production, feeding, production summary and growth chart."""

from __future__ import annotations

from datetime import timedelta

from flask import Blueprint

from app.deps import get_ctx
from app.errors import ApiError
from app.routers.crud import build_crud_blueprint, get_animal_or_404, path_of
from app.schemas import (
    DailyTotal,
    FeedingBase,
    FeedingOut,
    FeedingUpdate,
    GrowthOut,
    GrowthPoint,
    Product,
    ProductionBase,
    ProductionOut,
    ProductionSummary,
    ProductionUpdate,
    WeightBase,
    WeightOut,
    WeightUpdate,
    DEFAULT_UNIT,
)
from app.utils import parse_date, today
from app.web import body, out, q_date, q_enum, q_str

bp = Blueprint("growth_production", __name__)

weights = build_crud_blueprint(
    name="weights",
    collection="weights",
    create_model=WeightBase,
    update_model=WeightUpdate,
    out_model=WeightOut,
    date_field="date",
)
bp.register_blueprint(weights, url_prefix="/weights")


@bp.post("/weights/bulk")
def weighing_session():
    """POST /v1/weights/bulk {date, entries: [{animal_id, weight_kg}], notes?} - save a weighing session (several
    animals weighed the same day) at once. Workers and above. All or nothing: 404 if an animal is missing.
    An animal weighed twice in the list keeps the last weight. Returns {"created": n}."""
    from app.schemas import WeighingSessionIn

    ctx = get_ctx()
    data = body(WeighingSessionIn)
    entries = {e.animal_id: e.weight_kg for e in data.entries}
    for animal_id in entries:
        get_animal_or_404(ctx, animal_id)
    for animal_id, kg in entries.items():
        ctx.repo.create(path_of(ctx, "weights"), {"animal_id": animal_id, "date": data.date.isoformat(),
                                                  "weight_kg": kg, "notes": data.notes})
    return out({"created": len(entries)}, 201)

production_summary_bp = Blueprint("production_summary", __name__)


@production_summary_bp.get("/summary")
def production_summary():
    """Daily totals for one product (milk, eggs, ...) over a period. Defaults to the last 30 days."""
    ctx = get_ctx()
    product = q_enum("product", Product, required=True)
    date_from, date_to = q_date("date_from"), q_date("date_to")
    animal_id = q_str("animal_id")
    end = date_to or today()
    start = date_from or end - timedelta(days=29)
    if start > end:
        raise ApiError(422, "date_from must not be after date_to")
    filters: list[tuple[str, str, object]] = [
        ("product", "==", product.value),
        ("date", ">=", start.isoformat()),
        ("date", "<=", end.isoformat()),
    ]
    if animal_id:
        get_animal_or_404(ctx, animal_id)
        filters.append(("animal_id", "==", animal_id))
    rows = ctx.repo.list(path_of(ctx, "production"), filters, order_by="date")
    per_day: dict[str, float] = {}
    unit = DEFAULT_UNIT[product.value]
    for r in rows:
        per_day[r["date"]] = per_day.get(r["date"], 0.0) + float(r["quantity"])
        unit = r.get("unit") or unit
    total = round(sum(per_day.values()), 3)
    return out(ProductionSummary(
        product=product,
        unit=unit,
        date_from=start,
        date_to=end,
        total=total,
        days_with_records=len(per_day),
        average_per_record_day=round(total / len(per_day), 3) if per_day else 0.0,
        daily=[DailyTotal(date=d, total=round(v, 3)) for d, v in sorted(per_day.items())],
    ))


# "/production/summary" is a static rule, so it wins over the CRUD "/production/<record_id>" rule.
bp.register_blueprint(production_summary_bp, url_prefix="/production")
bp.register_blueprint(
    build_crud_blueprint(
        name="production",
        collection="production",
        create_model=ProductionBase,
        update_model=ProductionUpdate,
        out_model=ProductionOut,
        date_field="date",
    ),
    url_prefix="/production",
)

feedings = build_crud_blueprint(
    name="feedings",
    collection="feedings",
    create_model=FeedingBase,
    update_model=FeedingUpdate,
    out_model=FeedingOut,
    date_field="date",
)
bp.register_blueprint(feedings, url_prefix="/feedings")

growth_bp = Blueprint("growth_chart", __name__)


@growth_bp.get("/animals/<animal_id>/growth")
def growth_chart(animal_id: str):
    """Weight history as chart points plus total gain and average daily gain."""
    ctx = get_ctx()
    get_animal_or_404(ctx, animal_id)
    rows = ctx.repo.list(path_of(ctx, "weights"), [("animal_id", "==", animal_id)], order_by="date")
    points = [GrowthPoint(date=parse_date(r["date"]), weight_kg=r["weight_kg"]) for r in rows]  # type: ignore[arg-type]
    if not points:
        return out(GrowthOut(animal_id=animal_id, points=[]))
    first, last = points[0], points[-1]
    gain = round(last.weight_kg - first.weight_kg, 3)
    span = (last.date - first.date).days
    return out(GrowthOut(
        animal_id=animal_id,
        points=points,
        latest_weight_kg=last.weight_kg,
        total_gain_kg=gain,
        average_daily_gain_kg=round(gain / span, 3) if span > 0 else None,
    ))
