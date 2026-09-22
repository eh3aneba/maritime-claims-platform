from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from ipaddress import ip_address
from urllib.parse import quote, urlencode, urlparse

import httpx
import jwt

from app.modules.external_document_sources.change_detection_service import (
    ExactItemMetadataResult,
    register_external_document_source_change_detection_adapter,
)
from app.modules.external_document_sources.credential_reference_health_service import (
    CredentialReferenceHealthProbeResult,
    CredentialReferenceLocator,
    register_external_document_source_credential_reference_health_resolver,
)
from app.modules.external_document_sources.credential_resolution_execution_service import (
    CredentialReferenceResolutionResult,
    register_external_document_source_credential_resolution_resolver,
)
from app.modules.external_document_sources.provider_client_health_service import (
    ProviderClientHealthResult,
    register_external_document_source_provider_client_health_adapter,
)
from app.modules.external_document_sources.remote_file_content_read_service import (
    RemoteFileContentReadResult,
    register_external_document_source_remote_file_content_read_adapter,
)
from app.modules.external_document_sources.remote_metadata_listing_service import (
    RemoteMetadataItemProjection,
    RemoteMetadataListResult,
    register_external_document_source_remote_metadata_list_adapter,
)
from app.modules.external_document_sources.token_acquisition_execution_service import (
    TokenAcquisitionResult,
    register_external_document_source_token_acquirer,
)


