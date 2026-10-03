from __future__ import annotations

import stat as stat_module
from typing import Any

from app.modules.external_document_sources import live_sftp_adapters as live


_ORIGINAL_RUNTIME_CLASS = live.LiveSftpRuntime
_ORIGINAL_CONTENT_REGISTRAR = (
    live.register_external_document_source_sftp_file_content_read_adapter
)
_installed = False
_registration_complete = False


def _opened_file_snapshot_matches(pre_open: Any, opened: Any) -> None:
    pre_mode = getattr(pre_open, "st_mode", None)
    opened_mode = getattr(opened, "st_mode", None)
    pre_size = getattr(pre_open, "st_size", None)
    opened_size = getattr(opened, "st_size", None)

    if not all(
        isinstance(value, int)
        for value in (pre_mode, opened_mode, pre_size, opened_size)
    ):
        raise live._SftpRuntimeFailure("opened_file_snapshot_unverifiable")

    if not stat_module.S_ISREG(pre_mode) or not stat_module.S_ISREG(opened_mode):
        raise live._SftpRuntimeFailure("opened_file_snapshot_drift")
    if pre_mode != opened_mode or pre_size != opened_size:
        raise live._SftpRuntimeFailure("opened_file_snapshot_drift")

    for attribute in ("st_mtime", "st_uid", "st_gid"):
        before = getattr(pre_open, attribute, None)
        after = getattr(opened, attribute, None)
        if before is not None and after is not None and before != after:
            raise live._SftpRuntimeFailure("opened_file_snapshot_drift")


class _OpenedFileVerifiedSftpClient:
    """Read-only SFTP proxy that binds an opened handle to its lstat snapshot.

    This closes the ordinary lstat/open replacement window. It does not claim
    cryptographic identity against a malicious SFTP server, which controls both
    metadata responses and the opened handle.
    """

    def __init__(self, delegate: Any):
        self._delegate = delegate
        self._pre_open: dict[str, Any] = {}

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)

    def lstat(self, path: str) -> Any:
        result = self._delegate.lstat(path)
        self._pre_open[path] = result
        return result

    def open(self, path: str, mode: str = "rb") -> Any:
        handle = self._delegate.open(path, mode=mode)
        pre_open = self._pre_open.get(path)
        if mode != "rb" or pre_open is None:
            return handle

        try:
            opened = handle.stat()
            _opened_file_snapshot_matches(pre_open, opened)
        except live._SftpRuntimeFailure:
            try:
                handle.close()
            except Exception:
                pass
            raise
        except Exception as exc:
            try:
                handle.close()
            except Exception:
                pass
            raise live._SftpRuntimeFailure(
                "opened_file_snapshot_unverifiable"
            ) from exc
        return handle


class HardenedLiveSftpRuntime(_ORIGINAL_RUNTIME_CLASS):
    def __init__(self, *args: Any, **kwargs: Any):
        global _registration_complete
        _registration_complete = False
        super().__init__(*args, **kwargs)

    def _open_session(self, **kwargs: Any):
        session = super()._open_session(**kwargs)
        if not isinstance(session.sftp, _OpenedFileVerifiedSftpClient):
            session.sftp = _OpenedFileVerifiedSftpClient(session.sftp)
        return session


def _register_content_adapter_and_mark_complete(adapter: Any) -> None:
    global _registration_complete
    _ORIGINAL_CONTENT_REGISTRAR(adapter)
    _registration_complete = True


def install_sftp_production_hardening() -> None:
    """Install pure in-process production guards before live SFTP registration."""

    global _installed
    if _installed:
        return
    live.LiveSftpRuntime = HardenedLiveSftpRuntime
    live.register_external_document_source_sftp_file_content_read_adapter = (
        _register_content_adapter_and_mark_complete
    )
    _installed = True


def sftp_runtime_registration_complete() -> bool:
    """Return only whether the full live SFTP adapter registration completed."""

    return bool(_registration_complete)
