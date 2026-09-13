import hashlib
from dataclasses import dataclass

from app.modules.documents.models import Document
from app.modules.documents.service import _storage
from app.modules.documents.storage import StorageError


class PhysicalDisposalStorageError(RuntimeError):
    pass


@dataclass(frozen=True)
class LocalDisposalTarget:
    storage_key_fingerprint: str
    file_hash: str
    file_size_bytes: int


def inspect_local_disposal_target(document: Document) -> LocalDisposalTarget:
    storage = _storage()
    try:
        path = storage.path_for(document.storage_key)
        payload = path.read_bytes()
    except (FileNotFoundError, OSError, StorageError) as exc:
        raise PhysicalDisposalStorageError("Bound local evidence target is unavailable") from exc
    digest = hashlib.sha256(payload).hexdigest()
    return LocalDisposalTarget(
        storage_key_fingerprint=hashlib.sha256(document.storage_key.encode("utf-8")).hexdigest(),
        file_hash=digest,
        file_size_bytes=len(payload),
    )


def local_disposal_target_exists(document: Document) -> bool:
    try:
        _storage().path_for(document.storage_key)
        return True
    except FileNotFoundError:
        return False


def delete_exact_local_disposal_target(
    document: Document,
    *,
    expected_storage_key_fingerprint: str,
    expected_file_hash: str,
    expected_file_size_bytes: int,
) -> None:
    target = inspect_local_disposal_target(document)
    if not all(
        (
            target.storage_key_fingerprint == expected_storage_key_fingerprint,
            target.file_hash == expected_file_hash,
            target.file_size_bytes == expected_file_size_bytes,
            document.file_hash.lower() == expected_file_hash,
            document.file_size_bytes == expected_file_size_bytes,
        )
    ):
        raise PhysicalDisposalStorageError("Bound local evidence target drifted before deletion")
    try:
        _storage().delete_physical(document.storage_key)
    except (OSError, StorageError) as exc:
        raise PhysicalDisposalStorageError("Exact local evidence deletion failed") from exc
    if local_disposal_target_exists(document):
        raise PhysicalDisposalStorageError("Local evidence target still exists after deletion")
