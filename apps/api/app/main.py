from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.modules.auth.router import router as auth_router
from app.modules.assessments.router import router as assessments_router
from app.modules.claims.router import router as claims_router
from app.modules.chronology.router import router as chronology_router
from app.modules.documents.router import router as documents_router
from app.modules.health.router import router as health_router
from app.modules.financial.router import router as financial_router
from app.modules.intelligence.router import router as intelligence_router
from app.modules.processing.router import router as processing_router
from app.modules.pilot.router import router as pilot_router
from app.modules.outreach.router import router as outreach_router
from app.modules.review.router import router as review_router
from app.modules.rules.router import router as rules_router
from app.modules.users.router import router as users_router
from app.modules.tasks.router import router as tasks_router
from app.modules.technical.router import router as technical_router
from app.modules.vessels.router import router as vessels_router

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="API foundation for the Maritime Claims & Risk Intelligence Platform.",
)

# CORS is explicit and environment-configurable. Credentials require concrete origins.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router, prefix=settings.api_v1_prefix)
app.include_router(assessments_router, prefix=settings.api_v1_prefix)
app.include_router(financial_router, prefix=settings.api_v1_prefix)
app.include_router(intelligence_router, prefix=settings.api_v1_prefix)
app.include_router(auth_router, prefix=settings.api_v1_prefix)
app.include_router(claims_router, prefix=settings.api_v1_prefix)
app.include_router(chronology_router, prefix=settings.api_v1_prefix)
app.include_router(documents_router, prefix=settings.api_v1_prefix)
app.include_router(processing_router, prefix=settings.api_v1_prefix)
app.include_router(pilot_router, prefix=settings.api_v1_prefix)
app.include_router(outreach_router, prefix=settings.api_v1_prefix)
app.include_router(review_router, prefix=settings.api_v1_prefix)
app.include_router(rules_router, prefix=settings.api_v1_prefix)
app.include_router(tasks_router, prefix=settings.api_v1_prefix)
app.include_router(technical_router, prefix=settings.api_v1_prefix)
app.include_router(users_router, prefix=settings.api_v1_prefix)
app.include_router(vessels_router, prefix=settings.api_v1_prefix)


@app.get("/")
def root() -> dict[str, str]:
    return {
        "name": settings.app_name,
        "environment": settings.app_env,
        "docs": "/docs",
        "health": f"{settings.api_v1_prefix}/health",
    }
