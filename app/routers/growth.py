from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.deps import Ctx, get_ctx
from app.routers.crud import build_crud_router, get_animal_or_404, path_of
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

router = APIRouter()

weights = build_crud_router(
    collection="weights",
    create_model=WeightBase,
    update_model=WeightUpdate,
    out_model=WeightOut,
    date_field="date",
)
router.include_router(weights, prefix="/weights", tags=["Growth: weight"])

production_summary_router = APIRouter()


@production_summary_router.get("/summary", response_model=ProductionSummary)
def production_summary(
    product: Product,
    date_from: date | None = None,
    date_to: date | None = None,
    animal_id: str | None = None,
    ctx: Ctx = Depends(get_ctx),
):
    """Daily totals for one product (milk, eggs, ...) over a period. Defaults to the last 30 days."""
    end = date_to or today()
    start = date_from or end - timedelta(days=29)
    if start > end:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "date_from must not be after date_to")
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
    return ProductionSummary(
        product=product,
        unit=unit,
        date_from=start,
        date_to=end,
        total=total,
        days_with_records=len(per_day),
        average_per_record_day=round(total / len(per_day), 3) if per_day else 0.0,
        daily=[DailyTotal(date=d, total=round(v, 3)) for d, v in sorted(per_day.items())],
    )


# The summary route must be registered before the CRUD "/{record_id}" routes.
router.include_router(production_summary_router, prefix="/production", tags=["Production"])
router.include_router(
    build_crud_router(
        collection="production",
        create_model=ProductionBase,
        update_model=ProductionUpdate,
        out_model=ProductionOut,
        date_field="date",
    ),
    prefix="/production",
    tags=["Production"],
)

feedings = build_crud_router(
    collection="feedings",
    create_model=FeedingBase,
    update_model=FeedingUpdate,
    out_model=FeedingOut,
    date_field="date",
)
router.include_router(feedings, prefix="/feedings", tags=["Feeding"])

growth_router = APIRouter(prefix="/animals", tags=["Growth: weight"])


@growth_router.get("/{animal_id}/growth", response_model=GrowthOut)
def growth_chart(animal_id: str, ctx: Ctx = Depends(get_ctx)):
    """Weight history as chart points plus total gain and average daily gain."""
    get_animal_or_404(ctx, animal_id)
    rows = ctx.repo.list(path_of(ctx, "weights"), [("animal_id", "==", animal_id)], order_by="date")
    points = [GrowthPoint(date=parse_date(r["date"]), weight_kg=r["weight_kg"]) for r in rows]  # type: ignore[arg-type]
    if not points:
        return GrowthOut(animal_id=animal_id, points=[])
    first, last = points[0], points[-1]
    gain = round(last.weight_kg - first.weight_kg, 3)
    span = (last.date - first.date).days
    return GrowthOut(
        animal_id=animal_id,
        points=points,
        latest_weight_kg=last.weight_kg,
        total_gain_kg=gain,
        average_daily_gain_kg=round(gain / span, 3) if span > 0 else None,
    )
