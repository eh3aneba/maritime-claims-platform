import hashlib
import hmac
import secrets
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.auth.mfa_recovery_models import MfaRecoveryCode
from app.modules.auth.models import AuthSession, TotpMfaFactor
from app.modules.users.models import User

settings = get_settings()

RECOVERY_CODE_COUNT = 10
RECOVERY_CODE_HEX_LENGTH = 32
RECOVERY_MFA_METHOD = "recovery_code"
_ALLOWED_SESSION_MFA_METHODS = {"totp", RECOVERY_MFA_METHOD}
_RECOVERY_KEY_DOMAIN = b"mcri-mfa-recovery-code-v1\x00"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _recovery_hash_key() -> bytes:
    return hashlib.sha256(
        _RECOVERY_KEY_DOMAIN + settings.secret_key.encode("utf-8")
    ).digest()


def _normalize_recovery_code(code: str) -> str | None:
    normalized = "".join(character for character in code.upper() if character != "-").strip()
    if len(normalized) != RECOVERY_CODE_HEX_LENGTH:
        return None
    if any(character not in "0123456789ABCDEF" for character in normalized):
        return None
    return normalized


def _recovery_code_digest(code: str) -> str | None:
    normalized = _normalize_recovery_code(code)
    if normalized is None:
        return None
    return hmac.new(
        _recovery_hash_key(),
        normalized.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()


def _new_recovery_code() -> str:
    raw = secrets.token_hex(16).upper()
    return "-".join(raw[index : index + 8] for index in range(0, len(raw), 8))


def session_has_verified_mfa_for_factor(
    *,
    auth_session: AuthSession,
    factor: TotpMfaFactor,
) -> bool:
    return (
        factor.revoked_at is None
        and factor.confirmed_at is not None
        and auth_session.organization_id == factor.organization_id
        and auth_session.user_id == factor.user_id
        and auth_session.mfa_verified_at is not None
        and auth_session.mfa_method in _ALLOWED_SESSION_MFA_METHODS
        and auth_session.mfa_factor_id == factor.id
    )


def regenerate_recovery_codes(
    db: Session,
    *,
    user: User,
    factor: TotpMfaFactor,
    auth_session: AuthSession,
) -> tuple[UUID, list[str], int]:
    if not user.is_active or user.deleted_at is not None:
        raise ValueError("User is inactive or unavailable")
    if (
        factor.organization_id != user.organization_id
        or factor.user_id != user.id
        or factor.revoked_at is not None
        or factor.confirmed_at is None
    ):
        raise ValueError("Active confirmed TOTP factor required")
    if not session_has_verified_mfa_for_factor(
        auth_session=auth_session,
        factor=factor,
    ):
        raise PermissionError("MFA verification is required for the current session")

    now = _utc_now()
    existing_codes = db.scalars(
        select(MfaRecoveryCode)
        .where(
            MfaRecoveryCode.organization_id == user.organization_id,
            MfaRecoveryCode.user_id == user.id,
            MfaRecoveryCode.factor_id == factor.id,
            MfaRecoveryCode.consumed_at.is_(None),
            MfaRecoveryCode.invalidated_at.is_(None),
        )
        .with_for_update()
    ).all()
    for existing in existing_codes:
        existing.invalidated_at = now
        existing.invalidated_by_session_id = auth_session.id

    batch_id = uuid4()
    plaintext_codes: list[str] = []
    for position in range(1, RECOVERY_CODE_COUNT + 1):
        plaintext = _new_recovery_code()
        digest = _recovery_code_digest(plaintext)
        if digest is None:
            raise RuntimeError("Generated recovery code could not be normalized")
        db.add(
            MfaRecoveryCode(
                organization_id=user.organization_id,
                user_id=user.id,
                factor_id=factor.id,
                batch_id=batch_id,
                position=position,
                code_digest=digest,
            )
        )
        plaintext_codes.append(plaintext)

    db.flush()
    return batch_id, plaintext_codes, len(existing_codes)


def verify_recovery_code_for_session(
    db: Session,
    *,
    factor: TotpMfaFactor,
    auth_session: AuthSession,
    code: str,
) -> tuple[AuthSession, MfaRecoveryCode]:
    if factor.revoked_at is not None or factor.confirmed_at is None:
        raise ValueError("Active confirmed TOTP factor required")
    if (
        factor.organization_id != auth_session.organization_id
        or factor.user_id != auth_session.user_id
    ):
        raise ValueError("MFA factor and authentication session do not match")

    digest = _recovery_code_digest(code)
    if digest is None:
        raise ValueError("Invalid recovery code")

    recovery_code = db.scalar(
        select(MfaRecoveryCode)
        .where(
            MfaRecoveryCode.organization_id == auth_session.organization_id,
            MfaRecoveryCode.user_id == auth_session.user_id,
            MfaRecoveryCode.factor_id == factor.id,
            MfaRecoveryCode.code_digest == digest,
            MfaRecoveryCode.consumed_at.is_(None),
            MfaRecoveryCode.invalidated_at.is_(None),
        )
        .with_for_update()
    )
    if recovery_code is None:
        raise ValueError("Invalid recovery code")

    now = _utc_now()
    recovery_code.consumed_at = now
    recovery_code.consumed_auth_session_id = auth_session.id
    auth_session.mfa_verified_at = now
    auth_session.mfa_method = RECOVERY_MFA_METHOD
    auth_session.mfa_factor_id = factor.id
    db.flush()
    return auth_session, recovery_code
