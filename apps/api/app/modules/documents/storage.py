from dataclasses import dataclass
import os
from pathlib import Path
import tempfile
from typing import BinaryIO, Protocol

from fastapi import UploadFile


class StorageError(RuntimeError):
    pass


class UploadTooLarge(StorageError):
    pass


@dataclass(frozen=True)
class StoredUpload:
    storage_key: str
    file_size_bytes: int
    file_hash: str


class DocumentAdmissionStorage(Protocol):
    """Storage contract required by the current quarantine/admission workflow.

    Phase 17.3-A keeps this contract local-only because `promote` and cleanup
    semantics must be redesigned before an S3 backend can safely implement them.
    """

    async def save_upload(self, upload: UploadFile, storage_key: str) -> StoredUpload: ...

    def save_bytes(self, payload: bytes, storage_key: str) -> StoredUpload: ...

    def path_for(self, storage_key: str) -> Path: ...

    def promote(self, quarantine_key: str, storage_key: str) -> None: ...

    def delete_physical(self, storage_key: str) -> None: ...


class LocalDocumentStorage:
    """Local development storage behind the active admission interface boundary."""

    def __init__(self, root: str, *, max_upload_bytes: int) -> None:
        self.root = Path(root).expanduser().resolve()
        self.max_upload_bytes = max_upload_bytes
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve_key(self, storage_key: str) -> Path:
        candidate = (self.root / storage_key).resolve()
        if self.root not in candidate.parents:
            raise StorageError("Invalid storage key")
        return candidate

    @staticmethod
    def _private_staging_file(parent: Path) -> tuple[BinaryIO, Path]:
        # Staging on the target filesystem permits atomic no-clobber publish
        # only after all bytes have been written and validated. mkstemp creates
        # a fresh mode-0600 file, never a predictable or shared name.
        fd, name = tempfile.mkstemp(prefix=".mcri-upload-", suffix=".partial", dir=parent)
        partial = Path(name)
        try:
            return os.fdopen(fd, "wb"), partial
        except BaseException:
            os.close(fd)
            partial.unlink(missing_ok=True)
            raise

    async def save_upload(self, upload: UploadFile, storage_key: str) -> StoredUpload:
        import hashlib

        path = self._resolve_key(storage_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size = 0

        partial: Path | None = None
        try:
            destination, partial = self._private_staging_file(path.parent)
            with destination:
                while chunk := await upload.read(1024 * 1024):
                    size += len(chunk)
                    if size > self.max_upload_bytes:
                        raise UploadTooLarge(
                            f"File exceeds maximum size of {self.max_upload_bytes} bytes"
                        )
                    digest.update(chunk)
                    destination.write(chunk)
            # Unlike check-exists + rename, link creates the published name
            # exclusively. A pre-existing/raced-in Evidence file is untouched.
            os.link(partial, path, follow_symlinks=False)
        finally:
            if partial is not None:
                partial.unlink(missing_ok=True)
            await upload.close()

        return StoredUpload(
            storage_key=storage_key,
            file_size_bytes=size,
            file_hash=digest.hexdigest(),
        )

    def save_bytes(self, payload: bytes, storage_key: str) -> StoredUpload:
        import hashlib

        path = self._resolve_key(storage_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(payload).hexdigest()
        partial: Path | None = None
        try:
            destination, partial = self._private_staging_file(path.parent)
            with destination:
                destination.write(payload)
            os.link(partial, path, follow_symlinks=False)
        finally:
            if partial is not None:
                partial.unlink(missing_ok=True)
        return StoredUpload(
            storage_key=storage_key,
            file_size_bytes=len(payload),
            file_hash=digest,
        )

    def path_for(self, storage_key: str) -> Path:
        path = self._resolve_key(storage_key)
        if not path.is_file():
            raise FileNotFoundError(storage_key)
        return path

    def promote(self, quarantine_key: str, storage_key: str) -> None:
        try:
            source = self.path_for(quarantine_key)
            destination = self._resolve_key(storage_key)
            destination.parent.mkdir(parents=True, exist_ok=True)
            # Quarantine and admitted Evidence are on the same local store.
            # Link is atomic and refuses any existing destination. A
            # check-exists followed by rename could overwrite raced-in bytes.
            # If source cleanup fails, keep both links for safe reconciliation
            # rather than deleting the newly published Evidence.
            try:
                os.link(source, destination, follow_symlinks=False)
            except FileExistsError as exc:
                raise StorageError("Target storage key already exists") from exc
            source.unlink()
        except StorageError:
            raise
        except OSError as exc:
            raise StorageError(f"Storage move failed: {type(exc).__name__}") from exc

    def delete_physical(self, storage_key: str) -> None:
        self._resolve_key(storage_key).unlink(missing_ok=True)