_MAX_SECRET_BYTES = 65536
_AZURE_VAULT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{1,22}[A-Za-z0-9]$")
_SAFE_GCP_PROJECT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,126}[A-Za-z0-9]$|^[A-Za-z0-9]$")
_SAFE_TENANT_DOMAIN = re.compile(r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_SHAREPOINT_REDIRECT_SUFFIXES = (
    ".sharepoint.com",
    ".sharepoint-df.com",
    ".1drv.com",
    ".onedrive.com",
)


class _RuntimeFailure(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class _ProviderToken:
    value: str
    expires_in: int | None


class LiveExternalEvidenceRuntime:
    """Transient production runtime.

    Secret material, OAuth assertions, access tokens, response bodies and provider
    clients exist only inside a call to this object. Public adapter return values
    are the bounded non-secret dataclasses already defined by phases F-M.
    """

    def __init__(self, *, transport: httpx.BaseTransport | None = None):
        self._transport = transport

    def _client(self, timeout_seconds: float = 10.0) -> httpx.Client:
        return httpx.Client(
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=False,
            trust_env=False,
            transport=self._transport,
        )

    @staticmethod
    def _json(response: httpx.Response, *, max_bytes: int) -> dict:
        body = response.content
        if len(body) > max_bytes:
            raise _RuntimeFailure("oversized_response")
        try:
            payload = json.loads(body)
        except (TypeError, ValueError, UnicodeDecodeError):
            raise _RuntimeFailure("malformed_response") from None
        if not isinstance(payload, dict):
            raise _RuntimeFailure("malformed_response")
        return payload

    @staticmethod
    def _status_failure(status: int, *, allow_not_found: bool = False) -> str:
        if status == 401:
            return "unauthorized"
        if status == 403:
            return "permission_denied"
        if status == 404 and allow_not_found:
            return "not_found"
        if status in {408, 504}:
            return "timeout"
        if status == 429 or status >= 500:
            return "endpoint_unavailable"
        return "provider_rejected"

    @staticmethod
    def _secret_status_failure(status: int) -> str:
        if status == 404:
            return "reference_not_found"
        if status in {401, 403}:
            return "permission_denied"
        if status == 429 or status >= 500:
            return "backend_unavailable"
        return "reference_unresolved"

    @staticmethod
    def _latency_class(started: float) -> str:
        elapsed = max(0.0, time.monotonic() - started)
        if elapsed < 0.5:
            return "fast"
        if elapsed < 2.0:
            return "normal"
        return "slow"

    @staticmethod
    def _is_local_identity_endpoint(url: str) -> bool:
        parsed = urlparse(url)
        if parsed.scheme != "http" or not parsed.hostname or parsed.username or parsed.password:
            return False
        host = parsed.hostname
        if host == "metadata.google.internal":
            return True
        try:
            address = ip_address(host)
        except ValueError:
            return False
        return address.is_loopback or address.is_link_local

    def _azure_management_token(self) -> str:
        injected = os.getenv("AZURE_KEY_VAULT_ACCESS_TOKEN", "").strip()
        if injected:
            return injected

        endpoint = os.getenv("IDENTITY_ENDPOINT", "").strip()
        identity_header = os.getenv("IDENTITY_HEADER", "").strip()
        if endpoint:
            if not identity_header or not self._is_local_identity_endpoint(endpoint):
                raise _RuntimeFailure("backend_unavailable")
            headers = {"X-IDENTITY-HEADER": identity_header, "Metadata": "true"}
            params = {"api-version": "2019-08-01", "resource": "https://vault.azure.net"}
            token_url = endpoint
        else:
            token_url = "http://169.254.169.254/metadata/identity/oauth2/token"
            headers = {"Metadata": "true"}
            params = {"api-version": "2018-02-01", "resource": "https://vault.azure.net"}

        try:
            with self._client(3.0) as client:
                response = client.get(token_url, headers=headers, params=params)
        except httpx.TimeoutException:
            raise _RuntimeFailure("backend_unavailable") from None
        except httpx.HTTPError:
            raise _RuntimeFailure("backend_unavailable") from None
        if response.status_code != 200:
            raise _RuntimeFailure("backend_unavailable")
        payload = self._json(response, max_bytes=32768)
        token = payload.get("access_token")
        if not isinstance(token, str) or not token.strip():
            raise _RuntimeFailure("backend_unavailable")
        return token.strip()

    def _gcp_management_token(self) -> str:
        injected = os.getenv("GOOGLE_CLOUD_ACCESS_TOKEN", "").strip()
        if injected:
            return injected
        token_url = (
            "http://metadata.google.internal/computeMetadata/v1/instance/"
            "service-accounts/default/token"
        )
        try:
            with self._client(3.0) as client:
                response = client.get(token_url, headers={"Metadata-Flavor": "Google"})
        except httpx.TimeoutException:
            raise _RuntimeFailure("backend_unavailable") from None
        except httpx.HTTPError:
            raise _RuntimeFailure("backend_unavailable") from None
        if response.status_code != 200:
            raise _RuntimeFailure("backend_unavailable")
        payload = self._json(response, max_bytes=32768)
        token = payload.get("access_token")
        if not isinstance(token, str) or not token.strip():
            raise _RuntimeFailure("backend_unavailable")
        return token.strip()

    def load_secret(self, locator: CredentialReferenceLocator) -> str:
        if locator.backend == "azure_key_vault":
            return self._load_azure_secret(locator)
        if locator.backend == "gcp_secret_manager":
            return self._load_gcp_secret(locator)
        raise _RuntimeFailure("reference_unresolved")

    def _load_azure_secret(self, locator: CredentialReferenceLocator) -> str:
        if not _AZURE_VAULT_NAME.fullmatch(locator.namespace):
            raise _RuntimeFailure("reference_unresolved")
        version_segment = f"/{quote(locator.version, safe='')}" if locator.version else ""
        url = (
            f"https://{locator.namespace}.vault.azure.net/secrets/"
            f"{quote(locator.name, safe='')}{version_segment}?api-version=7.4"
        )
        try:
            token = self._azure_management_token()
            with self._client(8.0) as client:
                response = client.get(url, headers={"Authorization": f"Bearer {token}"})
        except _RuntimeFailure:
            raise
        except httpx.TimeoutException:
            raise _RuntimeFailure("backend_unavailable") from None
        except httpx.HTTPError:
            raise _RuntimeFailure("backend_unavailable") from None
        finally:
            token = None
        if response.status_code != 200:
            raise _RuntimeFailure(self._secret_status_failure(response.status_code))
        payload = self._json(response, max_bytes=_MAX_SECRET_BYTES)
        value = payload.get("value")
        if not isinstance(value, str) or not value or len(value.encode("utf-8")) > _MAX_SECRET_BYTES:
            raise _RuntimeFailure("reference_unresolved")
        return value

    def _load_gcp_secret(self, locator: CredentialReferenceLocator) -> str:
        if not _SAFE_GCP_PROJECT.fullmatch(locator.namespace):
            raise _RuntimeFailure("reference_unresolved")
        version = locator.version or "latest"
        url = (
            "https://secretmanager.googleapis.com/v1/projects/"
            f"{quote(locator.namespace, safe='')}/secrets/{quote(locator.name, safe='')}"
            f"/versions/{quote(version, safe='')}:access"
        )
        try:
            token = self._gcp_management_token()
            with self._client(8.0) as client:
                response = client.get(url, headers={"Authorization": f"Bearer {token}"})
        except _RuntimeFailure:
            raise
        except httpx.TimeoutException:
            raise _RuntimeFailure("backend_unavailable") from None
        except httpx.HTTPError:
            raise _RuntimeFailure("backend_unavailable") from None
        finally:
            token = None
        if response.status_code != 200:
            raise _RuntimeFailure(self._secret_status_failure(response.status_code))
        payload = self._json(response, max_bytes=_MAX_SECRET_BYTES)
        encoded = (payload.get("payload") or {}).get("data")
        if not isinstance(encoded, str) or not encoded:
            raise _RuntimeFailure("reference_unresolved")
        import base64

        try:
            raw = base64.b64decode(encoded, validate=True)
            value = raw.decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            raise _RuntimeFailure("reference_unresolved") from None
        if not value or len(raw) > _MAX_SECRET_BYTES:
            raise _RuntimeFailure("reference_unresolved")
        return value

    @staticmethod
    def _credential_object(secret: str) -> dict:
        try:
            value = json.loads(secret)
        except (TypeError, ValueError):
            raise _RuntimeFailure("reference_unresolved") from None
        if not isinstance(value, dict):
            raise _RuntimeFailure("reference_unresolved")
        return value

    def provider_token(self, locator: CredentialReferenceLocator, policy) -> _ProviderToken:
        secret = self.load_secret(locator)
        credentials = self._credential_object(secret)
        secret = ""
        try:
            if policy.provider_kind == "sharepoint":
                result = self._sharepoint_token(credentials, policy)
            elif policy.provider_kind == "google_drive":
                result = self._google_token(credentials, policy)
            else:
                raise _RuntimeFailure("provider_rejected")
        finally:
            credentials.clear()
        return result

    @staticmethod
    def _token_limits(policy) -> tuple[float, int]:
        timeout = getattr(policy, "total_timeout_seconds", 8.0)
        max_bytes = getattr(policy, "max_response_bytes", 65536)
        if not isinstance(timeout, (int, float)) or timeout <= 0:
            timeout = 8.0
        if not isinstance(max_bytes, int) or max_bytes <= 0:
            max_bytes = 65536
        return float(timeout), min(max_bytes, 65536)

    def _sharepoint_token(self, credentials: dict, policy) -> _ProviderToken:
        client_id = credentials.get("client_id")
        client_secret = credentials.get("client_secret")
        tenant_domain = credentials.get("tenant_domain")
        if not isinstance(client_id, str) or not client_id.strip():
            raise _RuntimeFailure("invalid_client")
        if not isinstance(client_secret, str) or not client_secret:
            raise _RuntimeFailure("invalid_client")
        if (
            not isinstance(tenant_domain, str)
            or not _SAFE_TENANT_DOMAIN.fullmatch(tenant_domain.strip().lower())
        ):
            raise _RuntimeFailure("invalid_client")

        tenant = tenant_domain.strip().lower()
        governed_hint = getattr(policy, "tenant_hint", None)
        if isinstance(governed_hint, str) and governed_hint and governed_hint.strip().lower() != tenant:
            raise _RuntimeFailure("invalid_client")

        governed_endpoint = getattr(policy, "token_endpoint_url", None)
        derived_endpoint = (
            "https://login.microsoftonline.com/"
            f"{quote(tenant, safe='')}/oauth2/v2.0/token"
        )
        if governed_endpoint is not None and governed_endpoint != derived_endpoint:
            raise _RuntimeFailure("invalid_client")
        endpoint = governed_endpoint or derived_endpoint
        timeout, max_bytes = self._token_limits(policy)
        form = {
            "client_id": client_id.strip(),
            "client_secret": client_secret,
            "grant_type": "client_credentials",
            "scope": "https://graph.microsoft.com/.default",
        }
        return self._post_token(endpoint, timeout, max_bytes, form)

    def _google_token(self, credentials: dict, policy) -> _ProviderToken:
        client_email = credentials.get("client_email")
        private_key = credentials.get("private_key")
        private_key_id = credentials.get("private_key_id")
        if not isinstance(client_email, str) or not client_email.strip():
            raise _RuntimeFailure("invalid_client")
        if not isinstance(private_key, str) or "PRIVATE KEY" not in private_key:
            raise _RuntimeFailure("invalid_client")
        endpoint = getattr(policy, "token_endpoint_url", None) or "https://oauth2.googleapis.com/token"
        if endpoint != "https://oauth2.googleapis.com/token":
            raise _RuntimeFailure("invalid_client")
        timeout, max_bytes = self._token_limits(policy)
        now = int(time.time())
        claims = {
            "iss": client_email.strip(),
            "scope": "https://www.googleapis.com/auth/drive.readonly",
            "aud": endpoint,
            "iat": now,
            "exp": now + 3300,
        }
        headers = {"kid": private_key_id} if isinstance(private_key_id, str) and private_key_id else None
        try:
            assertion = jwt.encode(claims, private_key, algorithm="RS256", headers=headers)
        except Exception:
            raise _RuntimeFailure("invalid_client") from None
        private_key = ""
        form = {
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": assertion,
        }
        try:
            return self._post_token(endpoint, timeout, max_bytes, form)
        finally:
            assertion = ""

    def _post_token(
        self,
        endpoint: str,
        timeout_seconds: float,
        max_response_bytes: int,
        form: dict[str, str],
    ) -> _ProviderToken:
        try:
            with self._client(timeout_seconds) as client:
                response = client.post(
                    endpoint,
                    data=form,
                    headers={"Accept": "application/json"},
                )
        except httpx.TimeoutException:
            raise _RuntimeFailure("timeout") from None
        except httpx.HTTPError:
            raise _RuntimeFailure("endpoint_unavailable") from None
        if len(response.content) > max_response_bytes:
            raise _RuntimeFailure("oversized_response")
        if response.status_code != 200:
            code = "provider_rejected"
            try:
                error = response.json().get("error")
            except Exception:
                error = None
            allowed = {"invalid_client", "invalid_grant", "unauthorized_client", "invalid_scope"}
            if isinstance(error, str) and error in allowed:
                code = error
            elif response.status_code == 403:
                code = "permission_denied"
            elif response.status_code in {408, 504}:
                code = "timeout"
            elif response.status_code == 429 or response.status_code >= 500:
                code = "endpoint_unavailable"
            raise _RuntimeFailure(code)
        payload = self._json(response, max_bytes=max_response_bytes)
        token = payload.get("access_token")
        expires = payload.get("expires_in")
        if not isinstance(token, str) or not token:
            raise _RuntimeFailure("malformed_response")
        if not isinstance(expires, int):
            try:
                expires = int(expires)
            except (TypeError, ValueError):
                expires = None
        return _ProviderToken(value=token, expires_in=expires)

    def provider_get(
        self,
        locator: CredentialReferenceLocator,
        policy,
        url: str,
        *,
        max_bytes: int,
        allow_not_found: bool = False,
    ) -> tuple[dict, str]:
        token = self.provider_token(locator, policy)
        started = time.monotonic()
        try:
            with self._client(policy.total_timeout_seconds) as client:
                response = client.get(
                    url,
                    headers={"Authorization": f"Bearer {token.value}", "Accept": "application/json"},
                )
        except httpx.TimeoutException:
            raise _RuntimeFailure("timeout") from None
        except httpx.HTTPError:
            raise _RuntimeFailure("endpoint_unavailable") from None
        finally:
            token = None
        if response.status_code != 200:
            raise _RuntimeFailure(
                self._status_failure(
                    response.status_code,
                    allow_not_found=allow_not_found,
                )
            )
        return self._json(response, max_bytes=max_bytes), self._latency_class(started)

    @staticmethod
    def _version_hash(provider: str, item: dict) -> str | None:
        if provider == "sharepoint":
            raw = item.get("eTag")
        else:
            version = item.get("version")
            if version is not None:
                raw = f"version:{version}"
            else:
                md5 = item.get("md5Checksum") or ""
                modified = item.get("modifiedTime") or ""
                raw = f"md5:{md5}|modified:{modified}" if md5 or modified else None
        if not isinstance(raw, str) or not raw:
            return None
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _parse_datetime(value) -> datetime | None:
        if not isinstance(value, str) or not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise _RuntimeFailure("malformed_response") from None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _project_metadata_item(
        self,
        provider_kind: str,
        raw: dict,
    ) -> RemoteMetadataItemProjection:
        if provider_kind == "sharepoint":
            provider_item_id = raw.get("id")
            display_name = raw.get("name")
            folder = raw.get("folder")
            file_info = raw.get("file")
            item_kind = "folder" if isinstance(folder, dict) else "file"
            mime = file_info.get("mimeType") if isinstance(file_info, dict) else None
            parent = raw.get("parentReference")
            parent_id = parent.get("id") if isinstance(parent, dict) else None
            byte_size = raw.get("size")
            modified = raw.get("lastModifiedDateTime")
        else:
            provider_item_id = raw.get("id")
            display_name = raw.get("name")
            mime = raw.get("mimeType")
            item_kind = (
                "folder"
                if mime == "application/vnd.google-apps.folder"
                else "file"
            )
            parents = raw.get("parents")
            parent_id = parents[0] if isinstance(parents, list) and parents else None
            byte_size = raw.get("size")
            modified = raw.get("modifiedTime")

        if not isinstance(provider_item_id, str) or not provider_item_id:
            raise _RuntimeFailure("malformed_response")
        if not isinstance(display_name, str) or not display_name:
            raise _RuntimeFailure("malformed_response")
        if byte_size is not None:
            try:
                byte_size = int(byte_size)
            except (TypeError, ValueError):
                raise _RuntimeFailure("malformed_response") from None

        return RemoteMetadataItemProjection(
            provider_item_id=provider_item_id,
            item_kind=item_kind,
            display_name=display_name,
            parent_item_id=parent_id if isinstance(parent_id, str) else None,
            mime_type_class=mime if isinstance(mime, str) else None,
            byte_size=byte_size,
            modified_at=self._parse_datetime(modified),
            version_token_hash=self._version_hash(provider_kind, raw),
        )

    def list_metadata(
        self,
        locator: CredentialReferenceLocator,
        policy,
    ) -> RemoteMetadataListResult:
        payload, _latency = self.provider_get(
            locator,
            policy,
            policy.listing_endpoint_url,
            max_bytes=policy.max_response_bytes,
        )
        if policy.provider_kind == "sharepoint":
            raw_items = payload.get("value")
            next_token = payload.get("@odata.nextLink")
        else:
            raw_items = payload.get("files")
            next_token = payload.get("nextPageToken")
        if not isinstance(raw_items, list):
            raise _RuntimeFailure("malformed_response")
        if len(raw_items) > policy.max_items:
            raise _RuntimeFailure("too_many_items")

        items: list[RemoteMetadataItemProjection] = []
        for raw in raw_items:
            if not isinstance(raw, dict):
                raise _RuntimeFailure("malformed_response")
            items.append(self._project_metadata_item(policy.provider_kind, raw))
        return RemoteMetadataListResult(
            listed=True,
            items=tuple(items),
            truncated=bool(next_token),
            page_count=1,
        )

    def read_exact_metadata(
        self,
        locator: CredentialReferenceLocator,
        policy,
    ) -> ExactItemMetadataResult:
        try:
            payload, _latency = self.provider_get(
                locator,
                policy,
                policy.metadata_endpoint_url,
                max_bytes=policy.max_response_bytes,
                allow_not_found=True,
            )
        except _RuntimeFailure as exc:
            if exc.code == "not_found":
                return ExactItemMetadataResult(
                    found=False,
                    item=None,
                    failure_code="not_found",
                )
            raise
        return ExactItemMetadataResult(
            found=True,
            item=self._project_metadata_item(policy.provider_kind, payload),
        )

    def _exact_metadata(self, locator: CredentialReferenceLocator, policy) -> dict:
        parsed = urlparse(policy.content_endpoint_url)
        if policy.provider_kind == "sharepoint":
            if not parsed.path.endswith("/content"):
                raise _RuntimeFailure("provider_rejected")
            path = parsed.path[: -len("/content")]
            url = f"{policy.provider_origin}{path}?{urlencode({'$select': 'id,eTag,size,file'})}"
        else:
            path = parsed.path
            query = urlencode(
                {
                    "fields": "id,mimeType,size,version,modifiedTime,md5Checksum",
                    "supportsAllDrives": "true",
                }
            )
            url = f"{policy.provider_origin}{path}?{query}"
        payload, _ = self.provider_get(
            locator,
            policy,
            url,
            max_bytes=65536,
            allow_not_found=True,
        )
        return payload

    @staticmethod
    def _safe_sharepoint_redirect(location: str) -> bool:
        parsed = urlparse(location)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            return False
        host = parsed.hostname.lower()
        return any(host.endswith(suffix) for suffix in _SHAREPOINT_REDIRECT_SUFFIXES)

    def _download(self, locator: CredentialReferenceLocator, policy) -> bytes:
        token = self.provider_token(locator, policy)
        headers = {"Authorization": f"Bearer {token.value}"}
        url = policy.content_endpoint_url
        try:
            with self._client(policy.total_timeout_seconds) as client:
                with client.stream("GET", url, headers=headers) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if (
                            policy.max_redirects != 1
                            or not isinstance(location, str)
                            or not self._safe_sharepoint_redirect(location)
                        ):
                            raise _RuntimeFailure("provider_rejected")
                        redirect = location
                    else:
                        redirect = None
                        if response.status_code != 200:
                            raise _RuntimeFailure(
                                self._status_failure(response.status_code, allow_not_found=True)
                            )
                        length = response.headers.get("content-length")
                        if length:
                            try:
                                if int(length) > policy.max_content_bytes:
                                    raise _RuntimeFailure("oversized_response")
                            except ValueError:
                                raise _RuntimeFailure("malformed_response") from None
                        chunks: list[bytes] = []
                        total = 0
                        for chunk in response.iter_bytes(policy.max_chunk_bytes):
                            total += len(chunk)
                            if total > policy.max_content_bytes:
                                raise _RuntimeFailure("oversized_response")
                            chunks.append(chunk)
                        return b"".join(chunks)

                if redirect is None:
                    raise _RuntimeFailure("provider_rejected")
                with client.stream("GET", redirect) as response:
                    if response.status_code != 200:
                        raise _RuntimeFailure(
                            self._status_failure(response.status_code, allow_not_found=True)
                        )
                    length = response.headers.get("content-length")
                    if length:
                        try:
                            if int(length) > policy.max_content_bytes:
                                raise _RuntimeFailure("oversized_response")
                        except ValueError:
                            raise _RuntimeFailure("malformed_response") from None
                    chunks = []
                    total = 0
                    for chunk in response.iter_bytes(policy.max_chunk_bytes):
                        total += len(chunk)
                        if total > policy.max_content_bytes:
                            raise _RuntimeFailure("oversized_response")
                        chunks.append(chunk)
                    return b"".join(chunks)
        except _RuntimeFailure:
            raise
        except httpx.TimeoutException:
            raise _RuntimeFailure("timeout") from None
        except httpx.HTTPError:
            raise _RuntimeFailure("endpoint_unavailable") from None
        finally:
            token = None

    def read_content(self, locator: CredentialReferenceLocator, policy) -> RemoteFileContentReadResult:
        started = time.monotonic()
        metadata = self._exact_metadata(locator, policy)
        version_hash = self._version_hash(policy.provider_kind, metadata)
        if policy.provider_kind == "sharepoint":
            file_info = metadata.get("file")
            media = file_info.get("mimeType") if isinstance(file_info, dict) else None
        else:
            media = metadata.get("mimeType")
        content = self._download(locator, policy)
        return RemoteFileContentReadResult(
            read=True,
            content=content,
            media_type_class=media if isinstance(media, str) else None,
            observed_version_token_hash=version_hash,
            latency_class=self._latency_class(started),
        )


class _SecretHealthResolver:
    def __init__(self, runtime: LiveExternalEvidenceRuntime, backend: str):
        self._runtime = runtime
        self._backend = backend
        self.resolver_kind = f"{backend}_live_health_v1"

    def check(self, locator: CredentialReferenceLocator) -> CredentialReferenceHealthProbeResult:
        try:
            secret = self._runtime.load_secret(locator)
            secret = ""
            return CredentialReferenceHealthProbeResult(resolvable=True)
        except _RuntimeFailure as exc:
            code = exc.code if exc.code in {
                "reference_not_found", "reference_unresolved", "permission_denied", "backend_unavailable"
            } else "resolver_rejected"
            return CredentialReferenceHealthProbeResult(resolvable=False, failure_code=code)


class _SecretResolutionResolver:
    def __init__(self, runtime: LiveExternalEvidenceRuntime, backend: str):
        self._runtime = runtime
        self._backend = backend
        self.resolver_kind = f"{backend}_live_resolution_v1"

    def resolve(self, locator: CredentialReferenceLocator) -> CredentialReferenceResolutionResult:
        try:
            secret = self._runtime.load_secret(locator)
            secret = ""
            return CredentialReferenceResolutionResult(resolved=True)
        except _RuntimeFailure as exc:
            code = exc.code if exc.code in {
                "reference_not_found", "reference_unresolved", "permission_denied", "backend_unavailable"
            } else "resolver_rejected"
            return CredentialReferenceResolutionResult(resolved=False, failure_code=code)


class _TokenAcquirer:
    def __init__(self, runtime: LiveExternalEvidenceRuntime, provider: str):
        self._runtime = runtime
        self.provider_kind = provider
        if provider == "sharepoint":
            self.acquirer_kind = "microsoft_graph_live_oauth_v1"
            self.token_flow_kind = "client_credentials"
            self.token_endpoint_origin = "https://login.microsoftonline.com"
        else:
            self.acquirer_kind = "google_drive_live_oauth_v1"
            self.token_flow_kind = "jwt_bearer"
            self.token_endpoint_origin = "https://oauth2.googleapis.com"

    def acquire(self, locator: CredentialReferenceLocator, policy) -> TokenAcquisitionResult:
        try:
            token = self._runtime.provider_token(locator, policy)
            expires = token.expires_in
            token = None
            if expires is None:
                expiry_class = "unknown"
            elif expires <= 900:
                expiry_class = "short"
            elif expires <= 7200:
                expiry_class = "standard"
            else:
                expiry_class = "long"
            return TokenAcquisitionResult(acquired=True, expiry_class=expiry_class)
        except _RuntimeFailure as exc:
            allowed = {
                "invalid_client", "invalid_grant", "unauthorized_client", "invalid_scope",
                "permission_denied", "endpoint_unavailable", "timeout", "malformed_response",
                "oversized_response", "provider_rejected",
            }
            return TokenAcquisitionResult(
                acquired=False,
                failure_code=exc.code if exc.code in allowed else "provider_rejected",
            )


class _ProviderHealthAdapter:
    def __init__(self, runtime: LiveExternalEvidenceRuntime, provider: str):
        self._runtime = runtime
        self.provider_kind = provider
        if provider == "sharepoint":
            self.adapter_kind = "microsoft_graph_live_health_v1"
            self.client_kind = "microsoft_graph_transient_v1"
            self.health_operation_kind = "graph_organization_health"
            self.provider_origin = "https://graph.microsoft.com"
        else:
            self.adapter_kind = "google_drive_live_health_v1"
            self.client_kind = "google_drive_transient_v3"
            self.health_operation_kind = "drive_about_health"
            self.provider_origin = "https://www.googleapis.com"

    def qualify(self, locator: CredentialReferenceLocator, policy) -> ProviderClientHealthResult:
        try:
            payload, latency = self._runtime.provider_get(
                locator, policy, policy.health_endpoint_url, max_bytes=policy.max_response_bytes
            )
            if self.provider_kind == "sharepoint":
                value = payload.get("value")
                valid = isinstance(value, list) and bool(value) and isinstance(value[0], dict) and bool(value[0].get("id"))
            else:
                user = payload.get("user")
                valid = isinstance(user, dict) and bool(user.get("permissionId"))
            if not valid:
                return ProviderClientHealthResult(healthy=False, failure_code="malformed_response")
            return ProviderClientHealthResult(healthy=True, latency_class=latency)
        except _RuntimeFailure as exc:
            allowed = {
                "unauthorized", "permission_denied", "endpoint_unavailable", "timeout",
                "malformed_response", "oversized_response", "provider_rejected",
            }
            return ProviderClientHealthResult(
                healthy=False,
                failure_code=exc.code if exc.code in allowed else "provider_rejected",
            )


class _MetadataListAdapter:
    def __init__(self, runtime: LiveExternalEvidenceRuntime, provider: str):
        self._runtime = runtime
        self.provider_kind = provider
        if provider == "sharepoint":
            self.adapter_kind = "microsoft_graph_live_metadata_v1"
            self.client_kind = "microsoft_graph_transient_v1"
            self.listing_operation_kind = "graph_drive_children_metadata_v1"
            self.provider_origin = "https://graph.microsoft.com"
        else:
            self.adapter_kind = "google_drive_live_metadata_v1"
            self.client_kind = "google_drive_transient_v3"
            self.listing_operation_kind = "drive_files_list_metadata_v1"
            self.provider_origin = "https://www.googleapis.com"

    def list_metadata(self, locator: CredentialReferenceLocator, policy) -> RemoteMetadataListResult:
        try:
            return self._runtime.list_metadata(locator, policy)
        except _RuntimeFailure as exc:
            allowed = {
                "unauthorized", "permission_denied", "endpoint_unavailable", "timeout",
                "malformed_response", "oversized_response", "too_many_items", "provider_rejected",
            }
            return RemoteMetadataListResult(
                listed=False,
                failure_code=exc.code if exc.code in allowed else "provider_rejected",
            )


class _ExactMetadataAdapter:
    def __init__(self, runtime: LiveExternalEvidenceRuntime, provider: str):
        self._runtime = runtime
        self.provider_kind = provider
        if provider == "sharepoint":
            self.adapter_kind = "microsoft_graph_live_exact_metadata_v1"
            self.client_kind = "microsoft_graph_transient_v1"
            self.observation_operation_kind = "graph_drive_item_metadata_read_v1"
            self.provider_origin = "https://graph.microsoft.com"
        else:
            self.adapter_kind = "google_drive_live_exact_metadata_v1"
            self.client_kind = "google_drive_transient_v3"
            self.observation_operation_kind = "drive_file_metadata_read_v1"
            self.provider_origin = "https://www.googleapis.com"

    def read_item_metadata(
        self,
        locator: CredentialReferenceLocator,
        policy,
    ) -> ExactItemMetadataResult:
        try:
            return self._runtime.read_exact_metadata(locator, policy)
        except _RuntimeFailure as exc:
            allowed = {
                "unauthorized",
                "permission_denied",
                "not_found",
                "endpoint_unavailable",
                "timeout",
                "malformed_response",
                "oversized_response",
                "provider_rejected",
            }
            return ExactItemMetadataResult(
                found=False,
                item=None,
                failure_code=(
                    exc.code if exc.code in allowed else "provider_rejected"
                ),
            )


class _ContentReadAdapter:
    def __init__(self, runtime: LiveExternalEvidenceRuntime, provider: str):
        self._runtime = runtime
        self.provider_kind = provider
        if provider == "sharepoint":
            self.adapter_kind = "microsoft_graph_live_content_v1"
            self.client_kind = "microsoft_graph_transient_v1"
            self.read_operation_kind = "graph_drive_item_content_read_v1"
            self.provider_origin = "https://graph.microsoft.com"
            self.redirect_policy_kind = "provider_internal_https_one_hop_v1"
        else:
            self.adapter_kind = "google_drive_live_content_v1"
            self.client_kind = "google_drive_transient_v3"
            self.read_operation_kind = "drive_file_media_read_v1"
            self.provider_origin = "https://www.googleapis.com"
            self.redirect_policy_kind = "no_redirects_v1"

    def read_content(self, locator: CredentialReferenceLocator, policy) -> RemoteFileContentReadResult:
        try:
            return self._runtime.read_content(locator, policy)
        except _RuntimeFailure as exc:
            allowed = {
                "unauthorized", "permission_denied", "not_found", "endpoint_unavailable",
                "timeout", "malformed_response", "oversized_response", "version_mismatch",
                "provider_rejected",
            }
            return RemoteFileContentReadResult(
                read=False,
                failure_code=exc.code if exc.code in allowed else "provider_rejected",
            )


def register_live_external_document_source_adapters(
    runtime: LiveExternalEvidenceRuntime | None = None,
) -> LiveExternalEvidenceRuntime:
    """Register production-shaped read-only adapters.

    Registration only makes the already-governed execution boundaries callable.
    It does not create a source profile, approve a credential reference, authorize
    provider activation, schedule observations, admit Evidence, release processing,
    or grant external-AI authority.
    """

    runtime = runtime or LiveExternalEvidenceRuntime()

    for backend in ("azure_key_vault", "gcp_secret_manager"):
        register_external_document_source_credential_reference_health_resolver(
            backend, _SecretHealthResolver(runtime, backend)
        )
        register_external_document_source_credential_resolution_resolver(
            backend, _SecretResolutionResolver(runtime, backend)
        )

    for provider in ("sharepoint", "google_drive"):
        token = _TokenAcquirer(runtime, provider)
        register_external_document_source_token_acquirer(
            provider, token.token_flow_kind, token
        )
        health = _ProviderHealthAdapter(runtime, provider)
        register_external_document_source_provider_client_health_adapter(
            provider, health.health_operation_kind, health
        )
        listing = _MetadataListAdapter(runtime, provider)
        register_external_document_source_remote_metadata_list_adapter(
            provider, listing.listing_operation_kind, listing
        )
        exact_metadata = _ExactMetadataAdapter(runtime, provider)
        register_external_document_source_change_detection_adapter(
            provider,
            exact_metadata.observation_operation_kind,
            exact_metadata,
        )
        reading = _ContentReadAdapter(runtime, provider)
        register_external_document_source_remote_file_content_read_adapter(
            provider, reading.read_operation_kind, reading
        )

    return runtime
