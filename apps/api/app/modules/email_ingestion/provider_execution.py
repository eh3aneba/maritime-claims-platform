from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from email.utils import getaddresses, parsedate_to_datetime
from hashlib import sha256
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen
from uuid import UUID

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.service import write_audit_log
from app.modules.email_ingestion.models import (
    EmailAdapterRun,
    EmailConnectionStatus,
    EmailIngestionConnection,
    EmailProviderAdapter,
    IngestedEmailMessage,
)
from app.modules.email_ingestion.provider_credentials import (
    CredentialReferenceError,
    resolve_credential_reference,
)
from app.modules.email_ingestion.provider_source import _stage_email
from app.modules.email_ingestion.schemas import (
    AttachmentManifestInput,
    EmailProviderExecutionRequest,
    NormalizedEmailInput,
)
from app.modules.users.models import User

_ALLOWED_PROVIDER_HOSTS = {"graph.microsoft.com", "gmail.googleapis.com"}
_GRAPH_ROOT = "https://graph.microsoft.com"
_GMAIL_ROOT = "https://gmail.googleapis.com"
_MAX_PROVIDER_RESPONSE_BYTES = 2_000_000


class ProviderExecutionFailure(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _hash_checkpoint(value: str | None) -> str | None:
    return sha256(value.encode()).hexdigest() if value else None


def _resolve_credential(reference: str) -> str:
    try:
        return resolve_credential_reference(reference)
    except CredentialReferenceError as exc:
        raise ProviderExecutionFailure(exc.code) from exc


def _http_json(url: str, bearer_token: str, *, headers: dict[str, str] | None = None) -> dict[str, Any]:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in _ALLOWED_PROVIDER_HOSTS:
        raise ProviderExecutionFailure("provider_url_rejected")
    request_headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {bearer_token}",
        "User-Agent": "MCRI-Provider-Intake/1.0",
    }
    if headers:
        request_headers.update(headers)
    request = Request(url, headers=request_headers, method="GET")
    try:
        with urlopen(request, timeout=10) as response:  # nosec B310 - HTTPS host allowlist enforced above
            raw = response.read(_MAX_PROVIDER_RESPONSE_BYTES + 1)
            if len(raw) > _MAX_PROVIDER_RESPONSE_BYTES:
                raise ProviderExecutionFailure("provider_response_too_large")
    except HTTPError as exc:
        raise ProviderExecutionFailure("provider_http_error") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise ProviderExecutionFailure("provider_transport_error") from exc
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderExecutionFailure("provider_payload_invalid") from exc
    if not isinstance(value, dict):
        raise ProviderExecutionFailure("provider_payload_invalid")
    return value


