"""controlled settlement and payment authorization ledger

Revision ID: 0025_settlement_payment_ledger
Revises: 0024_adjustment_controls
"""
import sqlalchemy as sa
from alembic import op

revision = "0025_settlement_payment_ledger"
down_revision = "0024_adjustment_controls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    settlement_status = sa.Enum("draft", "under_review", "approved", "rejected", "accepted", "declined", "withdrawn", name="settlement_status")
    settlement_type = sa.Enum("interim", "partial", "final", name="settlement_type")
    payment_status = sa.Enum("draft", "under_review", "first_approved", "authorized", "rejected", "paid_externally", "cancelled", name="payment_status")
    op.create_table(
        "settlement_proposals",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("adjustment_statement_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("reviewed_by_id", sa.Uuid(), nullable=True),
        sa.Column("disposition_by_id", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("settlement_type", settlement_type, nullable=False),
        sa.Column("status", settlement_status, server_default="draft", nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("terms", sa.Text(), nullable=False),
        sa.Column("release_required", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("without_prejudice", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("expires_on", sa.Date(), nullable=True),
        sa.Column("source_adjustment_hash", sa.String(64), nullable=False),
        sa.Column("source_snapshot", sa.JSON(), nullable=False),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("disposition_note", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disposition_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("amount > 0", name="ck_settlement_amount_positive"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["adjustment_statement_id"], ["adjustment_statements.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reviewed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["disposition_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("claim_id", "version", name="uq_settlement_claim_version"),
    )
    for name, cols in [
        ("ix_settlement_proposals_organization_id", ["organization_id"]),
        ("ix_settlement_proposals_claim_id", ["claim_id"]),
        ("ix_settlement_proposals_adjustment_statement_id", ["adjustment_statement_id"]),
        ("ix_settlement_org_claim_created", ["organization_id", "claim_id", "created_at"]),
    ]:
        op.create_index(name, "settlement_proposals", cols)

    op.create_table(
        "payment_authorizations",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("settlement_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("first_approved_by_id", sa.Uuid(), nullable=True),
        sa.Column("second_approved_by_id", sa.Uuid(), nullable=True),
        sa.Column("paid_recorded_by_id", sa.Uuid(), nullable=True),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("status", payment_status, server_default="draft", nullable=False),
        sa.Column("payee", sa.String(240), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("first_approval_note", sa.Text(), nullable=True),
        sa.Column("second_approval_note", sa.Text(), nullable=True),
        sa.Column("rejection_note", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column("first_approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("second_approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_channel", sa.String(60), nullable=True),
        sa.Column("external_reference", sa.String(240), nullable=True),
        sa.Column("value_date", sa.Date(), nullable=True),
        sa.Column("paid_note", sa.Text(), nullable=True),
        sa.Column("paid_recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("amount > 0", name="ck_payment_amount_positive"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["settlement_id"], ["settlement_proposals.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["first_approved_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["second_approved_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["paid_recorded_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("settlement_id", "sequence", name="uq_payment_settlement_sequence"),
    )
    for name, cols in [
        ("ix_payment_authorizations_organization_id", ["organization_id"]),
        ("ix_payment_authorizations_claim_id", ["claim_id"]),
        ("ix_payment_authorizations_settlement_id", ["settlement_id"]),
        ("ix_payment_org_claim_created", ["organization_id", "claim_id", "created_at"]),
    ]:
        op.create_index(name, "payment_authorizations", cols)


def downgrade() -> None:
    for name in ["ix_payment_org_claim_created", "ix_payment_authorizations_settlement_id", "ix_payment_authorizations_claim_id", "ix_payment_authorizations_organization_id"]:
        op.drop_index(name, table_name="payment_authorizations")
    op.drop_table("payment_authorizations")
    for name in ["ix_settlement_org_claim_created", "ix_settlement_proposals_adjustment_statement_id", "ix_settlement_proposals_claim_id", "ix_settlement_proposals_organization_id"]:
        op.drop_index(name, table_name="settlement_proposals")
    op.drop_table("settlement_proposals")
    sa.Enum(name="payment_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="settlement_type").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="settlement_status").drop(op.get_bind(), checkfirst=True)
