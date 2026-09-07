import base64
import hashlib
import hmac
import secrets
import struct
from datetime import datetime, timezone
from urllib.parse import quote, urlencode
from uuid import UUID

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.auth.models import AuthSession, TotpMfaFactor
from app.modules.users.models import User

settings = get_settings()

TOTP_ALGORITHM = "SHA1"
TOTP_DIGITS = 6
TOTP_PERIOD_SECONDS = 30
TOTP_SECRET_BYTES = 20
TOTP_MFA_METHOD = "totp"
_MFA_KEY_DOMAIN = b"mcri-totp-mfa-v1\x00"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _current_time_step(period_seconds: int = TOTP_PERIOD_SECONDS) -> int:
    return int(_utc_now().timestamp()) // period_seconds


def _encryption_key() -> bytes:
    return hashlib.sha256(_MFA_KEY_DOMAIN + settings.secret_key.encode("utf-8")).digest()


def _aad(organization_id: UUID, user_id: UUID) -> bytes:
    return f"mcri-totp-v1:{organization_id}:{user_id}".encode("utf-8")


def _encrypt_secret(secret: str, *, organization_id: UUID, user_id: UUID) -> tuple[str, str]:
    nonce = secrets.token_bytes(12)
    ciphertext = AESGCM(_encryption_key()).encrypt(
        nonce,
        secret.encode("ascii"),
        _aad(organization_id, user_id),
    )
    return (
        base64.urlsafe_b64encode(ciphertext).decode("ascii"),
        base64.urlsafe_b64encode(nonce).decode("ascii"),
    )


def _decrypt_secret(factor: TotpMfaFactor) -> str:
    ciphertext = base64.urlsafe_b64decode(factor.secret_ciphertext.encode("ascii"))
    nonce = base64.urlsafe_b64decode(factor.secret_nonce.encode("ascii"))
    plaintext = AESGCM(_encryption_key()).decrypt(
        nonce,
        ciphertext,
        _aad(factor.organization_id, factor.user_id),
    )
    return plaintext.decode("ascii")


def _secret_fingerprint(secret: str) -> str:
    return hashlib.sha256(secret.encode("ascii")).hexdigest()


def _decode_base32(secret: str) -> bytes:
    padding = "=" * ((8 - len(secret) % 8) % 8)
    return base64.b32decode((secret + padding).encode("ascii"), casefold=True)


def _totp_code(secret: str, time_step: int, digits: int = TOTP_DIGITS) -> str:
    digest = hmac.new(
        _decode_base32(secret),
        struct.pack(">Q", time_step),
        hashlib.sha1,
    ).digest()
    offset = digest[-1] & 0x0F
    binary = (
        ((digest[offset] & 0x7F) << 24)
        | ((digest[offset + 1] & 0xFF) << 16)
        | ((digest[offset + 2] & 0xFF) << 8)
        | (digest[offset + 3] & 0xFF)
    )
    return str(binary % (10**digits)).zfill(digits)


def _matched_time_step(
    secret: str,
    code: str,
    *,
    period_seconds: int = TOTP_PERIOD_SECONDS,
    digits: int = TOTP_DIGITS,
) -> int | None:
    if len(code) != digits or not code.isdigit():
        return None
    current = _current_time_step(period_seconds)
    for candidate in (current, current - 1, current + 1):
        if hmac.compare_digest(_totp_code(secret, candidate, digits), code):
            return candidate
    return None


def get_totp_factor_for_user(
    db: Session,
    *,
    factor_id: UUID,
    organization_id: UUID,
    user_id: UUID,
) -> TotpMfaFactor | None:
    return db.scalar(
        select(TotpMfaFactor).where(
            TotpMfaFactor.id == factor_id,
            TotpMfaFactor.organization_id == organization_id,
            TotpMfaFactor.user_id == user_id,
        )
    )


