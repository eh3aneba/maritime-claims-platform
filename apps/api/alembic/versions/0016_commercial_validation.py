"""design partner commercial validation

Revision ID: 0016_commercial_validation
Revises: 0015_pilot_instrumentation
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0016_commercial_validation"
down_revision: Union[str, None] = "0015_pilot_instrumentation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pilot_commercial_validations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("recorded_by_id", sa.Uuid(), nullable=True),
        sa.Column("annual_claim_volume", sa.Integer(), nullable=True),
        sa.Column("expected_users", sa.Integer(), nullable=True),
        sa.Column("fully_loaded_hourly_cost", sa.Numeric(14, 2), nullable=True),
        sa.Column("adoption_rate", sa.Numeric(5, 4), nullable=True),
        sa.Column("currency", sa.String(3), server_default="USD", nullable=False),
        sa.Column("buyer_role", sa.String(150), nullable=True),
        sa.Column("champion_role", sa.String(150), nullable=True),
        sa.Column("budget_owner_role", sa.String(150), nullable=True),
        sa.Column("procurement_owner_role", sa.String(150), nullable=True),
        sa.Column("security_approver_role", sa.String(150), nullable=True),
        sa.Column("budget_status", sa.String(30), server_default="unknown", nullable=False),
        sa.Column("buying_stage", sa.String(40), server_default="problem_validation", nullable=False),
        sa.Column("decision_timeline_days", sa.Integer(), nullable=True),
        sa.Column("pilot_fee_willingness", sa.Numeric(14, 2), nullable=True),
        sa.Column("annual_wtp_min", sa.Numeric(14, 2), nullable=True),
        sa.Column("annual_wtp_max", sa.Numeric(14, 2), nullable=True),
        sa.Column("preferred_pricing_model", sa.String(30), server_default="unknown", nullable=False),
        sa.Column("deployment_preference", sa.String(30), server_default="unknown", nullable=False),
        sa.Column("value_hypotheses", sa.JSON(), nullable=True),
        sa.Column("must_have_features", sa.JSON(), nullable=True),
        sa.Column("required_integrations", sa.JSON(), nullable=True),
        sa.Column("security_requirements", sa.JSON(), nullable=True),
        sa.Column("blockers", sa.JSON(), nullable=True),
        sa.Column("respondent_outcome", sa.String(30), server_default="unknown", nullable=False),
        sa.Column("next_step", sa.Text(), nullable=True),
        sa.Column("next_step_due_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("commercial_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("annual_claim_volume IS NULL OR annual_claim_volume >= 0", name="ck_pilot_commercial_annual_claim_volume_nonnegative"),
        sa.CheckConstraint("expected_users IS NULL OR expected_users >= 0", name="ck_pilot_commercial_expected_users_nonnegative"),
        sa.CheckConstraint("fully_loaded_hourly_cost IS NULL OR fully_loaded_hourly_cost >= 0", name="ck_pilot_commercial_hourly_cost_nonnegative"),
        sa.CheckConstraint("adoption_rate IS NULL OR (adoption_rate >= 0 AND adoption_rate <= 1)", name="ck_pilot_commercial_adoption_rate_range"),
        sa.CheckConstraint("pilot_fee_willingness IS NULL OR pilot_fee_willingness >= 0", name="ck_pilot_commercial_pilot_fee_nonnegative"),
        sa.CheckConstraint("annual_wtp_min IS NULL OR annual_wtp_min >= 0", name="ck_pilot_commercial_wtp_min_nonnegative"),
        sa.CheckConstraint("annual_wtp_max IS NULL OR annual_wtp_max >= 0", name="ck_pilot_commercial_wtp_max_nonnegative"),
        sa.CheckConstraint("decision_timeline_days IS NULL OR decision_timeline_days >= 0", name="ck_pilot_commercial_timeline_nonnegative"),
        sa.CheckConstraint("budget_status IN ('unknown','no_budget','exploring','budget_identified','approved')", name="ck_pilot_commercial_budget_status"),
        sa.CheckConstraint("buying_stage IN ('problem_validation','solution_evaluation','pilot','business_case','procurement','contracting','no_interest')", name="ck_pilot_commercial_buying_stage"),
        sa.CheckConstraint("deployment_preference IN ('unknown','cloud','private_cloud','on_prem')", name="ck_pilot_commercial_deployment_preference"),
        sa.CheckConstraint("preferred_pricing_model IN ('unknown','pilot_fee','annual_platform','per_user','per_claim','usage')", name="ck_pilot_commercial_pricing_model"),
        sa.CheckConstraint("respondent_outcome IN ('unknown','interested','pilot_extension','business_case','procurement','no_interest')", name="ck_pilot_commercial_outcome"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["session_id"], ["pilot_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["recorded_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", name="uq_pilot_commercial_validation_session"),
    )
    op.create_index("ix_pilot_commercial_org_created", "pilot_commercial_validations", ["organization_id", "created_at"])
    op.create_index(op.f("ix_pilot_commercial_validations_organization_id"), "pilot_commercial_validations", ["organization_id"])
    op.create_index(op.f("ix_pilot_commercial_validations_session_id"), "pilot_commercial_validations", ["session_id"])
    op.create_index(op.f("ix_pilot_commercial_validations_claim_id"), "pilot_commercial_validations", ["claim_id"])


def downgrade() -> None:
    op.drop_table("pilot_commercial_validations")
