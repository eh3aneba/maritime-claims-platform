from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.auth.dependencies import CurrentUser
from app.modules.claims.service import ClaimNotFoundError
from app.modules.evidence_matrix.schemas import EvidenceMatrixResponse
from app.modules.evidence_matrix.service import build_evidence_matrix


router = APIRouter(prefix="/claims", tags=["evidence-matrix"])


@router.get("/{claim_id}/evidence-matrix", response_model=EvidenceMatrixResponse)
def get_evidence_matrix(
    claim_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: CurrentUser,
) -> EvidenceMatrixResponse:
    try:
        return build_evidence_matrix(
            db,
            claim_id=claim_id,
            organization_id=current_user.organization_id,
        )
    except ClaimNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Claim not found",
        ) from exc
