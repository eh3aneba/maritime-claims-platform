from __future__ import annotations

import json
import logging
import re
from time import perf_counter
from uuid import uuid4

from fastapi import Request, Response

REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
request_logger = logging.getLogger("mcri.request")


def _request_id(raw_value: str | None) -> str:
    """Return a safe correlation ID without reflecting arbitrary header content."""
    candidate = (raw_value or "").strip()
    if candidate and _REQUEST_ID_PATTERN.fullmatch(candidate):
        return candidate
    return uuid4().hex


def _event_payload(
    *,
    event: str,
    request_id: str,
    method: str,
    path: str,
    status_code: int,
    duration_ms: float,
) -> str:
    # Deliberately log only operational metadata. Claim content, request bodies,
    # authorization headers and evidence payloads must never be included here.
    return json.dumps(
        {
            "event": event,
            "request_id": request_id,
            "method": method,
            "path": path,
            "status_code": status_code,
            "duration_ms": round(duration_ms, 3),
        },
        separators=(",", ":"),
        sort_keys=True,
    )


async def request_observability_middleware(request: Request, call_next) -> Response:
    request_id = _request_id(request.headers.get(REQUEST_ID_HEADER))
    request.state.request_id = request_id
    started = perf_counter()

    try:
        response = await call_next(request)
    except Exception:
        duration_ms = (perf_counter() - started) * 1000
        request_logger.exception(
            _event_payload(
                event="http_request_failed",
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                status_code=500,
                duration_ms=duration_ms,
            )
        )
        raise

    duration_ms = (perf_counter() - started) * 1000
    response.headers[REQUEST_ID_HEADER] = request_id
    request_logger.info(
        _event_payload(
            event="http_request_completed",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
    )
    return response
