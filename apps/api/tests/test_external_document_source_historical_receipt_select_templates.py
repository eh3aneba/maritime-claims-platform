"""Receipt SELECT shape is reusable; the database read and integrity refresh are not."""
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.modules.external_document_sources import checkpoint_generation_3_service
from app.modules.external_document_sources import successor_change_detection_service
from app.modules.external_document_sources import successor_versioned_restaging_service


_SERVICES = (
    checkpoint_generation_3_service,
    successor_versioned_restaging_service,
    successor_change_detection_service,
)


@pytest.mark.parametrize("service", _SERVICES)
def test_nested_receipt_select_binds_each_tenant_and_execution_on_every_call(service):
    seen = []

    class Rows:
        def __init__(self, value):
            self.value = value

        def all(self):
            return [self.value]

    class CaptureSession:
        def scalars(self, stmt, parameters):
            # Fake Session only: real PostgreSQL cross-Session tampering is
            # tested by test_nested_historical_receipt_reads_detect_... .
            seen.append((stmt, dict(parameters)))
            return Rows((parameters["receipt_organization_id"],
                         parameters["receipt_execution_id"]))

    first = SimpleNamespace(organization_id=uuid4(), id=uuid4())
    second = SimpleNamespace(organization_id=uuid4(), id=uuid4())
    db = CaptureSession()
    assert service._receipts(db, first) == [(first.organization_id, first.id)]
    assert service._receipts(db, second) == [(second.organization_id, second.id)]
    assert service._receipts(db, first) == [(first.organization_id, first.id)]

    assert len(seen) == 3
    assert seen[0][0] is seen[1][0] is seen[2][0]
    assert seen[0][1] == seen[2][1] != seen[1][1]
    for statement, params in seen:
        assert set(params) == {"receipt_organization_id", "receipt_execution_id"}
        assert statement.get_execution_options()["populate_existing"] is True
        query = str(statement.compile(dialect=postgresql.dialect()))
        assert "%(receipt_organization_id)s" in query
        assert "%(receipt_execution_id)s" in query
        assert "ORDER BY" in query and "sequence_number ASC" in query


def test_each_historical_receipt_service_uses_distinct_model_and_typed_bindings():
    statements = []
    for service in _SERVICES:
        names = [name for name in vars(service)
                 if name.endswith("_RECEIPTS_SELECT")
                 and name.startswith("_")]
        assert len(names) == 1, (service.__name__, names)
        stmt = getattr(service, names[0])
        statements.append(stmt)
        compiled = stmt.compile(dialect=postgresql.dialect())
        assert compiled.params == {
            "receipt_organization_id": None,
            "receipt_execution_id": None,
        }
        assert stmt.get_execution_options()["populate_existing"] is True
    assert len({stmt.column_descriptions[0]["entity"]
                for stmt in statements}) == 3
