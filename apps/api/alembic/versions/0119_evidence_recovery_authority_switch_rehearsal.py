"""add governed recovery authority-switch rehearsal

Revision ID: 0119_evidence_recovery_authority_switch_rehearsal
Revises: 0118_evidence_recovery_shadow_promotion
"""

from alembic import op
import sqlalchemy as sa

revision = "0119_evidence_recovery_authority_switch_rehearsal"
down_revision = "0118_evidence_recovery_shadow_promotion"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "evidence_recovery_authority_switch_rehearsals",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("shadow_promotion_id", sa.Uuid(), nullable=False),
        sa.Column("attestation_id", sa.Uuid(), nullable=False),
        sa.Column("replica_id", sa.Uuid(), nullable=False),
        sa.Column("restore_rehearsal_id", sa.Uuid(), nullable=False),
        sa.Column("restore_verification_id", sa.Uuid(), nullable=False),
        sa.Column("shadow_verification_id", sa.Uuid(), nullable=False),
        sa.Column("attestation_request_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("promotion_plan_hash", sa.String(length=64), nullable=False),
        sa.Column("configuration_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("shadow_promotion_hash", sa.String(length=64), nullable=False),
        sa.Column("shadow_verification_hash", sa.String(length=64), nullable=False),
        sa.Column("source_file_hash", sa.String(length=64), nullable=False),
        sa.Column("source_storage_key_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("shadow_storage_key_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("lineage_hash", sa.String(length=64), nullable=False),
        sa.Column("source_authority_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("candidate_authority_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("contract_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="prepared", nullable=False),
        sa.Column("virtual_authority_class", sa.String(length=40), server_default="authoritative_source", nullable=False),
        sa.Column("virtual_authority_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("activation_lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("prepared_by_id", sa.Uuid(), nullable=False),
        sa.Column("prepared_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("preparation_reason", sa.Text(), nullable=False),
        sa.Column("activated_by_id", sa.Uuid(), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activation_reason", sa.Text(), nullable=True),
        sa.Column("rolled_back_by_id", sa.Uuid(), nullable=True),
        sa.Column("rolled_back_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rollback_reason", sa.Text(), nullable=True),
        sa.Column("terminal_by_id", sa.Uuid(), nullable=True),
        sa.Column("terminal_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terminal_reason", sa.Text(), nullable=True),
        sa.Column("cutover_performed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("authoritative_storage_changed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("document_storage_key_mutated", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("active_backend_changed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('prepared', 'activated', 'rolled_back', 'expired', 'invalidated')",
            name="ck_evidence_recovery_authority_switch_status",
        ),
        sa.CheckConstraint(
            "virtual_authority_class IN ('authoritative_source', 'recovery_shadow_candidate')",
            name="ck_evidence_recovery_authority_switch_virtual_class",
        ),
        sa.CheckConstraint(
            "prepared_by_id <> activated_by_id OR activated_by_id IS NULL",
            name="ck_evidence_recovery_authority_switch_four_eyes",
        ),
        sa.CheckConstraint("cutover_performed = false", name="ck_evidence_recovery_authority_switch_no_cutover"),
        sa.CheckConstraint(
            "authoritative_storage_changed = false",
            name="ck_evidence_recovery_authority_switch_no_authority_change",
        ),
        sa.CheckConstraint(
            "document_storage_key_mutated = false",
            name="ck_evidence_recovery_authority_switch_no_key_mutation",
        ),
        sa.CheckConstraint(
            "active_backend_changed = false",
            name="ck_evidence_recovery_authority_switch_no_backend_change",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["shadow_promotion_id"], ["evidence_recovery_shadow_promotions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["attestation_id"], ["evidence_recovery_promotion_attestations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["replica_id"], ["evidence_recovery_replicas.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["restore_rehearsal_id"], ["evidence_recovery_restore_rehearsals.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["restore_verification_id"], ["evidence_recovery_restore_verifications.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["shadow_verification_id"], ["evidence_recovery_shadow_verifications.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["prepared_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["activated_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["rolled_back_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["terminal_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("shadow_promotion_id", name="uq_evidence_recovery_authority_switch_shadow"),
        sa.UniqueConstraint(
            "organization_id",
            "contract_hash",
            name="uq_evidence_recovery_authority_switch_org_contract",
        ),
    )
    for column in (
        "organization_id",
        "claim_id",
        "document_id",
        "shadow_promotion_id",
        "attestation_id",
        "replica_id",
        "restore_rehearsal_id",
        "restore_verification_id",
        "shadow_verification_id",
        "prepared_by_id",
        "activated_by_id",
        "rolled_back_by_id",
        "terminal_by_id",
    ):
        op.create_index(
            op.f(f"ix_evidence_recovery_authority_switch_rehearsals_{column}"),
            "evidence_recovery_authority_switch_rehearsals",
            [column],
            unique=False,
        )
    op.create_index(
        "ix_evidence_recovery_authority_switch_org_claim_status",
        "evidence_recovery_authority_switch_rehearsals",
        ["organization_id", "claim_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_evidence_recovery_authority_switch_org_document_status",
        "evidence_recovery_authority_switch_rehearsals",
        ["organization_id", "document_id", "status"],
        unique=False,
    )

    op.create_table(
        "evidence_recovery_authority_switch_receipts",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("authority_switch_rehearsal_id", sa.Uuid(), nullable=False),
        sa.Column("shadow_promotion_id", sa.Uuid(), nullable=False),
        sa.Column("phase", sa.String(length=24), nullable=False),
        sa.Column("from_authority_class", sa.String(length=40), nullable=False),
        sa.Column("to_authority_class", sa.String(length=40), nullable=False),
        sa.Column("from_authority_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("to_authority_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("lineage_hash", sa.String(length=64), nullable=False),
        sa.Column("contract_hash", sa.String(length=64), nullable=False),
        sa.Column("receipt_hash", sa.String(length=64), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("transitioned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cutover_performed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("authoritative_storage_changed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "phase IN ('prepared', 'activated', 'rolled_back', 'expired', 'invalidated')",
            name="ck_evidence_recovery_authority_switch_receipt_phase",
        ),
        sa.CheckConstraint(
            "cutover_performed = false",
            name="ck_evidence_recovery_authority_switch_receipt_no_cutover",
        ),
        sa.CheckConstraint(
            "authoritative_storage_changed = false",
            name="ck_recovery_auth_switch_receipt_no_authority_change",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["authority_switch_rehearsal_id"],
            ["evidence_recovery_authority_switch_rehearsals.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["shadow_promotion_id"], ["evidence_recovery_shadow_promotions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "receipt_hash",
            name="uq_evidence_recovery_authority_switch_receipt_org_hash",
        ),
    )
    for column in (
        "organization_id",
        "claim_id",
        "document_id",
        "authority_switch_rehearsal_id",
        "shadow_promotion_id",
        "actor_id",
    ):
        op.create_index(
            op.f(f"ix_evidence_recovery_authority_switch_receipts_{column}"),
            "evidence_recovery_authority_switch_receipts",
            [column],
            unique=False,
        )
    op.create_index(
        "ix_evidence_recovery_authority_switch_receipt_rehearsal_time",
        "evidence_recovery_authority_switch_receipts",
        ["authority_switch_rehearsal_id", "transitioned_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_evidence_recovery_authority_switch_receipt_rehearsal_time",
        table_name="evidence_recovery_authority_switch_receipts",
    )
    for column in (
        "actor_id",
        "shadow_promotion_id",
        "authority_switch_rehearsal_id",
        "document_id",
        "claim_id",
        "organization_id",
    ):
        op.drop_index(
            op.f(f"ix_evidence_recovery_authority_switch_receipts_{column}"),
            table_name="evidence_recovery_authority_switch_receipts",
        )
    op.drop_table("evidence_recovery_authority_switch_receipts")

    op.drop_index(
        "ix_evidence_recovery_authority_switch_org_document_status",
        table_name="evidence_recovery_authority_switch_rehearsals",
    )
    op.drop_index(
        "ix_evidence_recovery_authority_switch_org_claim_status",
        table_name="evidence_recovery_authority_switch_rehearsals",
    )
    for column in (
        "terminal_by_id",
        "rolled_back_by_id",
        "activated_by_id",
        "prepared_by_id",
        "shadow_verification_id",
        "restore_verification_id",
        "restore_rehearsal_id",
        "replica_id",
        "attestation_id",
        "shadow_promotion_id",
        "document_id",
        "claim_id",
        "organization_id",
    ):
        op.drop_index(
            op.f(f"ix_evidence_recovery_authority_switch_rehearsals_{column}"),
            table_name="evidence_recovery_authority_switch_rehearsals",
        )
    op.drop_table("evidence_recovery_authority_switch_rehearsals")
