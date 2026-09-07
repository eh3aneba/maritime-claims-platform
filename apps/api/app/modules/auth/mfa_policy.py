from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.auth.mfa_policy_models import MfaPolicy
from app.modules.users.models import UserRole

_ROLE_ORDER = [
    UserRole.ADMIN.value,
    UserRole.CLAIMS_MANAGER.value,
    UserRole.CLAIMS_HANDLER.value,
]
_ALLOWED_ROLES = set(_ROLE_ORDER)


def get_mfa_policy(
    db: Session,
    *,
    organization_id: UUID,
) -> MfaPolicy | None:
    return db.scalar(
        select(MfaPolicy).where(MfaPolicy.organization_id == organization_id)
    )


def normalize_required_roles(required_roles: list[str]) -> list[str]:
    normalized = {role.strip().lower() for role in required_roles}
    if any(role not in _ALLOWED_ROLES for role in normalized):
        raise ValueError("Unsupported MFA policy role")
    return [role for role in _ROLE_ORDER if role in normalized]


def upsert_mfa_policy(
    db: Session,
    *,
    organization_id: UUID,
    is_enabled: bool,
    required_roles: list[str],
    updated_by_id: UUID,
) -> tuple[MfaPolicy, dict[str, object]]:
    normalized_roles = normalize_required_roles(required_roles)
    if is_enabled and not normalized_roles:
        raise ValueError("At least one required role is needed when MFA policy is enabled")

    policy = get_mfa_policy(db, organization_id=organization_id)
    old_values: dict[str, object]
    if policy is None:
        old_values = {"is_enabled": False, "required_roles": []}
        policy = MfaPolicy(
            organization_id=organization_id,
            is_enabled=is_enabled,
            required_roles=normalized_roles,
            updated_by_id=updated_by_id,
        )
        db.add(policy)
        db.flush()
        return policy, old_values

    old_values = {
        "is_enabled": policy.is_enabled,
        "required_roles": list(policy.required_roles),
    }
    policy.is_enabled = is_enabled
    policy.required_roles = normalized_roles
    policy.updated_by_id = updated_by_id
    return policy, old_values


def mfa_required_for_role(
    policy: MfaPolicy | None,
    *,
    role: UserRole,
) -> bool:
    if policy is None or not policy.is_enabled:
        return False
    return role.value in set(policy.required_roles)
