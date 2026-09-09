"""add governed recovery promotion attestation

Revision ID: 0117_evidence_recovery_promotion_attestation
Revises: 0116_evidence_recovery_restore_rehearsal
"""

from alembic import op
import sqlalchemy as sa

revision = "0117_evidence_recovery_promotion_attestation"
down_revision = "0116_evidence_recovery_restore_rehearsal"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "evidence_recovery_promotion_attestations",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("replica_id", sa.Uuid(), nullable=False),
        sa.Column("rehearsal_id", sa.Uuid(), nullable=False),
        sa.Column("restore_verification_id", sa.Uuid(), nullable=False),
        sa.Column("replica_hash", sa.String(length=64), nullable=False),
        sa.Column("rehearsal_hash", sa.String(length=64), nullable=False),
        sa.Column("restore_verification_hash", sa.String(length=64), nullable=False),
        sa.Column("source_file_hash", sa.String(length=64), nullable=False),
        sa.Column("source_file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("source_document_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_storage_key_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("recovery_bucket_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("recovery_storage_key_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("staging_storage_key_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("configuration_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("promotion_plan", sa.JSON(), nullable=False),
        sa.Column("promotion_plan_hash", sa.String(length=64), nullable=False),
        sa.Column("request_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("requested_by_id", sa.Uuid(), nullable=False),
        sa.Column("request_reason", sa.Text(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attestation_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="pending_second_approval",
            nullable=False,
        ),
        sa.Column("approved_by_id", sa.Uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_by_id", sa.Uuid(), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidated_by_id", sa.Uuid(), nullable=True),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("cutover_performed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("authoritative_storage_changed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending_second_approval', 'approved', 'rejected', 'expired', 'invalidated')",
            name="ck_evidence_recovery_promotion_attestation_status",
        ),
        sa.CheckConstraint(
            "(status = 'pending_second_approval' AND approved_by_id IS NULL AND approved_at IS NULL "
            "AND rejected_by_id IS NULL AND rejected_at IS NULL AND invalidated_by_id IS NULL "
            "AND invalidated_at IS NULL AND decision_reason IS NULL) OR "
            "(status = 'approved' AND approved_by_id IS NOT NULL AND approved_at IS NOT NULL "
            "AND rejected_by_id IS NULL AND rejected_at IS NULL AND invalidated_by_id IS NULL "
            "AND invalidated_at IS NULL AND decision_reason IS NOT NULL) OR "
            "(status = 'rejected' AND approved_by_id IS NULL AND approved_at IS NULL "
            "AND rejected_by_id IS NOT NULL AND rejected_at IS NOT NULL AND invalidated_by_id IS NULL "
            "AND invalidated_at IS NULL AND decision_reason IS NOT NULL) OR "
            "(status IN ('expired', 'invalidated') AND approved_by_id IS NULL AND approved_at IS NULL "
            "AND rejected_by_id IS NULL AND rejected_at IS NULL AND invalidated_by_id IS NOT NULL "
            "AND invalidated_at IS NOT NULL AND decision_reason IS NOT NULL)",
            name="ck_evidence_recovery_promotion_attestation_lifecycle",
        ),
        sa.CheckConstraint(
            "requested_by_id <> approved_by_id OR approved_by_id IS NULL",
            name="ck_evidence_recovery_promotion_attestation_four_eyes",
        ),
        sa.CheckConstraint(
            "cutover_performed = false",
            name="ck_evidence_recovery_promotion_no_cutover",
        ),
        sa.CheckConstraint(
            "authoritative_storage_changed = false",
            name="ck_evidence_recovery_promotion_no_authority_change",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["replica_id"], ["evidence_recovery_replicas.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["rehearsal_id"], ["evidence_recovery_restore_rehearsals.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["restore_verification_id"],
            ["evidence_recovery_restore_verifications.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["approved_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["rejected_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["invalidated_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "request_snapshot_hash",
            name="uq_evidence_recovery_promotion_org_snapshot",
        ),
    )
    for column in (
        "organization_id",
        "claim_id",
        "document_id",
        "replica_id",
        "rehearsal_id",
        "restore_verification_id",
        "requested_by_id",
        "approved_by_id",
        "rejected_by_id",
        "invalidated_by_id",
    ):
        op.create_index(
            op.f(f"ix_evidence_recovery_promotion_attestations_{column}"),
            "evidence_recovery_promotion_attestations",
            [column],
            unique=False,
        )
    op.create_index(
        "ix_evidence_recovery_promotion_org_claim_status",
        "evidence_recovery_promotion_attestations",
        ["organization_id", "claim_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_evidence_recovery_promotion_org_document_status",
        "evidence_recovery_promotion_attestations",
        ["organization_id", "document_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_evidence_recovery_promotion_org_status_expiry",
        "evidence_recovery_promotion_attestations",
        ["organization_id", "status", "attestation_expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_evidence_recovery_promotion_org_status_expiry",
        table_name="evidence_recovery_promotion_attestations",
    )
    op.drop_index(
        "ix_evidence_recovery_promotion_org_document_status",
        table_name="evidence_recovery_promotion_attestations",
    )
    op.drop_index(
        "ix_evidence_recovery_promotion_org_claim_status",
        table_name="evidence_recovery_promotion_attestations",
    )
    for column in (
        "invalidated_by_id",
        "rejected_by_id",
        "approved_by_id",
        "requested_by_id",
        "restore_verification_id",
        "rehearsal_id",
        "replica_id",
        "document_id",
        "claim_id",
        "organization_id",
    ):
        op.drop_index(
            op.f(f"ix_evidence_recovery_promotion_attestations_{column}"),
            table_name="evidence_recovery_promotion_attestations",
        )
    op.drop_table("evidence_recovery_promotion_attestations")
