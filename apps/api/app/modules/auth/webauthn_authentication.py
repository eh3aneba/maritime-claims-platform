import base64
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import UUID

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.auth.models import AuthSession
from app.modules.auth.webauthn_models import (
    WebAuthnAuthenticationTransaction,
    WebAuthnCredential,
    WebAuthnRelyingPartyProfile,
)
from app.modules.auth.webauthn_profile import get_current_webauthn_rp_profile
from app.modules.auth.webauthn_registration import _as_utc, _validate_session_source
from app.modules.auth.webauthn_registration_finish import (
    WebAuthnVerificationError,
    _decode_base64url,
)
from app.modules.users.models import User

WEBAUTHN_AUTHENTICATION_TTL_MINUTES = 5
WEBAUTHN_AUTHENTICATION_TIMEOUT_MS = 300_000
WEBAUTHN_MFA_METHOD = "webauthn"
_CLIENT_DATA_MAX_BYTES = 16 * 1024
_AUTHENTICATOR_DATA_MAX_BYTES = 4096
_SIGNATURE_MAX_BYTES = 2048


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _challenge_hash(challenge: str) -> str:
    return sha256(challenge.encode("ascii")).hexdigest()


def _validate_profile_snapshot(
    db: Session,
    *,
    transaction: WebAuthnAuthenticationTransaction,
) -> WebAuthnRelyingPartyProfile:
    profile = db.get(WebAuthnRelyingPartyProfile, transaction.profile_id)
    if (
        profile is None
        or profile.organization_id != transaction.organization_id
        or profile.profile_number != transaction.profile_number
        or not hmac.compare_digest(profile.profile_hash, transaction.profile_hash)
    ):
        raise ValueError("WebAuthn authentication profile source does not match")
    return profile


def _active_credential_exists(db: Session, *, user: User) -> bool:
    return (
        db.scalar(
            select(WebAuthnCredential.id)
            .where(
                WebAuthnCredential.organization_id == user.organization_id,
                WebAuthnCredential.user_id == user.id,
                WebAuthnCredential.revoked_at.is_(None),
            )
            .limit(1)
        )
        is not None
    )


def _open_transaction_for_session(
    db: Session,
    *,
    auth_session_id: UUID,
) -> WebAuthnAuthenticationTransaction | None:
    return db.scalar(
        select(WebAuthnAuthenticationTransaction)
        .where(
            WebAuthnAuthenticationTransaction.auth_session_id == auth_session_id,
            WebAuthnAuthenticationTransaction.consumed_at.is_(None),
            WebAuthnAuthenticationTransaction.cancelled_at.is_(None),
        )
        .with_for_update()
    )


def begin_webauthn_authentication(
    db: Session,
    *,
    user: User,
    auth_session: AuthSession,
) -> tuple[WebAuthnAuthenticationTransaction, str, WebAuthnRelyingPartyProfile, UUID | None]:
    _validate_session_source(user=user, auth_session=auth_session)
    if not _active_credential_exists(db, user=user):
        raise ValueError("Active WebAuthn credential required")

    profile = get_current_webauthn_rp_profile(db, organization_id=user.organization_id)
    if profile is None:
        raise ValueError("WebAuthn relying-party profile is not configured")

    superseded_id: UUID | None = None
    existing = _open_transaction_for_session(db, auth_session_id=auth_session.id)
    if existing is not None:
        existing.cancelled_at = _utc_now()
        superseded_id = existing.id
        db.flush()

    challenge = _base64url(secrets.token_bytes(32))
    now = _utc_now()
    transaction = WebAuthnAuthenticationTransaction(
        organization_id=user.organization_id,
        user_id=user.id,
        auth_session_id=auth_session.id,
        profile_id=profile.id,
        profile_number=profile.profile_number,
        profile_hash=profile.profile_hash,
        challenge_hash=_challenge_hash(challenge),
        expires_at=now + timedelta(minutes=WEBAUTHN_AUTHENTICATION_TTL_MINUTES),
    )
    db.add(transaction)
    db.flush()
    return transaction, challenge, profile, superseded_id


