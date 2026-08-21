from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.modules.adjustments.router import router as adjustments_router
from app.modules.ai_broader_production.router import router as ai_broader_production_router
from app.modules.ai_broader_production_outcomes.router import router as ai_broader_production_outcomes_router
from app.modules.ai_evaluation.router import router as ai_evaluation_router
from app.modules.ai_final_production.router import router as ai_final_production_router
from app.modules.ai_final_production_readiness.router import router as ai_final_production_readiness_router
from app.modules.ai_governance.router import router as ai_governance_router
from app.modules.ai_high_coverage.router import router as ai_high_coverage_router
from app.modules.ai_high_coverage_outcomes.router import router as ai_high_coverage_outcomes_router
from app.modules.ai_limited_production.router import router as ai_limited_production_router
from app.modules.ai_limited_production_outcomes.router import router as ai_limited_production_outcomes_router
from app.modules.ai_pilot_outcomes.router import router as ai_pilot_outcomes_router
from app.modules.ai_private_pilot.router import router as ai_private_pilot_router
from app.modules.ai_scale_up.router import router as ai_scale_up_router
from app.modules.ai_scale_up_outcomes.router import router as ai_scale_up_outcomes_router
from app.modules.auth.router import router as auth_router
from app.modules.assessments.router import router as assessments_router
from app.modules.claim_packs.router import router as claim_packs_router
from app.modules.claims.router import router as claims_router
from app.modules.chronology.router import router as chronology_router
from app.modules.correspondence.router import router as correspondence_router
from app.modules.documents.router import router as documents_router
from app.modules.email_ingestion.router import router as email_ingestion_router
from app.modules.external_portal.router import router as external_portal_router
from app.modules.evidence_matrix.router import router as evidence_matrix_router
from app.modules.health.router import router as health_router
from app.modules.financial.router import router as financial_router
from app.modules.intelligence.router import router as intelligence_router
from app.modules.intake.router import router as intake_router
from app.modules.processing.router import router as processing_router
from app.modules.pilot.router import router as pilot_router
from app.modules.pilot_operations.router import router as pilot_operations_router
from app.modules.policy_intelligence.router import router as policy_intelligence_router
from app.modules.outreach.router import router as outreach_router
from app.modules.review.router import router as review_router
from app.modules.rules.router import router as rules_router
from app.modules.settlements.router import router as settlements_router
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router, prefix=settings.api_v1_prefix)
app.include_router(ai_evaluation_router, prefix=settings.api_v1_prefix)
app.include_router(ai_governance_router, prefix=settings.api_v1_prefix)
app.include_router(ai_private_pilot_router, prefix=settings.api_v1_prefix)
app.include_router(ai_pilot_outcomes_router, prefix=settings.api_v1_prefix)
app.include_router(ai_limited_production_router, prefix=settings.api_v1_prefix)
app.include_router(ai_limited_production_outcomes_router, prefix=settings.api_v1_prefix)
app.include_router(ai_scale_up_router, prefix=settings.api_v1_prefix)
app.include_router(ai_scale_up_outcomes_router, prefix=settings.api_v1_prefix)
app.include_router(ai_broader_production_router, prefix=settings.api_v1_prefix)
app.include_router(ai_broader_production_outcomes_router, prefix=settings.api_v1_prefix)
app.include_router(ai_high_coverage_router, prefix=settings.api_v1_prefix)
app.include_router(ai_high_coverage_outcomes_router, prefix=settings.api_v1_prefix)
app.include_router(ai_final_production_readiness_router, prefix=settings.api_v1_prefix)
app.include_router(ai_final_production_router, prefix=settings.api_v1_prefix)
app.include_router(adjustments_router, prefix=settings.api_v1_prefix)
app.include_router(assessments_router, prefix=settings.api_v1_prefix)
app.include_router(financial_router, prefix=settings.api_v1_prefix)
app.include_router(intelligence_router, prefix=settings.api_v1_prefix)
app.include_router(intake_router, prefix=settings.api_v1_prefix)
app.include_router(auth_router, prefix=settings.api_v1_prefix)
app.include_router(claims_router, prefix=settings.api_v1_prefix)
app.include_router(claim_packs_router, prefix=settings.api_v1_prefix)
app.include_router(chronology_router, prefix=settings.api_v1_prefix)
app.include_router(correspondence_router, prefix=settings.api_v1_prefix)
app.include_router(documents_router, prefix=settings.api_v1_prefix)
app.include_router(email_ingestion_router, prefix=settings.api_v1_prefix)
app.include_router(external_portal_router, prefix=settings.api_v1_prefix)
app.include_router(evidence_matrix_router, prefix=settings.api_v1_prefix)
app.include_router(processing_router, prefix=settings.api_v1_prefix)
app.include_router(pilot_router, prefix=settings.api_v1_prefix)
app.include_router(pilot_operations_router, prefix=settings.api_v1_prefix)
app.include_router(policy_intelligence_router, prefix=settings.api_v1_prefix)
app.include_router(outreach_router, prefix=settings.api_v1_prefix)
app.include_router(review_router, prefix=settings.api_v1_prefix)
app.include_router(rules_router, prefix=settings.api_v1_prefix)
app.include_router(settlements_router, prefix=settings.api_v1_prefix)
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
