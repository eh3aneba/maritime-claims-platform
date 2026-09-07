import base64
import copy
import hmac
import zlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from lxml import etree
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.service import write_audit_log
from app.modules.auth.models import (
    AuthSession,
    EnterpriseIdentityProvider,
    ExternalIdentityBinding,
)
from app.modules.auth.saml_models import SamlAuthnTransaction, SamlTrustRuntimeProfile
from app.modules.auth.saml_transaction import (
    SamlAuthnStartMaterial,
    consume_saml_authn_transaction,
    validate_saml_authn_transaction_proof,
    validate_saml_relay_state_source,
)
from app.modules.auth.service import _subject_fingerprint, create_auth_session
from app.modules.organizations.models import Organization, OrganizationStatus
from app.modules.users.models import User

SAML_AUTH_METHOD = "saml"
SAML_IDENTITY_SOURCE = "saml"
SAML_MAX_RESPONSE_BYTES = 1_048_576
SAML_MAX_ENCODED_RESPONSE_BYTES = 1_500_000
SAML_CLOCK_LEEWAY_SECONDS = 60
SAML_PROTOCOL_NS = "urn:oasis:names:tc:SAML:2.0:protocol"
SAML_ASSERTION_NS = "urn:oasis:names:tc:SAML:2.0:assertion"
DSIG_NS = "http://www.w3.org/2000/09/xmldsig#"
SAML_POST_BINDING = "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"
SAML_SUCCESS_STATUS = "urn:oasis:names:tc:SAML:2.0:status:Success"
SAML_BEARER_CONFIRMATION = "urn:oasis:names:tc:SAML:2.0:cm:bearer"
XMLDSIG_RSA_SHA256 = "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"
XMLDSIG_SHA256 = "http://www.w3.org/2001/04/xmlenc#sha256"
XMLDSIG_ENVELOPED = "http://www.w3.org/2000/09/xmldsig#enveloped-signature"
XMLDSIG_EXCLUSIVE_C14N = "http://www.w3.org/2001/10/xml-exc-c14n#"
_RESERVED_REDIRECT_PARAMS = {"SAMLRequest", "RelayState", "SigAlg", "Signature"}


class SamlCallbackError(ValueError):
    pass


@dataclass(frozen=True)
class VerifiedSamlIdentity:
    subject: str
    request_id: str


@dataclass(frozen=True)
class SamlCallbackResult:
    user: User
    auth_session: AuthSession
    provider: EnterpriseIdentityProvider
    binding: ExternalIdentityBinding
    transaction: SamlAuthnTransaction


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _saml_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_saml_authorization_url(
    *,
    profile: SamlTrustRuntimeProfile,
    material: SamlAuthnStartMaterial,
) -> str:
    """Build the exact unsigned HTTP-Redirect AuthnRequest from the pinned profile.

    SP request signing is intentionally absent until private-key custody is separately
    governed. Response authority comes only from the pinned IdP certificate and a signed
    assertion bound to this one-time request.
    """

    root = etree.Element(
        etree.QName(SAML_PROTOCOL_NS, "AuthnRequest"),
        nsmap={"samlp": SAML_PROTOCOL_NS, "saml": SAML_ASSERTION_NS},
    )
    root.set("ID", material.request_id)
    root.set("Version", "2.0")
    root.set("IssueInstant", _saml_timestamp(_utc_now()))
    root.set("Destination", profile.idp_sso_url)
    root.set("AssertionConsumerServiceURL", profile.acs_url)
    root.set("ProtocolBinding", SAML_POST_BINDING)
    issuer = etree.SubElement(root, etree.QName(SAML_ASSERTION_NS, "Issuer"))
    issuer.text = profile.sp_entity_id

    xml_bytes = etree.tostring(
        root,
        encoding="utf-8",
        xml_declaration=False,
        pretty_print=False,
    )
    compressor = zlib.compressobj(level=9, wbits=-15)
    deflated = compressor.compress(xml_bytes) + compressor.flush()
    encoded_request = base64.b64encode(deflated).decode("ascii")

    parts = urlsplit(profile.idp_sso_url)
    existing_query = parse_qsl(parts.query, keep_blank_values=True)
    if any(key in _RESERVED_REDIRECT_PARAMS for key, _ in existing_query):
        raise SamlCallbackError("SAML SSO endpoint contains reserved redirect parameters")
    query = existing_query + [
        ("SAMLRequest", encoded_request),
        ("RelayState", material.relay_state),
    ]
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )


