"""Recovery/time-bar maturity: counterparties and human scenario lineage.

Revision ID: 0073_recovery_timebar_maturity
Revises: 0072_authoritative_reserve_lineage
"""
import sqlalchemy as sa
from alembic import op

revision = "0073_recovery_timebar_maturity"
down_revision = "0072_authoritative_reserve_lineage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "recovery_counterparties",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("counterparty_key", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("supersedes_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(240), nullable=False),
        sa.Column("role", sa.String(120), nullable=False),
        sa.Column("allegation_basis", sa.Text(), nullable=False),
        sa.Column("source_reference", sa.Text(), nullable=False),
        sa.Column("source_document_id", sa.Uuid(), nullable=True),
        sa.Column("source_document_family_id", sa.Uuid(), nullable=True),
        sa.Column("source_document_version", sa.Integer(), nullable=True),
        sa.Column("source_document_hash", sa.String(64), nullable=True),
        sa.Column("record_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["supersedes_id"], ["recovery_counterparties.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "claim_id", "counterparty_key", "version", name="uq_recovery_counterparty_version"),
        sa.CheckConstraint("version >= 1", name="ck_recovery_counterparty_version"),
        sa.CheckConstraint("source_document_version IS NULL OR source_document_version >= 1", name="ck_recovery_counterparty_document_version"),
    )
    op.create_index("ix_recovery_counterparty_claim", "recovery_counterparties", ["organization_id", "claim_id", "counterparty_key", "version"])
    op.create_index("ix_recovery_counterparties_organization_id", "recovery_counterparties", ["organization_id"])
    op.create_index("ix_recovery_counterparties_claim_id", "recovery_counterparties", ["claim_id"])
    op.create_index("ix_recovery_counterparties_counterparty_key", "recovery_counterparties", ["counterparty_key"])

    op.create_table(
        "timebar_scenarios",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("scenario_key", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("supersedes_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("counterparty_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(220), nullable=False),
        sa.Column("legal_basis", sa.Text(), nullable=False),
        sa.Column("source_reference", sa.Text(), nullable=False),
        sa.Column("source_document_id", sa.Uuid(), nullable=True),
        sa.Column("source_document_family_id", sa.Uuid(), nullable=True),
        sa.Column("source_document_version", sa.Integer(), nullable=True),
        sa.Column("source_document_hash", sa.String(64), nullable=True),
        sa.Column("anchor_date", sa.Date(), nullable=False),
        sa.Column("period_value", sa.Integer(), nullable=False),
        sa.Column("period_unit", sa.String(16), nullable=False),
        sa.Column("extension_value", sa.Integer(), nullable=True),
        sa.Column("extension_unit", sa.String(16), nullable=True),
        sa.Column("extension_basis", sa.Text(), nullable=True),
        sa.Column("assumptions", sa.Text(), nullable=False),
        sa.Column("candidate_deadline", sa.Date(), nullable=False),
        sa.Column("scenario_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["supersedes_id"], ["timebar_scenarios.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["counterparty_id"], ["recovery_counterparties.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "claim_id", "scenario_key", "version", name="uq_timebar_scenario_version"),
        sa.CheckConstraint("version >= 1", name="ck_timebar_scenario_version"),
        sa.CheckConstraint("period_value > 0", name="ck_timebar_scenario_period_value"),
        sa.CheckConstraint("period_unit IN ('days','months','years')", name="ck_timebar_scenario_period_unit"),
        sa.CheckConstraint("extension_value IS NULL OR extension_value >= 0", name="ck_timebar_scenario_extension_value"),
        sa.CheckConstraint("extension_unit IS NULL OR extension_unit IN ('days','months','years')", name="ck_timebar_scenario_extension_unit"),
        sa.CheckConstraint("source_document_version IS NULL OR source_document_version >= 1", name="ck_timebar_scenario_document_version"),
    )
    op.create_index("ix_timebar_scenario_claim", "timebar_scenarios", ["organization_id", "claim_id", "scenario_key", "version"])
    op.create_index("ix_timebar_scenarios_organization_id", "timebar_scenarios", ["organization_id"])
    op.create_index("ix_timebar_scenarios_claim_id", "timebar_scenarios", ["claim_id"])
    op.create_index("ix_timebar_scenarios_scenario_key", "timebar_scenarios", ["scenario_key"])

    op.create_table(
        "timebar_scenario_reviews",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("scenario_id", sa.Uuid(), nullable=False),
        sa.Column("reviewed_by_id", sa.Uuid(), nullable=True),
        sa.Column("scenario_hash", sa.String(64), nullable=False),
        sa.Column("review_number", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(24), nullable=False),
        sa.Column("confirmed_deadline", sa.Date(), nullable=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("source_reference", sa.Text(), nullable=True),
        sa.Column("previous_review_hash", sa.String(64), nullable=True),
        sa.Column("review_hash", sa.String(64), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["scenario_id"], ["timebar_scenarios.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scenario_id", "review_number", name="uq_timebar_scenario_review_number"),
        sa.CheckConstraint("review_number >= 1", name="ck_timebar_scenario_review_number"),
        sa.CheckConstraint("action IN ('confirm','override','reject','review_needed')", name="ck_timebar_scenario_review_action"),
    )
    op.create_index("ix_timebar_scenario_review", "timebar_scenario_reviews", ["organization_id", "claim_id", "scenario_id", "review_number"])
    op.create_index("ix_timebar_scenario_reviews_organization_id", "timebar_scenario_reviews", ["organization_id"])
    op.create_index("ix_timebar_scenario_reviews_claim_id", "timebar_scenario_reviews", ["claim_id"])
    op.create_index("ix_timebar_scenario_reviews_scenario_id", "timebar_scenario_reviews", ["scenario_id"])


def downgrade() -> None:
    op.drop_index("ix_timebar_scenario_reviews_scenario_id", table_name="timebar_scenario_reviews")
    op.drop_index("ix_timebar_scenario_reviews_claim_id", table_name="timebar_scenario_reviews")
    op.drop_index("ix_timebar_scenario_reviews_organization_id", table_name="timebar_scenario_reviews")
    op.drop_index("ix_timebar_scenario_review", table_name="timebar_scenario_reviews")
    op.drop_table("timebar_scenario_reviews")

    op.drop_index("ix_timebar_scenarios_scenario_key", table_name="timebar_scenarios")
    op.drop_index("ix_timebar_scenarios_claim_id", table_name="timebar_scenarios")
    op.drop_index("ix_timebar_scenarios_organization_id", table_name="timebar_scenarios")
    op.drop_index("ix_timebar_scenario_claim", table_name="timebar_scenarios")
    op.drop_table("timebar_scenarios")

    op.drop_index("ix_recovery_counterparties_counterparty_key", table_name="recovery_counterparties")
    op.drop_index("ix_recovery_counterparties_claim_id", table_name="recovery_counterparties")
    op.drop_index("ix_recovery_counterparties_organization_id", table_name="recovery_counterparties")
    op.drop_index("ix_recovery_counterparty_claim", table_name="recovery_counterparties")
    op.drop_table("recovery_counterparties")
