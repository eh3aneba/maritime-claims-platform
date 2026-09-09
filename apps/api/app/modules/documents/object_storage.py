from __future__ import annotations

import hashlib
import hmac
import re
import ssl
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen
from uuid import UUID


class ObjectStorageError(RuntimeError):
    """Sanitized S3-compatible storage failure.

    Error text must never include credentials, signed headers, raw response bodies,
    or full object URLs.
    """


class ObjectStorageConfigurationError(ObjectStorageError):
    pass


class ObjectStorageIntegrityError(ObjectStorageError):
    pass


class ObjectStorageNotFound(ObjectStorageError):
    pass


@dataclass(frozen=True)
class S3ObjectStoreConfig:
    endpoint_url: str
    region: str
    bucket: str
    access_key_id: str
    secret_access_key: str
    session_token: str = ""
    request_timeout_seconds: float = 10.0
    max_attempts: int = 3
    tls_verify: bool = True

    def validate(self, *, require_https: bool = False) -> None:
        parsed = urlparse(self.endpoint_url.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ObjectStorageConfigurationError(
                "S3 endpoint must be an absolute HTTP(S) URL"
            )
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ObjectStorageConfigurationError(
                "S3 endpoint must not contain credentials, query parameters, or fragments"
            )
        if parsed.path not in {"", "/"}:
            raise ObjectStorageConfigurationError(
                "S3 endpoint path prefixes are not supported by the bounded foundation client"
            )
        if require_https and parsed.scheme != "https":
            raise ObjectStorageConfigurationError(
                "S3 endpoint must use HTTPS in staging/production"
            )
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{1,61}[A-Za-z0-9]", self.bucket):
            raise ObjectStorageConfigurationError("S3 bucket name is invalid")
        if ".." in self.bucket or ".-" in self.bucket or "-." in self.bucket:
            raise ObjectStorageConfigurationError("S3 bucket name is invalid")
        if not re.fullmatch(r"[A-Za-z0-9-]{1,64}", self.region):
            raise ObjectStorageConfigurationError("S3 region is invalid")
        if not self.access_key_id.strip() or not self.secret_access_key:
            raise ObjectStorageConfigurationError(
                "S3 access key ID and secret access key are required"
            )
        if not 0.25 <= self.request_timeout_seconds <= 120.0:
            raise ObjectStorageConfigurationError(
                "S3 request timeout must be between 0.25 and 120 seconds"
            )
        if not 1 <= self.max_attempts <= 5:
            raise ObjectStorageConfigurationError("S3 max attempts must be between 1 and 5")


@dataclass(frozen=True)
class StoredObject:
    storage_key: str
    file_size_bytes: int
    file_hash: str
    etag: str | None = None


@dataclass(frozen=True)
class ObjectMetadata:
    storage_key: str
    file_size_bytes: int
    file_hash: str
    etag: str | None


@dataclass(frozen=True)
class S3FoundationHealth:
    status: str
    backend: str
    endpoint_origin: str
    bucket_fingerprint: str
    region: str


def make_managed_evidence_object_key(
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    suffix: str,
) -> str:
    normalized_suffix = suffix.lower().strip()
    if not re.fullmatch(r"\.[a-z0-9]{1,10}", normalized_suffix):
        raise ObjectStorageConfigurationError("Evidence object suffix is invalid")
    return (
        f"evidence/{organization_id}/{claim_id}/"
        f"{document_id}{normalized_suffix}"
    )


def validate_managed_evidence_object_key(
    storage_key: str,
    *,
    organization_id: UUID,
    claim_id: UUID,
) -> None:
    prefix = f"evidence/{organization_id}/{claim_id}/"
    if not storage_key.startswith(prefix):
        raise ObjectStorageConfigurationError(
            "Object key is outside the tenant/claim managed evidence prefix"
        )
    _validate_storage_key(storage_key)


def _validate_storage_key(storage_key: str) -> None:
    if not storage_key or len(storage_key.encode("utf-8")) > 1024:
        raise ObjectStorageConfigurationError("Object key is invalid")
    if storage_key.startswith("/") or storage_key.endswith("/"):
        raise ObjectStorageConfigurationError("Object key is invalid")
    segments = storage_key.split("/")
    if any(segment in {"", ".", ".."} for segment in segments):
        raise ObjectStorageConfigurationError("Object key is invalid")
    if any(ord(char) < 32 or ord(char) == 127 for char in storage_key):
        raise ObjectStorageConfigurationError("Object key contains control characters")


def _sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _hmac_sha256(key: bytes, value: str) -> bytes:
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).digest()


