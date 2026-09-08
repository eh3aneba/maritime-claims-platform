import hmac
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID

import httpx
import jwt
from jwt import InvalidTokenError, PyJWK
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.service import write_audit_log
from app.modules.auth.models import (
    AuthSession,
    EnterpriseIdentityProvider,
    ExternalIdentityBinding,
    OidcAuthorizationTransaction,
    OidcRuntimeProfile,
    OidcTrustProfile,
)
from app.modules.auth.oidc_assurance import (
    OIDC_EXTERNAL_MFA_METHOD,
    evaluate_pinned_oidc_mfa_assurance,
    record_oidc_mfa_assurance_verification,
)
from app.modules.auth.oidc_transaction import (
    OidcAuthorizationStartMaterial,
    consume_oidc_authorization_transaction,
    validate_oidc_authorization_transaction_proof,
)
from app.modules.auth.service import _subject_fingerprint, create_auth_session
from app.modules.organizations.models import Organization, OrganizationStatus
from app.modules.users.models import User

OIDC_AUTH_METHOD = "oidc"
OIDC_IDENTITY_SOURCE = "oidc"
OIDC_HTTP_TIMEOUT_SECONDS = 5.0
OIDC_MAX_RESPONSE_BYTES = 1_048_576
OIDC_CLOCK_LEEWAY_SECONDS = 60
OIDC_MAX_JWKS_KEYS = 100
_RESERVED_AUTHORIZATION_PARAMS = {
    "response_type",
    "client_id",
    "redirect_uri",
    "scope",
    "state",
    "nonce",
    "code_challenge",
    "code_challenge_method",
}


class OidcCallbackError(ValueError):
    pass


class OidcProviderUnavailable(OidcCallbackError):
    pass


class OidcRuntimeNotOperational(OidcCallbackError):
    pass


@dataclass(frozen=True)
class VerifiedOidcIdentity:
    subject: str
    claims: dict[str, Any]


@dataclass(frozen=True)
class OidcCallbackResult:
    user: User
    auth_session: AuthSession
    provider: EnterpriseIdentityProvider
    binding: ExternalIdentityBinding
    transaction: OidcAuthorizationTransaction


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def build_oidc_authorization_url(
    *,
    trust_profile: OidcTrustProfile,
    runtime_profile: OidcRuntimeProfile,
    material: OidcAuthorizationStartMaterial,
) -> str:
    """Construct an authorization request from the exact pinned runtime source."""

    parts = urlsplit(runtime_profile.authorization_endpoint)
    existing_query = parse_qsl(parts.query, keep_blank_values=True)
    if any(key in _RESERVED_AUTHORIZATION_PARAMS for key, _ in existing_query):
        raise OidcRuntimeNotOperational(
            "OIDC authorization endpoint contains reserved authorization parameters"
        )

    query = existing_query + [
        ("response_type", "code"),
        ("client_id", trust_profile.audience),
        ("redirect_uri", runtime_profile.redirect_uri),
        ("scope", " ".join(runtime_profile.scopes)),
        ("state", material.state),
        ("nonce", material.nonce),
        ("code_challenge", material.code_challenge),
        ("code_challenge_method", "S256"),
    ]
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )


def _bounded_json_response(response: httpx.Response) -> dict[str, Any]:
    if response.status_code < 200 or response.status_code >= 300:
        raise OidcProviderUnavailable("OIDC provider returned an unsuccessful response")
    content = response.content
    if len(content) > OIDC_MAX_RESPONSE_BYTES:
        raise OidcProviderUnavailable("OIDC provider response exceeded the size limit")
    try:
        payload = response.json()
    except ValueError as exc:
        raise OidcProviderUnavailable("OIDC provider returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise OidcProviderUnavailable("OIDC provider returned an invalid JSON object")
    return payload


def _post_token_request(
    *,
    token_endpoint: str,
    data: dict[str, str],
) -> dict[str, Any]:
    try:
        with httpx.Client(
            follow_redirects=False,
            timeout=OIDC_HTTP_TIMEOUT_SECONDS,
        ) as client:
            response = client.post(
                token_endpoint,
                data=data,
                headers={"Accept": "application/json"},
            )
    except httpx.HTTPError as exc:
        raise OidcProviderUnavailable("OIDC token endpoint is unavailable") from exc
    return _bounded_json_response(response)


def _get_jwks(*, jwks_uri: str) -> dict[str, Any]:
    try:
        with httpx.Client(
            follow_redirects=False,
            timeout=OIDC_HTTP_TIMEOUT_SECONDS,
        ) as client:
            response = client.get(jwks_uri, headers={"Accept": "application/json"})
    except httpx.HTTPError as exc:
        raise OidcProviderUnavailable("OIDC JWKS endpoint is unavailable") from exc
    return _bounded_json_response(response)


def _exchange_authorization_code(
    *,
    runtime_profile: OidcRuntimeProfile,
    trust_profile: OidcTrustProfile,
    authorization_code: str,
    code_verifier: str,
) -> str:
    if runtime_profile.client_auth_method != "none":
        raise OidcRuntimeNotOperational(
            "OIDC client authentication requires separately governed secret custody"
        )
    code = authorization_code.strip()
    if not code or len(code) > 4096:
        raise OidcCallbackError("OIDC authorization code is invalid")

    payload = _post_token_request(
        token_endpoint=runtime_profile.token_endpoint,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": runtime_profile.redirect_uri,
            "client_id": trust_profile.audience,
            "code_verifier": code_verifier,
        },
    )
    if payload.get("refresh_token"):
        raise OidcCallbackError("OIDC refresh-token authority is not enabled")
    id_token = payload.get("id_token")
    if not isinstance(id_token, str) or not id_token.strip() or len(id_token) > 32_768:
        raise OidcCallbackError("OIDC token response did not contain a bounded ID token")
    return id_token.strip()


