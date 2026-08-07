"""Development bootstrap helper for creating the first organization administrator.

Run from apps/api after the database migration:
    MCRI_BOOTSTRAP_ORG_NAME="Demo Marine Insurer" \
    MCRI_BOOTSTRAP_ORG_SLUG="demo" \
    MCRI_BOOTSTRAP_ADMIN_EMAIL="admin@example.com" \
    MCRI_BOOTSTRAP_ADMIN_PASSWORD="replace-with-strong-password" \
    python -m app.modules.auth.seed
"""

import os

from sqlalchemy import func, select

from app.core.security import hash_password
from app.db.session import create_session
from app.modules.organizations.models import Organization
from app.modules.users.models import User, UserRole


def main() -> None:
    org_name = os.getenv("MCRI_BOOTSTRAP_ORG_NAME")
    org_slug = os.getenv("MCRI_BOOTSTRAP_ORG_SLUG")
    admin_email = os.getenv("MCRI_BOOTSTRAP_ADMIN_EMAIL")
    admin_password = os.getenv("MCRI_BOOTSTRAP_ADMIN_PASSWORD")
    if not all([org_name, org_slug, admin_email, admin_password]):
        raise SystemExit("Bootstrap environment variables are incomplete")
    if len(admin_password) < 12:
        raise SystemExit("Bootstrap admin password must contain at least 12 characters")

    with create_session() as db:
        org = db.scalar(select(Organization).where(func.lower(Organization.slug) == org_slug.lower()))
        if org is None:
            org = Organization(name=org_name, slug=org_slug.lower())
            db.add(org)
            db.flush()

        user = db.scalar(
            select(User).where(User.organization_id == org.id, func.lower(User.email) == admin_email.lower())
        )
        if user is None:
            user = User(
                organization_id=org.id,
                email=admin_email.lower(),
                full_name="Platform Administrator",
                password_hash=hash_password(admin_password),
                role=UserRole.ADMIN,
                is_active=True,
            )
            db.add(user)
        db.commit()
        print(f"Bootstrap complete for organization '{org.slug}' and admin '{admin_email.lower()}'.")


if __name__ == "__main__":
    main()
