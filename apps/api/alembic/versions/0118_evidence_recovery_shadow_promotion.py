"""add governed recovery shadow promotion rehearsal

Revision ID: 0118_evidence_recovery_shadow_promotion
Revises: 0117_evidence_recovery_promotion_attestation
"""

from alembic import op
import sqlalchemy as sa

revision = "0118_evidence_recovery_shadow_promotion"
down_revision = "0117_evidence_recovery_promotion_attestation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "evidence_recovery_shadow_promotions",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("attestation_id", sa.Uuid(), nullable=False),
        sa.Column("replica_id", sa.Uuid(), nullable=False),
        sa.Column("rehearsal_id", sa.Uuid(), nullable=False),
        sa.Column("restore_verification_id", sa.Uuid(), nullable=False),
        sa.Column("attestation_request_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("promotion_plan_hash", sa.String(length=64), nullable=False),
        sa.Column("configuration_fingerprint", sa.String(length=64), nullable=False),
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
        sa.Column("shadow_storage_key", sa.String(length=500), nullable=False),
        sa.Column("shadow_storage_key_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("shadow_file_hash", sa.String(length=64), nullable=False),
        sa.Column("shadow_file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("shadow_promotion_hash", sa.String(length=64), nullable=False),
        sa.Column("rehearsal_reason", sa.Text(), nullable=False),
        sa.Column("promoted_by_id", sa.Uuid(), nullable=False),
        sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("source_file_size_bytes >= 0", name="ck_evidence_recovery_shadow_promotion_source_size"),
        sa.CheckConstraint("shadow_file_size_bytes >= 0", name="ck_evidence_recovery_shadow_promotion_shadow_size"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["attestation_id"], ["evidence_recovery_promotion_attestations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["replica_id"], ["evidence_recovery_replicas.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["rehearsal_id"], ["evidence_recovery_restore_rehearsals.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["restore_verification_id"], ["evidence_recovery_restore_verifications.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["promoted_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("attestation_id", name="uq_evidence_recovery_shadow_promotion_attestation"),
        sa.UniqueConstraint("organization_id", "shadow_promotion_hash", name="uq_evidence_recovery_shadow_promotion_org_hash"),
    )
    for column in (
        "organization_id",
        "claim_id",
        "document_id",
        "attestation_id",
        "replica_id",
        "rehearsal_id",
        "restore_verification_id",
        "promoted_by_id",
    ):
        op.create_index(
            op.f(f"ix_evidence_recovery_shadow_promotions_{column}"),
            "evidence_recovery_shadow_promotions",
            [column],
            unique=False,
        )
    op.create_index(
        "ix_evidence_recovery_shadow_promotions_org_claim",
        "evidence_recovery_shadow_promotions",
        ["organization_id", "claim_id"],
        unique=False,
    )

    op.create_table(
        "evidence_recovery_shadow_verifications",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("attestation_id", sa.Uuid(), nullable=False),
        sa.Column("shadow_promotion_id", sa.Uuid(), nullable=False),
        sa.Column("expected_file_hash", sa.String(length=64), nullable=False),
        sa.Column("expected_file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("shadow_file_hash", sa.String(length=64), nullable=False),
        sa.Column("shadow_file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("promotion_plan_hash", sa.String(length=64), nullable=False),
        sa.Column("configuration_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("shadow_storage_key_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("verification_reason", sa.Text(), nullable=False),
        sa.Column("verification_hash", sa.String(length=64), nullable=False),
        sa.Column("verified_by_id", sa.Uuid(), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("expected_file_size_bytes >= 0", name="ck_evidence_recovery_shadow_verification_expected_size"),
        sa.CheckConstraint("shadow_file_size_bytes >= 0", name="ck_evidence_recovery_shadow_verification_shadow_size"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["attestation_id"], ["evidence_recovery_promotion_attestations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["shadow_promotion_id"], ["evidence_recovery_shadow_promotions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["verified_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "verification_hash", name="uq_evidence_recovery_shadow_verification_org_hash"),
    )
    for column in (
        "organization_id",
        "claim_id",
        "document_id",
        "attestation_id",
        "shadow_promotion_id",
        "verified_by_id",
    ):
        op.create_index(
            op.f(f"ix_evidence_recovery_shadow_verifications_{column}"),
            "evidence_recovery_shadow_verifications",
            [column],
            unique=False,
        )
    op.create_index(
        "ix_evidence_recovery_shadow_verifications_rehearsal_time",
        "evidence_recovery_shadow_verifications",
        ["shadow_promotion_id", "verified_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_evidence_recovery_shadow_verifications_rehearsal_time",
        table_name="evidence_recovery_shadow_verifications",
    )
    for column in (
        "verified_by_id",
        "shadow_promotion_id",
        "attestation_id",
        "document_id",
        "claim_id",
        "organization_id",
    ):
        op.drop_index(
            op.f(f"ix_evidence_recovery_shadow_verifications_{column}"),
            table_name="evidence_recovery_shadow_verifications",
        )
    op.drop_table("evidence_recovery_shadow_verifications")

    op.drop_index(
        "ix_evidence_recovery_shadow_promotions_org_claim",
        table_name="evidence_recovery_shadow_promotions",
    )
    for column in (
        "promoted_by_id",
        "restore_verification_id",
        "rehearsal_id",
        "replica_id",
        "attestation_id",
        "document_id",
        "claim_id",
        "organization_id",
    ):
        op.drop_index(
            op.f(f"ix_evidence_recovery_shadow_promotions_{column}"),
            table_name="evidence_recovery_shadow_promotions",
        )
    op.drop_table("evidence_recovery_shadow_promotions")
