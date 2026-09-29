from __future__ import annotations

import base64
import hashlib
import hmac
import importlib
import io
import ipaddress
import json
import posixpath
import socket
import stat as stat_module
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.core.config import get_settings
from app.modules.external_document_sources.credential_reference_health_service import (
    CredentialReferenceLocator,
)
from app.modules.external_document_sources.live_provider_adapters import (
    LiveExternalEvidenceRuntime,
    _RuntimeFailure,
)
from app.modules.external_document_sources.sftp_change_detection_service import (
    SftpExactFileMetadataRequest,
    SftpExactFileMetadataResult,
    register_external_document_source_sftp_exact_file_metadata_adapter,
)
from app.modules.external_document_sources.sftp_credential_health_service import (
    SftpCredentialHealthProbeResult,
    SftpCredentialReferenceLocator,
    register_external_document_source_sftp_credential_health_resolver,
)
from app.modules.external_document_sources.sftp_directory_listing_service import (
    SftpDirectoryListingRequest,
    SftpDirectoryListingResult,
    SftpDirectoryMetadataEntry,
    register_external_document_source_sftp_directory_listing_adapter,
)
from app.modules.external_document_sources.sftp_file_content_proof_service import (
    SftpFileContentReadRequest,
    SftpFileContentReadResult,
    register_external_document_source_sftp_file_content_read_adapter,
)
from app.modules.external_document_sources.sftp_session_activation_service import (
    SftpSessionActivationRequest,
    SftpSessionActivationResult,
    register_external_document_source_sftp_session_activation_adapter,
)
from app.modules.external_document_sources.sftp_transport_verification_service import (
    SftpTransportHostKeyProbeRequest,
    SftpTransportHostKeyProbeResult,
    register_external_document_source_sftp_transport_adapter,
)


_SUPPORTED_SECRET_BACKENDS = frozenset(
    {
        "azure_key_vault",
        "gcp_secret_manager",
    }
)
_ALLOWED_AUTH_KINDS = frozenset({"password", "private_key"})


