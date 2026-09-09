"""add governed evidence recovery replication

Revision ID: 0115_evidence_recovery_replication
Revises: 0114_disposal_release_review
"""

from alembic import op
import sqlalchemy as sa

revision = "0115_evidence_recovery_replication"
down_revision = "0114_disposal_release_review"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "evidence_recovery_replicas",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("source_file_hash", sa.String(length=64), nullable=False),
        sa.Column("source_file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("source_document_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_storage_key_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("recovery_storage_key", sa.String(length=500), nullable=False),
        sa.Column("recovery_bucket_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("remote_etag", sa.String(length=128), nullable=True),
        sa.Column("replica_hash", sa.String(length=64), nullable=False),
        sa.Column("request_reason", sa.Text(), nullable=False),
        sa.Column("replicated_by_id", sa.Uuid(), nullable=False),
        sa.Column("replicated_at", sa.DateTime(timezone=True), nullable=False),
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
            name="ck_evidence_recovery_replica_source_size",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["replicated_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", name="uq_evidence_recovery_replica_document"),
        sa.UniqueConstraint(
            "organization_id",
            "replica_hash",
            name="uq_evidence_recovery_replica_org_hash",
        ),
    )
    for column in ("organization_id", "claim_id", "document_id", "replicated_by_id"):
        op.create_index(
            op.f(f"ix_evidence_recovery_replicas_{column}"),
            "evidence_recovery_replicas",
            [column],
            unique=False,
        )
    op.create_index(
        "ix_evidence_recovery_replicas_org_claim",
        "evidence_recovery_replicas",
        ["organization_id", "claim_id"],
        unique=False,
    )

    op.create_table(
        "evidence_recovery_verifications",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("replica_id", sa.Uuid(), nullable=False),
        sa.Column("expected_file_hash", sa.String(length=64), nullable=False),
        sa.Column("expected_file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("observed_file_hash", sa.String(length=64), nullable=False),
        sa.Column("observed_file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("recovery_bucket_fingerprint", sa.String(length=64), nullable=False),
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
            name="ck_evidence_recovery_verification_expected_size",
        ),
        sa.CheckConstraint(
            "observed_file_size_bytes >= 0",
            name="ck_evidence_recovery_verification_observed_size",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["replica_id"], ["evidence_recovery_replicas.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["verified_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "verification_hash",
            name="uq_evidence_recovery_verification_org_hash",
        ),
    )
    for column in (
        "organization_id",
        "claim_id",
        "document_id",
        "replica_id",
        "verified_by_id",
    ):
        op.create_index(
            op.f(f"ix_evidence_recovery_verifications_{column}"),
            "evidence_recovery_verifications",
            [column],
            unique=False,
        )
    op.create_index(
        "ix_evidence_recovery_verifications_org_claim",
        "evidence_recovery_verifications",
        ["organization_id", "claim_id"],
        unique=False,
    )
    op.create_index(
        "ix_evidence_recovery_verifications_replica_time",
        "evidence_recovery_verifications",
        ["replica_id", "verified_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_evidence_recovery_verifications_replica_time",
        table_name="evidence_recovery_verifications",
    )
    op.drop_index(
        "ix_evidence_recovery_verifications_org_claim",
        table_name="evidence_recovery_verifications",
    )
    for column in (
        "verified_by_id",
        "replica_id",
        "document_id",
        "claim_id",
        "organization_id",
    ):
        op.drop_index(
            op.f(f"ix_evidence_recovery_verifications_{column}"),
            table_name="evidence_recovery_verifications",
        )
    op.drop_table("evidence_recovery_verifications")

    op.drop_index(
        "ix_evidence_recovery_replicas_org_claim",
        table_name="evidence_recovery_replicas",
    )
    for column in ("replicated_by_id", "document_id", "claim_id", "organization_id"):
        op.drop_index(
            op.f(f"ix_evidence_recovery_replicas_{column}"),
            table_name="evidence_recovery_replicas",
        )
    op.drop_table("evidence_recovery_replicas")
