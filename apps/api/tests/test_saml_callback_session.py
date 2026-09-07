import base64
import copy
import json
import zlib
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID
from lxml import etree

from app.core.security import create_access_token
from app.modules.audit.models import AuditLog
from app.modules.auth.models import (
    AuthSession,
    EnterpriseIdentityProvider,
    ExternalIdentityBinding,
)
from app.modules.auth.saml_callback import (
    DSIG_NS,
    SAML_ASSERTION_NS,
    SAML_BEARER_CONFIRMATION,
    SAML_POST_BINDING,
    SAML_PROTOCOL_NS,
    SAML_SUCCESS_STATUS,
    XMLDSIG_ENVELOPED,
    XMLDSIG_EXCLUSIVE_C14N,
    XMLDSIG_RSA_SHA256,
    XMLDSIG_SHA256,
)
from app.modules.auth.saml_models import SamlAuthnTransaction
from app.modules.auth.service import create_auth_session, create_external_identity_binding
from app.modules.organizations.models import Organization
from app.modules.users.models import User, UserRole
from tests.db_harness import TestingSessionLocal, client, reset_database


def setup_function() -> None:
    reset_database()


def _seed() -> tuple[UUID, UUID, UUID]:
    with TestingSessionLocal() as db:
        org = Organization(name="SAML Callback Marine", slug="saml-callback-marine")
        db.add(org)
        db.flush()
        admin = User(
            organization_id=org.id,
            email="saml-callback-admin@example.com",
            full_name="SAML Callback Admin",
            password_hash="",
            role=UserRole.ADMIN,
            is_active=True,
        )
        handler = User(
            organization_id=org.id,
            email="saml-callback-handler@example.com",
            full_name="SAML Callback Handler",
            password_hash="",
            role=UserRole.CLAIMS_HANDLER,
            is_active=True,
        )
        db.add_all([admin, handler])
        db.commit()
        return org.id, admin.id, handler.id


def _headers(user_id: UUID) -> dict[str, str]:
    with TestingSessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None
        session = create_auth_session(db, user=user)
        db.commit()
        token = create_access_token(
            user_id=user.id,
            organization_id=user.organization_id,
            role=user.role.value,
            session_id=session.id,
            identity_source=session.identity_source,
            auth_method=session.auth_method,
        )
    return {"Authorization": f"Bearer {token}"}


def _certificate(private_key: rsa.RSAPrivateKey) -> str:
    now = datetime.now(timezone.utc)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "MCRI SAML Callback IdP")])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=365))
        .sign(private_key, hashes.SHA256())
    )
    return certificate.public_bytes(serialization.Encoding.PEM).decode("ascii")


