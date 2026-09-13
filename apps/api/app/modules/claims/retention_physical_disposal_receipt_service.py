from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.claims.retention_physical_disposal_authorization_models import (
    PhysicalDisposalAdmissionAuthorizationReceipt,
)
from app.modules.claims.retention_physical_disposal_authorization_service import (
    get_physical_disposal_admission,
)


def list_physical_disposal_admission_receipts(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    authorization_id: UUID,
) -> list[PhysicalDisposalAdmissionAuthorizationReceipt]:
    # Resolve the tenant/claim-scoped authorization first so an unknown or cross-tenant
    # credential fails with the same not-found semantics as the primary read API.
    get_physical_disposal_admission(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        authorization_id=authorization_id,
    )
    return list(
        db.scalars(
            select(PhysicalDisposalAdmissionAuthorizationReceipt)
            .where(
                PhysicalDisposalAdmissionAuthorizationReceipt.organization_id
                == organization_id,
                PhysicalDisposalAdmissionAuthorizationReceipt.claim_id == claim_id,
                PhysicalDisposalAdmissionAuthorizationReceipt.authorization_id
                == authorization_id,
            )
            .order_by(
                PhysicalDisposalAdmissionAuthorizationReceipt.sequence_number.asc(),
                PhysicalDisposalAdmissionAuthorizationReceipt.id.asc(),
            )
        ).all()
    )