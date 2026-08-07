from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.auth.dependencies import require_roles
from app.modules.users.models import User, UserRole
from app.modules.users.schemas import UserCreate, UserRead
from app.modules.users.service import DuplicateUserError, create_user_in_organization

router = APIRouter(prefix="/users", tags=["users"])


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> UserRead:
    try:
        user = create_user_in_organization(db, organization_id=current_user.organization_id, payload=payload)
    except DuplicateUserError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    write_audit_log(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        action="CREATE_USER",
        entity_type="user",
        entity_id=user.id,
        new_values={"email": user.email, "role": user.role.value},
    )
    db.commit()
    db.refresh(user)
    return UserRead.model_validate(user)
