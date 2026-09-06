from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.email_ingestion.models import (
    EmailConnectionStatus,
    EmailIngestionConnection,
    EmailProviderAdapter,
    IngestedEmailMessage,
)
from app.modules.email_ingestion.provider_execution import (
    ProviderExecutionFailure,
    _existing_run,
    _hash_checkpoint,
    _normalize_gmail_message,
    _record_execution_run,
    _resolve_credential,
)
from app.modules.email_ingestion.provider_source import _stage_email
from app.modules.email_ingestion.schemas import EmailProviderExecutionRequest, NormalizedEmailInput
from app.modules.users.models import User

_GMAIL_ROOT = "https://gmail.googleapis.com"
_GMAIL_HOST = "gmail.googleapis.com"
_MAX_PROVIDER_RESPONSE_BYTES = 2_000_000
_CHECKPOINT_PREFIX = "mcri:gmail:v1:"
_MAX_PAGE_TOKEN_LENGTH = 3000
_MAX_CHECKPOINT_LENGTH = 4000


@dataclass(frozen=True)
class GmailCheckpoint:
    mode: str
    history_id: str
    page_token: str | None = None


def _valid_history_id(value: Any) -> str:
    if not isinstance(value, str) or not value.isdigit() or len(value) > 80:
        raise ProviderExecutionFailure("provider_payload_invalid")
    return value


def _valid_page_token(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > _MAX_PAGE_TOKEN_LENGTH:
        raise ProviderExecutionFailure("provider_payload_invalid")
    return value


def encode_gmail_checkpoint(mode: str, history_id: str, page_token: str | None = None) -> str:
    history_id = _valid_history_id(history_id)
    if mode not in {"bootstrap_page", "history", "history_page"}:
        raise ProviderExecutionFailure("provider_payload_invalid")
    payload: dict[str, str] = {"m": mode, "h": history_id}
    if mode in {"bootstrap_page", "history_page"}:
        payload["p"] = _valid_page_token(page_token)
    elif page_token is not None:
        raise ProviderExecutionFailure("provider_payload_invalid")
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).decode("ascii").rstrip("=")
    checkpoint = _CHECKPOINT_PREFIX + encoded
    if len(checkpoint) > _MAX_CHECKPOINT_LENGTH:
        raise ProviderExecutionFailure("provider_payload_invalid")
    return checkpoint


def decode_gmail_checkpoint(value: str) -> GmailCheckpoint:
    # Pre-15.6 Gmail page tokens are deliberately not interpreted as durable
    # incremental cursors. Operators must explicitly reset and bootstrap.
    if not isinstance(value, str) or not value.startswith(_CHECKPOINT_PREFIX):
        raise ProviderExecutionFailure("gmail_checkpoint_resync_required")
    encoded = value.removeprefix(_CHECKPOINT_PREFIX)
    try:
        padded = encoded + "=" * (-len(encoded) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
        raise ProviderExecutionFailure("gmail_checkpoint_resync_required") from exc
    if not isinstance(payload, dict) or set(payload) - {"m", "h", "p"}:
        raise ProviderExecutionFailure("gmail_checkpoint_resync_required")
    mode = payload.get("m")
    history_id = payload.get("h")
    page_token = payload.get("p")
    if mode not in {"bootstrap_page", "history", "history_page"}:
        raise ProviderExecutionFailure("gmail_checkpoint_resync_required")
    try:
        checked_history_id = _valid_history_id(history_id)
        if mode in {"bootstrap_page", "history_page"}:
            checked_page_token = _valid_page_token(page_token)
        else:
            if page_token is not None:
                raise ProviderExecutionFailure("provider_payload_invalid")
            checked_page_token = None
    except ProviderExecutionFailure as exc:
        raise ProviderExecutionFailure("gmail_checkpoint_resync_required") from exc
    return GmailCheckpoint(mode=mode, history_id=checked_history_id, page_token=checked_page_token)


def _gmail_http_json(
    url: str,
    bearer_token: str,
    *,
    map_history_404: bool = False,
) -> dict[str, Any]:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != _GMAIL_HOST:
        raise ProviderExecutionFailure("provider_url_rejected")
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {bearer_token}",
            "User-Agent": "MCRI-Gmail-History-Intake/1.0",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=10) as response:  # nosec B310 - HTTPS host allowlist enforced above
            raw = response.read(_MAX_PROVIDER_RESPONSE_BYTES + 1)
            if len(raw) > _MAX_PROVIDER_RESPONSE_BYTES:
                raise ProviderExecutionFailure("provider_response_too_large")
    except HTTPError as exc:
        if map_history_404 and exc.code == 404:
            raise ProviderExecutionFailure("gmail_history_resync_required") from exc
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


def _profile_history_id(token: str) -> str:
    profile = _gmail_http_json(f"{_GMAIL_ROOT}/gmail/v1/users/me/profile", token)
    return _valid_history_id(profile.get("historyId"))


def _fetch_full_message(
    connection: EmailIngestionConnection,
    adapter: EmailProviderAdapter,
    token: str,
    message_id: str,
) -> NormalizedEmailInput:
    encoded_id = quote(message_id, safe="")
    item = _gmail_http_json(
        f"{_GMAIL_ROOT}/gmail/v1/users/me/messages/{encoded_id}?format=full",
        token,
    )
    return _normalize_gmail_message(connection, adapter, item)


