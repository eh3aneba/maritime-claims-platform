from app.db.metadata import Base


def test_database_foundation_tables_present() -> None:
    expected = {"organizations", "users", "vessels", "claims", "documents", "audit_logs"}
    assert expected.issubset(Base.metadata.tables.keys())


def test_claims_have_tenant_column() -> None:
    claims = Base.metadata.tables["claims"]
    assert "organization_id" in claims.c


def test_documents_have_hash_and_tenant_columns() -> None:
    documents = Base.metadata.tables["documents"]
    assert "organization_id" in documents.c
    assert "file_hash" in documents.c
    assert "malware_scan_status" in documents.c


def test_quarantined_uploads_are_separate_from_active_documents() -> None:
    quarantined = Base.metadata.tables["quarantined_uploads"]
    assert "organization_id" in quarantined.c
    assert "claim_id" in quarantined.c
    assert "quarantine_key" in quarantined.c
    assert "status" in quarantined.c
    assert "source_document_id" in quarantined.c
    assert "resolved_by_id" in quarantined.c
    assert "resolution_note" in quarantined.c


def test_audit_log_is_immutable_shape() -> None:
    audit = Base.metadata.tables["audit_logs"]
    assert "created_at" in audit.c
    assert "updated_at" not in audit.c
    assert "deleted_at" not in audit.c


def test_enum_columns_persist_public_values() -> None:
    claims = Base.metadata.tables["claims"]
    assert claims.c.status.type.enums[0] == "new"
    users = Base.metadata.tables["users"]
    assert users.c.role.type.enums == ["admin", "claims_manager", "claims_handler"]


def test_document_processing_foundation_tables_exist() -> None:
    expected = {"document_processing_jobs", "document_text_extractions", "document_text_segments"}
    assert expected.issubset(set(Base.metadata.tables))


def test_human_reviewed_claim_intake_tables_exist() -> None:
    expected = {"claim_intake_drafts", "claim_intake_processing_jobs"}
    assert expected.issubset(set(Base.metadata.tables))
    drafts = Base.metadata.tables["claim_intake_drafts"]
    assert {"organization_id", "file_hash", "status", "approved_claim_id", "source_document_id"}.issubset(
        drafts.c.keys()
    )


def test_rules_engine_tables_exist() -> None:
    expected = {"claim_document_requirements", "claim_issues", "rule_evaluation_runs"}
    assert expected.issubset(set(Base.metadata.tables))


def test_requirement_lineage_tables_exist() -> None:
    expected = {"claim_document_requirement_states", "claim_document_requirement_decisions"}
    assert expected.issubset(set(Base.metadata.tables))
    state = Base.metadata.tables["claim_document_requirement_states"]
    decisions = Base.metadata.tables["claim_document_requirement_decisions"]
    assert {"requirement_id", "state_fingerprint", "state_version"}.issubset(state.c.keys())
    assert {
        "requirement_id",
        "state_fingerprint",
        "state_version",
        "decision_number",
        "decision_hash",
        "previous_decision_hash",
        "claim_fact_version",
    }.issubset(decisions.c.keys())


def test_rule_driven_task_tables_exist() -> None:
    assert "claim_tasks" in Base.metadata.tables
    assert "document_request_batches" in Base.metadata.tables
    correspondence = Base.metadata.tables["claim_correspondence"]
    assert {"organization_id", "claim_id", "status", "content_hash", "request_batch_id"}.issubset(correspondence.c.keys())
    statement = Base.metadata.tables["adjustment_statements"]
    line = Base.metadata.tables["adjustment_lines"]
    assert {"organization_id", "claim_id", "version", "status", "content_hash", "net_adjusted"}.issubset(statement.c.keys())
    assert {"statement_id", "cost_item_id", "claimed_amount", "considered_amount", "treatment", "basis"}.issubset(line.c.keys())