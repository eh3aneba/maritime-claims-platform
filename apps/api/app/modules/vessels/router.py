from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.auth.dependencies import CurrentUser
from app.modules.vessels.schemas import VesselCreate, VesselListResponse, VesselRead
from app.modules.vessels.service import DuplicateVesselError, create_vessel, list_vessels

router = APIRouter(prefix="/vessels", tags=["vessels"])


@router.get("", response_model=VesselListResponse)
def list_vessels_endpoint(
    db: Annotated[Session, Depends(get_db)],
    current_user: CurrentUser,
    search: Annotated[str | None, Query(max_length=200)] = None,
) -> VesselListResponse:
    vessels, total = list_vessels(db, organization_id=current_user.organization_id, search=search)
    return VesselListResponse(items=[VesselRead.model_validate(v) for v in vessels], total=total)


@router.post("", response_model=VesselRead, status_code=status.HTTP_201_CREATED)
def create_vessel_endpoint(
    payload: VesselCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: CurrentUser,
) -> VesselRead:
    try:
        vessel = create_vessel(db, organization_id=current_user.organization_id, payload=payload)
    except DuplicateVesselError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    write_audit_log(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        action="CREATE_VESSEL",
        entity_type="vessel",
        entity_id=vessel.id,
        new_values={"name": vessel.name, "imo_number": vessel.imo_number},
    )
    db.commit()
    db.refresh(vessel)
    return VesselRead.model_validate(vessel)