def get_current_totp_factor(
    db: Session,
    *,
    organization_id: UUID,
    user_id: UUID,
) -> TotpMfaFactor | None:
    return db.scalar(
        select(TotpMfaFactor).where(
            TotpMfaFactor.organization_id == organization_id,
            TotpMfaFactor.user_id == user_id,
            TotpMfaFactor.revoked_at.is_(None),
        )
    )


def start_totp_enrollment(
    db: Session,
    *,
    user: User,
) -> tuple[TotpMfaFactor, str, str]:
    if not user.is_active or user.deleted_at is not None:
        raise ValueError("User is inactive or unavailable")
    if get_current_totp_factor(
        db,
        organization_id=user.organization_id,
        user_id=user.id,
    ) is not None:
        raise ValueError("User already has an unrevoked TOTP factor")

    secret = base64.b32encode(secrets.token_bytes(TOTP_SECRET_BYTES)).decode("ascii").rstrip("=")
    ciphertext, nonce = _encrypt_secret(
        secret,
        organization_id=user.organization_id,
        user_id=user.id,
    )
    issuer = settings.app_name[:160]
    account_label = user.email[:320]
    factor = TotpMfaFactor(
        organization_id=user.organization_id,
        user_id=user.id,
        issuer=issuer,
        account_label=account_label,
        algorithm=TOTP_ALGORITHM,
        digits=TOTP_DIGITS,
        period_seconds=TOTP_PERIOD_SECONDS,
        secret_ciphertext=ciphertext,
        secret_nonce=nonce,
        secret_fingerprint=_secret_fingerprint(secret),
    )
    db.add(factor)
    db.flush()

    label = quote(f"{issuer}:{account_label}", safe="")
    query = urlencode(
        {
            "secret": secret,
            "issuer": issuer,
            "algorithm": TOTP_ALGORITHM,
            "digits": TOTP_DIGITS,
            "period": TOTP_PERIOD_SECONDS,
        }
    )
    otpauth_uri = f"otpauth://totp/{label}?{query}"
    return factor, secret, otpauth_uri


def confirm_totp_enrollment(
    *,
    factor: TotpMfaFactor,
    code: str,
) -> TotpMfaFactor:
    if factor.revoked_at is not None:
        raise ValueError("TOTP factor is revoked")
    if factor.confirmed_at is not None:
        raise ValueError("TOTP factor is already confirmed")

    secret = _decrypt_secret(factor)
    matched_step = _matched_time_step(
        secret,
        code,
        period_seconds=factor.period_seconds,
        digits=factor.digits,
    )
    if matched_step is None:
        raise ValueError("Invalid TOTP code")

    factor.confirmed_at = _utc_now()
    factor.last_accepted_time_step = matched_step
    return factor


def verify_totp_for_session(
    *,
    factor: TotpMfaFactor,
    auth_session: AuthSession,
    code: str,
) -> AuthSession:
    if factor.revoked_at is not None or factor.confirmed_at is None:
        raise ValueError("Active confirmed TOTP factor required")
    if (
        factor.organization_id != auth_session.organization_id
        or factor.user_id != auth_session.user_id
    ):
        raise ValueError("TOTP factor and authentication session do not match")

    secret = _decrypt_secret(factor)
    matched_step = _matched_time_step(
        secret,
        code,
        period_seconds=factor.period_seconds,
        digits=factor.digits,
    )
    if matched_step is None:
        raise ValueError("Invalid TOTP code")
    if (
        factor.last_accepted_time_step is not None
        and matched_step <= factor.last_accepted_time_step
    ):
        raise ValueError("TOTP time-step replay rejected")

    factor.last_accepted_time_step = matched_step
    auth_session.mfa_verified_at = _utc_now()
    auth_session.mfa_method = TOTP_MFA_METHOD
    auth_session.mfa_factor_id = factor.id
    return auth_session


def revoke_totp_factor(
    *,
    factor: TotpMfaFactor,
    revoked_by_id: UUID,
    reason: str = "self_revocation",
) -> bool:
    if factor.revoked_at is not None:
        return False
    factor.revoked_at = _utc_now()
    factor.revoked_by_id = revoked_by_id
    factor.revocation_reason = reason
    return True
