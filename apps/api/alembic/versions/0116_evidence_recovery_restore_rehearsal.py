"""add governed evidence recovery restore rehearsal

Revision ID: 0116_evidence_recovery_restore_rehearsal
Revises: 0115_evidence_recovery_replication
"""

from alembic import op
import sqlalchemy as sa

revision = "0116_evidence_recovery_restore_rehearsal"
down_revision = "0115_evidence_recovery_replication"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "evidence_recovery_restore_rehearsals",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("replica_id", sa.Uuid(), nullable=False),
        sa.Column("replica_hash", sa.String(length=64), nullable=False),
        sa.Column("source_file_hash", sa.String(length=64), nullable=False),
        sa.Column("source_file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("source_document_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_storage_key_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("recovery_bucket_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("recovery_storage_key_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("staging_storage_key", sa.String(length=500), nullable=False),
        sa.Column("staging_storage_key_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("restored_file_hash", sa.String(length=64), nullable=False),
        sa.Column("restored_file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("remote_etag", sa.String(length=128), nullable=True),
        sa.Column("rehearsal_hash", sa.String(length=64), nullable=False),
        sa.Column("request_reason", sa.Text(), nullable=False),
        sa.Column("restored_by_id", sa.Uuid(), nullable=False),
        sa.Column("restored_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
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
            "source_file_size_bytes >= 0",
            name="ck_evidence_recovery_restore_rehearsal_source_size",
        ),
        sa.CheckConstraint(
            "restored_file_size_bytes >= 0",
            name="ck_evidence_recovery_restore_rehearsal_restored_size",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["replica_id"], ["evidence_recovery_replicas.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["restored_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "replica_id",
            name="uq_evidence_recovery_restore_rehearsal_replica",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "rehearsal_hash",
            name="uq_evidence_recovery_restore_rehearsal_org_hash",
        ),
    )
    for column in (
        "organization_id",
        "claim_id",
        "document_id",
        "replica_id",
        "restored_by_id",
    ):
        op.create_index(
            op.f(f"ix_evidence_recovery_restore_rehearsals_{column}"),
            "evidence_recovery_restore_rehearsals",
            [column],
            unique=False,
        )
    op.create_index(
        "ix_evidence_recovery_restore_rehearsals_org_claim",
        "evidence_recovery_restore_rehearsals",
        ["organization_id", "claim_id"],
        unique=False,
    )

    op.create_table(
        "evidence_recovery_restore_verifications",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("replica_id", sa.Uuid(), nullable=False),
        sa.Column("rehearsal_id", sa.Uuid(), nullable=False),
        sa.Column("expected_file_hash", sa.String(length=64), nullable=False),
        sa.Column("expected_file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("remote_file_hash", sa.String(length=64), nullable=False),
        sa.Column("remote_file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("staged_file_hash", sa.String(length=64), nullable=False),
        sa.Column("staged_file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("recovery_bucket_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("staging_storage_key_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("remote_etag", sa.String(length=128), nullable=True),
        sa.Column("verification_reason", sa.Text(), nullable=False),
        sa.Column("verification_hash", sa.String(length=64), nullable=False),
        sa.Column("verified_by_id", sa.Uuid(), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
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
            "expected_file_size_bytes >= 0",
            name="ck_evidence_recovery_restore_verification_expected_size",
        ),
        sa.CheckConstraint(
            "remote_file_size_bytes >= 0",
            name="ck_evidence_recovery_restore_verification_remote_size",
        ),
        sa.CheckConstraint(
            "staged_file_size_bytes >= 0",
            name="ck_evidence_recovery_restore_verification_staged_size",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["replica_id"], ["evidence_recovery_replicas.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["rehearsal_id"],
            ["evidence_recovery_restore_rehearsals.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["verified_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "verification_hash",
            name="uq_evidence_recovery_restore_verification_org_hash",
        ),
    )
    for column in (
        "organization_id",
        "claim_id",
        "document_id",
        "replica_id",
        "rehearsal_id",
        "verified_by_id",
    ):
        op.create_index(
            op.f(f"ix_evidence_recovery_restore_verifications_{column}"),
            "evidence_recovery_restore_verifications",
            [column],
            unique=False,
        )
    op.create_index(
        "ix_evidence_recovery_restore_verifications_org_claim",
        "evidence_recovery_restore_verifications",
        ["organization_id", "claim_id"],
        unique=False,
    )
    op.create_index(
        "ix_evidence_recovery_restore_verifications_rehearsal_time",
        "evidence_recovery_restore_verifications",
        ["rehearsal_id", "verified_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_evidence_recovery_restore_verifications_rehearsal_time",
        table_name="evidence_recovery_restore_verifications",
    )
    op.drop_index(
        "ix_evidence_recovery_restore_verifications_org_claim",
        table_name="evidence_recovery_restore_verifications",
    )
    for column in (
        "verified_by_id",
        "rehearsal_id",
        "replica_id",
        "document_id",
        "claim_id",
        "organization_id",
    ):
        op.drop_index(
            op.f(f"ix_evidence_recovery_restore_verifications_{column}"),
            table_name="evidence_recovery_restore_verifications",
        )
    op.drop_table("evidence_recovery_restore_verifications")

    op.drop_index(
        "ix_evidence_recovery_restore_rehearsals_org_claim",
        table_name="evidence_recovery_restore_rehearsals",
    )
    for column in (
        "restored_by_id",
        "replica_id",
        "document_id",
        "claim_id",
        "organization_id",
    ):
        op.drop_index(
            op.f(f"ix_evidence_recovery_restore_rehearsals_{column}"),
            table_name="evidence_recovery_restore_rehearsals",
        )
    op.drop_table("evidence_recovery_restore_rehearsals")