def _select_signing_key(
    *,
    id_token: str,
    trust_profile: OidcTrustProfile,
    jwks: dict[str, Any],
) -> tuple[str, Any]:
    try:
        header = jwt.get_unverified_header(id_token)
    except InvalidTokenError as exc:
        raise OidcCallbackError("OIDC ID token header is invalid") from exc

    algorithm = header.get("alg")
    key_id = header.get("kid")
    if not isinstance(algorithm, str) or algorithm not in trust_profile.allowed_algorithms:
        raise OidcCallbackError("OIDC ID token algorithm is not allowed")
    if algorithm not in {"RS256", "ES256"}:
        raise OidcCallbackError("OIDC ID token algorithm is unsupported")
    if not isinstance(key_id, str) or not key_id or len(key_id) > 256:
        raise OidcCallbackError("OIDC ID token key identifier is invalid")

    keys = jwks.get("keys")
    if not isinstance(keys, list) or not keys or len(keys) > OIDC_MAX_JWKS_KEYS:
        raise OidcCallbackError("OIDC JWKS key set is invalid")

    expected_kty = "RSA" if algorithm == "RS256" else "EC"
    matches = [
        item
        for item in keys
        if isinstance(item, dict)
        and item.get("kid") == key_id
        and item.get("kty") == expected_kty
        and item.get("alg") in {None, algorithm}
        and item.get("use") in {None, "sig"}
    ]
    if len(matches) != 1:
        raise OidcCallbackError("OIDC signing key is missing or ambiguous")

    try:
        key = PyJWK.from_dict(matches[0], algorithm=algorithm).key
    except Exception as exc:
        raise OidcCallbackError("OIDC signing key is invalid") from exc
    return algorithm, key


def _verify_id_token(
    *,
    id_token: str,
    nonce: str,
    trust_profile: OidcTrustProfile,
    jwks: dict[str, Any],
) -> VerifiedOidcIdentity:
    algorithm, key = _select_signing_key(
        id_token=id_token,
        trust_profile=trust_profile,
        jwks=jwks,
    )
    try:
        claims = jwt.decode(
            id_token,
            key=key,
            algorithms=[algorithm],
            audience=trust_profile.audience,
            issuer=trust_profile.issuer_identifier,
            leeway=OIDC_CLOCK_LEEWAY_SECONDS,
            options={
                "require": ["iss", "aud", "sub", "nonce", "exp", "iat"],
                "verify_signature": True,
                "verify_exp": True,
                "verify_nbf": True,
                "verify_iat": True,
                "verify_aud": True,
                "verify_iss": True,
            },
        )
    except InvalidTokenError as exc:
        raise OidcCallbackError("OIDC ID token verification failed") from exc

    token_nonce = claims.get("nonce")
    if not isinstance(token_nonce, str) or not hmac.compare_digest(token_nonce, nonce):
        raise OidcCallbackError("OIDC ID token nonce does not match")

    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject.strip() or len(subject) > 1024:
        raise OidcCallbackError("OIDC ID token subject is invalid")

    audience = claims.get("aud")
    authorized_party = claims.get("azp")
    if isinstance(audience, list) and len(audience) > 1:
        if authorized_party != trust_profile.audience:
            raise OidcCallbackError("OIDC ID token authorized party does not match")
    elif authorized_party is not None and authorized_party != trust_profile.audience:
        raise OidcCallbackError("OIDC ID token authorized party does not match")

    return VerifiedOidcIdentity(subject=subject.strip(), claims=dict(claims))


def _resolve_bound_user(
    db: Session,
    *,
    organization_id: UUID,
    provider: EnterpriseIdentityProvider,
    external_subject: str,
) -> tuple[ExternalIdentityBinding, User]:
    fingerprint = _subject_fingerprint(provider.id, external_subject)
    binding = db.scalar(
        select(ExternalIdentityBinding).where(
            ExternalIdentityBinding.organization_id == organization_id,
            ExternalIdentityBinding.provider_id == provider.id,
            ExternalIdentityBinding.subject_fingerprint == fingerprint,
            ExternalIdentityBinding.revoked_at.is_(None),
        )
    )
    if binding is None:
        raise OidcCallbackError("OIDC external identity is not bound")

    organization = db.scalar(
        select(Organization).where(
            Organization.id == organization_id,
            Organization.status == OrganizationStatus.ACTIVE,
            Organization.deleted_at.is_(None),
        )
    )
    if organization is None:
        raise OidcCallbackError("OIDC application tenant is unavailable")

    user = db.scalar(
        select(User).where(
            User.id == binding.user_id,
            User.organization_id == organization_id,
            User.is_active.is_(True),
            User.deleted_at.is_(None),
        )
    )
    if user is None:
        raise OidcCallbackError("OIDC bound application user is unavailable")
    return binding, user


