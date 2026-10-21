"""Regression checks for non-destructive, effective-UID Evidence preflight."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import os

import pytest

from app.core import preflight


def test_strict_preflight_requires_existing_storage_root(tmp_path: Path) -> None:
    missing = tmp_path / "not-created"
    with pytest.raises(OSError):
        preflight._check_local_evidence_write_access(missing, strict=True)
    assert not missing.exists()


def test_exclusive_probe_never_overwrites_existing_named_evidence(tmp_path: Path) -> None:
    legacy = tmp_path / ".mcri-write-probe"
    legacy.write_bytes(b"PRIVATE-EXISTING-EVIDENCE")
    other = tmp_path / "immutable-outside"
    other.write_bytes(b"PRIVATE-EXISTING-OUTSIDE")
    collision = tmp_path / ".mcri-preflight-predictable.tmp"
    collision.symlink_to(other)

    before = sorted(item.name for item in tmp_path.iterdir())
    preflight._check_local_evidence_write_access(tmp_path, strict=True)
    assert sorted(item.name for item in tmp_path.iterdir()) == before
    assert legacy.read_bytes() == b"PRIVATE-EXISTING-EVIDENCE"
    assert other.read_bytes() == b"PRIVATE-EXISTING-OUTSIDE"
    assert collision.is_symlink()


def test_missing_development_root_may_be_initialized(tmp_path: Path) -> None:
    root = tmp_path / "synthetic" / "storage"
    preflight._check_local_evidence_write_access(root, strict=False)
    assert root.is_dir()
    assert not tuple(root.iterdir())


@pytest.mark.skipif(os.name != "posix", reason="POSIX symlink and mode contract")
def test_symlink_root_is_rejected_without_touching_target(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    marker = real / "private"
    marker.write_bytes(b"DO-NOT-ALTER")
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    with pytest.raises(OSError):
        preflight._check_local_evidence_write_access(alias, strict=True)
    assert marker.read_bytes() == b"DO-NOT-ALTER"
    assert sorted(item.name for item in real.iterdir()) == ["private"]


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode contract")
def test_world_writable_root_is_rejected(tmp_path: Path) -> None:
    original_mode = tmp_path.stat().st_mode & 0o777
    tmp_path.chmod(0o777)
    try:
        with pytest.raises(OSError):
            preflight._check_local_evidence_write_access(tmp_path, strict=True)
    finally:
        tmp_path.chmod(original_mode)
    assert not list(tmp_path.iterdir())


def test_preflight_never_emits_os_error_with_private_storage_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    secret_path = str(tmp_path / "PRIVATE-CUSTOMER-STORAGE-PATH")
    settings = SimpleNamespace(
        app_env="test",
        cors_origins=["http://127.0.0.1:3000"],
        ai_provider="disabled",
        storage_backend="local",
        local_storage_path=secret_path,
        malware_scan_enabled=False,
        s3_foundation_enabled=False,
    )
    monkeypatch.setattr(preflight, "get_settings", lambda: settings)

    def deny(_root: Path, *, strict: bool) -> None:
        raise OSError(f"permission denied at {secret_path}")

    monkeypatch.setattr(preflight, "_check_local_evidence_write_access", deny)
    errors, _ = preflight.run_preflight(require_db=False)
    assert errors == ["Local evidence storage is unavailable or unsafe"]
    assert secret_path not in str(errors)
