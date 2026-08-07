from dataclasses import dataclass
from pathlib import Path

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


class LocalDocumentStorage:
    """Local development storage behind a small S3-compatible-style interface boundary."""

    def __init__(self, root: str, *, max_upload_bytes: int) -> None:
        self.root = Path(root).expanduser().resolve()
        self.max_upload_bytes = max_upload_bytes
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve_key(self, storage_key: str) -> Path:
        candidate = (self.root / storage_key).resolve()
        if self.root not in candidate.parents:
            raise StorageError("Invalid storage key")
        return candidate

    async def save_upload(self, upload: UploadFile, storage_key: str) -> StoredUpload:
        import hashlib

        path = self._resolve_key(storage_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size = 0

        try:
            with path.open("xb") as destination:
                while chunk := await upload.read(1024 * 1024):
                    size += len(chunk)
                    if size > self.max_upload_bytes:
                        raise UploadTooLarge(
                            f"File exceeds maximum size of {self.max_upload_bytes} bytes"
                        )
                    digest.update(chunk)
                    destination.write(chunk)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        finally:
            await upload.close()

        return StoredUpload(
            storage_key=storage_key,
            file_size_bytes=size,
            file_hash=digest.hexdigest(),
        )

    def path_for(self, storage_key: str) -> Path:
        path = self._resolve_key(storage_key)
        if not path.is_file():
            raise FileNotFoundError(storage_key)
        return path

    def delete_physical(self, storage_key: str) -> None:
        self._resolve_key(storage_key).unlink(missing_ok=True)
