"""Governed structured Claim Q&A synthesis ledger

Revision ID: 0063_claim_qa_synthesis
Revises: 0062_claim_evidence_search
"""
import sqlalchemy as sa
from alembic import op

revision = "0063_claim_qa_synthesis"
down_revision = "0062_claim_evidence_search"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "claim_qa_synthesis_runs",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_id", sa.Uuid(), nullable=True),
        sa.Column("retrieval_run_id", sa.Uuid(), nullable=True),
        sa.Column("production_authorization_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("failure_code", sa.String(80), nullable=True),
        sa.Column("fallback_used", sa.Boolean(), nullable=False),
        sa.Column("provider_call_made", sa.Boolean(), nullable=False),
        sa.Column("provider", sa.String(80), nullable=True),
        sa.Column("model", sa.String(120), nullable=True),
        sa.Column("prompt_bundle_version", sa.String(80), nullable=True),
        sa.Column("schema_bundle_version", sa.String(80), nullable=True),
        sa.Column("authorization_hash", sa.String(64), nullable=True),
        sa.Column("eligibility_policy_hash", sa.String(64), nullable=True),
        sa.Column("question_hash", sa.String(64), nullable=False),
        sa.Column("result_set_hash", sa.String(64), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=True),
        sa.Column("output_hash", sa.String(64), nullable=True),
        sa.Column("answer_hash", sa.String(64), nullable=False),
        sa.Column("source_unit_ids", sa.JSON(), nullable=False),
        sa.Column("source_count", sa.Integer(), nullable=False),
        sa.Column("input_chars", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("provider_response_id_hash", sa.String(64), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["retrieval_run_id"], ["claim_evidence_search_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["production_authorization_id"], ["ai_production_wide_authorizations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('completed','blocked','verification_failed','provider_error','extractive_bypass')",
            name="ck_claim_qa_synthesis_status",
        ),
        sa.CheckConstraint("source_count >= 0", name="ck_claim_qa_synthesis_source_count"),
        sa.CheckConstraint("input_chars >= 0", name="ck_claim_qa_synthesis_input_chars"),
        sa.CheckConstraint("latency_ms >= 0", name="ck_claim_qa_synthesis_latency_ms"),
    )
    op.create_index(
        "ix_claim_qa_synthesis_scope",
        "claim_qa_synthesis_runs",
        ["organization_id", "claim_id", "created_at"],
    )
    op.create_index(
        "ix_claim_qa_synthesis_authorization",
        "claim_qa_synthesis_runs",
        ["production_authorization_id", "created_at"],
    )
    op.create_index("ix_claim_qa_synthesis_runs_organization_id", "claim_qa_synthesis_runs", ["organization_id"])
    op.create_index("ix_claim_qa_synthesis_runs_claim_id", "claim_qa_synthesis_runs", ["claim_id"])
    op.create_index("ix_claim_qa_synthesis_runs_retrieval_run_id", "claim_qa_synthesis_runs", ["retrieval_run_id"])
    op.create_index(
        "ix_claim_qa_synthesis_runs_production_authorization_id",
        "claim_qa_synthesis_runs",
        ["production_authorization_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_claim_qa_synthesis_runs_production_authorization_id", table_name="claim_qa_synthesis_runs")
    op.drop_index("ix_claim_qa_synthesis_runs_retrieval_run_id", table_name="claim_qa_synthesis_runs")
    op.drop_index("ix_claim_qa_synthesis_runs_claim_id", table_name="claim_qa_synthesis_runs")
    op.drop_index("ix_claim_qa_synthesis_runs_organization_id", table_name="claim_qa_synthesis_runs")
    op.drop_index("ix_claim_qa_synthesis_authorization", table_name="claim_qa_synthesis_runs")
    op.drop_index("ix_claim_qa_synthesis_scope", table_name="claim_qa_synthesis_runs")
    op.drop_table("claim_qa_synthesis_runs")