def _bootstrap_page(
    connection: EmailIngestionConnection,
    adapter: EmailProviderAdapter,
    token: str,
    *,
    baseline_history_id: str,
    page_token: str | None,
) -> tuple[list[NormalizedEmailInput], str]:
    query: dict[str, Any] = {
        "labelIds": adapter.allowed_folder,
        "maxResults": adapter.batch_limit,
        "includeSpamTrash": "false",
    }
    if page_token:
        query["pageToken"] = page_token
    listing = _gmail_http_json(
        f"{_GMAIL_ROOT}/gmail/v1/users/me/messages?{urlencode(query)}",
        token,
    )
    refs = listing.get("messages", [])
    if not isinstance(refs, list):
        raise ProviderExecutionFailure("provider_payload_invalid")
    if len(refs) > adapter.batch_limit:
        raise ProviderExecutionFailure("provider_payload_invalid")
    messages: list[NormalizedEmailInput] = []
    for ref in refs:
        if not isinstance(ref, dict) or not isinstance(ref.get("id"), str) or not ref["id"]:
            raise ProviderExecutionFailure("provider_payload_invalid")
        messages.append(_fetch_full_message(connection, adapter, token, ref["id"]))
    next_page = listing.get("nextPageToken")
    if next_page is not None:
        next_checkpoint = encode_gmail_checkpoint(
            "bootstrap_page",
            baseline_history_id,
            _valid_page_token(next_page),
        )
    else:
        next_checkpoint = encode_gmail_checkpoint("history", baseline_history_id)
    return messages, next_checkpoint


def _history_message_ids(payload: dict[str, Any], batch_limit: int) -> list[str]:
    history = payload.get("history", [])
    if not isinstance(history, list):
        raise ProviderExecutionFailure("provider_payload_invalid")
    ids: list[str] = []
    seen: set[str] = set()
    for record in history:
        if not isinstance(record, dict):
            raise ProviderExecutionFailure("provider_payload_invalid")
        added = record.get("messagesAdded", [])
        if not isinstance(added, list):
            raise ProviderExecutionFailure("provider_payload_invalid")
        for entry in added:
            message = entry.get("message") if isinstance(entry, dict) else None
            message_id = message.get("id") if isinstance(message, dict) else None
            if not isinstance(message_id, str) or not message_id:
                raise ProviderExecutionFailure("provider_payload_invalid")
            if message_id not in seen:
                seen.add(message_id)
                ids.append(message_id)
                if len(ids) > batch_limit:
                    raise ProviderExecutionFailure("gmail_history_batch_overflow")
    return ids


def _history_page(
    connection: EmailIngestionConnection,
    adapter: EmailProviderAdapter,
    token: str,
    *,
    start_history_id: str,
    page_token: str | None,
) -> tuple[list[NormalizedEmailInput], str]:
    query: dict[str, Any] = {
        "startHistoryId": start_history_id,
        "labelId": adapter.allowed_folder,
        "historyTypes": "messageAdded",
        "maxResults": adapter.batch_limit,
    }
    if page_token:
        query["pageToken"] = page_token
    payload = _gmail_http_json(
        f"{_GMAIL_ROOT}/gmail/v1/users/me/history?{urlencode(query)}",
        token,
        map_history_404=True,
    )
    ids = _history_message_ids(payload, adapter.batch_limit)
    messages = [_fetch_full_message(connection, adapter, token, message_id) for message_id in ids]
    next_page = payload.get("nextPageToken")
    if next_page is not None:
        next_checkpoint = encode_gmail_checkpoint(
            "history_page",
            start_history_id,
            _valid_page_token(next_page),
        )
    else:
        next_checkpoint = encode_gmail_checkpoint(
            "history",
            _valid_history_id(payload.get("historyId")),
        )
    return messages, next_checkpoint


def fetch_gmail_provider_page(
    connection: EmailIngestionConnection,
    adapter: EmailProviderAdapter,
    token: str,
    checkpoint: str | None,
) -> tuple[list[NormalizedEmailInput], str]:
    if checkpoint is None:
        baseline = _profile_history_id(token)
        return _bootstrap_page(
            connection,
            adapter,
            token,
            baseline_history_id=baseline,
            page_token=None,
        )

    parsed = decode_gmail_checkpoint(checkpoint)
    if parsed.mode == "bootstrap_page":
        return _bootstrap_page(
            connection,
            adapter,
            token,
            baseline_history_id=parsed.history_id,
            page_token=parsed.page_token,
        )
    if parsed.mode == "history":
        return _history_page(
            connection,
            adapter,
            token,
            start_history_id=parsed.history_id,
            page_token=None,
        )
    return _history_page(
        connection,
        adapter,
        token,
        start_history_id=parsed.history_id,
        page_token=parsed.page_token,
    )


def execute_gmail_history_adapter(
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
    if adapter.provider_kind != "gmail_api":
        raise HTTPException(409, "This execution path is Gmail-only")
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
        messages, next_checkpoint = fetch_gmail_provider_page(
            connection,
            adapter,
            token,
            payload.provider_checkpoint,
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
