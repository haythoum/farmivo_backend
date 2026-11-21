"""Dashboard charts and key figures (GET /v1/dashboard/charts).

Everything is worked out from the records the farm already keeps (animals, weights, production, transactions), so a
farm sees its charts with no extra typing:

* ``herd_trend``: animals on the farm at the end of each of the last 12 months (this month: today);
* ``movements``: births, deaths, sales and purchases in each of the last 6 months;
* ``age_groups``: animals on the farm by age (under 6 months, 6-12 months, 1-2 years, over 2 years, unknown);
* ``milk``: litres per day over the last 14 days;
* ``finance``: income, expenses and net in each of the last 6 months (owner and managers only, else null);
* ``kpis``: the year's birth and death rates, the average daily gain of the animals weighed lately, this month
  against last month, and for the owner and managers the cost per animal this month and the profit per animal over
  the year.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.permissions import can_see_finance
from app.routers.crud import path_of
from app.routers.finance import compute_finance
from app.schemas import ON_FARM_STATUSES
from app.utils import parse_date, today

#: Days of weighings used for the average daily gain.
GAIN_WINDOW_DAYS = 120
AGE_GROUPS = ("under_6m", "6_12m", "1_2y", "over_2y", "unknown")


def day(value: Any) -> date | None:
    """A stored date (string or date) as a date; None when empty or not a date."""
    try:
        return parse_date(value or None)
    except (TypeError, ValueError):
        return None


def month_start(d: date, back: int = 0) -> date:
    """First day of the month ``back`` months before the month of ``d``."""
    m = d.year * 12 + d.month - 1 - back
    return date(m // 12, m % 12 + 1, 1)


def month_end(first: date) -> date:
    """Last day of the month that starts on ``first``."""
    return month_start(first, -1) - timedelta(days=1)


def arrived(a: dict) -> date | None:
    """The day an animal came onto the farm: its birth for one born there, otherwise the day it was added."""
    if a.get("origin") == "born_on_farm" and a.get("date_of_birth"):
        return day(a["date_of_birth"])
    return day(a.get("date_added") or a.get("date_of_birth"))


def left(a: dict) -> date | None:
    """The day an animal left (sold, died, ...), None while it is on the farm."""
    if a.get("status") in ON_FARM_STATUSES:
        return None
    return day(a.get("status_date")) or arrived(a)


def on_farm_at(animals: list[dict], day: date) -> int:
    """Animals on the farm at the end of ``day``."""
    n = 0
    for a in animals:
        came, went = arrived(a), left(a)
        if came is not None and came <= day and (went is None or went > day):
            n += 1
    return n


def age_group(a: dict, now: date) -> str:
    """One of AGE_GROUPS for an animal's age today."""
    born = day(a.get("date_of_birth"))
    if born is None:
        return "unknown"
    days = (now - born).days
    if days < 183:
        return "under_6m"
    if days < 365:
        return "6_12m"
    if days < 730:
        return "1_2y"
    return "over_2y"


def movement(a: dict) -> tuple[str, date] | None:
    """("births" | "purchases", day) for an arrival worth counting."""
    if a.get("origin") == "born_on_farm" and a.get("date_of_birth"):
        return ("births", day(a["date_of_birth"])) if day(a["date_of_birth"]) else None
    if a.get("origin") == "purchased" and a.get("date_added"):
        return ("purchases", day(a["date_added"])) if day(a["date_added"]) else None
    return None


def departure(a: dict) -> tuple[str, date] | None:
    """("deaths" | "sales", day) for a death or a sale."""
    kind = {"deceased": "deaths", "sold": "sales"}.get(a.get("status") or "")
    when = day(a.get("status_date"))
    return (kind, when) if kind and when else None


def average_daily_gain(weights: list[dict]) -> tuple[float | None, int]:
    """Mean of each animal's gain per day between its first and last weighing (animals weighed twice or more)."""
    by_animal: dict[str, list[tuple[date, float]]] = {}
    for w in weights:
        d = day(w.get("date"))
        if w.get("animal_id") and d is not None:
            by_animal.setdefault(w["animal_id"], []).append((d, float(w["weight_kg"])))
    gains = []
    for rows in by_animal.values():
        rows.sort()
        span = (rows[-1][0] - rows[0][0]).days
        if span > 0:
            gains.append((rows[-1][1] - rows[0][1]) / span)
    return (round(sum(gains) / len(gains), 3) if gains else None), len(gains)


def pct(part: float, whole: float) -> float | None:
    """part / whole in %, one decimal; None when whole is 0."""
    return round(100 * part / whole, 1) if whole else None


