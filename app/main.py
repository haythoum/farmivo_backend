from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import animals, breeding, dashboard, farm, finance, growth, health, internal, notifications, photos, reports

API_PREFIX = "/v1"

app = FastAPI(
    title="Farmivo API",
    description="Smart Farming. Better Living.",
    version="1.0.0",
)

settings = get_settings()
if settings.cors_origin_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.get("/healthz", tags=["Meta"])
def healthz() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(farm.router, prefix=API_PREFIX)
app.include_router(animals.router, prefix=API_PREFIX)
app.include_router(growth.growth_router, prefix=API_PREFIX)  # /animals/{id}/growth
app.include_router(health.router, prefix=API_PREFIX)
app.include_router(health.reminders_router, prefix=API_PREFIX)
app.include_router(breeding.router, prefix=f"{API_PREFIX}/breedings", tags=["Breeding"])
app.include_router(growth.router, prefix=API_PREFIX)
app.include_router(finance.router, prefix=API_PREFIX)
app.include_router(dashboard.router, prefix=API_PREFIX)
app.include_router(notifications.router, prefix=API_PREFIX)
app.include_router(photos.router, prefix=API_PREFIX)
app.include_router(reports.router, prefix=API_PREFIX)
app.include_router(internal.router, prefix=API_PREFIX)
