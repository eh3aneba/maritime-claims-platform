"""Private source-linked claim evidence search foundation

Revision ID: 0062_claim_evidence_search
Revises: 0061_severity_reserve_support
"""
import sqlalchemy as sa
from alembic import op

revision = "0062_claim_evidence_search"
down_revision = "0061_severity_reserve_support"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "claim_evidence_search_units",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("extraction_id", sa.Uuid(), nullable=False),
        sa.Column("segment_id", sa.Uuid(), nullable=False),
        sa.Column("document_family_id", sa.Uuid(), nullable=False),
        sa.Column("document_version", sa.Integer(), nullable=False),
        sa.Column("is_current_document", sa.Boolean(), nullable=False),
        sa.Column("document_type", sa.String(100), nullable=True),
        sa.Column("confidentiality_level", sa.String(24), nullable=False),
        sa.Column("source_file_hash", sa.String(64), nullable=False),
        sa.Column("extraction_text_hash", sa.String(64), nullable=True),
        sa.Column("normalized_text_hash", sa.String(64), nullable=False),
        sa.Column("locator_type", sa.String(30), nullable=False),
        sa.Column("locator_value", sa.String(100), nullable=False),
        sa.Column("index_version", sa.String(30), nullable=False),
        sa.Column("search_unit_hash", sa.String(64), nullable=False),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["extraction_id"], ["document_text_extractions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["segment_id"], ["document_text_segments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("segment_id", "index_version", name="uq_claim_evidence_search_unit_segment_version"),
    )
    op.create_index(
        "ix_claim_evidence_search_units_scope",
        "claim_evidence_search_units",
        ["organization_id", "claim_id", "is_current_document", "deactivated_at"],
    )
    op.create_index(
        "ix_claim_evidence_search_units_document",
        "claim_evidence_search_units",
        ["document_id", "document_version"],
    )
    op.create_index("ix_claim_evidence_search_units_organization_id", "claim_evidence_search_units", ["organization_id"])
    op.create_index("ix_claim_evidence_search_units_claim_id", "claim_evidence_search_units", ["claim_id"])
    op.create_index("ix_claim_evidence_search_units_document_id", "claim_evidence_search_units", ["document_id"])
    op.create_index("ix_claim_evidence_search_units_extraction_id", "claim_evidence_search_units", ["extraction_id"])
    op.create_index("ix_claim_evidence_search_units_segment_id", "claim_evidence_search_units", ["segment_id"])

    op.create_table(
        "claim_evidence_search_runs",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_id", sa.Uuid(), nullable=True),
        sa.Column("normalized_query_hash", sa.String(64), nullable=False),
        sa.Column("retrieval_mode", sa.String(20), nullable=False),
        sa.Column("ranking_version", sa.String(30), nullable=False),
        sa.Column("filters", sa.JSON(), nullable=False),
        sa.Column("filters_hash", sa.String(64), nullable=False),
        sa.Column("result_ledger", sa.JSON(), nullable=False),
        sa.Column("result_set_hash", sa.String(64), nullable=False),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("semantic_provider", sa.String(100), nullable=True),
        sa.Column("semantic_model", sa.String(120), nullable=True),
        sa.Column("semantic_authorization_hash", sa.String(64), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("result_count >= 0", name="ck_claim_evidence_search_run_result_count"),
        sa.CheckConstraint("latency_ms >= 0", name="ck_claim_evidence_search_run_latency"),
    )
    op.create_index(
        "ix_claim_evidence_search_runs_scope",
        "claim_evidence_search_runs",
        ["organization_id", "claim_id", "created_at"],
    )
    op.create_index("ix_claim_evidence_search_runs_organization_id", "claim_evidence_search_runs", ["organization_id"])
    op.create_index("ix_claim_evidence_search_runs_claim_id", "claim_evidence_search_runs", ["claim_id"])

    # PostgreSQL-only acceleration over the canonical source text. The search
    # projection deliberately does not duplicate raw evidence text.
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "CREATE INDEX ix_document_text_segments_search_fts "
            "ON document_text_segments USING gin (to_tsvector('simple', text))"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_document_text_segments_search_fts")

    op.drop_index("ix_claim_evidence_search_runs_claim_id", table_name="claim_evidence_search_runs")
    op.drop_index("ix_claim_evidence_search_runs_organization_id", table_name="claim_evidence_search_runs")
    op.drop_index("ix_claim_evidence_search_runs_scope", table_name="claim_evidence_search_runs")
    op.drop_table("claim_evidence_search_runs")

    op.drop_index("ix_claim_evidence_search_units_segment_id", table_name="claim_evidence_search_units")
    op.drop_index("ix_claim_evidence_search_units_extraction_id", table_name="claim_evidence_search_units")
    op.drop_index("ix_claim_evidence_search_units_document_id", table_name="claim_evidence_search_units")
    op.drop_index("ix_claim_evidence_search_units_claim_id", table_name="claim_evidence_search_units")
    op.drop_index("ix_claim_evidence_search_units_organization_id", table_name="claim_evidence_search_units")
    op.drop_index("ix_claim_evidence_search_units_document", table_name="claim_evidence_search_units")
    op.drop_index("ix_claim_evidence_search_units_scope", table_name="claim_evidence_search_units")
    op.drop_table("claim_evidence_search_units")