class S3CompatibleEvidenceStore:
    """Small, bounded S3-compatible foundation client.

    Phase 17.3-A intentionally exposes PUT/GET/HEAD only. There is no DELETE,
    COPY, lifecycle, migration, or active-document cutover method here.
    """

    def __init__(self, config: S3ObjectStoreConfig) -> None:
        config.validate()
        self._config = config
        parsed = urlparse(config.endpoint_url.strip())
        self._scheme = parsed.scheme
        self._host = parsed.netloc
        self._origin = f"{parsed.scheme}://{parsed.netloc}"
        self._ssl_context = None
        if self._scheme == "https" and not config.tls_verify:
            self._ssl_context = ssl._create_unverified_context()  # noqa: SLF001

    @property
    def sanitized_health_identity(self) -> S3FoundationHealth:
        return S3FoundationHealth(
            status="configured",
            backend="s3-compatible-foundation",
            endpoint_origin=self._origin,
            bucket_fingerprint=hashlib.sha256(
                self._config.bucket.encode("utf-8")
            ).hexdigest()[:16],
            region=self._config.region,
        )

    def _canonical_path(self, storage_key: str | None) -> str:
        bucket = quote(self._config.bucket, safe="-_.~")
        if storage_key is None:
            return f"/{bucket}"
        _validate_storage_key(storage_key)
        encoded_key = quote(storage_key, safe="/-_.~")
        return f"/{bucket}/{encoded_key}"

    def _signed_headers(
        self,
        *,
        method: str,
        canonical_path: str,
        payload_hash: str,
        extra_headers: Mapping[str, str] | None = None,
        now: datetime | None = None,
    ) -> dict[str, str]:
        timestamp = (now or datetime.now(UTC)).astimezone(UTC)
        amz_date = timestamp.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = timestamp.strftime("%Y%m%d")
        headers: dict[str, str] = {
            "host": self._host,
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amz_date,
        }
        if self._config.session_token:
            headers["x-amz-security-token"] = self._config.session_token
        if extra_headers:
            for name, value in extra_headers.items():
                normalized_name = name.strip().lower()
                if not normalized_name.startswith("x-amz-"):
                    raise ObjectStorageConfigurationError(
                        "Only bounded x-amz-* extra headers may be signed"
                    )
                headers[normalized_name] = " ".join(value.strip().split())

        signed_names = sorted(headers)
        canonical_headers = "".join(
            f"{name}:{headers[name]}\n" for name in signed_names
        )
        signed_headers = ";".join(signed_names)
        canonical_request = "\n".join(
            [
                method,
                canonical_path,
                "",
                canonical_headers,
                signed_headers,
                payload_hash,
            ]
        )
        scope = f"{date_stamp}/{self._config.region}/s3/aws4_request"
        string_to_sign = "\n".join(
            [
                "AWS4-HMAC-SHA256",
                amz_date,
                scope,
                hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
            ]
        )
        date_key = _hmac_sha256(
            ("AWS4" + self._config.secret_access_key).encode("utf-8"),
            date_stamp,
        )
        region_key = _hmac_sha256(date_key, self._config.region)
        service_key = _hmac_sha256(region_key, "s3")
        signing_key = _hmac_sha256(service_key, "aws4_request")
        signature = hmac.new(
            signing_key,
            string_to_sign.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        headers["authorization"] = (
            "AWS4-HMAC-SHA256 "
            f"Credential={self._config.access_key_id}/{scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )
        return headers

    def _request(
        self,
        *,
        method: str,
        storage_key: str | None,
        payload: bytes = b"",
        extra_headers: Mapping[str, str] | None = None,
    ) -> tuple[bytes, Mapping[str, str]]:
        canonical_path = self._canonical_path(storage_key)
        payload_hash = _sha256_hex(payload)
        url = f"{self._origin}{canonical_path}"
        retryable_statuses = {429, 500, 502, 503, 504}
        last_error: Exception | None = None

        for attempt in range(1, self._config.max_attempts + 1):
            headers = self._signed_headers(
                method=method,
                canonical_path=canonical_path,
                payload_hash=payload_hash,
                extra_headers=extra_headers,
            )
            request = Request(
                url,
                data=payload if method in {"PUT", "POST"} else None,
                headers=headers,
                method=method,
            )
            try:
                with urlopen(
                    request,
                    timeout=self._config.request_timeout_seconds,
                    context=self._ssl_context,
                ) as response:
                    body = b"" if method == "HEAD" else response.read()
                    return body, dict(response.headers.items())
            except HTTPError as exc:
                if exc.code == 404:
                    raise ObjectStorageNotFound("S3-compatible object was not found") from exc
                last_error = exc
                if exc.code not in retryable_statuses or attempt >= self._config.max_attempts:
                    raise ObjectStorageError(
                        f"S3-compatible storage request failed with HTTP {exc.code}"
                    ) from exc
            except (URLError, TimeoutError, OSError) as exc:
                last_error = exc
                if attempt >= self._config.max_attempts:
                    raise ObjectStorageError(
                        "S3-compatible storage request failed after bounded retries"
                    ) from exc
            time.sleep(min(0.1 * (2 ** (attempt - 1)), 0.8))

        raise ObjectStorageError("S3-compatible storage request failed") from last_error

    def put_bytes(
        self,
        payload: bytes,
        *,
        storage_key: str,
        expected_sha256: str | None = None,
    ) -> StoredObject:
        _validate_storage_key(storage_key)
        digest = _sha256_hex(payload)
        if expected_sha256 is not None and digest != expected_sha256.lower():
            raise ObjectStorageIntegrityError(
                "Payload hash does not match the expected evidence hash"
            )
        _body, headers = self._request(
            method="PUT",
            storage_key=storage_key,
            payload=payload,
            extra_headers={"x-amz-meta-mcri-sha256": digest},
        )
        etag = headers.get("ETag") or headers.get("Etag") or headers.get("etag")
        return StoredObject(
            storage_key=storage_key,
            file_size_bytes=len(payload),
            file_hash=digest,
            etag=None if etag is None else etag.strip('"'),
        )

    def get_bytes(
        self,
        *,
        storage_key: str,
        expected_sha256: str | None = None,
    ) -> bytes:
        _validate_storage_key(storage_key)
        payload, headers = self._request(method="GET", storage_key=storage_key)
        digest = _sha256_hex(payload)
        metadata_hash = (
            headers.get("x-amz-meta-mcri-sha256")
            or headers.get("X-Amz-Meta-Mcri-Sha256")
        )
        authoritative_hash = expected_sha256.lower() if expected_sha256 else metadata_hash
        if not authoritative_hash:
            raise ObjectStorageIntegrityError(
                "Remote object is missing MCRI integrity metadata"
            )
        if digest != authoritative_hash.lower():
            raise ObjectStorageIntegrityError(
                "Remote evidence bytes failed SHA-256 integrity verification"
            )
        return payload

    def head_object(self, *, storage_key: str) -> ObjectMetadata:
        _validate_storage_key(storage_key)
        _body, headers = self._request(method="HEAD", storage_key=storage_key)
        metadata_hash = (
            headers.get("x-amz-meta-mcri-sha256")
            or headers.get("X-Amz-Meta-Mcri-Sha256")
        )
        if not metadata_hash:
            raise ObjectStorageIntegrityError(
                "Remote object is missing MCRI integrity metadata"
            )
        length = headers.get("Content-Length") or headers.get("content-length")
        if length is None:
            raise ObjectStorageIntegrityError("Remote object size metadata is missing")
        try:
            file_size_bytes = int(length)
        except ValueError as exc:
            raise ObjectStorageIntegrityError(
                "Remote object size metadata is invalid"
            ) from exc
        etag = headers.get("ETag") or headers.get("Etag") or headers.get("etag")
        return ObjectMetadata(
            storage_key=storage_key,
            file_size_bytes=file_size_bytes,
            file_hash=metadata_hash.lower(),
            etag=None if etag is None else etag.strip('"'),
        )

    def probe_bucket(self) -> S3FoundationHealth:
        self._request(method="HEAD", storage_key=None)
        identity = self.sanitized_health_identity
        return S3FoundationHealth(
            status="ok",
            backend=identity.backend,
            endpoint_origin=identity.endpoint_origin,
            bucket_fingerprint=identity.bucket_fingerprint,
            region=identity.region,
        )