class _SftpRuntimeFailure(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass
class _CredentialMaterial:
    username: str
    authentication_kind: str
    password: str | None = None
    private_key: str | None = None
    passphrase: str | None = None

    def clear(self) -> None:
        self.username = ""
        self.authentication_kind = ""
        self.password = None
        self.private_key = None
        self.passphrase = None


@dataclass
class _LiveSftpSession:
    sock: socket.socket
    transport: Any
    sftp: Any
    authentication_method: str

    def close(self) -> None:
        try:
            self.sftp.close()
        except Exception:
            pass
        try:
            self.transport.close()
        except Exception:
            pass
        try:
            self.sock.close()
        except Exception:
            pass


def _paramiko():
    try:
        return importlib.import_module("paramiko")
    except Exception as exc:
        raise RuntimeError(
            "Production SFTP adapters require the pinned Paramiko runtime"
        ) from exc


def _latency_class(started: float) -> str:
    elapsed = time.monotonic() - started
    if elapsed < 0.25:
        return "fast"
    if elapsed < 1.5:
        return "normal"
    return "slow"


def _openssh_sha256(raw_key: bytes) -> str:
    digest = hashlib.sha256(raw_key).digest()
    return "SHA256:" + base64.b64encode(digest).decode("ascii").rstrip("=")


def _safe_metadata_hash(
    *,
    path: str,
    mode: int | None,
    size: int | None,
    mtime: int | float | None,
    uid: int | None,
    gid: int | None,
) -> str:
    payload = {
        "path": path,
        "mode": mode,
        "size": size,
        "mtime": mtime,
        "uid": uid,
        "gid": gid,
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


def _entry_kind(mode: int | None) -> str:
    if not isinstance(mode, int):
        return "other"
    if stat_module.S_ISREG(mode):
        return "file"
    if stat_module.S_ISDIR(mode):
        return "directory"
    if stat_module.S_ISLNK(mode):
        return "symlink"
    return "other"


def _modified_at(value: int | float | None) -> datetime | None:
    if not isinstance(value, (int, float)):
        return None
    return datetime.fromtimestamp(value, tz=timezone.utc)


def _normalize_remote_path(root: str, effective: str) -> str:
    if not isinstance(root, str) or not isinstance(effective, str):
        raise _SftpRuntimeFailure("path_policy_violation")
    if "\x00" in root or "\x00" in effective:
        raise _SftpRuntimeFailure("path_policy_violation")
    normalized_root = posixpath.normpath(root)
    normalized_effective = posixpath.normpath(effective)
    if not normalized_root.startswith("/") or not normalized_effective.startswith("/"):
        raise _SftpRuntimeFailure("path_policy_violation")
    if normalized_root == "/":
        return normalized_effective
    prefix = normalized_root.rstrip("/") + "/"
    if normalized_effective != normalized_root and not normalized_effective.startswith(prefix):
        raise _SftpRuntimeFailure("path_policy_violation")
    return normalized_effective


def _canonical_remote_path(sftp, path: str) -> str:
    try:
        canonical = sftp.normalize(path)
    except Exception as exc:
        raise _SftpRuntimeFailure("path_policy_violation") from exc
    if not isinstance(canonical, str) or not canonical.startswith("/") or "\x00" in canonical:
        raise _SftpRuntimeFailure("path_policy_violation")
    return posixpath.normpath(canonical)


def _ensure_canonical_path_within_root(
    sftp,
    *,
    remote_root_path: str,
    effective_remote_path: str,
    exact_entry: bool,
) -> None:
    canonical_root = _canonical_remote_path(sftp, remote_root_path)
    target_for_resolution = (
        posixpath.dirname(effective_remote_path)
        if exact_entry
        else effective_remote_path
    )
    canonical_target = _canonical_remote_path(sftp, target_for_resolution)
    if canonical_root == "/":
        return
    prefix = canonical_root.rstrip("/") + "/"
    if canonical_target != canonical_root and not canonical_target.startswith(prefix):
        raise _SftpRuntimeFailure("symlink_escape_detected")



def _resolved_public_addresses(hostname: str, port: int) -> list[str]:
    try:
        records = socket.getaddrinfo(
            hostname,
            port,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )
    except socket.gaierror as exc:
        raise _SftpRuntimeFailure("dns_resolution_failed") from exc

    addresses: list[str] = []
    for _family, _type, _proto, _canon, sockaddr in records:
        address = sockaddr[0]
        if address not in addresses:
            addresses.append(address)
    if not addresses:
        raise _SftpRuntimeFailure("dns_resolution_failed")

    for address in addresses:
        ip = ipaddress.ip_address(address)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise _SftpRuntimeFailure("destination_policy_violation")
    return addresses


def _connect_socket(
    hostname: str,
    port: int,
    *,
    timeout_seconds: float,
    allow_private_destinations: bool,
) -> tuple[socket.socket, bool]:
    if allow_private_destinations:
        addresses = [hostname]
        dns_performed = not _is_literal_ip(hostname)
    else:
        addresses = _resolved_public_addresses(hostname, port)
        dns_performed = not _is_literal_ip(hostname)

    last_error: Exception | None = None
    for address in addresses:
        try:
            sock = socket.create_connection(
                (address, port),
                timeout=max(0.5, float(timeout_seconds)),
            )
            sock.settimeout(max(0.5, float(timeout_seconds)))
            return sock, dns_performed
        except socket.timeout as exc:
            last_error = exc
        except ConnectionRefusedError as exc:
            last_error = exc
        except OSError as exc:
            last_error = exc

    if isinstance(last_error, socket.timeout):
        raise _SftpRuntimeFailure("connection_timeout") from last_error
    if isinstance(last_error, ConnectionRefusedError):
        raise _SftpRuntimeFailure("connection_refused") from last_error
    raise _SftpRuntimeFailure("network_unavailable") from last_error


def _is_literal_ip(hostname: str) -> bool:
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        return False
    return True


class LiveSftpRuntime:
    """Transient production SFTP runtime.

    Secret material, private keys, passwords, SSH transports and SFTP sessions are
    kept in local call scope only. Public adapter results contain bounded facts,
    never credentials, remote raw responses or session objects.
    """

    def __init__(
        self,
        *,
        secret_runtime: LiveExternalEvidenceRuntime | None = None,
    ):
        self._secret_runtime = secret_runtime or LiveExternalEvidenceRuntime()

    def _load_credential(
        self,
        *,
        backend: str,
        namespace: str,
        name: str,
        version: str | None,
        expected_authentication_kind: str,
        expected_username: str | None = None,
    ) -> _CredentialMaterial:
        if backend not in _SUPPORTED_SECRET_BACKENDS:
            raise _SftpRuntimeFailure("credential_unavailable")
        if expected_authentication_kind not in _ALLOWED_AUTH_KINDS:
            raise _SftpRuntimeFailure("unsupported_authentication_method")

        locator = CredentialReferenceLocator(
            backend=backend,
            namespace=namespace,
            name=name,
            version=version,
        )
        try:
            raw = self._secret_runtime.load_secret(locator)
        except _RuntimeFailure as exc:
            if exc.code in {
                "reference_not_found",
                "reference_unresolved",
                "permission_denied",
                "backend_unavailable",
            }:
                raise _SftpRuntimeFailure("credential_unavailable") from None
            raise _SftpRuntimeFailure("credential_resolution_failed") from None
        except Exception:
            raise _SftpRuntimeFailure("credential_resolution_failed") from None

        try:
            payload = json.loads(raw)
        except Exception:
            raise _SftpRuntimeFailure("credential_resolution_failed") from None
        finally:
            raw = ""

        if not isinstance(payload, dict):
            raise _SftpRuntimeFailure("credential_resolution_failed")

        try:
            username = payload.get("username")
            auth_kind = payload.get(
                "authentication_kind",
                expected_authentication_kind,
            )
            if (
                not isinstance(username, str)
                or not username.strip()
                or auth_kind != expected_authentication_kind
            ):
                raise _SftpRuntimeFailure("credential_unavailable")
            username = username.strip()
            if expected_username is not None and not hmac.compare_digest(
                username,
                expected_username,
            ):
                raise _SftpRuntimeFailure("credential_unavailable")

            if expected_authentication_kind == "password":
                password = payload.get("password")
                if not isinstance(password, str) or not password:
                    raise _SftpRuntimeFailure("credential_unavailable")
                return _CredentialMaterial(
                    username=username,
                    authentication_kind="password",
                    password=password,
                )

            private_key = payload.get("private_key")
            passphrase = payload.get("passphrase")
            if not isinstance(private_key, str) or not private_key.strip():
                raise _SftpRuntimeFailure("credential_unavailable")
            if passphrase is not None and not isinstance(passphrase, str):
                raise _SftpRuntimeFailure("credential_unavailable")
            return _CredentialMaterial(
                username=username,
                authentication_kind="private_key",
                private_key=private_key,
                passphrase=passphrase,
            )
        finally:
            payload.clear()

    def _load_private_key(self, material: _CredentialMaterial):
        paramiko = _paramiko()
        if material.private_key is None:
            raise _SftpRuntimeFailure("credential_unavailable")
        last_error: Exception | None = None
        classes = (
            getattr(paramiko, "Ed25519Key", None),
            getattr(paramiko, "ECDSAKey", None),
            getattr(paramiko, "RSAKey", None),
        )
        for key_class in classes:
            if key_class is None:
                continue
            try:
                return key_class.from_private_key(
                    io.StringIO(material.private_key),
                    password=material.passphrase,
                )
            except Exception as exc:
                last_error = exc
        raise _SftpRuntimeFailure("credential_unavailable") from last_error

    def _start_transport(
        self,
        *,
        hostname: str,
        port: int,
        connect_timeout_seconds: float,
        handshake_timeout_seconds: float,
        allow_private_destinations: bool,
    ) -> tuple[socket.socket, Any, str, str, bool]:
        paramiko = _paramiko()
        sock, dns_performed = _connect_socket(
            hostname,
            port,
            timeout_seconds=connect_timeout_seconds,
            allow_private_destinations=allow_private_destinations,
        )
        try:
            transport = paramiko.Transport(sock)
            if hasattr(transport, "banner_timeout"):
                transport.banner_timeout = max(0.5, float(handshake_timeout_seconds))
            transport.start_client(timeout=max(0.5, float(handshake_timeout_seconds)))
            remote_key = transport.get_remote_server_key()
            fingerprint = _openssh_sha256(remote_key.asbytes())
            algorithm = (
                getattr(transport, "host_key_type", None)
                or remote_key.get_name()
            )
            return sock, transport, fingerprint, str(algorithm), dns_performed
        except socket.timeout as exc:
            try:
                sock.close()
            except Exception:
                pass
            raise _SftpRuntimeFailure("connection_timeout") from exc
        except Exception as exc:
            try:
                sock.close()
            except Exception:
                pass
            raise _SftpRuntimeFailure("ssh_negotiation_failed") from exc

    def probe_host_key(
        self,
        request: SftpTransportHostKeyProbeRequest,
    ) -> SftpTransportHostKeyProbeResult:
        started = time.monotonic()
        sock = None
        transport = None
        try:
            sock, transport, fingerprint, algorithm, dns_performed = self._start_transport(
                hostname=request.hostname,
                port=request.port,
                connect_timeout_seconds=request.connect_timeout_seconds,
                handshake_timeout_seconds=request.handshake_timeout_seconds,
                allow_private_destinations=request.allow_private_destinations,
            )
            return SftpTransportHostKeyProbeResult(
                observed_host_key_fingerprint=fingerprint,
                host_key_algorithm=algorithm,
                latency_class=_latency_class(started),
                failure_code=None,
                destination_policy_enforced=True,
                dns_resolution_performed=dns_performed,
                provider_network_performed=True,
                ssh_transport_performed=True,
                authentication_performed=False,
                sftp_session_opened=False,
                remote_operation_performed=False,
            )
        except _SftpRuntimeFailure as exc:
            code = exc.code
            if code not in {
                "destination_policy_violation",
                "dns_resolution_failed",
                "connection_timeout",
                "connection_refused",
                "network_unavailable",
                "ssh_negotiation_failed",
            }:
                code = "ssh_negotiation_failed"
            return SftpTransportHostKeyProbeResult(
                latency_class=_latency_class(started),
                failure_code=code,
                destination_policy_enforced=True,
                dns_resolution_performed=not _is_literal_ip(request.hostname),
                provider_network_performed=code not in {
                    "destination_policy_violation",
                    "dns_resolution_failed",
                },
                ssh_transport_performed=False,
                authentication_performed=False,
                sftp_session_opened=False,
                remote_operation_performed=False,
            )
        finally:
            if transport is not None:
                try:
                    transport.close()
                except Exception:
                    pass
            if sock is not None:
                try:
                    sock.close()
                except Exception:
                    pass

    def _open_session(
        self,
        *,
        hostname: str,
        port: int,
        pinned_host_key_fingerprint: str,
        authentication_kind: str,
        reference_backend: str,
        reference_namespace: str,
        reference_name: str,
        reference_version: str | None,
        expected_username: str | None,
        connect_timeout_seconds: float,
        authentication_timeout_seconds: float,
        subsystem_timeout_seconds: float,
        allow_private_destinations: bool,
    ) -> _LiveSftpSession:
        paramiko = _paramiko()
        sock = None
        transport = None
        material = None
        try:
            sock, transport, observed, _algorithm, _dns = self._start_transport(
                hostname=hostname,
                port=port,
                connect_timeout_seconds=connect_timeout_seconds,
                handshake_timeout_seconds=authentication_timeout_seconds,
                allow_private_destinations=allow_private_destinations,
            )
            if not hmac.compare_digest(
                observed,
                pinned_host_key_fingerprint,
            ):
                raise _SftpRuntimeFailure("host_key_revalidation_failed")

            material = self._load_credential(
                backend=reference_backend,
                namespace=reference_namespace,
                name=reference_name,
                version=reference_version,
                expected_authentication_kind=authentication_kind,
                expected_username=expected_username,
            )

            try:
                if authentication_kind == "password":
                    transport.auth_password(
                        material.username,
                        material.password or "",
                        fallback=False,
                    )
                    auth_method = "password"
                elif authentication_kind == "private_key":
                    pkey = self._load_private_key(material)
                    transport.auth_publickey(material.username, pkey)
                    auth_method = "public_key"
                else:
                    raise _SftpRuntimeFailure(
                        "unsupported_authentication_method"
                    )
            except _SftpRuntimeFailure:
                raise
            except Exception as exc:
                authentication_exception = getattr(
                    paramiko,
                    "AuthenticationException",
                    (),
                )
                if authentication_exception and isinstance(
                    exc,
                    authentication_exception,
                ):
                    raise _SftpRuntimeFailure("authentication_failed") from None
                if isinstance(exc, socket.timeout):
                    raise _SftpRuntimeFailure("authentication_timeout") from None
                raise _SftpRuntimeFailure("authentication_failed") from None

            if not transport.is_authenticated():
                raise _SftpRuntimeFailure("authentication_failed")

            try:
                sftp = paramiko.SFTPClient.from_transport(transport)
                if sftp is None:
                    raise _SftpRuntimeFailure(
                        "sftp_subsystem_activation_failed"
                    )
                channel = sftp.get_channel()
                if channel is not None:
                    channel.settimeout(
                        max(0.5, float(subsystem_timeout_seconds))
                    )
            except _SftpRuntimeFailure:
                raise
            except Exception as exc:
                raise _SftpRuntimeFailure(
                    "sftp_subsystem_activation_failed"
                ) from exc

            session = _LiveSftpSession(
                sock=sock,
                transport=transport,
                sftp=sftp,
                authentication_method=auth_method,
            )
            sock = None
            transport = None
            return session
        finally:
            if material is not None:
                material.clear()
            if transport is not None:
                try:
                    transport.close()
                except Exception:
                    pass
            if sock is not None:
                try:
                    sock.close()
                except Exception:
                    pass

    def activate(
        self,
        request: SftpSessionActivationRequest,
    ) -> SftpSessionActivationResult:
        started = time.monotonic()
        session = None
        try:
            session = self._open_session(
                hostname=request.hostname,
                port=request.port,
                pinned_host_key_fingerprint=request.pinned_host_key_fingerprint,
                authentication_kind=request.authentication_kind,
                reference_backend=request.reference_backend,
                reference_namespace=request.reference_namespace,
                reference_name=request.reference_name,
                reference_version=request.reference_version,
                expected_username=None,
                connect_timeout_seconds=request.connect_timeout_seconds,
                authentication_timeout_seconds=request.authentication_timeout_seconds,
                subsystem_timeout_seconds=request.subsystem_timeout_seconds,
                allow_private_destinations=request.allow_private_destinations,
            )
            method = session.authentication_method
            return SftpSessionActivationResult(
                failure_code=None,
                authentication_method=method,
                latency_class=_latency_class(started),
                secret_resolution_performed=True,
                provider_network_performed=True,
                ssh_transport_performed=True,
                host_key_verification_performed=True,
                host_key_verified=True,
                authentication_performed=True,
                authentication_succeeded=True,
                sftp_session_opened=True,
                sftp_session_closed=True,
                credential_persisted=False,
                remote_operation_performed=False,
                command_executed=False,
            )
        except _SftpRuntimeFailure as exc:
            code = exc.code
            allowed = {
                "credential_resolution_failed",
                "credential_unavailable",
                "authentication_failed",
                "authentication_timeout",
                "unsupported_authentication_method",
                "host_key_revalidation_failed",
                "sftp_subsystem_activation_failed",
                "destination_policy_violation",
            }
            if code in {"connection_refused", "network_unavailable", "ssh_negotiation_failed", "dns_resolution_failed", "connection_timeout"}:
                code = "host_key_revalidation_failed"
            if code not in allowed:
                code = "adapter_boundary_violation"
            return SftpSessionActivationResult(
                failure_code=code,
                latency_class=_latency_class(started),
                secret_resolution_performed=code
                not in {
                    "destination_policy_violation",
                    "host_key_revalidation_failed",
                },
                provider_network_performed=code
                not in {
                    "destination_policy_violation",
                    "credential_resolution_failed",
                    "credential_unavailable",
                },
                ssh_transport_performed=False,
                host_key_verification_performed=code
                not in {
                    "destination_policy_violation",
                    "credential_resolution_failed",
                    "credential_unavailable",
                },
                host_key_verified=False,
                authentication_performed=code
                in {
                    "authentication_failed",
                    "authentication_timeout",
                    "sftp_subsystem_activation_failed",
                },
                authentication_succeeded=code
                == "sftp_subsystem_activation_failed",
                sftp_session_opened=False,
                sftp_session_closed=False,
                credential_persisted=False,
                remote_operation_performed=False,
                command_executed=False,
            )
        finally:
            if session is not None:
                session.close()

    def list_metadata(
        self,
        request: SftpDirectoryListingRequest,
    ) -> SftpDirectoryListingResult:
        started = time.monotonic()
        session = None
        try:
            path = _normalize_remote_path(
                request.remote_root_path,
                request.effective_remote_path,
            )
            session = self._open_session(
                hostname=request.hostname,
                port=request.port,
                pinned_host_key_fingerprint=request.pinned_host_key_fingerprint,
                authentication_kind=request.authentication_kind,
                reference_backend=request.reference_backend,
                reference_namespace=request.reference_namespace,
                reference_name=request.reference_name,
                reference_version=request.reference_version,
                expected_username=request.username,
                connect_timeout_seconds=request.connect_timeout_seconds,
                authentication_timeout_seconds=request.authentication_timeout_seconds,
                subsystem_timeout_seconds=request.listing_timeout_seconds,
                allow_private_destinations=request.allow_private_destinations,
            )
            _ensure_canonical_path_within_root(
                session.sftp,
                remote_root_path=request.remote_root_path,
                effective_remote_path=path,
                exact_entry=False,
            )
            attrs = session.sftp.listdir_attr(path)
            if len(attrs) > request.max_entries:
                return SftpDirectoryListingResult(
                    failure_code="too_many_entries",
                    authentication_method=session.authentication_method,
                    latency_class=_latency_class(started),
                    page_count=1,
                    secret_resolution_performed=True,
                    provider_network_performed=True,
                    ssh_transport_performed=True,
                    host_key_verification_performed=True,
                    host_key_verified=True,
                    authentication_performed=True,
                    authentication_succeeded=True,
                    sftp_session_opened=True,
                    remote_list_performed=True,
                    sftp_session_closed=True,
                )

            entries: list[SftpDirectoryMetadataEntry] = []
            base_relative = request.relative_path.strip("/")
            if base_relative in {"", "."}:
                base_relative = ""
            for attr in attrs:
                filename = getattr(attr, "filename", None)
                if (
                    not isinstance(filename, str)
                    or not filename
                    or filename in {".", ".."}
                    or "/" in filename
                    or "\x00" in filename
                ):
                    raise _SftpRuntimeFailure(
                        "unsupported_entry_metadata"
                    )
                relative = (
                    posixpath.join(base_relative, filename)
                    if base_relative
                    else filename
                )
                mode = getattr(attr, "st_mode", None)
                size = getattr(attr, "st_size", None)
                mtime = getattr(attr, "st_mtime", None)
                uid = getattr(attr, "st_uid", None)
                gid = getattr(attr, "st_gid", None)
                entries.append(
                    SftpDirectoryMetadataEntry(
                        relative_path=relative,
                        entry_kind=_entry_kind(mode),
                        byte_size=size if isinstance(size, int) else None,
                        modified_at=_modified_at(mtime),
                        metadata_id_hash=_safe_metadata_hash(
                            path=relative,
                            mode=mode if isinstance(mode, int) else None,
                            size=size if isinstance(size, int) else None,
                            mtime=mtime if isinstance(mtime, (int, float)) else None,
                            uid=uid if isinstance(uid, int) else None,
                            gid=gid if isinstance(gid, int) else None,
                        ),
                    )
                )

            return SftpDirectoryListingResult(
                failure_code=None,
                authentication_method=session.authentication_method,
                latency_class=_latency_class(started),
                entries=tuple(entries),
                truncated=False,
                page_count=1,
                secret_resolution_performed=True,
                provider_network_performed=True,
                ssh_transport_performed=True,
                host_key_verification_performed=True,
                host_key_verified=True,
                authentication_performed=True,
                authentication_succeeded=True,
                sftp_session_opened=True,
                remote_list_performed=True,
                sftp_session_closed=True,
                credential_persisted=False,
                session_persisted=False,
                raw_response_persisted=False,
                remote_stat_performed=False,
                remote_read_performed=False,
                remote_write_performed=False,
                remote_rename_performed=False,
                remote_delete_performed=False,
                remote_mkdir_performed=False,
                remote_chmod_performed=False,
                remote_chown_performed=False,
                remote_touch_performed=False,
                command_executed=False,
                symlink_escape_detected=False,
            )
        except _SftpRuntimeFailure as exc:
            code = exc.code
            if code in {
                "connection_refused",
                "network_unavailable",
                "dns_resolution_failed",
                "ssh_negotiation_failed",
            }:
                code = "connection_failed"
            if code == "credential_unavailable":
                code = "credential_unavailable"
            allowed = {
                "credential_resolution_failed",
                "credential_unavailable",
                "connection_failed",
                "connection_timeout",
                "host_key_revalidation_failed",
                "authentication_failed",
                "authentication_timeout",
                "sftp_subsystem_activation_failed",
                "listing_failed",
                "listing_timeout",
                "path_policy_violation",
                "symlink_escape_detected",
                "too_many_entries",
                "oversized_metadata",
                "unsupported_entry_metadata",
            }
            if code not in allowed:
                code = "listing_failed"
            return SftpDirectoryListingResult(
                failure_code=code,
                latency_class=_latency_class(started),
            )
        except socket.timeout:
            return SftpDirectoryListingResult(
                failure_code="listing_timeout",
                latency_class=_latency_class(started),
            )
        except PermissionError:
            return SftpDirectoryListingResult(
                failure_code="listing_failed",
                latency_class=_latency_class(started),
            )
        except Exception:
            return SftpDirectoryListingResult(
                failure_code="listing_failed",
                latency_class=_latency_class(started),
            )
        finally:
            if session is not None:
                session.close()

    def stat_metadata(
        self,
        request: SftpExactFileMetadataRequest,
    ) -> SftpExactFileMetadataResult:
        started = time.monotonic()
        session = None
        try:
            path = _normalize_remote_path(
                request.remote_root_path,
                request.effective_remote_path,
            )
            session = self._open_session(
                hostname=request.hostname,
                port=request.port,
                pinned_host_key_fingerprint=request.pinned_host_key_fingerprint,
                authentication_kind=request.authentication_kind,
                reference_backend=request.reference_backend,
                reference_namespace=request.reference_namespace,
                reference_name=request.reference_name,
                reference_version=request.reference_version,
                expected_username=request.username,
                connect_timeout_seconds=request.connect_timeout_seconds,
                authentication_timeout_seconds=request.authentication_timeout_seconds,
                subsystem_timeout_seconds=request.stat_timeout_seconds,
                allow_private_destinations=request.allow_private_destinations,
            )
            _ensure_canonical_path_within_root(
                session.sftp,
                remote_root_path=request.remote_root_path,
                effective_remote_path=path,
                exact_entry=True,
            )
            try:
                attr = session.sftp.lstat(path)
            except FileNotFoundError:
                return SftpExactFileMetadataResult(
                    found=False,
                    failure_code="not_found",
                    authentication_method=session.authentication_method,
                    latency_class=_latency_class(started),
                    secret_resolution_performed=True,
                    provider_network_performed=True,
                    ssh_transport_performed=True,
                    host_key_verification_performed=True,
                    host_key_verified=True,
                    authentication_performed=True,
                    authentication_succeeded=True,
                    sftp_session_opened=True,
                    remote_stat_performed=True,
                    sftp_session_closed=True,
                )

            mode = getattr(attr, "st_mode", None)
            kind = _entry_kind(mode)
            if kind == "symlink":
                return SftpExactFileMetadataResult(
                    found=False,
                    failure_code="symlink_escape_detected",
                    authentication_method=session.authentication_method,
                    latency_class=_latency_class(started),
                    secret_resolution_performed=True,
                    provider_network_performed=True,
                    ssh_transport_performed=True,
                    host_key_verification_performed=True,
                    host_key_verified=True,
                    authentication_performed=True,
                    authentication_succeeded=True,
                    sftp_session_opened=True,
                    remote_stat_performed=True,
                    sftp_session_closed=True,
                    symlink_escape_detected=True,
                )

            size = getattr(attr, "st_size", None)
            mtime = getattr(attr, "st_mtime", None)
            uid = getattr(attr, "st_uid", None)
            gid = getattr(attr, "st_gid", None)
            return SftpExactFileMetadataResult(
                found=True,
                failure_code=None,
                entry_kind=kind,
                byte_size=size if isinstance(size, int) else None,
                modified_at=_modified_at(mtime),
                metadata_id_hash=_safe_metadata_hash(
                    path=request.entry_relative_path,
                    mode=mode if isinstance(mode, int) else None,
                    size=size if isinstance(size, int) else None,
                    mtime=mtime if isinstance(mtime, (int, float)) else None,
                    uid=uid if isinstance(uid, int) else None,
                    gid=gid if isinstance(gid, int) else None,
                ),
                authentication_method=session.authentication_method,
                latency_class=_latency_class(started),
                secret_resolution_performed=True,
                provider_network_performed=True,
                ssh_transport_performed=True,
                host_key_verification_performed=True,
                host_key_verified=True,
                authentication_performed=True,
                authentication_succeeded=True,
                sftp_session_opened=True,
                remote_stat_performed=True,
                sftp_session_closed=True,
            )
        except _SftpRuntimeFailure as exc:
            code = exc.code
            if code in {
                "connection_refused",
                "network_unavailable",
                "dns_resolution_failed",
                "ssh_negotiation_failed",
            }:
                code = "connection_failed"
            allowed = {
                "not_found",
                "credential_resolution_failed",
                "credential_unavailable",
                "connection_failed",
                "connection_timeout",
                "host_key_revalidation_failed",
                "authentication_failed",
                "authentication_timeout",
                "sftp_subsystem_activation_failed",
                "stat_failed",
                "stat_timeout",
                "permission_denied",
                "path_policy_violation",
                "symlink_escape_detected",
                "invalid_adapter_result",
            }
            if code not in allowed:
                code = "stat_failed"
            return SftpExactFileMetadataResult(
                found=False,
                failure_code=code,
                latency_class=_latency_class(started),
            )
        except socket.timeout:
            return SftpExactFileMetadataResult(
                found=False,
                failure_code="stat_timeout",
                latency_class=_latency_class(started),
            )
        except PermissionError:
            return SftpExactFileMetadataResult(
                found=False,
                failure_code="permission_denied",
                latency_class=_latency_class(started),
            )
        except Exception:
            return SftpExactFileMetadataResult(
                found=False,
                failure_code="stat_failed",
                latency_class=_latency_class(started),
            )
        finally:
            if session is not None:
                session.close()

    def read_content(
        self,
        request: SftpFileContentReadRequest,
    ) -> SftpFileContentReadResult:
        started = time.monotonic()
        session = None
        remote_stat_performed = False
        remote_read_performed = False
        try:
            path = _normalize_remote_path(
                request.remote_root_path,
                request.effective_remote_path,
            )
            session = self._open_session(
                hostname=request.hostname,
                port=request.port,
                pinned_host_key_fingerprint=request.pinned_host_key_fingerprint,
                authentication_kind=request.authentication_kind,
                reference_backend=request.reference_backend,
                reference_namespace=request.reference_namespace,
                reference_name=request.reference_name,
                reference_version=request.reference_version,
                expected_username=request.username,
                connect_timeout_seconds=request.connect_timeout_seconds,
                authentication_timeout_seconds=request.authentication_timeout_seconds,
                subsystem_timeout_seconds=request.read_timeout_seconds,
                allow_private_destinations=request.allow_private_destinations,
            )

            _ensure_canonical_path_within_root(
                session.sftp,
                remote_root_path=request.remote_root_path,
                effective_remote_path=path,
                exact_entry=True,
            )
            attr = session.sftp.lstat(path)
            remote_stat_performed = True
            mode = getattr(attr, "st_mode", None)
            if _entry_kind(mode) != "file":
                raise _SftpRuntimeFailure("symlink_escape_detected")

            chunks: list[bytes] = []
            total = 0
            with session.sftp.open(path, mode="rb") as handle:
                try:
                    handle.settimeout(
                        max(0.5, float(request.read_timeout_seconds))
                    )
                except Exception:
                    pass
                while True:
                    chunk = handle.read(request.max_chunk_bytes)
                    if not chunk:
                        break
                    remote_read_performed = True
                    total += len(chunk)
                    if total > request.max_content_bytes:
                        raise _SftpRuntimeFailure("content_too_large")
                    chunks.append(bytes(chunk))
            content = b"".join(chunks)
            if not remote_read_performed and content == b"":
                remote_read_performed = True

            return SftpFileContentReadResult(
                content=content,
                failure_code=None,
                authentication_method=session.authentication_method,
                latency_class=_latency_class(started),
                secret_resolution_performed=True,
                provider_network_performed=True,
                ssh_transport_performed=True,
                host_key_verification_performed=True,
                host_key_verified=True,
                authentication_performed=True,
                authentication_succeeded=True,
                sftp_session_opened=True,
                remote_read_performed=True,
                content_read_count=1,
                sftp_session_closed=True,
                credential_persisted=False,
                session_persisted=False,
                raw_response_persisted=False,
                remote_content_persisted=False,
                remote_content_returned=False,
                remote_content_logged=False,
                content_parsed=False,
                content_extracted=False,
                remote_list_performed=False,
                remote_stat_performed=remote_stat_performed,
                remote_write_performed=False,
                remote_rename_performed=False,
                remote_delete_performed=False,
                remote_mkdir_performed=False,
                remote_chmod_performed=False,
                remote_chown_performed=False,
                remote_touch_performed=False,
                command_executed=False,
            )
        except _SftpRuntimeFailure as exc:
            return SftpFileContentReadResult(
                content=None,
                failure_code=exc.code,
                latency_class=_latency_class(started),
                remote_stat_performed=remote_stat_performed,
                remote_read_performed=remote_read_performed,
                content_read_count=0,
            )
        except Exception:
            return SftpFileContentReadResult(
                content=None,
                failure_code="read_failed",
                latency_class=_latency_class(started),
                remote_stat_performed=remote_stat_performed,
                remote_read_performed=remote_read_performed,
                content_read_count=0,
            )
        finally:
            if session is not None:
                session.close()


class _SftpCredentialHealthResolver:
    def __init__(self, runtime: LiveSftpRuntime, backend: str):
        self._runtime = runtime
        self._backend = backend
        self.resolver_kind = f"{backend}_live_sftp_health_v1"

    def check(
        self,
        locator: SftpCredentialReferenceLocator,
    ) -> SftpCredentialHealthProbeResult:
        material = None
        try:
            material = self._runtime._load_credential(
                backend=locator.backend,
                namespace=locator.namespace,
                name=locator.name,
                version=locator.version,
                expected_authentication_kind=locator.authentication_kind,
            )
            return SftpCredentialHealthProbeResult(
                resolved=True,
                material_kind=material.authentication_kind,
                failure_code=None,
            )
        except _SftpRuntimeFailure as exc:
            if exc.code == "credential_unavailable":
                code = "material_missing"
            elif exc.code == "unsupported_authentication_method":
                code = "authentication_kind_mismatch"
            elif exc.code == "credential_resolution_failed":
                code = "reference_unresolved"
            else:
                code = "resolver_rejected"
            return SftpCredentialHealthProbeResult(
                resolved=False,
                material_kind=None,
                failure_code=code,
            )
        finally:
            if material is not None:
                material.clear()


class _SftpTransportAdapter:
    adapter_kind = "paramiko_live_sftp_transport_v1"

    def __init__(self, runtime: LiveSftpRuntime):
        self._runtime = runtime

    def probe(
        self,
        request: SftpTransportHostKeyProbeRequest,
    ) -> SftpTransportHostKeyProbeResult:
        return self._runtime.probe_host_key(request)


class _SftpActivationAdapter:
    adapter_kind = "paramiko_live_sftp_activation_v1"

    def __init__(self, runtime: LiveSftpRuntime):
        self._runtime = runtime

    def activate(
        self,
        request: SftpSessionActivationRequest,
    ) -> SftpSessionActivationResult:
        return self._runtime.activate(request)


class _SftpListingAdapter:
    adapter_kind = "paramiko_live_sftp_listing_v1"

    def __init__(self, runtime: LiveSftpRuntime):
        self._runtime = runtime

    def list_metadata(
        self,
        request: SftpDirectoryListingRequest,
    ) -> SftpDirectoryListingResult:
        return self._runtime.list_metadata(request)


class _SftpExactMetadataAdapter:
    adapter_kind = "paramiko_live_sftp_exact_metadata_v1"

    def __init__(self, runtime: LiveSftpRuntime):
        self._runtime = runtime

    def stat_metadata(
        self,
        request: SftpExactFileMetadataRequest,
    ) -> SftpExactFileMetadataResult:
        return self._runtime.stat_metadata(request)


class _SftpContentReadAdapter:
    adapter_kind = "paramiko_live_sftp_content_v1"

    def __init__(self, runtime: LiveSftpRuntime):
        self._runtime = runtime

    def read_content(
        self,
        request: SftpFileContentReadRequest,
    ) -> SftpFileContentReadResult:
        return self._runtime.read_content(request)


def _configured_secret_backends() -> tuple[str, ...]:
    settings = get_settings()
    backends = tuple(
        dict.fromkeys(
            item.strip().lower()
            for item in settings.external_evidence_sftp_secret_backends.split(",")
            if item.strip()
        )
    )
    if not backends:
        raise ValueError(
            "At least one production SFTP secret backend must be configured"
        )
    unsupported = set(backends) - _SUPPORTED_SECRET_BACKENDS
    if unsupported:
        raise ValueError(
            "Unsupported production SFTP secret backend configuration"
        )
    return backends


def register_live_sftp_adapters(
    runtime: LiveSftpRuntime | None = None,
) -> LiveSftpRuntime:
    """Register production SFTP adapters behind the existing governed boundaries.

    Registration itself grants no source, credential, network, Evidence, processing
    or AI authority. When this feature is enabled the Paramiko dependency must be
    present; otherwise application startup fails closed.
    """

    _paramiko()
    runtime = runtime or LiveSftpRuntime()

    for backend in _configured_secret_backends():
        register_external_document_source_sftp_credential_health_resolver(
            backend,
            _SftpCredentialHealthResolver(runtime, backend),
        )

    register_external_document_source_sftp_transport_adapter(
        _SftpTransportAdapter(runtime)
    )
    register_external_document_source_sftp_session_activation_adapter(
        _SftpActivationAdapter(runtime)
    )
    register_external_document_source_sftp_directory_listing_adapter(
        _SftpListingAdapter(runtime)
    )
    register_external_document_source_sftp_exact_file_metadata_adapter(
        _SftpExactMetadataAdapter(runtime)
    )
    register_external_document_source_sftp_file_content_read_adapter(
        _SftpContentReadAdapter(runtime)
    )
    return runtime
