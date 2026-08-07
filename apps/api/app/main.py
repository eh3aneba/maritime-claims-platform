from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.modules.health.router import router as health_router

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="API foundation for the Maritime Claims & Risk Intelligence Platform.",
)

# Development-only origin. Production/staging origins will become configuration-driven.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router, prefix=settings.api_v1_prefix)


@app.get("/")
def root() -> dict[str, str]:
    return {
        "name": settings.app_name,
        "environment": settings.app_env,
        "docs": "/docs",
        "health": f"{settings.api_v1_prefix}/health",
    }
