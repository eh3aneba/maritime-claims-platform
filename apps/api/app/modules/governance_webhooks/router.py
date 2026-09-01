from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.auth.dependencies import require_roles
from app.modules.governance_webhooks.schemas import (
    GovernanceWebhookDashboard,
    GovernanceWebhookDeliveryPage,
    GovernanceWebhookDeliveryView,
    GovernanceWebhookDestinationCreate,
    GovernanceWebhookDestinationUpdate,
    GovernanceWebhookDestinationView,
    GovernanceWebhookRetryResult,
    GovernanceWebhookSecretIssued,
    GovernanceWebhookTestResult,
)
from app.modules.governance_webhooks.service import (
    create_destination,
    dashboard,
    enqueue_test_delivery,
    list_deliveries,
    list_destinations,
    manual_retry_delivery,
    rotate_destination_secret,
    update_destination,
)
from app.modules.users.models import User, UserRole

router = APIRouter(prefix="/governance-webhooks", tags=["governance-webhooks"])
Manager = Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.CLAIMS_MANAGER))]
Admin = Annotated[User, Depends(require_roles(UserRole.ADMIN))]


@router.get("", response_model=GovernanceWebhookDashboard)
def webhook_dashboard(manager: Manager, db: Annotated[Session, Depends(get_db)]):
    return dashboard(db, manager.organization_id)


@router.get("/destinations", response_model=list[GovernanceWebhookDestinationView])
def destinations_list(manager: Manager, db: Annotated[Session, Depends(get_db)]):
    return list_destinations(db, manager.organization_id)


@router.post("/destinations", response_model=GovernanceWebhookSecretIssued, status_code=201)
def destination_create(
    payload: GovernanceWebhookDestinationCreate,
    admin: Admin,
    db: Annotated[Session, Depends(get_db)],
):
    destination, secret = create_destination(db, admin, **payload.model_dump())
    return {
        "destination": destination,
        "signing_secret": secret,
        "secret_version": destination.secret_version,
        "secret_reference": destination.secret_reference,
    }


@router.patch("/destinations/{destination_id}", response_model=GovernanceWebhookDestinationView)
def destination_update(
    destination_id: UUID,
    payload: GovernanceWebhookDestinationUpdate,
    admin: Admin,
    db: Annotated[Session, Depends(get_db)],
):
    return update_destination(
        db,
        admin,
        destination_id,
        **payload.model_dump(exclude_unset=True),
    )


@router.post(
    "/destinations/{destination_id}/rotate-secret",
    response_model=GovernanceWebhookSecretIssued,
)
def destination_rotate_secret(
    destination_id: UUID,
    admin: Admin,
    db: Annotated[Session, Depends(get_db)],
):
    destination, secret = rotate_destination_secret(db, admin, destination_id)
    return {
        "destination": destination,
        "signing_secret": secret,
        "secret_version": destination.secret_version,
        "secret_reference": destination.secret_reference,
    }


@router.post("/destinations/{destination_id}/test", response_model=GovernanceWebhookTestResult)
def destination_test(
    destination_id: UUID,
    admin: Admin,
    db: Annotated[Session, Depends(get_db)],
):
    return {"delivery": enqueue_test_delivery(db, admin, destination_id)}


@router.get("/deliveries", response_model=GovernanceWebhookDeliveryPage)
def deliveries_list(
    manager: Manager,
    db: Annotated[Session, Depends(get_db)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    destination_id: UUID | None = None,
    status: str | None = Query(default=None, max_length=30),
):
    return list_deliveries(
        db,
        manager.organization_id,
        page=page,
        page_size=page_size,
        destination_id=destination_id,
        status=status,
    )


@router.post("/deliveries/{delivery_id}/retry", response_model=GovernanceWebhookRetryResult)
def delivery_retry(
    delivery_id: UUID,
    admin: Admin,
    db: Annotated[Session, Depends(get_db)],
):
    return {"delivery": manual_retry_delivery(db, admin, delivery_id)}


@router.get("/deliveries/{delivery_id}", response_model=GovernanceWebhookDeliveryView)
def delivery_detail(
    delivery_id: UUID,
    manager: Manager,
    db: Annotated[Session, Depends(get_db)],
):
    page = list_deliveries(db, manager.organization_id, page=1, page_size=100)
    for delivery in page["deliveries"]:
        if delivery.id == delivery_id:
            return delivery
    from fastapi import HTTPException

    raise HTTPException(404, "Governance webhook delivery not found")