def _decode_saml_response(encoded_response: str) -> bytes:
    if not encoded_response or len(encoded_response) > SAML_MAX_ENCODED_RESPONSE_BYTES:
        raise SamlCallbackError("SAML response is invalid")
    compact = "".join(encoded_response.split())
    try:
        raw = base64.b64decode(compact.encode("ascii"), validate=True)
    except (ValueError, UnicodeEncodeError) as exc:
        raise SamlCallbackError("SAML response is not valid base64") from exc
    if not raw or len(raw) > SAML_MAX_RESPONSE_BYTES:
        raise SamlCallbackError("SAML response exceeded the size limit")
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise SamlCallbackError("SAML response contains forbidden XML declarations")
    return raw


def _parse_xml(encoded_response: str) -> etree._Element:
    raw = _decode_saml_response(encoded_response)
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        huge_tree=False,
        recover=False,
        remove_comments=False,
    )
    try:
        root = etree.fromstring(raw, parser=parser)
    except (etree.XMLSyntaxError, ValueError) as exc:
        raise SamlCallbackError("SAML response XML is invalid") from exc
    if root.getroottree().docinfo.doctype:
        raise SamlCallbackError("SAML response XML doctype is forbidden")
    return root


def _children(parent: etree._Element, tag: str) -> list[etree._Element]:
    return [child for child in parent if child.tag == tag]


def _one_child(parent: etree._Element, tag: str, *, label: str) -> etree._Element:
    matches = _children(parent, tag)
    if len(matches) != 1:
        raise SamlCallbackError(f"SAML {label} is missing or ambiguous")
    return matches[0]


def _text(element: etree._Element, *, label: str, max_length: int = 1024) -> str:
    value = (element.text or "").strip()
    if not value or len(value) > max_length:
        raise SamlCallbackError(f"SAML {label} is invalid")
    return value


