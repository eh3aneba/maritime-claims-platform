import base64
from uuid import UUID

from lxml import etree
from sqlalchemy.orm import Session

from app.modules.audit.service import write_audit_log
from app.modules.auth.models import AuthSession
from app.modules.auth.saml_assurance import (
    SAML_EXTERNAL_MFA_METHOD,
    evaluate_pinned_saml_mfa_assurance,
    record_saml_mfa_assurance_verification,
)
from app.modules.auth.saml_models import SamlAuthnTransaction

SAML_PROTOCOL_NS = "urn:oasis:names:tc:SAML:2.0:protocol"
SAML_ASSERTION_NS = "urn:oasis:names:tc:SAML:2.0:assertion"
SAML_MAX_RESPONSE_BYTES = 1_048_576
SAML_MAX_ENCODED_RESPONSE_BYTES = 1_500_000
MAX_AUTHN_CONTEXT_LENGTH = 512


def _children(parent: etree._Element, tag: str) -> list[etree._Element]:
    return [child for child in parent if child.tag == tag]


def _extract_authn_context_from_verified_response(saml_response: str) -> str | None:
    """Extract bounded AuthnContext only after the same response passed SAML verification.

    The caller must invoke this only after complete_saml_callback succeeds for this exact
    saml_response value in the same request/transaction. This function deliberately does
    not create identity authority; it only reads optional assurance evidence from that
    already verified response.
    """

    if not saml_response or len(saml_response) > SAML_MAX_ENCODED_RESPONSE_BYTES:
        return None
    compact = "".join(saml_response.split())
    try:
        raw = base64.b64decode(compact.encode("ascii"), validate=True)
    except (ValueError, UnicodeEncodeError):
        return None
    if not raw or len(raw) > SAML_MAX_RESPONSE_BYTES:
        return None
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        return None

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
    except (etree.XMLSyntaxError, ValueError):
        return None
    if root.getroottree().docinfo.doctype:
        return None
    if root.tag != f"{{{SAML_PROTOCOL_NS}}}Response":
        return None

    assertion_tag = f"{{{SAML_ASSERTION_NS}}}Assertion"
    assertions = _children(root, assertion_tag)
    if len(assertions) != 1 or len(list(root.iter(assertion_tag))) != 1:
        return None
    assertion = assertions[0]

    authn_statements = _children(
        assertion,
        f"{{{SAML_ASSERTION_NS}}}AuthnStatement",
    )
    if len(authn_statements) != 1:
        return None
    contexts = _children(
        authn_statements[0],
        f"{{{SAML_ASSERTION_NS}}}AuthnContext",
    )
    if len(contexts) != 1:
        return None
    refs = _children(
        contexts[0],
        f"{{{SAML_ASSERTION_NS}}}AuthnContextClassRef",
    )
    if len(refs) != 1 or len(refs[0]) != 0:
        return None
    value = (refs[0].text or "").strip()
    if not value or len(value) > MAX_AUTHN_CONTEXT_LENGTH:
        return None
    return value


def apply_saml_mfa_assurance_after_verified_callback(
    db: Session,
    *,
    transaction: SamlAuthnTransaction,
    auth_session: AuthSession,
    saml_response: str,
    user_id: UUID,
) -> bool:
    """Elevate only the exact callback session from optional signed AuthnContext evidence."""

    authn_context = _extract_authn_context_from_verified_response(saml_response)
    binding, result = evaluate_pinned_saml_mfa_assurance(
        db,
        transaction=transaction,
        authn_context=authn_context,
    )
    if not result.verified:
        return False
    if binding is None:
        raise ValueError("SAML MFA assurance binding is unavailable")

    verified_at = record_saml_mfa_assurance_verification(
        db,
        binding=binding,
        result=result,
    )
    auth_session.mfa_verified_at = verified_at
    auth_session.mfa_method = SAML_EXTERNAL_MFA_METHOD
    auth_session.mfa_factor_id = None
    db.flush()

    write_audit_log(
        db,
        organization_id=transaction.organization_id,
        user_id=user_id,
        action="SAML_EXTERNAL_MFA_ASSURANCE_VERIFIED",
        entity_type="auth_session",
        entity_id=auth_session.id,
        new_values={
            "provider_id": str(transaction.provider_id),
            "saml_authn_transaction_id": str(transaction.id),
            "saml_profile_id": str(binding.saml_profile_id),
            "saml_profile_number": binding.saml_profile_number,
            "saml_profile_hash": binding.saml_profile_hash,
            "assurance_profile_id": str(binding.assurance_profile_id),
            "assurance_profile_number": binding.assurance_profile_number,
            "assurance_profile_hash": binding.assurance_profile_hash,
            "evidence_type": binding.evidence_type,
            "evidence_hash": binding.evidence_hash,
        },
    )
    db.flush()
    return True
