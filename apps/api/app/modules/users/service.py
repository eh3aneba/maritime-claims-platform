from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.modules.users.models import User
from app.modules.users.schemas import UserCreate


class DuplicateUserError(ValueError):
    pass


def create_user_in_organization(db: Session, *, organization_id, payload: UserCreate) -> User:
    normalized_email = str(payload.email).strip().lower()
    exists = db.scalar(
        select(User.id).where(
            User.organization_id == organization_id,
            func.lower(User.email) == normalized_email,
        )
    )
    if exists is not None:
        raise DuplicateUserError("A user with this email already exists in the organization")

    user = User(
        organization_id=organization_id,
        email=normalized_email,
        full_name=payload.full_name.strip(),
        password_hash=hash_password(payload.password),
        role=payload.role,
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user
