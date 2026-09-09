"""add governed recovery cutover admission

Revision ID: 0120_recovery_cutover_admission
Revises: 0119_evidence_recovery_authority_switch_rehearsal
"""

from alembic import op
import sqlalchemy as sa

revision = "0120_recovery_cutover_admission"
down_revision = "0119_evidence_recovery_authority_switch_rehearsal"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "evidence_recovery_cutover_admissions",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("authority_switch_rehearsal_id", sa.Uuid(), nullable=False),
        sa.Column("activation_receipt_id", sa.Uuid(), nullable=False),
        sa.Column("rollback_receipt_id", sa.Uuid(), nullable=False),
        sa.Column("shadow_promotion_id", sa.Uuid(), nullable=False),
        sa.Column("attestation_id", sa.Uuid(), nullable=False),
        sa.Column("replica_id", sa.Uuid(), nullable=False),
        sa.Column("restore_rehearsal_id", sa.Uuid(), nullable=False),
        sa.Column("restore_verification_id", sa.Uuid(), nullable=False),
        sa.Column("shadow_verification_id", sa.Uuid(), nullable=False),
        sa.Column("rehearsal_contract_hash", sa.String(length=64), nullable=False),
        sa.Column("rehearsal_lineage_hash", sa.String(length=64), nullable=False),
        sa.Column("activation_receipt_hash", sa.String(length=64), nullable=False),
        sa.Column("rollback_receipt_hash", sa.String(length=64), nullable=False),
        sa.Column("transition_proof_hash", sa.String(length=64), nullable=False),
        sa.Column("source_authority_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("candidate_authority_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("configuration_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("request_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("admission_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="pending_second_approval", nullable=False),
        sa.Column("admission_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("requested_by_id", sa.Uuid(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_reason", sa.Text(), nullable=False),
        sa.Column("approved_by_id", sa.Uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approval_reason", sa.Text(), nullable=True),
        sa.Column("rejected_by_id", sa.Uuid(), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("terminal_by_id", sa.Uuid(), nullable=True),
        sa.Column("terminal_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terminal_reason", sa.Text(), nullable=True),
        sa.Column("cutover_performed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("authoritative_storage_changed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("document_storage_key_mutated", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("active_backend_changed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("production_execution_token_created", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("execution_authority_created", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending_second_approval', 'approved', 'rejected', 'expired', 'invalidated')",
            name="ck_recovery_cutover_adm_status",
        ),
        sa.CheckConstraint("requested_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_recovery_cutover_adm_four_eyes"),
        sa.CheckConstraint("cutover_performed = false", name="ck_recovery_cutover_adm_no_cutover"),
        sa.CheckConstraint("authoritative_storage_changed = false", name="ck_recovery_cutover_adm_no_authority"),
        sa.CheckConstraint("document_storage_key_mutated = false", name="ck_recovery_cutover_adm_no_key_mutation"),
        sa.CheckConstraint("active_backend_changed = false", name="ck_recovery_cutover_adm_no_backend"),
        sa.CheckConstraint("production_execution_token_created = false", name="ck_recovery_cutover_adm_no_exec_token"),
        sa.CheckConstraint("execution_authority_created = false", name="ck_recovery_cutover_adm_no_exec_authority"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authority_switch_rehearsal_id"], ["evidence_recovery_authority_switch_rehearsals.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["activation_receipt_id"], ["evidence_recovery_authority_switch_receipts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["rollback_receipt_id"], ["evidence_recovery_authority_switch_receipts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["shadow_promotion_id"], ["evidence_recovery_shadow_promotions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["attestation_id"], ["evidence_recovery_promotion_attestations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["replica_id"], ["evidence_recovery_replicas.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["restore_rehearsal_id"], ["evidence_recovery_restore_rehearsals.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["restore_verification_id"], ["evidence_recovery_restore_verifications.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["shadow_verification_id"], ["evidence_recovery_shadow_verifications.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["approved_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["rejected_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["terminal_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("authority_switch_rehearsal_id", name="uq_recovery_cutover_adm_rehearsal"),
        sa.UniqueConstraint("organization_id", "admission_hash", name="uq_recovery_cutover_adm_org_hash"),
    )
    op.create_index("ix_recovery_cutover_adm_org_claim_status", "evidence_recovery_cutover_admissions", ["organization_id", "claim_id", "status"])
    op.create_index("ix_recovery_cutover_adm_org_doc_status", "evidence_recovery_cutover_admissions", ["organization_id", "document_id", "status"])
    for name, column in (
        ("ix_cutover_adm_org", "organization_id"),
        ("ix_cutover_adm_claim", "claim_id"),
        ("ix_cutover_adm_doc", "document_id"),
        ("ix_cutover_adm_switch", "authority_switch_rehearsal_id"),
        ("ix_cutover_adm_requester", "requested_by_id"),
        ("ix_cutover_adm_approver", "approved_by_id"),
    ):
        op.create_index(name, "evidence_recovery_cutover_admissions", [column])

    op.create_table(
        "evidence_recovery_cutover_admission_receipts",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("cutover_admission_id", sa.Uuid(), nullable=False),
        sa.Column("authority_switch_rehearsal_id", sa.Uuid(), nullable=False),
        sa.Column("phase", sa.String(length=20), nullable=False),
        sa.Column("request_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("admission_hash", sa.String(length=64), nullable=False),
        sa.Column("transition_proof_hash", sa.String(length=64), nullable=False),
        sa.Column("receipt_hash", sa.String(length=64), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("transitioned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("execution_authority_created", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("phase IN ('requested', 'approved', 'rejected', 'expired', 'invalidated')", name="ck_recovery_cutover_adm_receipt_phase"),
        sa.CheckConstraint("execution_authority_created = false", name="ck_recovery_cutover_adm_receipt_no_authority"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["cutover_admission_id"], ["evidence_recovery_cutover_admissions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authority_switch_rehearsal_id"], ["evidence_recovery_authority_switch_rehearsals.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "receipt_hash", name="uq_recovery_cutover_adm_receipt_org_hash"),
    )
    op.create_index("ix_recovery_cutover_adm_receipt_time", "evidence_recovery_cutover_admission_receipts", ["cutover_admission_id", "transitioned_at"])
    op.create_index("ix_cutover_adm_receipt_org", "evidence_recovery_cutover_admission_receipts", ["organization_id"])
    op.create_index("ix_cutover_adm_receipt_actor", "evidence_recovery_cutover_admission_receipts", ["actor_id"])


def downgrade() -> None:
    op.drop_index("ix_cutover_adm_receipt_actor", table_name="evidence_recovery_cutover_admission_receipts")
    op.drop_index("ix_cutover_adm_receipt_org", table_name="evidence_recovery_cutover_admission_receipts")
    op.drop_index("ix_recovery_cutover_adm_receipt_time", table_name="evidence_recovery_cutover_admission_receipts")
    op.drop_table("evidence_recovery_cutover_admission_receipts")

    for name in (
        "ix_cutover_adm_approver",
        "ix_cutover_adm_requester",
        "ix_cutover_adm_switch",
        "ix_cutover_adm_doc",
        "ix_cutover_adm_claim",
        "ix_cutover_adm_org",
        "ix_recovery_cutover_adm_org_doc_status",
        "ix_recovery_cutover_adm_org_claim_status",
    ):
        op.drop_index(name, table_name="evidence_recovery_cutover_admissions")
    op.drop_table("evidence_recovery_cutover_admissions")
