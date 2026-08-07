from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import create_access_token
from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.auth.dependencies import CurrentUser
from app.modules.auth.schemas import LoginRequest, LoginResponse
from app.modules.auth.service import authenticate_user
from app.modules.users.schemas import UserRead

router = APIRouter(prefix="/auth", tags=["authentication"])
settings = get_settings()


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, response: Response, db: Annotated[Session, Depends(get_db)]) -> LoginResponse:
    user = authenticate_user(
        db,
        organization_slug=payload.organization_slug,
        email=str(payload.email),
        password=payload.password,
    )
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid organization, email, or password")

    token = create_access_token(user_id=user.id, organization_id=user.organization_id, role=user.role.value)
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        httponly=True,
        secure=settings.app_env.lower() in {"staging", "production"},
        samesite="lax",
        max_age=settings.access_token_expire_minutes * 60,
        path="/",
    )
    write_audit_log(
        db,
        organization_id=user.organization_id,
        user_id=user.id,
        action="LOGIN_SUCCESS",
        entity_type="user",
        entity_id=user.id,
    )
    db.commit()
    db.refresh(user)
    return LoginResponse(access_token=token, user=UserRead.model_validate(user))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    current_user: CurrentUser,
) -> None:
    write_audit_log(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        action="LOGOUT",
        entity_type="user",
        entity_id=current_user.id,
    )
    db.commit()
    response.delete_cookie(key=settings.auth_cookie_name, path="/")
    return None


@router.get("/me", response_model=UserRead)
def me(current_user: CurrentUser) -> UserRead:
    return UserRead.model_validate(current_user)