def _verify_client_data(
    *,
    encoded: str,
    transaction: WebAuthnAuthenticationTransaction,
    profile: WebAuthnRelyingPartyProfile,
) -> bytes:
    raw = _decode_base64url(
        encoded,
        field="clientDataJSON",
        max_bytes=_CLIENT_DATA_MAX_BYTES,
    )
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WebAuthnVerificationError("WebAuthn clientDataJSON is invalid") from exc
    if not isinstance(payload, dict) or payload.get("type") != "webauthn.get":
        raise WebAuthnVerificationError("WebAuthn clientDataJSON type is invalid")
    challenge = payload.get("challenge")
    origin = payload.get("origin")
    if not isinstance(challenge, str):
        raise WebAuthnVerificationError("WebAuthn client challenge is invalid")
    try:
        challenge.encode("ascii")
    except UnicodeEncodeError as exc:
        raise WebAuthnVerificationError("WebAuthn client challenge is invalid") from exc
    if not hmac.compare_digest(_challenge_hash(challenge), transaction.challenge_hash):
        raise WebAuthnVerificationError("WebAuthn authentication challenge does not match")
    if not isinstance(origin, str) or origin not in profile.allowed_origins:
        raise WebAuthnVerificationError("WebAuthn authentication origin is not allowed")
    if payload.get("crossOrigin") not in (None, False):
        raise WebAuthnVerificationError("Cross-origin WebAuthn authentication is not allowed")
    return raw


def _verify_authenticator_data(
    *,
    encoded: str,
    profile: WebAuthnRelyingPartyProfile,
) -> tuple[bytes, int]:
    auth_data = _decode_base64url(
        encoded,
        field="authenticatorData",
        max_bytes=_AUTHENTICATOR_DATA_MAX_BYTES,
    )
    if len(auth_data) < 37:
        raise WebAuthnVerificationError("WebAuthn authenticator data is too short")
    expected_rp_hash = sha256(profile.rp_id.encode("utf-8")).digest()
    if not hmac.compare_digest(auth_data[:32], expected_rp_hash):
        raise WebAuthnVerificationError("WebAuthn RP ID hash does not match")
    flags = auth_data[32]
    if flags & 0x01 == 0 or flags & 0x04 == 0:
        raise WebAuthnVerificationError("WebAuthn authentication requires UP and UV flags")
    if flags & 0x40 or flags & 0x80:
        raise WebAuthnVerificationError(
            "WebAuthn assertion attested data or extensions are not supported in this tranche"
        )
    if len(auth_data) != 37:
        raise WebAuthnVerificationError("Unexpected WebAuthn authenticator data payload")
    return auth_data, int.from_bytes(auth_data[33:37], "big")


def _verify_signature(
    *,
    credential: WebAuthnCredential,
    signed_data: bytes,
    signature: bytes,
) -> None:
    try:
        public_key = serialization.load_pem_public_key(credential.public_key_pem.encode("ascii"))
    except (ValueError, TypeError) as exc:
        raise WebAuthnVerificationError("Stored WebAuthn public key is invalid") from exc

    try:
        if credential.algorithm == -7 and isinstance(public_key, ec.EllipticCurvePublicKey):
            if not isinstance(public_key.curve, ec.SECP256R1):
                raise WebAuthnVerificationError("Stored WebAuthn ES256 key curve is invalid")
            public_key.verify(signature, signed_data, ec.ECDSA(hashes.SHA256()))
        elif credential.algorithm == -257 and isinstance(public_key, rsa.RSAPublicKey):
            if public_key.key_size < 2048:
                raise WebAuthnVerificationError("Stored WebAuthn RS256 key is too small")
            public_key.verify(signature, signed_data, padding.PKCS1v15(), hashes.SHA256())
        else:
            raise WebAuthnVerificationError("Stored WebAuthn credential algorithm is invalid")
    except InvalidSignature as exc:
        raise WebAuthnVerificationError("WebAuthn assertion signature is invalid") from exc


def _apply_signature_counter(*, credential: WebAuthnCredential, new_count: int) -> None:
    current = int(credential.sign_count)
    if current == 0 and new_count == 0:
        return
    if new_count == 0 or new_count <= current:
        raise WebAuthnVerificationError("WebAuthn signature-counter replay or regression rejected")
    credential.sign_count = new_count


