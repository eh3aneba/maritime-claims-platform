from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import verify_password
from app.modules.organizations.models import Organization, OrganizationStatus
from app.modules.users.models import User


def authenticate_user(
    db: Session,
    *,
    organization_slug: str,
    email: str,
    password: str,
) -> User | None:
    stmt = (
        select(User)
        .join(Organization, User.organization_id == Organization.id)
        .where(
            func.lower(Organization.slug) == organization_slug.strip().lower(),
            Organization.status == OrganizationStatus.ACTIVE,
            Organization.deleted_at.is_(None),
            func.lower(User.email) == email.strip().lower(),
            User.is_active.is_(True),
            User.deleted_at.is_(None),
        )
    )
    user = db.scalar(stmt)
    if user is None or not verify_password(password, user.password_hash):
        return None

    user.last_login_at = datetime.now(timezone.utc)
    return user