def charts(ctx: Any) -> dict:
    """The whole answer of GET /v1/dashboard/charts for the caller's farm."""
    now = today()
    animals = ctx.repo.list(path_of(ctx, "animals"))
    on_farm = [a for a in animals if a.get("status") in ON_FARM_STATUSES]

    trend = []
    for back in range(11, -1, -1):
        first = month_start(now, back)
        end = now if back == 0 else month_end(first)
        trend.append({"month": first.strftime("%Y-%m"), "animals": on_farm_at(animals, end)})

    months6 = [month_start(now, back).strftime("%Y-%m") for back in range(5, -1, -1)]
    moves = {m: {"month": m, "births": 0, "deaths": 0, "sales": 0, "purchases": 0} for m in months6}
    year_ago = now - timedelta(days=364)
    year = {"births": 0, "deaths": 0, "sales": 0, "purchases": 0}
    this_m, last_m = months6[-1], months6[-2]
    for a in animals:
        for ev in (movement(a), departure(a)):
            if ev is None:
                continue
            kind, when = ev
            key = when.strftime("%Y-%m")
            if key in moves:
                moves[key][kind] += 1
            if year_ago <= when <= now:
                year[kind] += 1

    ages = {g: 0 for g in AGE_GROUPS}
    for a in on_farm:
        ages[age_group(a, now)] += 1

    milk_from = now - timedelta(days=13)
    milk_rows = ctx.repo.list(path_of(ctx, "production"), [
        ("product", "==", "milk"), ("date", ">=", milk_from.isoformat()), ("date", "<=", now.isoformat())])
    per_day: dict[str, float] = {}
    for r in milk_rows:
        per_day[r["date"][:10]] = per_day.get(r["date"][:10], 0.0) + float(r["quantity"])
    milk = [{"date": (milk_from + timedelta(days=i)).isoformat(),
             "quantity": round(per_day.get((milk_from + timedelta(days=i)).isoformat(), 0.0), 2)} for i in range(14)]
    milk_month = {m: 0.0 for m in (this_m, last_m)}
    for r in ctx.repo.list(path_of(ctx, "production"), [
            ("product", "==", "milk"), ("date", ">=", month_start(now, 1).isoformat()), ("date", "<=", now.isoformat())]):
        if r["date"][:7] in milk_month:
            milk_month[r["date"][:7]] += float(r["quantity"])

    weights = ctx.repo.list(path_of(ctx, "weights"), [("date", ">=", (now - timedelta(days=GAIN_WINDOW_DAYS)).isoformat())])
    adg, weighed = average_daily_gain(weights)

    avg_herd = sum(p["animals"] for p in trend) / len(trend)
    kpis: dict[str, Any] = {
        "animals": len(on_farm),
        "births_year": year["births"],
        "deaths_year": year["deaths"],
        "sales_year": year["sales"],
        "average_herd_year": round(avg_herd, 1),
        "birth_rate_pct": pct(year["births"], avg_herd),
        "mortality_pct": pct(year["deaths"], avg_herd),
        "average_daily_gain_kg": adg,
        "animals_weighed": weighed,
        "this_month": {"births": moves[this_m]["births"], "deaths": moves[this_m]["deaths"],
                       "sales": moves[this_m]["sales"], "milk": round(milk_month[this_m], 2)},
        "last_month": {"births": moves[last_m]["births"], "deaths": moves[last_m]["deaths"],
                       "sales": moves[last_m]["sales"], "milk": round(milk_month[last_m], 2)},
    }

    finance = None
    if can_see_finance(ctx.role):
        summary = compute_finance(ctx.repo, ctx.farm_id, month_start(now, 11), now)
        by_month = {m.month: m for m in summary.monthly}
        finance = {"currency": summary.currency, "months": []}
        for m in months6:
            row = by_month.get(m)
            inc, exp = (row.income, row.expenses) if row else (0.0, 0.0)
            finance["months"].append({"month": m, "income": inc, "expenses": exp, "net": round(inc - exp, 2)})
        cur, prev = finance["months"][-1], finance["months"][-2]
        kpis["this_month"].update(income=cur["income"], expenses=cur["expenses"])
        kpis["last_month"].update(income=prev["income"], expenses=prev["expenses"])
        kpis["cost_per_animal_month"] = round(cur["expenses"] / len(on_farm), 2) if on_farm else None
        kpis["profit_per_animal_year"] = round(summary.net / avg_herd, 2) if avg_herd else None
        kpis["currency"] = summary.currency

    return {
        "generated_for": now.isoformat(),
        "herd_trend": trend,
        "movements": list(moves.values()),
        "age_groups": ages,
        "milk": {"unit": "liters", "days": milk},
        "finance": finance,
        "kpis": kpis,
    }