def complete_oidc_callback(
    db: Session,
    *,
    transaction_id: UUID,
    state: str,
    nonce: str,
    code_verifier: str,
    authorization_code: str,
) -> OidcCallbackResult:
    transaction, source = validate_oidc_authorization_transaction_proof(
        db,
        transaction_id=transaction_id,
        state=state,
        nonce=nonce,
        code_verifier=code_verifier,
    )

    runtime_profile = source.runtime_profile
    trust_profile = source.trust_profile
    provider = source.provider
    if runtime_profile.client_auth_method != "none":
        raise OidcRuntimeNotOperational(
            "OIDC client authentication requires separately governed secret custody"
        )

    id_token = _exchange_authorization_code(
        runtime_profile=runtime_profile,
        trust_profile=trust_profile,
        authorization_code=authorization_code,
        code_verifier=code_verifier,
    )
    jwks = _get_jwks(jwks_uri=trust_profile.jwks_uri)
    identity = _verify_id_token(
        id_token=id_token,
        nonce=nonce,
        trust_profile=trust_profile,
        jwks=jwks,
    )
    binding, user = _resolve_bound_user(
        db,
        organization_id=transaction.organization_id,
        provider=provider,
        external_subject=identity.subject,
    )
    assurance_binding, assurance_result = evaluate_pinned_oidc_mfa_assurance(
        db,
        transaction=transaction,
        claims=identity.claims,
    )

    consumed = consume_oidc_authorization_transaction(
        db,
        transaction_id=transaction.id,
        state=state,
        nonce=nonce,
        code_verifier=code_verifier,
    )
    auth_session = create_auth_session(
        db,
        user=user,
        identity_source=OIDC_IDENTITY_SOURCE,
        auth_method=OIDC_AUTH_METHOD,
    )
    auth_session.external_identity_provider_id = provider.id
    auth_session.external_identity_binding_id = binding.id
    auth_session.oidc_authorization_transaction_id = consumed.id

    assurance_verified = False
    assurance_profile_id = None
    assurance_profile_number = None
    assurance_profile_hash = None
    evidence_type = None
    evidence_hash = None
    if assurance_result.verified:
        if assurance_binding is None:
            raise OidcCallbackError("OIDC MFA assurance source is unavailable")
        verified_at = record_oidc_mfa_assurance_verification(
            db,
            binding=assurance_binding,
            result=assurance_result,
        )
        auth_session.mfa_verified_at = verified_at
        auth_session.mfa_method = OIDC_EXTERNAL_MFA_METHOD
        auth_session.mfa_factor_id = None
        assurance_verified = True
        assurance_profile_id = assurance_binding.assurance_profile_id
        assurance_profile_number = assurance_binding.assurance_profile_number
        assurance_profile_hash = assurance_binding.assurance_profile_hash
        evidence_type = assurance_binding.evidence_type
        evidence_hash = assurance_binding.evidence_hash

    user.last_login_at = _utc_now()
    db.flush()

    write_audit_log(
        db,
        organization_id=user.organization_id,
        user_id=user.id,
        action="OIDC_LOGIN_SUCCESS",
        entity_type="auth_session",
        entity_id=auth_session.id,
        new_values={
            "identity_source": auth_session.identity_source,
            "auth_method": auth_session.auth_method,
            "provider_id": str(provider.id),
            "binding_id": str(binding.id),
            "oidc_authorization_transaction_id": str(consumed.id),
            "trust_profile_id": str(consumed.trust_profile_id),
            "trust_profile_number": consumed.trust_profile_number,
            "trust_profile_hash": consumed.trust_profile_hash,
            "runtime_profile_id": str(consumed.runtime_profile_id),
            "runtime_profile_number": consumed.runtime_profile_number,
            "runtime_profile_hash": consumed.runtime_profile_hash,
            "mfa_assurance_verified": assurance_verified,
            "mfa_method": auth_session.mfa_method,
            "mfa_assurance_profile_id": (
                None if assurance_profile_id is None else str(assurance_profile_id)
            ),
            "mfa_assurance_profile_number": assurance_profile_number,
            "mfa_assurance_profile_hash": assurance_profile_hash,
            "mfa_evidence_type": evidence_type,
            "mfa_evidence_hash": evidence_hash,
        },
    )
    db.flush()
    return OidcCallbackResult(
        user=user,
        auth_session=auth_session,
        provider=provider,
        binding=binding,
        transaction=consumed,
    )