def finish_webauthn_authentication(
    db: Session,
    *,
    transaction_id: UUID,
    user: User,
    auth_session: AuthSession,
    credential_id: str,
    client_data_json: str,
    authenticator_data: str,
    signature: str,
) -> tuple[AuthSession, WebAuthnAuthenticationTransaction, WebAuthnCredential]:
    _validate_session_source(user=user, auth_session=auth_session)
    transaction = db.scalar(
        select(WebAuthnAuthenticationTransaction)
        .where(WebAuthnAuthenticationTransaction.id == transaction_id)
        .with_for_update()
    )
    if transaction is None or (
        transaction.organization_id != user.organization_id
        or transaction.user_id != user.id
        or transaction.auth_session_id != auth_session.id
    ):
        raise ValueError("WebAuthn authentication transaction not found")
    if transaction.cancelled_at is not None:
        raise ValueError("WebAuthn authentication transaction is cancelled")
    if transaction.consumed_at is not None:
        raise ValueError("WebAuthn authentication transaction is already consumed")
    if _as_utc(transaction.expires_at) <= _utc_now():
        raise ValueError("WebAuthn authentication transaction is expired")

    profile = _validate_profile_snapshot(db, transaction=transaction)
    credential_id_bytes = _decode_base64url(
        credential_id,
        field="credentialId",
        max_bytes=1024,
    )
    credential_hash = sha256(credential_id_bytes).hexdigest()
    credential = db.scalar(
        select(WebAuthnCredential)
        .where(WebAuthnCredential.credential_id_hash == credential_hash)
        .with_for_update()
    )
    if credential is None or (
        credential.organization_id != user.organization_id
        or credential.user_id != user.id
        or credential.revoked_at is not None
    ):
        raise ValueError("Active WebAuthn credential not found")

    client_data_raw = _verify_client_data(
        encoded=client_data_json,
        transaction=transaction,
        profile=profile,
    )
    auth_data_raw, new_sign_count = _verify_authenticator_data(
        encoded=authenticator_data,
        profile=profile,
    )
    signature_raw = _decode_base64url(
        signature,
        field="signature",
        max_bytes=_SIGNATURE_MAX_BYTES,
    )
    signed_data = auth_data_raw + sha256(client_data_raw).digest()
    _verify_signature(
        credential=credential,
        signed_data=signed_data,
        signature=signature_raw,
    )
    _apply_signature_counter(credential=credential, new_count=new_sign_count)

    now = _utc_now()
    transaction.credential_id = credential.id
    transaction.consumed_at = now
    auth_session.mfa_verified_at = now
    auth_session.mfa_method = WEBAUTHN_MFA_METHOD
    auth_session.mfa_factor_id = None
    db.flush()
    return auth_session, transaction, credential


def cancel_webauthn_authentication(
    db: Session,
    *,
    transaction_id: UUID,
    user: User,
    auth_session: AuthSession,
) -> WebAuthnAuthenticationTransaction:
    _validate_session_source(user=user, auth_session=auth_session)
    transaction = db.scalar(
        select(WebAuthnAuthenticationTransaction)
        .where(WebAuthnAuthenticationTransaction.id == transaction_id)
        .with_for_update()
    )
    if transaction is None or (
        transaction.organization_id != user.organization_id
        or transaction.user_id != user.id
        or transaction.auth_session_id != auth_session.id
    ):
        raise ValueError("WebAuthn authentication transaction not found")
    _validate_profile_snapshot(db, transaction=transaction)
    if transaction.consumed_at is not None:
        raise ValueError("WebAuthn authentication transaction is already consumed")
    if transaction.cancelled_at is not None:
        raise ValueError("WebAuthn authentication transaction is already cancelled")
    transaction.cancelled_at = _utc_now()
    db.flush()
    return transaction


def session_has_verified_webauthn_mfa(
    db: Session,
    *,
    user: User,
    auth_session: AuthSession,
) -> bool:
    if auth_session.mfa_method != WEBAUTHN_MFA_METHOD or auth_session.mfa_verified_at is None:
        return False
    transaction = db.scalar(
        select(WebAuthnAuthenticationTransaction)
        .where(
            WebAuthnAuthenticationTransaction.organization_id == user.organization_id,
            WebAuthnAuthenticationTransaction.user_id == user.id,
            WebAuthnAuthenticationTransaction.auth_session_id == auth_session.id,
            WebAuthnAuthenticationTransaction.credential_id.is_not(None),
            WebAuthnAuthenticationTransaction.consumed_at.is_not(None),
        )
        .order_by(WebAuthnAuthenticationTransaction.consumed_at.desc())
        .limit(1)
    )
    if transaction is None or transaction.credential_id is None:
        return False
    if _as_utc(transaction.consumed_at) != _as_utc(auth_session.mfa_verified_at):
        return False
    credential = db.get(WebAuthnCredential, transaction.credential_id)
    return bool(
        credential is not None
        and credential.organization_id == user.organization_id
        and credential.user_id == user.id
        and credential.revoked_at is None
    )