def _create_profile(
    headers: dict[str, str],
    provider_id: str,
    private_key: rsa.RSAPrivateKey,
    *,
    suffix: str = "",
) -> dict[str, object]:
    response = client.post(
        f"/api/v1/auth/identity-providers/{provider_id}/saml-trust-runtime-profiles",
        headers=headers,
        json={
            "idp_sso_url": f"https://idp.saml-callback.example.test/sso{suffix}",
            "sp_entity_id": "https://mcri.example.test/saml/sp",
            "acs_url": "https://mcri.example.test/api/v1/auth/saml/callback",
            "authn_request_binding": "HTTP-Redirect",
            "response_binding": "HTTP-POST",
            "allowed_signature_algorithms": ["RSA-SHA256"],
            "allowed_digest_algorithms": ["SHA-256"],
            "idp_signing_certificate_pem": _certificate(private_key),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_provider_stack(
    headers: dict[str, str],
    private_key: rsa.RSAPrivateKey,
) -> dict[str, object]:
    response = client.post(
        "/api/v1/auth/identity-providers",
        headers=headers,
        json={
            "provider_key": "corp-saml",
            "display_name": "Corporate SAML",
            "protocol": "saml",
            "issuer_identifier": "https://idp.saml-callback.example.test/entity",
        },
    )
    assert response.status_code == 201
    provider = response.json()
    response = client.post(
        f"/api/v1/auth/identity-providers/{provider['id']}/enable",
        headers=headers,
    )
    assert response.status_code == 200
    profile = _create_profile(headers, provider["id"], private_key)
    return {"provider": provider, "profile": profile}


def _bind(provider_id: str, handler_id: UUID, subject: str = "saml-subject-123") -> None:
    with TestingSessionLocal() as db:
        provider = db.get(EnterpriseIdentityProvider, UUID(provider_id))
        handler = db.get(User, handler_id)
        assert provider is not None
        assert handler is not None
        create_external_identity_binding(
            db,
            provider=provider,
            user=handler,
            external_subject=subject,
        )
        db.commit()


def _start() -> dict[str, object]:
    response = client.post(
        "/api/v1/auth/saml/transactions",
        json={
            "organization_slug": "saml-callback-marine",
            "provider_key": "corp-saml",
        },
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    parts = urlsplit(payload["authorization_url"])
    query = parse_qs(parts.query)
    assert query["RelayState"] == [payload["relay_state"]]
    deflated = base64.b64decode(query["SAMLRequest"][0])
    request_xml = zlib.decompress(deflated, wbits=-15)
    request = etree.fromstring(request_xml)
    assert request.get("ID") == payload["request_id"]
    assert request.get("Destination") == payload["idp_sso_url"]
    assert request.get("AssertionConsumerServiceURL") == payload["acs_url"]
    assert request.get("ProtocolBinding") == SAML_POST_BINDING
    return payload


def _canonicalize(element: etree._Element) -> bytes:
    return etree.tostring(
        element,
        method="c14n",
        exclusive=True,
        with_comments=False,
    )


def _signed_response(
    start: dict[str, object],
    private_key: rsa.RSAPrivateKey,
    *,
    subject: str = "saml-subject-123",
    request_id: str | None = None,
    audience: str = "https://mcri.example.test/saml/sp",
    recipient: str = "https://mcri.example.test/api/v1/auth/saml/callback",
    destination: str = "https://mcri.example.test/api/v1/auth/saml/callback",
    assertion_issuer: str = "https://idp.saml-callback.example.test/entity",
    response_issuer: str = "https://idp.saml-callback.example.test/entity",
) -> str:
    now = datetime.now(timezone.utc)
    correlation = request_id or str(start["request_id"])
    response = etree.Element(
        etree.QName(SAML_PROTOCOL_NS, "Response"),
        nsmap={"samlp": SAML_PROTOCOL_NS, "saml": SAML_ASSERTION_NS},
    )
    response.set("ID", "_response-" + str(start["transaction_id"]))
    response.set("Version", "2.0")
    response.set("IssueInstant", now.strftime("%Y-%m-%dT%H:%M:%SZ"))
    response.set("Destination", destination)
    response.set("InResponseTo", correlation)
    response_issuer_node = etree.SubElement(
        response,
        etree.QName(SAML_ASSERTION_NS, "Issuer"),
    )
    response_issuer_node.text = response_issuer
    status_node = etree.SubElement(response, etree.QName(SAML_PROTOCOL_NS, "Status"))
    status_code = etree.SubElement(
        status_node,
        etree.QName(SAML_PROTOCOL_NS, "StatusCode"),
    )
    status_code.set("Value", SAML_SUCCESS_STATUS)

    assertion = etree.SubElement(
        response,
        etree.QName(SAML_ASSERTION_NS, "Assertion"),
    )
    assertion.set("ID", "_assertion-" + str(start["transaction_id"]))
    assertion.set("Version", "2.0")
    assertion.set("IssueInstant", now.strftime("%Y-%m-%dT%H:%M:%SZ"))
    assertion_issuer_node = etree.SubElement(
        assertion,
        etree.QName(SAML_ASSERTION_NS, "Issuer"),
    )
    assertion_issuer_node.text = assertion_issuer

    signature = etree.Element(
        etree.QName(DSIG_NS, "Signature"),
        nsmap={"ds": DSIG_NS},
    )
    assertion.insert(1, signature)

    subject_node = etree.SubElement(
        assertion,
        etree.QName(SAML_ASSERTION_NS, "Subject"),
    )
    name_id = etree.SubElement(subject_node, etree.QName(SAML_ASSERTION_NS, "NameID"))
    name_id.text = subject
    confirmation = etree.SubElement(
        subject_node,
        etree.QName(SAML_ASSERTION_NS, "SubjectConfirmation"),
    )
    confirmation.set("Method", SAML_BEARER_CONFIRMATION)
    confirmation_data = etree.SubElement(
        confirmation,
        etree.QName(SAML_ASSERTION_NS, "SubjectConfirmationData"),
    )
    confirmation_data.set("InResponseTo", correlation)
    confirmation_data.set("Recipient", recipient)
    confirmation_data.set(
        "NotOnOrAfter",
        (now + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )

    conditions = etree.SubElement(
        assertion,
        etree.QName(SAML_ASSERTION_NS, "Conditions"),
    )
    conditions.set(
        "NotBefore",
        (now - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    conditions.set(
        "NotOnOrAfter",
        (now + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    restriction = etree.SubElement(
        conditions,
        etree.QName(SAML_ASSERTION_NS, "AudienceRestriction"),
    )
    audience_node = etree.SubElement(
        restriction,
        etree.QName(SAML_ASSERTION_NS, "Audience"),
    )
    audience_node.text = audience
    authn_statement = etree.SubElement(
        assertion,
        etree.QName(SAML_ASSERTION_NS, "AuthnStatement"),
    )
    authn_statement.set("AuthnInstant", now.strftime("%Y-%m-%dT%H:%M:%SZ"))

    attribute_statement = etree.SubElement(
        assertion,
        etree.QName(SAML_ASSERTION_NS, "AttributeStatement"),
    )
    role_attribute = etree.SubElement(
        attribute_statement,
        etree.QName(SAML_ASSERTION_NS, "Attribute"),
    )
    role_attribute.set("Name", "role")
    role_value = etree.SubElement(
        role_attribute,
        etree.QName(SAML_ASSERTION_NS, "AttributeValue"),
    )
    role_value.text = "admin"

    signed_info = etree.SubElement(signature, etree.QName(DSIG_NS, "SignedInfo"))
    canonicalization = etree.SubElement(
        signed_info,
        etree.QName(DSIG_NS, "CanonicalizationMethod"),
    )
    canonicalization.set("Algorithm", XMLDSIG_EXCLUSIVE_C14N)
    signature_method = etree.SubElement(
        signed_info,
        etree.QName(DSIG_NS, "SignatureMethod"),
    )
    signature_method.set("Algorithm", XMLDSIG_RSA_SHA256)
    reference = etree.SubElement(signed_info, etree.QName(DSIG_NS, "Reference"))
    reference.set("URI", f"#{assertion.get('ID')}")
    transforms = etree.SubElement(reference, etree.QName(DSIG_NS, "Transforms"))
    transform = etree.SubElement(transforms, etree.QName(DSIG_NS, "Transform"))
    transform.set("Algorithm", XMLDSIG_ENVELOPED)
    transform = etree.SubElement(transforms, etree.QName(DSIG_NS, "Transform"))
    transform.set("Algorithm", XMLDSIG_EXCLUSIVE_C14N)
    digest_method = etree.SubElement(reference, etree.QName(DSIG_NS, "DigestMethod"))
    digest_method.set("Algorithm", XMLDSIG_SHA256)
    digest_value = etree.SubElement(reference, etree.QName(DSIG_NS, "DigestValue"))

    assertion_for_digest = copy.deepcopy(assertion)
    assertion_for_digest.remove(
        next(
            child
            for child in assertion_for_digest
            if child.tag == f"{{{DSIG_NS}}}Signature"
        )
    )
    digest_value.text = base64.b64encode(
        sha256(_canonicalize(assertion_for_digest)).digest()
    ).decode("ascii")

    signature_value = etree.SubElement(signature, etree.QName(DSIG_NS, "SignatureValue"))
    signature_value.text = base64.b64encode(
        private_key.sign(
            _canonicalize(signed_info),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
    ).decode("ascii")

    return base64.b64encode(etree.tostring(response, encoding="utf-8")).decode("ascii")


def _callback(start: dict[str, object], saml_response: str):
    return client.post(
        "/api/v1/auth/saml/callback",
        data={
            "RelayState": start["relay_state"],
            "SAMLResponse": saml_response,
        },
    )


def test_valid_signed_saml_callback_issues_one_bound_session_and_db_role_wins() -> None:
    _, admin_id, handler_id = _seed()
    headers = _headers(admin_id)
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    stack = _create_provider_stack(headers, private_key)
    _bind(str(stack["provider"]["id"]), handler_id)
    start = _start()
    saml_response = _signed_response(start, private_key)

    with TestingSessionLocal() as db:
        users_before = db.query(User).count()
        bindings_before = db.query(ExternalIdentityBinding).count()
        sessions_before = db.query(AuthSession).count()

    response = _callback(start, saml_response)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["user"]["id"] == str(handler_id)
    assert payload["user"]["role"] == UserRole.CLAIMS_HANDLER.value

    session_response = client.get(
        "/api/v1/auth/session",
        headers={"Authorization": f"Bearer {payload['access_token']}"},
    )
    assert session_response.status_code == 200
    session_payload = session_response.json()
    assert session_payload["identity_source"] == "saml"
    assert session_payload["auth_method"] == "saml"
    assert session_payload["external_identity_provider_id"] == stack["provider"]["id"]
    assert session_payload["saml_authn_transaction_id"] == start["transaction_id"]
    assert session_payload["oidc_authorization_transaction_id"] is None

    with TestingSessionLocal() as db:
        assert db.query(User).count() == users_before
        assert db.query(ExternalIdentityBinding).count() == bindings_before
        assert db.query(AuthSession).count() == sessions_before + 1
        transaction = db.get(SamlAuthnTransaction, UUID(str(start["transaction_id"])))
        assert transaction is not None and transaction.consumed_at is not None
        session = db.query(AuthSession).filter(
            AuthSession.saml_authn_transaction_id == transaction.id
        ).one()
        assert session.user_id == handler_id
        assert transaction.request_id_hash != start["request_id"]
        assert transaction.relay_state_hash != start["relay_state"]

        audits = db.query(AuditLog).filter(
            AuditLog.action.in_(
                [
                    "SAML_AUTHN_TRANSACTION_CREATED",
                    "SAML_AUTHN_TRANSACTION_CONSUMED",
                    "SAML_LOGIN_SUCCESS",
                ]
            )
        ).all()
        serialized = json.dumps([row.new_values or {} for row in audits], sort_keys=True)
        for secret in (
            "saml-subject-123",
            str(start["request_id"]),
            str(start["relay_state"]),
            saml_response,
        ):
            assert secret not in serialized

    replay = _callback(start, saml_response)
    assert replay.status_code == 401
    with TestingSessionLocal() as db:
        assert db.query(AuthSession).count() == sessions_before + 1


def test_signed_assertion_tampering_fails_without_consuming_transaction() -> None:
    _, admin_id, handler_id = _seed()
    headers = _headers(admin_id)
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    stack = _create_provider_stack(headers, private_key)
    _bind(str(stack["provider"]["id"]), handler_id)
    start = _start()
    encoded = _signed_response(start, private_key)
    root = etree.fromstring(base64.b64decode(encoded))
    name_id = next(root.iter(f"{{{SAML_ASSERTION_NS}}}NameID"))
    name_id.text = "tampered-subject"
    tampered = base64.b64encode(etree.tostring(root)).decode("ascii")

    assert _callback(start, tampered).status_code == 401
    with TestingSessionLocal() as db:
        transaction = db.get(SamlAuthnTransaction, UUID(str(start["transaction_id"])))
        assert transaction is not None and transaction.consumed_at is None
        assert db.query(AuthSession).filter(
            AuthSession.saml_authn_transaction_id == transaction.id
        ).count() == 0


def test_signed_wrong_in_response_to_fails_closed() -> None:
    _, admin_id, handler_id = _seed()
    headers = _headers(admin_id)
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    stack = _create_provider_stack(headers, private_key)
    _bind(str(stack["provider"]["id"]), handler_id)
    start = _start()
    wrong = _signed_response(start, private_key, request_id="_wrong-request-correlation")

    assert _callback(start, wrong).status_code == 401
    with TestingSessionLocal() as db:
        transaction = db.get(SamlAuthnTransaction, UUID(str(start["transaction_id"])))
        assert transaction is not None and transaction.consumed_at is None


def test_unsigned_response_fields_cannot_override_signed_recipient_or_correlation() -> None:
    _, admin_id, handler_id = _seed()
    headers = _headers(admin_id)
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    stack = _create_provider_stack(headers, private_key)
    _bind(str(stack["provider"]["id"]), handler_id)
    start = _start()

    wrong_destination = _signed_response(
        start,
        private_key,
        destination="https://attacker.example.test/acs",
    )
    assert _callback(start, wrong_destination).status_code == 401

    wrong_recipient = _signed_response(
        start,
        private_key,
        recipient="https://attacker.example.test/acs",
    )
    assert _callback(start, wrong_recipient).status_code == 401


def test_duplicate_assertion_wrapping_shape_is_rejected() -> None:
    _, admin_id, handler_id = _seed()
    headers = _headers(admin_id)
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    stack = _create_provider_stack(headers, private_key)
    _bind(str(stack["provider"]["id"]), handler_id)
    start = _start()
    encoded = _signed_response(start, private_key)
    root = etree.fromstring(base64.b64decode(encoded))
    assertion = next(root.iter(f"{{{SAML_ASSERTION_NS}}}Assertion"))
    duplicate = copy.deepcopy(assertion)
    duplicate.set("ID", "_attacker-assertion")
    root.append(duplicate)
    wrapped = base64.b64encode(etree.tostring(root)).decode("ascii")

    assert _callback(start, wrapped).status_code == 401


def test_unbound_subject_fails_without_consuming_transaction() -> None:
    _, admin_id, _ = _seed()
    headers = _headers(admin_id)
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    _create_provider_stack(headers, private_key)
    start = _start()

    assert _callback(start, _signed_response(start, private_key)).status_code == 401
    with TestingSessionLocal() as db:
        transaction = db.get(SamlAuthnTransaction, UUID(str(start["transaction_id"])))
        assert transaction is not None and transaction.consumed_at is None


def test_inflight_transaction_keeps_exact_pinned_profile_after_rotation() -> None:
    _, admin_id, handler_id = _seed()
    headers = _headers(admin_id)
    first_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    stack = _create_provider_stack(headers, first_key)
    _bind(str(stack["provider"]["id"]), handler_id)
    start = _start()

    second_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    second_profile = _create_profile(
        headers,
        str(stack["provider"]["id"]),
        second_key,
        suffix="-rotated",
    )
    assert second_profile["profile_number"] == 2
    assert start["profile_number"] == 1

    response = _callback(start, _signed_response(start, first_key))
    assert response.status_code == 200, response.text


def test_provider_disablement_invalidates_inflight_saml_authority() -> None:
    _, admin_id, handler_id = _seed()
    headers = _headers(admin_id)
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    stack = _create_provider_stack(headers, private_key)
    _bind(str(stack["provider"]["id"]), handler_id)
    start = _start()

    response = client.post(
        f"/api/v1/auth/identity-providers/{stack['provider']['id']}/disable",
        headers=headers,
    )
    assert response.status_code == 200
    assert _callback(start, _signed_response(start, private_key)).status_code == 401
