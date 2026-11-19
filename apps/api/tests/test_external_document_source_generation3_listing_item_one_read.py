"""Tenant-scoped generation-3 listing/item read without result or integrity caching."""
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.modules.external_document_sources import generation_3_change_detection_service as service
from app.modules.external_document_sources.service import ExternalDocumentSourceConflictError


class _OneQueryResult:
    def __init__(self, row):
        self.row = row

    def one_or_none(self):
        return self.row


class _CaptureSession:
    def __init__(self, row):
        self.row = row
        self.calls = []

    def execute(self, statement):
        self.calls.append(statement)
        return _OneQueryResult(self.row)


def _checkpoint():
    return SimpleNamespace(
        organization_id=uuid4(),
        profile_id=uuid4(),
        listing_execution_id=uuid4(),
        metadata_item_id=uuid4(),
    )


def test_exact_item_and_listing_use_one_fresh_scoped_statement():
    listing = SimpleNamespace(id=uuid4())
    item = SimpleNamespace(item_kind="file", id=uuid4())
    checkpoint = _checkpoint()
    db = _CaptureSession((listing, item))
    for _ in range(3):
        loaded_listing, loaded_item = service._read_listing_and_exact_item(db, checkpoint)
        assert loaded_listing is listing
        assert loaded_item is item
    # Three separate DB executions, not one pre-fetched result reused.
    assert len(db.calls) == 3
    statement = db.calls[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "LEFT OUTER JOIN" in sql
    assert "external_doc_source_remote_metadata_list" in sql
    assert "ON " in sql and "execution_id" in sql
    assert "organization_id" in sql and "profile_id" in sql
    assert set(compiled.params.values()) == {
        checkpoint.organization_id,
        checkpoint.profile_id,
        checkpoint.listing_execution_id,
        checkpoint.metadata_item_id,
    }
    assert len(statement.column_descriptions) == 2
    # No rows, verdicts, completed receipt states or signature values cached.
    assert "populate_existing" not in statement.get_execution_options()


def test_no_listing_fails_with_original_distinct_error():
    db = _CaptureSession(None)
    with pytest.raises(ExternalDocumentSourceConflictError, match="metadata-listing lineage is missing"):
        service._read_listing_and_exact_item(db, _checkpoint())
    assert len(db.calls) == 1


@pytest.mark.parametrize("item_kind", [None, "directory"])
def test_missing_or_non_file_item_fails_closed(item_kind):
    listing = SimpleNamespace(id=uuid4())
    item = None if item_kind is None else SimpleNamespace(item_kind=item_kind)
    db = _CaptureSession((listing, item))
    with pytest.raises(ExternalDocumentSourceConflictError, match="exact metadata-item lineage"):
        service._read_listing_and_exact_item(db, _checkpoint())
    assert len(db.calls) == 1


def test_separate_tenants_bind_separate_ids_on_every_call():
    db = _CaptureSession((SimpleNamespace(id=uuid4()), SimpleNamespace(item_kind="file")))
    first, second = _checkpoint(), _checkpoint()
    service._read_listing_and_exact_item(db, first)
    service._read_listing_and_exact_item(db, second)
    assert len(db.calls) == 2
    parameters = [
        stmt.compile(dialect=postgresql.dialect()).params
        for stmt in db.calls
    ]
    assert first.organization_id in parameters[0].values()
    assert first.profile_id in parameters[0].values()
    assert second.organization_id in parameters[1].values()
    assert second.profile_id in parameters[1].values()
    assert first.organization_id not in parameters[1].values()
    assert second.organization_id not in parameters[0].values()
