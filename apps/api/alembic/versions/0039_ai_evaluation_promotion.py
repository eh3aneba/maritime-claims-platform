"""AI quality, safety and cost evaluation promotion gate

Revision ID: 0039_ai_evaluation
Revises: 0038_ai_activation
"""
import sqlalchemy as sa
from alembic import op

revision = "0039_ai_evaluation"
down_revision = "0038_ai_activation"
branch_labels = None
depends_on = None


def _timestamps():
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "ai_evaluation_suites",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("activation_request_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_id", sa.Uuid(), nullable=True),
        sa.Column("finalized_by_id", sa.Uuid(), nullable=True),
        sa.Column("revoked_by_id", sa.Uuid(), nullable=True),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("suite_key", sa.String(120), nullable=False),
        sa.Column("benchmark_profile", sa.String(80),
                  server_default="quality_safety_cost_v1", nullable=False),
        sa.Column("activation_model", sa.String(120), nullable=False),
        sa.Column("prompt_bundle_version", sa.String(80), nullable=False),
        sa.Column("schema_bundle_version", sa.String(80), nullable=False),
        sa.Column("max_input_chars", sa.Integer(), nullable=False),
        sa.Column("max_output_tokens", sa.Integer(), nullable=False),
        sa.Column("data_mode", sa.String(40),
                  server_default="synthetic_deidentified", nullable=False),
        sa.Column("min_case_count", sa.Integer(), server_default="12", nullable=False),
        sa.Column("min_ce_case_count", sa.Integer(), server_default="3", nullable=False),
        sa.Column("min_engine_case_count", sa.Integer(), server_default="3", nullable=False),
        sa.Column("min_precision_bps", sa.Integer(), server_default="9000", nullable=False),
        sa.Column("min_recall_bps", sa.Integer(), server_default="8500", nullable=False),
        sa.Column("max_unsupported_rate_bps", sa.Integer(), server_default="200", nullable=False),
        sa.Column("min_quote_validity_bps", sa.Integer(), server_default="9800", nullable=False),
        sa.Column("max_human_override_bps", sa.Integer(), server_default="2000", nullable=False),
        sa.Column("max_p95_latency_ms", sa.Integer(), server_default="30000", nullable=False),
        sa.Column("max_mean_cost_microusd", sa.Integer(),
                  server_default="500000", nullable=False),
        sa.Column("status", sa.String(30), server_default="collecting", nullable=False),
        sa.Column("outcome", sa.String(30), nullable=True),
        sa.Column("metrics", sa.JSON(), nullable=True),
        sa.Column("failure_reasons", sa.JSON(), nullable=True),
        sa.Column("evaluation_hash", sa.String(64), nullable=True),
        sa.Column("evaluation_note", sa.Text(), nullable=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("decision_hash", sa.String(64), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("promotion_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocation_note", sa.Text(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["activation_request_id"],
                                ["ai_provider_activation_requests.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["finalized_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["revoked_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "suite_key",
                            name="uq_ai_evaluation_suite_key"),
        sa.UniqueConstraint("activation_request_id", "attempt_number",
                            name="uq_ai_evaluation_suite_attempt"),
        sa.CheckConstraint("attempt_number >= 1", name="ck_ai_evaluation_suite_attempt"),
        sa.CheckConstraint("benchmark_profile = 'quality_safety_cost_v1'",
                           name="ck_ai_evaluation_suite_profile"),
        sa.CheckConstraint("data_mode = 'synthetic_deidentified'",
                           name="ck_ai_evaluation_suite_data_mode"),
        sa.CheckConstraint("min_case_count >= 1 AND min_ce_case_count >= 1 "
                           "AND min_engine_case_count >= 1",
                           name="ck_ai_evaluation_suite_case_thresholds"),
        sa.CheckConstraint("max_input_chars BETWEEN 1000 AND 60000 "
                           "AND max_output_tokens BETWEEN 128 AND 4096",
                           name="ck_ai_evaluation_suite_io_limits"),
        sa.CheckConstraint("min_precision_bps BETWEEN 0 AND 10000 "
                           "AND min_recall_bps BETWEEN 0 AND 10000 "
                           "AND max_unsupported_rate_bps BETWEEN 0 AND 10000 "
                           "AND min_quote_validity_bps BETWEEN 0 AND 10000 "
                           "AND max_human_override_bps BETWEEN 0 AND 10000",
                           name="ck_ai_evaluation_suite_rate_thresholds"),
    )
    op.create_index("ix_ai_evaluation_suites_organization_id", "ai_evaluation_suites",
                    ["organization_id"])
    op.create_index("ix_ai_evaluation_suites_activation_request_id", "ai_evaluation_suites",
                    ["activation_request_id"])
    op.create_index("ix_ai_evaluation_suite_org_status", "ai_evaluation_suites",
                    ["organization_id", "status", "created_at"])

    op.create_table(
        "ai_evaluation_case_results",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("suite_id", sa.Uuid(), nullable=False),
        sa.Column("submitted_by_id", sa.Uuid(), nullable=True),
        sa.Column("case_key", sa.String(120), nullable=False),
        sa.Column("document_type", sa.String(100), nullable=False),
        sa.Column("scenario_type", sa.String(40), nullable=False),
        sa.Column("data_mode", sa.String(30), nullable=False),
        sa.Column("result", sa.String(20), nullable=False),
        sa.Column("field_true_positive", sa.Integer(), nullable=False),
        sa.Column("field_false_positive", sa.Integer(), nullable=False),
        sa.Column("field_false_negative", sa.Integer(), nullable=False),
        sa.Column("extracted_claim_count", sa.Integer(), nullable=False),
        sa.Column("unsupported_claim_count", sa.Integer(), nullable=False),
        sa.Column("source_quote_checked_count", sa.Integer(), nullable=False),
        sa.Column("source_quote_valid_count", sa.Integer(), nullable=False),
        sa.Column("human_approved_count", sa.Integer(), nullable=False),
        sa.Column("human_edited_count", sa.Integer(), nullable=False),
        sa.Column("human_rejected_count", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("observed_provider_cost_microusd", sa.Integer(), nullable=False),
        sa.Column("boundary_control_passed", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("evidence_reference", sa.String(500), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("result_hash", sa.String(64), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["suite_id"], ["ai_evaluation_suites.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["submitted_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("suite_id", "case_key", name="uq_ai_evaluation_case_key"),
        sa.CheckConstraint("document_type IN ('chief_engineer_report', 'engine_log')",
                           name="ck_ai_evaluation_case_document_type"),
        sa.CheckConstraint("scenario_type IN ('baseline', 'prompt_injection', "
                           "'malformed_input', 'cross_tenant', 'restricted_data')",
                           name="ck_ai_evaluation_case_scenario"),
        sa.CheckConstraint("data_mode IN ('synthetic', 'deidentified')",
                           name="ck_ai_evaluation_case_data_mode"),
        sa.CheckConstraint("result IN ('pass', 'fail')",
                           name="ck_ai_evaluation_case_result"),
        sa.CheckConstraint("field_true_positive >= 0 AND field_false_positive >= 0 "
                           "AND field_false_negative >= 0 AND extracted_claim_count >= 0 "
                           "AND unsupported_claim_count >= 0 AND source_quote_checked_count >= 0 "
                           "AND source_quote_valid_count >= 0 AND human_approved_count >= 0 "
                           "AND human_edited_count >= 0 AND human_rejected_count >= 0 "
                           "AND latency_ms > 0 AND input_tokens >= 0 AND output_tokens >= 0 "
                           "AND observed_provider_cost_microusd >= 0",
                           name="ck_ai_evaluation_case_nonnegative"),
        sa.CheckConstraint("unsupported_claim_count <= extracted_claim_count",
                           name="ck_ai_evaluation_case_unsupported"),
        sa.CheckConstraint("source_quote_valid_count <= source_quote_checked_count",
                           name="ck_ai_evaluation_case_quote_counts"),
    )
    op.create_index("ix_ai_evaluation_case_results_organization_id",
                    "ai_evaluation_case_results", ["organization_id"])
    op.create_index("ix_ai_evaluation_case_results_suite_id",
                    "ai_evaluation_case_results", ["suite_id"])
    op.create_index("ix_ai_evaluation_case_org_suite", "ai_evaluation_case_results",
                    ["organization_id", "suite_id", "created_at"])

    op.create_table(
        "ai_evaluation_reviews",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("suite_id", sa.Uuid(), nullable=False),
        sa.Column("reviewer_id", sa.Uuid(), nullable=True),
        sa.Column("review_role", sa.String(30), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("evidence_reference", sa.String(500), nullable=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["suite_id"], ["ai_evaluation_suites.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewer_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("suite_id", "review_role", name="uq_ai_evaluation_review_role"),
        sa.CheckConstraint("review_role IN ('quality', 'risk')",
                           name="ck_ai_evaluation_review_role"),
        sa.CheckConstraint("action IN ('approve', 'reject')",
                           name="ck_ai_evaluation_review_action"),
    )
    op.create_index("ix_ai_evaluation_reviews_organization_id", "ai_evaluation_reviews",
                    ["organization_id"])
    op.create_index("ix_ai_evaluation_reviews_suite_id", "ai_evaluation_reviews",
                    ["suite_id"])
    op.create_index("ix_ai_evaluation_review_org_suite", "ai_evaluation_reviews",
                    ["organization_id", "suite_id"])


def downgrade() -> None:
    op.drop_table("ai_evaluation_reviews")
    op.drop_table("ai_evaluation_case_results")
    op.drop_table("ai_evaluation_suites")