def _parse_time(value: str | None, *, label: str) -> datetime:
    if not value or len(value) > 64:
        raise SamlCallbackError(f"SAML {label} timestamp is invalid")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise SamlCallbackError(f"SAML {label} timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise SamlCallbackError(f"SAML {label} timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def _validate_issue_instant(
    value: str | None,
    *,
    transaction: SamlAuthnTransaction,
    label: str,
) -> None:
    instant = _parse_time(value, label=label)
    now = _utc_now()
    leeway = timedelta(seconds=SAML_CLOCK_LEEWAY_SECONDS)
    created_at = transaction.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    else:
        created_at = created_at.astimezone(timezone.utc)
    if instant > now + leeway or instant < created_at - leeway:
        raise SamlCallbackError(f"SAML {label} timestamp is outside the request window")


def _assert_unique_ids(root: etree._Element) -> None:
    seen: set[str] = set()
    for element in root.iter():
        identifier = element.get("ID")
        if identifier is None:
            continue
        if not identifier or len(identifier) > 256 or identifier in seen:
            raise SamlCallbackError("SAML XML contains invalid or duplicate IDs")
        seen.add(identifier)


def _canonicalize(element: etree._Element) -> bytes:
    return etree.tostring(
        element,
        method="c14n",
        exclusive=True,
        with_comments=False,
    )


def _decode_signature_value(value: str, *, label: str, max_bytes: int) -> bytes:
    compact = "".join(value.split())
    try:
        decoded = base64.b64decode(compact.encode("ascii"), validate=True)
    except (ValueError, UnicodeEncodeError) as exc:
        raise SamlCallbackError(f"SAML {label} is invalid") from exc
    if not decoded or len(decoded) > max_bytes:
        raise SamlCallbackError(f"SAML {label} is invalid")
    return decoded


def _load_pinned_certificate(profile: SamlTrustRuntimeProfile) -> x509.Certificate:
    try:
        certificate = x509.load_pem_x509_certificate(
            profile.idp_signing_certificate_pem.encode("ascii")
        )
    except (ValueError, TypeError, UnicodeEncodeError) as exc:
        raise SamlCallbackError("Pinned SAML signing certificate is invalid") from exc
    if not hmac.compare_digest(
        certificate.fingerprint(hashes.SHA256()).hex(),
        profile.certificate_sha256,
    ):
        raise SamlCallbackError("Pinned SAML signing certificate fingerprint changed")
    public_key = certificate.public_key()
    if not isinstance(public_key, rsa.RSAPublicKey) or public_key.key_size < 2048:
        raise SamlCallbackError("Pinned SAML signing certificate key is unsupported")
    now = _utc_now()
    if now < certificate.not_valid_before_utc or now > certificate.not_valid_after_utc:
        raise SamlCallbackError("Pinned SAML signing certificate is not currently valid")
    return certificate


def _verify_assertion_signature(
    root: etree._Element,
    *,
    assertion: etree._Element,
    profile: SamlTrustRuntimeProfile,
) -> None:
    if "RSA-SHA256" not in profile.allowed_signature_algorithms:
        raise SamlCallbackError("Pinned SAML signature policy is unsupported")
    if "SHA-256" not in profile.allowed_digest_algorithms:
        raise SamlCallbackError("Pinned SAML digest policy is unsupported")

    signature_tag = f"{{{DSIG_NS}}}Signature"
    signatures = list(root.iter(signature_tag))
    direct_signatures = _children(assertion, signature_tag)
    if len(signatures) != 1 or len(direct_signatures) != 1:
        raise SamlCallbackError("SAML assertion signature is missing or ambiguous")
    signature = direct_signatures[0]

    assertion_id = assertion.get("ID")
    if not assertion_id:
        raise SamlCallbackError("SAML Assertion ID is required")

    signed_info = _one_child(
        signature,
        f"{{{DSIG_NS}}}SignedInfo",
        label="SignedInfo",
    )
    canonicalization_method = _one_child(
        signed_info,
        f"{{{DSIG_NS}}}CanonicalizationMethod",
        label="CanonicalizationMethod",
    )
    if (
        canonicalization_method.get("Algorithm") != XMLDSIG_EXCLUSIVE_C14N
        or len(canonicalization_method) != 0
    ):
        raise SamlCallbackError("SAML canonicalization algorithm is unsupported")

    signature_method = _one_child(
        signed_info,
        f"{{{DSIG_NS}}}SignatureMethod",
        label="SignatureMethod",
    )
    if signature_method.get("Algorithm") != XMLDSIG_RSA_SHA256 or len(signature_method) != 0:
        raise SamlCallbackError("SAML signature algorithm is unsupported")

    reference = _one_child(
        signed_info,
        f"{{{DSIG_NS}}}Reference",
        label="Reference",
    )
    if reference.get("URI") != f"#{assertion_id}":
        raise SamlCallbackError("SAML signature reference does not bind the Assertion ID")
    if len(list(signature.iter(f"{{{DSIG_NS}}}Reference"))) != 1:
        raise SamlCallbackError("SAML signature contains multiple references")

    transforms = _one_child(
        reference,
        f"{{{DSIG_NS}}}Transforms",
        label="Transforms",
    )
    transform_nodes = _children(transforms, f"{{{DSIG_NS}}}Transform")
    transform_algorithms = [node.get("Algorithm") for node in transform_nodes]
    if transform_algorithms != [XMLDSIG_ENVELOPED, XMLDSIG_EXCLUSIVE_C14N]:
        raise SamlCallbackError("SAML signature transforms are unsupported")
    if any(len(node) != 0 for node in transform_nodes):
        raise SamlCallbackError("SAML signature transform parameters are unsupported")

    digest_method = _one_child(
        reference,
        f"{{{DSIG_NS}}}DigestMethod",
        label="DigestMethod",
    )
    if digest_method.get("Algorithm") != XMLDSIG_SHA256 or len(digest_method) != 0:
        raise SamlCallbackError("SAML digest algorithm is unsupported")
    digest_value_element = _one_child(
        reference,
        f"{{{DSIG_NS}}}DigestValue",
        label="DigestValue",
    )
    expected_digest = _decode_signature_value(
        _text(digest_value_element, label="DigestValue", max_length=256),
        label="DigestValue",
        max_bytes=64,
    )
    if len(expected_digest) != 32:
        raise SamlCallbackError("SAML assertion digest length is invalid")

    copied_root = copy.deepcopy(root)
    copied_assertions = [
        element
        for element in copied_root.iter(f"{{{SAML_ASSERTION_NS}}}Assertion")
        if element.get("ID") == assertion_id
    ]
    if len(copied_assertions) != 1:
        raise SamlCallbackError("SAML signed Assertion target is ambiguous")
    copied_assertion = copied_assertions[0]
    copied_signatures = _children(copied_assertion, signature_tag)
    if len(copied_signatures) != 1:
        raise SamlCallbackError("SAML signed Assertion transform target is invalid")
    copied_assertion.remove(copied_signatures[0])
    actual_digest = sha256(_canonicalize(copied_assertion)).digest()
    if not hmac.compare_digest(expected_digest, actual_digest):
        raise SamlCallbackError("SAML assertion digest verification failed")

    signature_value_element = _one_child(
        signature,
        f"{{{DSIG_NS}}}SignatureValue",
        label="SignatureValue",
    )
    certificate = _load_pinned_certificate(profile)
    public_key = certificate.public_key()
    assert isinstance(public_key, rsa.RSAPublicKey)
    signature_value = _decode_signature_value(
        _text(signature_value_element, label="SignatureValue", max_length=8192),
        label="SignatureValue",
        max_bytes=max(1024, public_key.key_size // 8 + 16),
    )
    try:
        public_key.verify(
            signature_value,
            _canonicalize(signed_info),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
    except InvalidSignature as exc:
        raise SamlCallbackError("SAML assertion signature verification failed") from exc


def _validate_response_and_assertion(
    root: etree._Element,
    *,
    transaction: SamlAuthnTransaction,
    profile: SamlTrustRuntimeProfile,
) -> VerifiedSamlIdentity:
    response_tag = f"{{{SAML_PROTOCOL_NS}}}Response"
    assertion_tag = f"{{{SAML_ASSERTION_NS}}}Assertion"
    if root.tag != response_tag:
        raise SamlCallbackError("SAML payload is not a Response")
    if root.get("Version") != "2.0":
        raise SamlCallbackError("SAML Response version is unsupported")
    _assert_unique_ids(root)
    _validate_issue_instant(
        root.get("IssueInstant"),
        transaction=transaction,
        label="Response IssueInstant",
    )

    all_assertions = list(root.iter(assertion_tag))
    direct_assertions = _children(root, assertion_tag)
    if len(all_assertions) != 1 or len(direct_assertions) != 1:
        raise SamlCallbackError("SAML Response must contain exactly one direct Assertion")
    if list(root.iter(f"{{{SAML_ASSERTION_NS}}}EncryptedAssertion")):
        raise SamlCallbackError("Encrypted SAML assertions are not enabled")
    assertion = direct_assertions[0]
    if assertion.get("Version") != "2.0":
        raise SamlCallbackError("SAML Assertion version is unsupported")
    _validate_issue_instant(
        assertion.get("IssueInstant"),
        transaction=transaction,
        label="Assertion IssueInstant",
    )

    _verify_assertion_signature(root, assertion=assertion, profile=profile)

    assertion_issuer = _text(
        _one_child(
            assertion,
            f"{{{SAML_ASSERTION_NS}}}Issuer",
            label="Assertion Issuer",
        ),
        label="Assertion Issuer",
        max_length=500,
    )
    if not hmac.compare_digest(assertion_issuer, profile.idp_entity_identifier):
        raise SamlCallbackError("SAML Assertion issuer does not match")

    subject = _one_child(
        assertion,
        f"{{{SAML_ASSERTION_NS}}}Subject",
        label="Subject",
    )
    name_id = _text(
        _one_child(
            subject,
            f"{{{SAML_ASSERTION_NS}}}NameID",
            label="NameID",
        ),
        label="NameID",
        max_length=1024,
    )
    confirmations = _children(
        subject,
        f"{{{SAML_ASSERTION_NS}}}SubjectConfirmation",
    )
    if len(confirmations) != 1 or confirmations[0].get("Method") != SAML_BEARER_CONFIRMATION:
        raise SamlCallbackError("SAML bearer SubjectConfirmation is missing or ambiguous")
    confirmation_data = _one_child(
        confirmations[0],
        f"{{{SAML_ASSERTION_NS}}}SubjectConfirmationData",
        label="SubjectConfirmationData",
    )
    request_id = confirmation_data.get("InResponseTo") or ""
    if not request_id or len(request_id) > 256:
        raise SamlCallbackError("SAML signed InResponseTo is invalid")
    if confirmation_data.get("Recipient") != profile.acs_url:
        raise SamlCallbackError("SAML signed recipient does not match the ACS URL")
    confirmation_expiry = _parse_time(
        confirmation_data.get("NotOnOrAfter"),
        label="SubjectConfirmationData NotOnOrAfter",
    )
    if _utc_now() - timedelta(seconds=SAML_CLOCK_LEEWAY_SECONDS) >= confirmation_expiry:
        raise SamlCallbackError("SAML SubjectConfirmation has expired")

    conditions = _one_child(
        assertion,
        f"{{{SAML_ASSERTION_NS}}}Conditions",
        label="Conditions",
    )
    not_before = _parse_time(conditions.get("NotBefore"), label="Conditions NotBefore")
    not_on_or_after = _parse_time(
        conditions.get("NotOnOrAfter"),
        label="Conditions NotOnOrAfter",
    )
    now = _utc_now()
    leeway = timedelta(seconds=SAML_CLOCK_LEEWAY_SECONDS)
    if now + leeway < not_before or now - leeway >= not_on_or_after:
        raise SamlCallbackError("SAML Assertion conditions are outside the valid window")
    audience_restriction = _one_child(
        conditions,
        f"{{{SAML_ASSERTION_NS}}}AudienceRestriction",
        label="AudienceRestriction",
    )
    audiences = _children(
        audience_restriction,
        f"{{{SAML_ASSERTION_NS}}}Audience",
    )
    if len(audiences) != 1 or _text(
        audiences[0], label="Audience", max_length=500
    ) != profile.sp_entity_id:
        raise SamlCallbackError("SAML Assertion audience does not match the SP entity ID")

    authn_statements = _children(
        assertion,
        f"{{{SAML_ASSERTION_NS}}}AuthnStatement",
    )
    if len(authn_statements) != 1:
        raise SamlCallbackError("SAML Assertion must contain exactly one AuthnStatement")

    response_issuer = _text(
        _one_child(
            root,
            f"{{{SAML_ASSERTION_NS}}}Issuer",
            label="Response Issuer",
        ),
        label="Response Issuer",
        max_length=500,
    )
    if not hmac.compare_digest(response_issuer, profile.idp_entity_identifier):
        raise SamlCallbackError("SAML Response issuer does not match")
    if root.get("Destination") != profile.acs_url:
        raise SamlCallbackError("SAML Response destination does not match the ACS URL")
    if root.get("InResponseTo") != request_id:
        raise SamlCallbackError("SAML Response correlation does not match the signed Assertion")

    status_element = _one_child(
        root,
        f"{{{SAML_PROTOCOL_NS}}}Status",
        label="Status",
    )
    status_code = _one_child(
        status_element,
        f"{{{SAML_PROTOCOL_NS}}}StatusCode",
        label="StatusCode",
    )
    if status_code.get("Value") != SAML_SUCCESS_STATUS:
        raise SamlCallbackError("SAML Response status is not Success")

    return VerifiedSamlIdentity(subject=name_id, request_id=request_id)


def _resolve_bound_user(
    db: Session,
    *,
    organization_id: UUID,
    provider: EnterpriseIdentityProvider,
    external_subject: str,
) -> tuple[ExternalIdentityBinding, User]:
    fingerprint = _subject_fingerprint(provider.id, external_subject)
    binding = db.scalar(
        select(ExternalIdentityBinding)
        .where(
            ExternalIdentityBinding.organization_id == organization_id,
            ExternalIdentityBinding.provider_id == provider.id,
            ExternalIdentityBinding.subject_fingerprint == fingerprint,
            ExternalIdentityBinding.revoked_at.is_(None),
        )
        .with_for_update()
    )
    if binding is None:
        raise SamlCallbackError("SAML external identity is not bound")

    organization = db.scalar(
        select(Organization).where(
            Organization.id == organization_id,
            Organization.status == OrganizationStatus.ACTIVE,
            Organization.deleted_at.is_(None),
        )
    )
    if organization is None:
        raise SamlCallbackError("SAML application tenant is unavailable")

    user = db.scalar(
        select(User)
        .where(
            User.id == binding.user_id,
            User.organization_id == organization_id,
            User.is_active.is_(True),
            User.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if user is None:
        raise SamlCallbackError("SAML bound application user is unavailable")
    return binding, user


def complete_saml_callback(
    db: Session,
    *,
    relay_state: str,
    saml_response: str,
) -> SamlCallbackResult:
    transaction, source = validate_saml_relay_state_source(
        db,
        relay_state=relay_state,
    )
    identity = _validate_response_and_assertion(
        _parse_xml(saml_response),
        transaction=transaction,
        profile=source.profile,
    )
    validate_saml_authn_transaction_proof(
        db,
        relay_state=relay_state,
        request_id=identity.request_id,
    )
    binding, user = _resolve_bound_user(
        db,
        organization_id=transaction.organization_id,
        provider=source.provider,
        external_subject=identity.subject,
    )

    consumed = consume_saml_authn_transaction(
        db,
        relay_state=relay_state,
        request_id=identity.request_id,
    )
    auth_session = create_auth_session(
        db,
        user=user,
        identity_source=SAML_IDENTITY_SOURCE,
        auth_method=SAML_AUTH_METHOD,
    )
    auth_session.external_identity_provider_id = source.provider.id
    auth_session.external_identity_binding_id = binding.id
    auth_session.saml_authn_transaction_id = consumed.id
    user.last_login_at = _utc_now()
    db.flush()

    write_audit_log(
        db,
        organization_id=user.organization_id,
        user_id=user.id,
        action="SAML_LOGIN_SUCCESS",
        entity_type="auth_session",
        entity_id=auth_session.id,
        new_values={
            "identity_source": auth_session.identity_source,
            "auth_method": auth_session.auth_method,
            "provider_id": str(source.provider.id),
            "binding_id": str(binding.id),
            "saml_authn_transaction_id": str(consumed.id),
            "profile_id": str(consumed.profile_id),
            "profile_number": consumed.profile_number,
            "profile_hash": consumed.profile_hash,
        },
    )
    db.flush()
    return SamlCallbackResult(
        user=user,
        auth_session=auth_session,
        provider=source.provider,
        binding=binding,
        transaction=consumed,
    )
