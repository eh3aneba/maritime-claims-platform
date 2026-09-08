import base64
import hmac
import json
import re
from dataclasses import dataclass
from hashlib import sha256
from typing import Any
from uuid import UUID

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.auth.models import AuthSession
from app.modules.auth.webauthn_models import (
    WebAuthnCredential,
    WebAuthnRegistrationTransaction,
    WebAuthnRelyingPartyProfile,
)
from app.modules.auth.webauthn_registration import (
    _as_utc,
    _utc_now,
    _validate_profile_snapshot,
    _validate_session_source,
)
from app.modules.users.models import User

_CLIENT_DATA_MAX_BYTES = 16 * 1024
_ATTESTATION_OBJECT_MAX_BYTES = 64 * 1024
_BASE64URL_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class WebAuthnVerificationError(ValueError):
    """Registration material failed bounded WebAuthn verification."""


@dataclass(frozen=True)
class VerifiedCredentialMaterial:
    credential_id_hash: str
    public_key_pem: str
    algorithm: int
    sign_count: int
    aaguid: str
    attestation_format: str


class _CborDecoder:
    """Small definite-length CBOR decoder for bounded WebAuthn registration data."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    def _read(self, length: int) -> bytes:
        if length < 0 or self.pos + length > len(self.data):
            raise WebAuthnVerificationError("WebAuthn CBOR payload is truncated")
        value = self.data[self.pos : self.pos + length]
        self.pos += length
        return value

    def _length(self, additional: int) -> int:
        if additional < 24:
            return additional
        if additional == 24:
            return int.from_bytes(self._read(1), "big")
        if additional == 25:
            return int.from_bytes(self._read(2), "big")
        if additional == 26:
            return int.from_bytes(self._read(4), "big")
        if additional == 27:
            return int.from_bytes(self._read(8), "big")
        raise WebAuthnVerificationError("Indefinite or reserved CBOR lengths are not supported")

    def decode(self, *, depth: int = 0) -> Any:
        if depth > 8:
            raise WebAuthnVerificationError("WebAuthn CBOR nesting is too deep")
        initial = self._read(1)[0]
        major = initial >> 5
        additional = initial & 0x1F
        if major in (0, 1):
            value = self._length(additional)
            return value if major == 0 else -1 - value
        if major == 2:
            length = self._length(additional)
            if length > _ATTESTATION_OBJECT_MAX_BYTES:
                raise WebAuthnVerificationError("WebAuthn CBOR byte string is too large")
            return self._read(length)
        if major == 3:
            length = self._length(additional)
            if length > _ATTESTATION_OBJECT_MAX_BYTES:
                raise WebAuthnVerificationError("WebAuthn CBOR text string is too large")
            try:
                return self._read(length).decode("utf-8")
            except UnicodeDecodeError as exc:
                raise WebAuthnVerificationError("WebAuthn CBOR text is not UTF-8") from exc
        if major == 4:
            length = self._length(additional)
            if length > 32:
                raise WebAuthnVerificationError("WebAuthn CBOR array is too large")
            return [self.decode(depth=depth + 1) for _ in range(length)]
        if major == 5:
            length = self._length(additional)
            if length > 32:
                raise WebAuthnVerificationError("WebAuthn CBOR map is too large")
            result: dict[Any, Any] = {}
            for _ in range(length):
                key = self.decode(depth=depth + 1)
                if not isinstance(key, (int, str)) or key in result:
                    raise WebAuthnVerificationError("WebAuthn CBOR map key is invalid or duplicated")
                result[key] = self.decode(depth=depth + 1)
            return result
        if major == 7:
            if additional == 20:
                return False
            if additional == 21:
                return True
            if additional == 22:
                return None
        raise WebAuthnVerificationError("Unsupported WebAuthn CBOR value")


def _decode_base64url(value: str, *, field: str, max_bytes: int) -> bytes:
    if not value or not _BASE64URL_RE.fullmatch(value):
        raise WebAuthnVerificationError(f"{field} is not valid base64url")
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except Exception as exc:  # pragma: no cover - defensive decoder boundary
        raise WebAuthnVerificationError(f"{field} is not valid base64url") from exc
    if not decoded or len(decoded) > max_bytes:
        raise WebAuthnVerificationError(f"{field} has an invalid size")
    return decoded


def _decode_attestation_object(encoded: str) -> dict[str, Any]:
    raw = _decode_base64url(
        encoded,
        field="attestationObject",
        max_bytes=_ATTESTATION_OBJECT_MAX_BYTES,
    )
    decoder = _CborDecoder(raw)
    decoded = decoder.decode()
    if decoder.pos != len(raw) or not isinstance(decoded, dict):
        raise WebAuthnVerificationError("WebAuthn attestationObject is not a canonical bounded map")
    return decoded


def _verify_client_data(
    *,
    encoded: str,
    transaction: WebAuthnRegistrationTransaction,
    profile: WebAuthnRelyingPartyProfile,
) -> None:
    raw = _decode_base64url(
        encoded,
        field="clientDataJSON",
        max_bytes=_CLIENT_DATA_MAX_BYTES,
    )
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WebAuthnVerificationError("WebAuthn clientDataJSON is invalid") from exc
    if not isinstance(payload, dict) or payload.get("type") != "webauthn.create":
        raise WebAuthnVerificationError("WebAuthn clientDataJSON type is invalid")
    challenge = payload.get("challenge")
    origin = payload.get("origin")
    if not isinstance(challenge, str) or not _BASE64URL_RE.fullmatch(challenge):
        raise WebAuthnVerificationError("WebAuthn client challenge is invalid")
    challenge_hash = sha256(challenge.encode("ascii")).hexdigest()
    if not hmac.compare_digest(challenge_hash, transaction.challenge_hash):
        raise WebAuthnVerificationError("WebAuthn registration challenge does not match")
    if not isinstance(origin, str) or origin not in profile.allowed_origins:
        raise WebAuthnVerificationError("WebAuthn registration origin is not allowed")
    if payload.get("crossOrigin") not in (None, False):
        raise WebAuthnVerificationError("Cross-origin WebAuthn registration is not allowed")


def _credential_public_key(cose: dict[Any, Any]) -> tuple[int, str]:
    kty = cose.get(1)
    alg = cose.get(3)
    if kty == 2 and alg == -7:
        if cose.get(-1) != 1:
            raise WebAuthnVerificationError("WebAuthn ES256 curve is not P-256")
        x = cose.get(-2)
        y = cose.get(-3)
        if not isinstance(x, bytes) or not isinstance(y, bytes) or len(x) != 32 or len(y) != 32:
            raise WebAuthnVerificationError("WebAuthn ES256 public key coordinates are invalid")
        try:
            public_key = ec.EllipticCurvePublicNumbers(
                int.from_bytes(x, "big"),
                int.from_bytes(y, "big"),
                ec.SECP256R1(),
            ).public_key()
        except ValueError as exc:
            raise WebAuthnVerificationError("WebAuthn ES256 public key is not on P-256") from exc
    elif kty == 3 and alg == -257:
        modulus = cose.get(-1)
        exponent = cose.get(-2)
        if not isinstance(modulus, bytes) or not isinstance(exponent, bytes):
            raise WebAuthnVerificationError("WebAuthn RS256 public key is invalid")
        n = int.from_bytes(modulus, "big")
        e = int.from_bytes(exponent, "big")
        if n.bit_length() < 2048 or e != 65537:
            raise WebAuthnVerificationError("WebAuthn RS256 public key parameters are not allowed")
        try:
            public_key = rsa.RSAPublicNumbers(e=e, n=n).public_key()
        except ValueError as exc:
            raise WebAuthnVerificationError("WebAuthn RS256 public key is invalid") from exc
    else:
        raise WebAuthnVerificationError("WebAuthn credential algorithm is not supported")

    pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    return int(alg), pem


def _verify_authenticator_data(
    *,
    auth_data: bytes,
    credential_id: bytes,
    profile: WebAuthnRelyingPartyProfile,
) -> VerifiedCredentialMaterial:
    if len(auth_data) < 55:
        raise WebAuthnVerificationError("WebAuthn authenticator data is too short")
    expected_rp_hash = sha256(profile.rp_id.encode("utf-8")).digest()
    if not hmac.compare_digest(auth_data[:32], expected_rp_hash):
        raise WebAuthnVerificationError("WebAuthn RP ID hash does not match")
    flags = auth_data[32]
    if flags & 0x01 == 0 or flags & 0x04 == 0 or flags & 0x40 == 0:
        raise WebAuthnVerificationError("WebAuthn registration requires UP, UV and AT flags")
    if flags & 0x80:
        raise WebAuthnVerificationError("WebAuthn registration extensions are not supported in this tranche")
    sign_count = int.from_bytes(auth_data[33:37], "big")
    aaguid = auth_data[37:53].hex()
    credential_length = int.from_bytes(auth_data[53:55], "big")
    if credential_length < 16 or credential_length > 1024:
        raise WebAuthnVerificationError("WebAuthn credential ID length is invalid")
    credential_end = 55 + credential_length
    if credential_end >= len(auth_data):
        raise WebAuthnVerificationError("WebAuthn attested credential data is truncated")
    attested_credential_id = auth_data[55:credential_end]
    if not hmac.compare_digest(attested_credential_id, credential_id):
        raise WebAuthnVerificationError("WebAuthn credential ID does not match authenticator data")

    cose_decoder = _CborDecoder(auth_data[credential_end:])
    cose = cose_decoder.decode()
    if cose_decoder.pos != len(auth_data) - credential_end or not isinstance(cose, dict):
        raise WebAuthnVerificationError("WebAuthn credential public key encoding is invalid")
    algorithm, public_key_pem = _credential_public_key(cose)
    return VerifiedCredentialMaterial(
        credential_id_hash=sha256(credential_id).hexdigest(),
        public_key_pem=public_key_pem,
        algorithm=algorithm,
        sign_count=sign_count,
        aaguid=aaguid,
        attestation_format="none",
    )


def _verify_attestation_object(
    *,
    encoded: str,
    credential_id: bytes,
    profile: WebAuthnRelyingPartyProfile,
) -> VerifiedCredentialMaterial:
    payload = _decode_attestation_object(encoded)
    if payload.get("fmt") != "none" or payload.get("attStmt") != {}:
        raise WebAuthnVerificationError("Only WebAuthn none attestation is supported")
    auth_data = payload.get("authData")
    if not isinstance(auth_data, bytes):
        raise WebAuthnVerificationError("WebAuthn authenticator data is missing")
    return _verify_authenticator_data(
        auth_data=auth_data,
        credential_id=credential_id,
        profile=profile,
    )


def finish_webauthn_registration(
    db: Session,
    *,
    transaction_id: UUID,
    user: User,
    auth_session: AuthSession,
    credential_id: str,
    client_data_json: str,
    attestation_object: str,
) -> WebAuthnCredential:
    _validate_session_source(user=user, auth_session=auth_session)
    transaction = db.scalar(
        select(WebAuthnRegistrationTransaction)
        .where(WebAuthnRegistrationTransaction.id == transaction_id)
        .with_for_update()
    )
    if transaction is None or (
        transaction.organization_id != user.organization_id
        or transaction.user_id != user.id
        or transaction.auth_session_id != auth_session.id
    ):
        raise ValueError("WebAuthn registration transaction not found")
    if transaction.cancelled_at is not None:
        raise ValueError("WebAuthn registration transaction is cancelled")
    if transaction.consumed_at is not None:
        raise ValueError("WebAuthn registration transaction is already consumed")
    if _as_utc(transaction.expires_at) <= _utc_now():
        raise ValueError("WebAuthn registration transaction is expired")

    profile = _validate_profile_snapshot(db, transaction=transaction)
    credential_id_bytes = _decode_base64url(
        credential_id,
        field="credentialId",
        max_bytes=1024,
    )
    _verify_client_data(
        encoded=client_data_json,
        transaction=transaction,
        profile=profile,
    )
    material = _verify_attestation_object(
        encoded=attestation_object,
        credential_id=credential_id_bytes,
        profile=profile,
    )

    existing = db.scalar(
        select(WebAuthnCredential)
        .where(WebAuthnCredential.credential_id_hash == material.credential_id_hash)
        .with_for_update()
    )
    if existing is not None:
        raise ValueError("WebAuthn credential is already registered")

    credential = WebAuthnCredential(
        organization_id=user.organization_id,
        user_id=user.id,
        profile_id=profile.id,
        profile_number=transaction.profile_number,
        profile_hash=transaction.profile_hash,
        registration_transaction_id=transaction.id,
        credential_id_hash=material.credential_id_hash,
        public_key_pem=material.public_key_pem,
        algorithm=material.algorithm,
        sign_count=material.sign_count,
        aaguid=material.aaguid,
        attestation_format=material.attestation_format,
    )
    db.add(credential)
    transaction.consumed_at = _utc_now()
    db.flush()
    return credential


def list_current_webauthn_credentials(
    db: Session,
    *,
    user: User,
) -> list[WebAuthnCredential]:
    return list(
        db.scalars(
            select(WebAuthnCredential)
            .where(
                WebAuthnCredential.organization_id == user.organization_id,
                WebAuthnCredential.user_id == user.id,
            )
            .order_by(WebAuthnCredential.created_at.desc())
        )
    )


def revoke_webauthn_credential(
    db: Session,
    *,
    credential_id: UUID,
    user: User,
    auth_session: AuthSession,
) -> WebAuthnCredential:
    _validate_session_source(user=user, auth_session=auth_session)
    credential = db.scalar(
        select(WebAuthnCredential)
        .where(WebAuthnCredential.id == credential_id)
        .with_for_update()
    )
    if credential is None or (
        credential.organization_id != user.organization_id or credential.user_id != user.id
    ):
        raise ValueError("WebAuthn credential not found")
    if credential.revoked_at is not None:
        raise ValueError("WebAuthn credential is already revoked")
    credential.revoked_at = _utc_now()
    db.flush()
    return credential
