"""Guard that fresh Initial Assessments never list superseded documents.

Focused no-DB query contract; the protected browser HM-04 test separately
verifies the full upload/version/staleness behavior in a real SQL database.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from app.modules.assessments.service import _docs


def test_initial_assessment_current_document_projection_filters_superseded_rows():
    db = MagicMock()
    db.scalars.return_value = []
    claim = SimpleNamespace(id=uuid4(), organization_id=uuid4())
    assert _docs(db, claim) == []
    query = db.scalars.call_args.args[0]
    sql = str(query).lower()
    assert "documents.organization_id =" in sql
    assert "documents.claim_id =" in sql
    assert "documents.deleted_at is null" in sql
    assert "documents.is_current is true" in sql
    assert "order by documents.created_at" in sql
