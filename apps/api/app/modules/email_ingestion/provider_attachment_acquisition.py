from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.audit.service import write_audit_log
from app.modules.documents.malware import MalwareScannerError, MalwareScanVerdict, scan_file
from app.modules.documents.service import (
    _storage,
    normalize_original_filename,
    validate_file_signature,
    validate_upload,
)
from app.modules.email_ingestion.models import (
    EmailAttachmentManifest,
    EmailConnectionStatus,
    EmailIngestionConnection,
    EmailMessageStatus,
    EmailProviderAdapter,
    IngestedEmailMessage,
)
from app.modules.email_ingestion.provider_execution import (
    ProviderExecutionFailure,
    _http_json,
    _resolve_credential,
)
from app.modules.users.models import User

settings = get_settings()

_GRAPH_ROOT = "https://graph.microsoft.com"
_GMAIL_ROOT = "https://gmail.googleapis.com"
_ALLOWED_PROVIDER_HOSTS = {"graph.microsoft.com", "gmail.googleapis.com"}
_TERMINAL_QUARANTINE_STATES = {
    "clean_pending_human_admission",
    "infected_quarantined",
    "scan_error_quarantined",
}


class ProviderAttachmentFailure(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _response(manifest: EmailAttachmentManifest, *, replayed: bool) -> dict:
    return {
        "manifest_id": manifest.id,
        "message_id": manifest.message_id,
        "acquired_claim_id": manifest.acquired_claim_id,
        "admission_status": manifest.admission_status,
        "acquired_file_size_bytes": manifest.acquired_file_size_bytes,
        "acquired_file_hash": manifest.acquired_file_hash,
        "malware_scan_status": manifest.malware_scan_status,
        "acquired_at": manifest.acquired_at,
        "malware_scanned_at": manifest.malware_scanned_at,
        "acquisition_failure_code": manifest.acquisition_failure_code,
        "replayed": replayed,
    }


def _audit_failure(
    db: Session,
    *,
    manifest: EmailAttachmentManifest,
    user: User,
    provider_kind: str,
    code: str,
) -> None:
    write_audit_log(
        db,
        organization_id=manifest.organization_id,
        user_id=user.id,
        action="REJECT_EMAIL_PROVIDER_ATTACHMENT_ACQUISITION",
        entity_type="email_attachment_manifest",
        entity_id=manifest.id,
        new_values={
            "provider_kind": provider_kind,
            "failure_code": code,
            "message_id": str(manifest.message_id),
        },
        details=(
            "Content-free attachment acquisition failure metadata only. Provider locator, filename, "
            "message content, credential values, raw responses and attachment bytes are excluded."
        ),
    )


def _mark_failure(
    db: Session,
    *,
    manifest: EmailAttachmentManifest,
    user: User,
    provider_kind: str,
    code: str,
) -> None:
    manifest.admission_status = "acquisition_failed"
    manifest.acquisition_failure_code = code
    _audit_failure(db, manifest=manifest, user=user, provider_kind=provider_kind, code=code)
    db.commit()


def _http_bytes(url: str, bearer_token: str, *, max_bytes: int, accept: str) -> bytes:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in _ALLOWED_PROVIDER_HOSTS:
        raise ProviderAttachmentFailure("provider_url_rejected")
    request = Request(
        url,
        headers={
            "Accept": accept,
            "Authorization": f"Bearer {bearer_token}",
            "User-Agent": "MCRI-Provider-Attachment-Quarantine/1.0",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=10) as response:  # nosec B310 - HTTPS host allowlist enforced above
            declared_length = response.headers.get("Content-Length")
            if declared_length:
                try:
                    if int(declared_length) > max_bytes:
                        raise ProviderAttachmentFailure("provider_attachment_too_large")
                except ValueError:
                    pass
            raw = response.read(max_bytes + 1)
    except HTTPError as exc:
        raise ProviderAttachmentFailure("provider_attachment_http_error") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise ProviderAttachmentFailure("provider_attachment_transport_error") from exc
    if len(raw) > max_bytes:
        raise ProviderAttachmentFailure("provider_attachment_too_large")
    return raw


def _graph_locator(
    token: str,
    message: IngestedEmailMessage,
    manifest: EmailAttachmentManifest,
) -> str:
    encoded_message = quote(message.provider_message_id, safe="")
    query = urlencode({"$select": "id,name,contentType,size,isInline"})
    payload = _http_json(
        f"{_GRAPH_ROOT}/v1.0/me/messages/{encoded_message}/attachments?{query}",
        token,
    )
    values = payload.get("value")
    if not isinstance(values, list):
        raise ProviderAttachmentFailure("provider_attachment_locator_unresolved")
    matches: list[str] = []
    for item in values[:25]:
        if not isinstance(item, dict):
            continue
        attachment_id = item.get("id")
        name = item.get("name")
        mime_type = item.get("contentType")
        try:
            size = int(item.get("size") or 0)
        except (TypeError, ValueError):
            continue
        if (
            isinstance(attachment_id, str)
            and attachment_id
            and isinstance(name, str)
            and name == manifest.filename
            and (mime_type if isinstance(mime_type, str) and mime_type else "application/octet-stream")
            == manifest.mime_type
            and size == manifest.file_size_bytes
        ):
            matches.append(attachment_id)
    if len(matches) != 1:
        raise ProviderAttachmentFailure("provider_attachment_locator_unresolved")
    return matches[0]


def _gmail_parts(payload: dict) -> list[dict]:
    result = [payload]
    parts = payload.get("parts")
    if isinstance(parts, list):
        for part in parts:
            if isinstance(part, dict):
                result.extend(_gmail_parts(part))
    return result


def _gmail_locator(
    token: str,
    message: IngestedEmailMessage,
    manifest: EmailAttachmentManifest,
) -> str:
    encoded_message = quote(message.provider_message_id, safe="")
    item = _http_json(
        f"{_GMAIL_ROOT}/gmail/v1/users/me/messages/{encoded_message}?format=full",
        token,
    )
    payload = item.get("payload")
    if not isinstance(payload, dict):
        raise ProviderAttachmentFailure("provider_attachment_locator_unresolved")
    matches: list[str] = []
    for part in _gmail_parts(payload):
        filename = part.get("filename")
        mime_type = part.get("mimeType")
        body = part.get("body")
        if not isinstance(body, dict):
            continue
        attachment_id = body.get("attachmentId")
        try:
            size = int(body.get("size") or 0)
        except (TypeError, ValueError):
            continue
        if (
            isinstance(attachment_id, str)
            and attachment_id
            and isinstance(filename, str)
            and filename == manifest.filename
            and (mime_type if isinstance(mime_type, str) and mime_type else "application/octet-stream")
            == manifest.mime_type
            and size == manifest.file_size_bytes
        ):
            matches.append(attachment_id)
    if len(matches) != 1:
        raise ProviderAttachmentFailure("provider_attachment_locator_unresolved")
    return matches[0]


def _resolve_locator(
    adapter: EmailProviderAdapter,
    token: str,
    message: IngestedEmailMessage,
    manifest: EmailAttachmentManifest,
) -> str:
    if manifest.provider_attachment_id:
        return manifest.provider_attachment_id
    if adapter.provider_kind == "microsoft_graph":
        return _graph_locator(token, message, manifest)
    if adapter.provider_kind == "gmail_api":
        return _gmail_locator(token, message, manifest)
    raise ProviderAttachmentFailure("provider_attachment_kind_not_supported")


def _fetch_attachment_bytes(
    adapter: EmailProviderAdapter,
    token: str,
    message: IngestedEmailMessage,
    provider_attachment_id: str,
) -> bytes:
    max_bytes = settings.max_upload_bytes
    encoded_message = quote(message.provider_message_id, safe="")
    encoded_attachment = quote(provider_attachment_id, safe="")
    if adapter.provider_kind == "microsoft_graph":
        return _http_bytes(
            f"{_GRAPH_ROOT}/v1.0/me/messages/{encoded_message}/attachments/{encoded_attachment}/$value",
            token,
            max_bytes=max_bytes,
            accept="application/octet-stream",
        )
    if adapter.provider_kind == "gmail_api":
        # Gmail wraps attachment bytes in URL-safe base64 JSON, so cap the encoded
        # response separately and always enforce the decoded byte limit again.
        encoded_limit = min((max_bytes * 4 // 3) + 1_048_576, 40_000_000)
        raw = _http_bytes(
            f"{_GMAIL_ROOT}/gmail/v1/users/me/messages/{encoded_message}/attachments/{encoded_attachment}",
            token,
            max_bytes=encoded_limit,
            accept="application/json",
        )
        try:
            payload = json.loads(raw.decode("utf-8"))
            data = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(data, str) or not data:
                raise ValueError("missing data")
            padded = data + "=" * (-len(data) % 4)
            decoded = base64.urlsafe_b64decode(padded.encode())
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
            raise ProviderAttachmentFailure("provider_attachment_payload_invalid") from exc
        if len(decoded) > max_bytes:
            raise ProviderAttachmentFailure("provider_attachment_too_large")
        return decoded
    raise ProviderAttachmentFailure("provider_attachment_kind_not_supported")


def get_attachment_for_tenant(
    db: Session,
    *,
    organization_id: UUID,
    message_id: UUID,
    manifest_id: UUID,
) -> tuple[IngestedEmailMessage, EmailAttachmentManifest]:
    message = db.scalar(
        select(IngestedEmailMessage).where(
            IngestedEmailMessage.id == message_id,
            IngestedEmailMessage.organization_id == organization_id,
        )
    )
    if message is None:
        raise HTTPException(404, "Ingested email not found")
    manifest = db.scalar(
        select(EmailAttachmentManifest).where(
            EmailAttachmentManifest.id == manifest_id,
            EmailAttachmentManifest.message_id == message.id,
            EmailAttachmentManifest.organization_id == organization_id,
        )
    )
    if manifest is None:
        raise HTTPException(404, "Email attachment manifest not found")
    return message, manifest


def acquire_provider_attachment(
    db: Session,
    *,
    message: IngestedEmailMessage,
    manifest: EmailAttachmentManifest,
    user: User,
) -> dict:
    if message.status != EmailMessageStatus.LINKED or message.linked_claim_id is None:
        raise HTTPException(409, "Attachment acquisition requires a human-linked email claim context")
    if manifest.admission_status in {"expired_manifest", "expired_quarantine_purged"}:
        raise HTTPException(409, "Expired attachment staging cannot be acquired")
    if manifest.acquired_claim_id is not None and manifest.acquired_claim_id != message.linked_claim_id:
        raise HTTPException(409, "Attachment staging is bound to a different claim context")
    if manifest.admission_status in _TERMINAL_QUARANTINE_STATES and manifest.quarantine_key:
        return _response(manifest, replayed=True)
    if message.adapter_id is None:
        raise HTTPException(409, "Legacy connection-only email has no provider attachment acquisition authority")

    adapter = db.scalar(
        select(EmailProviderAdapter).where(
            EmailProviderAdapter.id == message.adapter_id,
            EmailProviderAdapter.organization_id == user.organization_id,
        )
    )
    if adapter is None:
        raise HTTPException(404, "Email provider adapter not found")
    connection = db.scalar(
        select(EmailIngestionConnection).where(
            EmailIngestionConnection.id == message.connection_id,
            EmailIngestionConnection.organization_id == user.organization_id,
        )
    )
    if connection is None:
        raise HTTPException(404, "Email ingestion connection not found")
    if adapter.status != "active" or connection.status != EmailConnectionStatus.ACTIVE:
        raise HTTPException(409, "Adapter and consented connection must both be active")
    if adapter.provider_kind not in {"microsoft_graph", "gmail_api"}:
        raise HTTPException(409, "This provider adapter has no attachment byte acquisition authority")
    permissions = set(adapter.permission_manifest)
    if not {"messages.read.allowed_folder", "attachments.metadata.read"}.issubset(permissions):
        raise HTTPException(409, "Attachment acquisition requires selected-folder and attachment-metadata read authority")
    if not settings.malware_scan_enabled:
        _mark_failure(
            db,
            manifest=manifest,
            user=user,
            provider_kind=adapter.provider_kind,
            code="malware_scanner_disabled",
        )
        raise HTTPException(503, "Provider attachment acquisition requires malware scanning")
    if manifest.file_size_bytes > settings.max_upload_bytes:
        _mark_failure(
            db,
            manifest=manifest,
            user=user,
            provider_kind=adapter.provider_kind,
            code="provider_attachment_too_large",
        )
        raise HTTPException(413, "Provider attachment exceeds the configured upload limit")

    original_filename = normalize_original_filename(manifest.filename)
    try:
        suffix = validate_upload(original_filename, manifest.mime_type)
    except HTTPException as exc:
        _mark_failure(
            db,
            manifest=manifest,
            user=user,
            provider_kind=adapter.provider_kind,
            code="provider_attachment_type_rejected",
        )
        raise HTTPException(exc.status_code, "Provider attachment type is not admissible for quarantine") from exc

    try:
        token = _resolve_credential(adapter.credential_reference)
        locator = _resolve_locator(adapter, token, message, manifest)
        payload = _fetch_attachment_bytes(adapter, token, message, locator)
    except (ProviderExecutionFailure, ProviderAttachmentFailure) as exc:
        code = exc.code
        _mark_failure(
            db,
            manifest=manifest,
            user=user,
            provider_kind=adapter.provider_kind,
            code=code,
        )
        http_status = 413 if code == "provider_attachment_too_large" else 502
        raise HTTPException(http_status, "Provider attachment acquisition failed") from exc

    if not payload:
        _mark_failure(
            db,
            manifest=manifest,
            user=user,
            provider_kind=adapter.provider_kind,
            code="provider_attachment_empty",
        )
        raise HTTPException(422, "Empty provider attachments are not accepted")
    if len(payload) > settings.max_upload_bytes:
        _mark_failure(
            db,
            manifest=manifest,
            user=user,
            provider_kind=adapter.provider_kind,
            code="provider_attachment_too_large",
        )
        raise HTTPException(413, "Provider attachment exceeds the configured upload limit")

    quarantine_key = (
        f"_provider_quarantine/{user.organization_id}/{message.linked_claim_id}/"
        f"{manifest.id}-{uuid4()}{suffix}"
    )
    storage = _storage()
    try:
        stored = storage.save_bytes(payload, quarantine_key)
    except OSError as exc:
        _mark_failure(
            db,
            manifest=manifest,
            user=user,
            provider_kind=adapter.provider_kind,
            code="provider_attachment_storage_error",
        )
        raise HTTPException(503, "Provider attachment quarantine storage failed") from exc

    try:
        validate_file_signature(storage, stored.storage_key, suffix)
    except HTTPException as exc:
        _mark_failure(
            db,
            manifest=manifest,
            user=user,
            provider_kind=adapter.provider_kind,
            code="provider_attachment_signature_rejected",
        )
        raise HTTPException(exc.status_code, "Provider attachment signature validation failed") from exc

    if manifest.provider_sha256 and stored.file_hash.lower() != manifest.provider_sha256.lower():
        storage.delete_physical(stored.storage_key)
        _mark_failure(
            db,
            manifest=manifest,
            user=user,
            provider_kind=adapter.provider_kind,
            code="provider_attachment_hash_mismatch",
        )
        raise HTTPException(409, "Provider attachment hash does not match staged metadata")

    now = datetime.now(UTC)
    manifest.provider_attachment_id = locator
    manifest.acquired_claim_id = message.linked_claim_id
    manifest.acquired_by_id = user.id
    manifest.quarantine_key = stored.storage_key
    manifest.acquired_file_hash = stored.file_hash
    manifest.acquired_file_size_bytes = stored.file_size_bytes
    manifest.acquired_at = now
    manifest.acquisition_failure_code = None

    try:
        scan_result = scan_file(
            storage.path_for(stored.storage_key),
            host=settings.clamav_host,
            port=settings.clamav_port,
            timeout_seconds=settings.clamav_timeout_seconds,
        )
    except MalwareScannerError:
        manifest.malware_scan_status = "scan_error"
        manifest.malware_scanned_at = now
        manifest.admission_status = "scan_error_quarantined"
        manifest.acquisition_failure_code = "malware_scan_error"
    else:
        manifest.malware_scanned_at = now
        if scan_result.verdict == MalwareScanVerdict.INFECTED:
            manifest.malware_scan_status = "infected"
            manifest.admission_status = "infected_quarantined"
        else:
            manifest.malware_scan_status = "clean"
            manifest.admission_status = "clean_pending_human_admission"

    write_audit_log(
        db,
        organization_id=manifest.organization_id,
        user_id=user.id,
        action="ACQUIRE_EMAIL_PROVIDER_ATTACHMENT_QUARANTINE",
        entity_type="email_attachment_manifest",
        entity_id=manifest.id,
        new_values={
            "provider_kind": adapter.provider_kind,
            "message_id": str(message.id),
            "claim_id": str(message.linked_claim_id),
            "admission_status": manifest.admission_status,
            "malware_scan_status": manifest.malware_scan_status,
            "file_size_bytes": stored.file_size_bytes,
        },
        details=(
            "Provider bytes acquired into quarantine-only staging after explicit human claim linkage. "
            "No Document, processing job or canonical Evidence record was created. Provider locator, "
            "filename, credential values, hashes, message content and attachment bytes are excluded from audit metadata."
        ),
    )
    db.commit()
    db.refresh(manifest)
    return _response(manifest, replayed=False)


def purge_provider_attachment_for_retention(manifest: EmailAttachmentManifest) -> None:
    if manifest.quarantine_key:
        _storage().delete_physical(manifest.quarantine_key)
    manifest.provider_attachment_id = None
    manifest.quarantine_key = None
    manifest.acquired_file_hash = None
    manifest.acquired_file_size_bytes = None
    manifest.malware_scan_status = None
    manifest.acquisition_failure_code = None
    manifest.admission_status = (
        "expired_quarantine_purged" if manifest.acquired_at is not None else "expired_manifest"
    )