def _iso_datetime(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ProviderExecutionFailure("provider_payload_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProviderExecutionFailure("provider_payload_invalid") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _graph_addresses(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    result: list[str] = []
    for value in values:
        if not isinstance(value, dict):
            continue
        email_address = value.get("emailAddress")
        address = email_address.get("address") if isinstance(email_address, dict) else None
        if isinstance(address, str) and address.strip():
            result.append(address.strip())
    return result[:50]


def _graph_checkpoint_url(adapter: EmailProviderAdapter, checkpoint: str | None) -> str:
    folder = quote(adapter.allowed_folder, safe="")
    expected_path = f"/v1.0/me/mailFolders/{folder}/messages/delta"
    if checkpoint:
        parsed = urlparse(checkpoint)
        if parsed.scheme != "https" or parsed.hostname != "graph.microsoft.com" or parsed.path != expected_path:
            raise HTTPException(409, "Microsoft Graph checkpoint is outside the configured folder scope")
        return checkpoint
    query = urlencode(
        {
            "$top": adapter.batch_limit,
            "$select": (
                "id,internetMessageId,subject,body,bodyPreview,receivedDateTime,"
                "from,toRecipients,ccRecipients,hasAttachments"
            ),
        }
    )
    return f"{_GRAPH_ROOT}{expected_path}?{query}"


def _graph_attachments(adapter: EmailProviderAdapter, token: str, message_id: str) -> list[AttachmentManifestInput]:
    if "attachments.metadata.read" not in set(adapter.permission_manifest):
        return []
    encoded_id = quote(message_id, safe="")
    query = urlencode({"$select": "id,name,contentType,size,isInline"})
    payload = _http_json(f"{_GRAPH_ROOT}/v1.0/me/messages/{encoded_id}/attachments?{query}", token)
    values = payload.get("value")
    if not isinstance(values, list):
        raise ProviderExecutionFailure("provider_payload_invalid")
    manifests: list[AttachmentManifestInput] = []
    for item in values[:25]:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        mime_type = item.get("contentType")
        size = item.get("size")
        if not isinstance(name, str) or not name.strip():
            continue
        manifests.append(
            AttachmentManifestInput(
                filename=name[:255],
                mime_type=(mime_type if isinstance(mime_type, str) and mime_type else "application/octet-stream")[:150],
                file_size_bytes=max(0, min(int(size or 0), 26_214_400)),
            )
        )
    return manifests


def _normalize_graph_message(
    connection: EmailIngestionConnection,
    adapter: EmailProviderAdapter,
    token: str,
    item: dict[str, Any],
) -> NormalizedEmailInput:
    message_id = item.get("id")
    if not isinstance(message_id, str) or not message_id:
        raise ProviderExecutionFailure("provider_payload_invalid")
    sender_values = _graph_addresses([item.get("from")])
    recipients = _graph_addresses(item.get("toRecipients")) or [connection.mailbox_address]
    body = item.get("body")
    if isinstance(body, dict) and body.get("contentType") == "text" and isinstance(body.get("content"), str):
        body_text = body["content"]
    else:
        body_text = item.get("bodyPreview") if isinstance(item.get("bodyPreview"), str) else ""
    attachments = _graph_attachments(adapter, token, message_id) if item.get("hasAttachments") else []
    try:
        return NormalizedEmailInput(
            provider_message_id=message_id[:240],
            internet_message_id=(item.get("internetMessageId")[:500] if isinstance(item.get("internetMessageId"), str) else None),
            sender=(sender_values[0] if sender_values else "unknown@graph.invalid")[:500],
            recipients=recipients,
            cc=_graph_addresses(item.get("ccRecipients")),
            subject=((item.get("subject") if isinstance(item.get("subject"), str) else "") or "(No subject)")[:500],
            body_text=body_text[:50_000],
            received_at=_iso_datetime(item.get("receivedDateTime")),
            attachments=attachments,
        )
    except ValidationError as exc:
        raise ProviderExecutionFailure("provider_payload_invalid") from exc


def _validate_graph_next(adapter: EmailProviderAdapter, checkpoint: Any) -> str | None:
    if checkpoint is None:
        return None
    if not isinstance(checkpoint, str) or len(checkpoint) > 4000:
        raise ProviderExecutionFailure("provider_payload_invalid")
    _graph_checkpoint_url(adapter, checkpoint)
    return checkpoint


def _fetch_graph_page(
    connection: EmailIngestionConnection,
    adapter: EmailProviderAdapter,
    token: str,
    checkpoint: str | None,
) -> tuple[list[NormalizedEmailInput], str | None]:
    payload = _http_json(
        _graph_checkpoint_url(adapter, checkpoint),
        token,
        headers={"Prefer": 'outlook.body-content-type="text"'},
    )
    values = payload.get("value")
    if not isinstance(values, list):
        raise ProviderExecutionFailure("provider_payload_invalid")
    messages = [
        _normalize_graph_message(connection, adapter, token, item)
        for item in values[: adapter.batch_limit]
        if isinstance(item, dict)
    ]
    next_checkpoint = payload.get("@odata.nextLink") or payload.get("@odata.deltaLink")
    return messages, _validate_graph_next(adapter, next_checkpoint)


def _gmail_addresses(value: str | None) -> list[str]:
    if not value:
        return []
    return [address.strip() for _, address in getaddresses([value]) if address.strip()][:50]


def _gmail_header(payload: dict[str, Any], name: str) -> str | None:
    headers = payload.get("headers")
    if not isinstance(headers, list):
        return None
    for item in headers:
        if isinstance(item, dict) and str(item.get("name", "")).lower() == name.lower():
            value = item.get("value")
            return value if isinstance(value, str) else None
    return None


def _decode_gmail_data(value: Any) -> str:
    if not isinstance(value, str) or not value:
        return ""
    try:
        padded = value + "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode(padded.encode()).decode("utf-8", errors="replace")
    except (ValueError, TypeError):
        return ""


def _gmail_walk_parts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    result = [payload]
    parts = payload.get("parts")
    if isinstance(parts, list):
        for part in parts:
            if isinstance(part, dict):
                result.extend(_gmail_walk_parts(part))
    return result


def _gmail_body(payload: dict[str, Any], snippet: Any) -> str:
    chunks: list[str] = []
    for part in _gmail_walk_parts(payload):
        if part.get("mimeType") != "text/plain" or part.get("filename"):
            continue
        body = part.get("body")
        if isinstance(body, dict):
            decoded = _decode_gmail_data(body.get("data"))
            if decoded:
                chunks.append(decoded)
    text = "\n".join(chunks).strip()
    if not text and isinstance(snippet, str):
        text = snippet
    return text[:50_000]


def _gmail_attachments(adapter: EmailProviderAdapter, payload: dict[str, Any]) -> list[AttachmentManifestInput]:
    if "attachments.metadata.read" not in set(adapter.permission_manifest):
        return []
    manifests: list[AttachmentManifestInput] = []
    for part in _gmail_walk_parts(payload):
        filename = part.get("filename")
        if not isinstance(filename, str) or not filename.strip():
            continue
        body = part.get("body")
        size = body.get("size") if isinstance(body, dict) else 0
        mime_type = part.get("mimeType")
        manifests.append(
            AttachmentManifestInput(
                filename=filename[:255],
                mime_type=(mime_type if isinstance(mime_type, str) and mime_type else "application/octet-stream")[:150],
                file_size_bytes=max(0, min(int(size or 0), 26_214_400)),
            )
        )
        if len(manifests) >= 25:
            break
    return manifests


def _gmail_received_at(item: dict[str, Any], payload: dict[str, Any]) -> datetime:
    internal_date = item.get("internalDate")
    try:
        if internal_date is not None:
            return datetime.fromtimestamp(int(internal_date) / 1000, tz=UTC)
    except (TypeError, ValueError, OverflowError):
        pass
    date_header = _gmail_header(payload, "Date")
    if date_header:
        try:
            parsed = parsedate_to_datetime(date_header)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except (TypeError, ValueError):
            pass
    raise ProviderExecutionFailure("provider_payload_invalid")


def _normalize_gmail_message(
    connection: EmailIngestionConnection,
    adapter: EmailProviderAdapter,
    item: dict[str, Any],
) -> NormalizedEmailInput:
    message_id = item.get("id")
    payload = item.get("payload")
    if not isinstance(message_id, str) or not message_id or not isinstance(payload, dict):
        raise ProviderExecutionFailure("provider_payload_invalid")
    from_header = _gmail_header(payload, "From")
    to_header = _gmail_header(payload, "To")
    cc_header = _gmail_header(payload, "Cc")
    subject = _gmail_header(payload, "Subject") or "(No subject)"
    internet_message_id = _gmail_header(payload, "Message-ID")
    try:
        return NormalizedEmailInput(
            provider_message_id=message_id[:240],
            internet_message_id=internet_message_id[:500] if internet_message_id else None,
            sender=(_gmail_addresses(from_header) or ["unknown@gmail.invalid"])[0][:500],
            recipients=_gmail_addresses(to_header) or [connection.mailbox_address],
            cc=_gmail_addresses(cc_header),
            subject=subject[:500],
            body_text=_gmail_body(payload, item.get("snippet")),
            received_at=_gmail_received_at(item, payload),
            attachments=_gmail_attachments(adapter, payload),
        )
    except ValidationError as exc:
        raise ProviderExecutionFailure("provider_payload_invalid") from exc


def _fetch_gmail_page(
    connection: EmailIngestionConnection,
    adapter: EmailProviderAdapter,
    token: str,
    checkpoint: str | None,
) -> tuple[list[NormalizedEmailInput], str | None]:
    query: dict[str, Any] = {
        "labelIds": adapter.allowed_folder,
        "maxResults": adapter.batch_limit,
        "includeSpamTrash": "false",
    }
    if checkpoint:
        query["pageToken"] = checkpoint
    listing = _http_json(f"{_GMAIL_ROOT}/gmail/v1/users/me/messages?{urlencode(query)}", token)
    refs = listing.get("messages", [])
    if not isinstance(refs, list):
        raise ProviderExecutionFailure("provider_payload_invalid")
    messages: list[NormalizedEmailInput] = []
    for ref in refs[: adapter.batch_limit]:
        if not isinstance(ref, dict) or not isinstance(ref.get("id"), str):
            raise ProviderExecutionFailure("provider_payload_invalid")
        message_id = quote(ref["id"], safe="")
        item = _http_json(f"{_GMAIL_ROOT}/gmail/v1/users/me/messages/{message_id}?format=full", token)
        messages.append(_normalize_gmail_message(connection, adapter, item))
    next_checkpoint = listing.get("nextPageToken")
    if next_checkpoint is not None and (not isinstance(next_checkpoint, str) or len(next_checkpoint) > 4000):
        raise ProviderExecutionFailure("provider_payload_invalid")
    return messages, next_checkpoint


def _existing_run(db: Session, adapter_id: UUID, idempotency_key: str) -> EmailAdapterRun | None:
    return db.scalar(
        select(EmailAdapterRun).where(
            EmailAdapterRun.adapter_id == adapter_id,
            EmailAdapterRun.idempotency_key == idempotency_key,
        )
    )


def _record_execution_run(
    db: Session,
    *,
    adapter: EmailProviderAdapter,
    user: User,
    payload: EmailProviderExecutionRequest,
    status: str,
    messages_seen: int,
    messages_ingested: int,
    next_checkpoint: str | None,
    failure_summary: str | None,
) -> EmailAdapterRun:
    now = datetime.now(UTC)
    checkpoint_hash = _hash_checkpoint(next_checkpoint)
    run = EmailAdapterRun(
        organization_id=adapter.organization_id,
        adapter_id=adapter.id,
        initiated_by_id=user.id,
        idempotency_key=payload.idempotency_key,
        trigger=payload.trigger,
        status=status,
        messages_seen=messages_seen,
        messages_ingested=messages_ingested,
        checkpoint_hash=checkpoint_hash if status == "succeeded" else None,
        failure_summary=failure_summary,
        started_at=now,
        finished_at=now,
    )
    db.add(run)
    db.flush()
    adapter.last_sync_at = now
    adapter.next_sync_at = now + timedelta(minutes=15)
    if status == "succeeded":
        adapter.checkpoint_hash = checkpoint_hash
    write_audit_log(
        db,
        organization_id=adapter.organization_id,
        user_id=user.id,
        action="EXECUTE_EMAIL_PROVIDER_PULL",
        entity_type="email_adapter_run",
        entity_id=run.id,
        new_values={
            "provider_kind": adapter.provider_kind,
            "status": status,
            "messages_seen": messages_seen,
            "messages_ingested": messages_ingested,
            "checkpoint_present": bool(next_checkpoint) if status == "succeeded" else False,
            "failure_summary": failure_summary,
        },
        details="Pull-only provider execution. Credential values, provider content and opaque checkpoint values are not persisted in audit metadata.",
    )
    db.commit()
    db.refresh(run)
    return run


def execute_provider_adapter(
    db: Session,
    adapter: EmailProviderAdapter,
    user: User,
    payload: EmailProviderExecutionRequest,
) -> dict[str, Any]:
    existing = _existing_run(db, adapter.id, payload.idempotency_key)
    if existing is not None:
        return {"run": existing, "next_checkpoint": None, "replayed": True}

    connection = db.scalar(
        select(EmailIngestionConnection).where(
            EmailIngestionConnection.id == adapter.connection_id,
            EmailIngestionConnection.organization_id == user.organization_id,
        )
    )
    if connection is None:
        raise HTTPException(404, "Email ingestion connection not found")
    if adapter.organization_id != user.organization_id:
        raise HTTPException(404, "Email provider adapter not found")
    if adapter.status != "active" or connection.status != EmailConnectionStatus.ACTIVE:
        raise HTTPException(409, "Adapter and consented connection must both be active")
    if adapter.provider_kind not in {"microsoft_graph", "gmail_api"}:
        raise HTTPException(409, "This adapter kind has no pull execution authority")
    if "messages.read.allowed_folder" not in set(adapter.permission_manifest):
        raise HTTPException(409, "Provider execution requires selected-folder message read permission")

    expected_checkpoint_hash = adapter.checkpoint_hash
    supplied_checkpoint_hash = _hash_checkpoint(payload.provider_checkpoint)
    if expected_checkpoint_hash:
        if supplied_checkpoint_hash != expected_checkpoint_hash:
            raise HTTPException(409, "Provider checkpoint does not match the last successful execution")
    elif payload.provider_checkpoint:
        raise HTTPException(409, "No provider checkpoint is expected for this adapter")

    try:
        token = _resolve_credential(adapter.credential_reference)
        if adapter.provider_kind == "microsoft_graph":
            messages, next_checkpoint = _fetch_graph_page(
                connection, adapter, token, payload.provider_checkpoint
            )
        else:
            messages, next_checkpoint = _fetch_gmail_page(
                connection, adapter, token, payload.provider_checkpoint
            )
    except ProviderExecutionFailure as exc:
        run = _record_execution_run(
            db,
            adapter=adapter,
            user=user,
            payload=payload,
            status="failed",
            messages_seen=0,
            messages_ingested=0,
            next_checkpoint=None,
            failure_summary=exc.code,
        )
        return {"run": run, "next_checkpoint": None, "replayed": False}

    messages_seen = len(messages)
    messages_ingested = 0
    try:
        for message in messages:
            already_exists = db.scalar(
                select(IngestedEmailMessage.id).where(
                    IngestedEmailMessage.connection_id == connection.id,
                    IngestedEmailMessage.provider_message_id == message.provider_message_id,
                )
            )
            _stage_email(db, connection=connection, adapter=adapter, payload=message)
            if already_exists is None:
                messages_ingested += 1
    except HTTPException:
        run = _record_execution_run(
            db,
            adapter=adapter,
            user=user,
            payload=payload,
            status="failed",
            messages_seen=messages_seen,
            messages_ingested=messages_ingested,
            next_checkpoint=None,
            failure_summary="provider_staging_rejected",
        )
        return {"run": run, "next_checkpoint": None, "replayed": False}

    run = _record_execution_run(
        db,
        adapter=adapter,
        user=user,
        payload=payload,
        status="succeeded",
        messages_seen=messages_seen,
        messages_ingested=messages_ingested,
        next_checkpoint=next_checkpoint,
        failure_summary=None,
    )
    return {"run": run, "next_checkpoint": next_checkpoint, "replayed": False}
