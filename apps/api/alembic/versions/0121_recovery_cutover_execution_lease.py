"""add bounded recovery cutover execution lease

Revision ID: 0121_recovery_cutover_execution_lease
Revises: 0120_recovery_cutover_admission
"""

from alembic import op
import sqlalchemy as sa

revision = "0121_recovery_cutover_execution_lease"
down_revision = "0120_recovery_cutover_admission"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "evidence_recovery_cutover_execution_leases",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("cutover_admission_id", sa.Uuid(), nullable=False),
        sa.Column("admission_approval_receipt_id", sa.Uuid(), nullable=False),
        sa.Column("authority_switch_rehearsal_id", sa.Uuid(), nullable=False),
        sa.Column("shadow_promotion_id", sa.Uuid(), nullable=False),
        sa.Column("attestation_id", sa.Uuid(), nullable=False),
        sa.Column("replica_id", sa.Uuid(), nullable=False),
        sa.Column("restore_rehearsal_id", sa.Uuid(), nullable=False),
        sa.Column("restore_verification_id", sa.Uuid(), nullable=False),
        sa.Column("shadow_verification_id", sa.Uuid(), nullable=False),
        sa.Column("admission_hash", sa.String(length=64), nullable=False),
        sa.Column("admission_request_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("admission_approval_receipt_hash", sa.String(length=64), nullable=False),
        sa.Column("transition_proof_hash", sa.String(length=64), nullable=False),
        sa.Column("rehearsal_contract_hash", sa.String(length=64), nullable=False),
        sa.Column("rehearsal_lineage_hash", sa.String(length=64), nullable=False),
        sa.Column("source_authority_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("candidate_authority_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("configuration_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("execution_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("lease_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="prepared", nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("admission_approved_by_id", sa.Uuid(), nullable=False),
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
        sa.Column("read_path_switched", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("document_storage_key_mutated", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("active_backend_changed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("authoritative_storage_changed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("destructive_action_performed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("s3_delete_performed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("local_delete_performed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('prepared', 'activated', 'rolled_back', 'expired', 'invalidated')", name="ck_recovery_cutover_exec_status"),
        sa.CheckConstraint("prepared_by_id <> activated_by_id OR activated_by_id IS NULL", name="ck_recovery_cutover_exec_four_eyes"),
        sa.CheckConstraint("admission_approved_by_id <> activated_by_id OR activated_by_id IS NULL", name="ck_recovery_cutover_exec_approver_split"),
        sa.CheckConstraint("read_path_switched = false", name="ck_recovery_cutover_exec_no_read_switch"),
        sa.CheckConstraint("document_storage_key_mutated = false", name="ck_recovery_cutover_exec_no_key_mut"),
        sa.CheckConstraint("active_backend_changed = false", name="ck_recovery_cutover_exec_no_backend"),
        sa.CheckConstraint("authoritative_storage_changed = false", name="ck_recovery_cutover_exec_no_authority"),
        sa.CheckConstraint("destructive_action_performed = false", name="ck_recovery_cutover_exec_no_destructive"),
        sa.CheckConstraint("s3_delete_performed = false", name="ck_recovery_cutover_exec_no_s3_del"),
        sa.CheckConstraint("local_delete_performed = false", name="ck_recovery_cutover_exec_no_local_del"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["cutover_admission_id"], ["evidence_recovery_cutover_admissions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["admission_approval_receipt_id"], ["evidence_recovery_cutover_admission_receipts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authority_switch_rehearsal_id"], ["evidence_recovery_authority_switch_rehearsals.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["shadow_promotion_id"], ["evidence_recovery_shadow_promotions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["attestation_id"], ["evidence_recovery_promotion_attestations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["replica_id"], ["evidence_recovery_replicas.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["restore_rehearsal_id"], ["evidence_recovery_restore_rehearsals.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["restore_verification_id"], ["evidence_recovery_restore_verifications.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["shadow_verification_id"], ["evidence_recovery_shadow_verifications.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["admission_approved_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["prepared_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["activated_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["rolled_back_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["terminal_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cutover_admission_id", name="uq_recovery_cutover_exec_admission"),
        sa.UniqueConstraint("organization_id", "lease_hash", name="uq_recovery_cutover_exec_org_hash"),
    )
    op.create_index("ix_recovery_cutover_exec_org_claim_status", "evidence_recovery_cutover_execution_leases", ["organization_id", "claim_id", "status"])
    op.create_index("ix_recovery_cutover_exec_org_doc_status", "evidence_recovery_cutover_execution_leases", ["organization_id", "document_id", "status"])
    for name, column in (
        ("ix_cutover_exec_org", "organization_id"),
        ("ix_cutover_exec_claim", "claim_id"),
        ("ix_cutover_exec_doc", "document_id"),
        ("ix_cutover_exec_adm", "cutover_admission_id"),
        ("ix_cutover_exec_adm_rec", "admission_approval_receipt_id"),
        ("ix_cutover_exec_preparer", "prepared_by_id"),
        ("ix_cutover_exec_activator", "activated_by_id"),
    ):
        op.create_index(name, "evidence_recovery_cutover_execution_leases", [column])

    op.create_table(
        "evidence_recovery_cutover_execution_receipts",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("execution_lease_id", sa.Uuid(), nullable=False),
        sa.Column("cutover_admission_id", sa.Uuid(), nullable=False),
        sa.Column("phase", sa.String(length=20), nullable=False),
        sa.Column("from_state", sa.String(length=20), nullable=False),
        sa.Column("to_state", sa.String(length=20), nullable=False),
        sa.Column("admission_hash", sa.String(length=64), nullable=False),
        sa.Column("admission_approval_receipt_hash", sa.String(length=64), nullable=False),
        sa.Column("execution_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("lease_hash", sa.String(length=64), nullable=False),
        sa.Column("receipt_hash", sa.String(length=64), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("transitioned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_path_switched", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("authoritative_storage_changed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("destructive_action_performed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("phase IN ('prepared', 'activated', 'rolled_back', 'expired', 'invalidated')", name="ck_recovery_cutover_exec_receipt_phase"),
        sa.CheckConstraint("read_path_switched = false", name="ck_recovery_cutover_exec_rec_no_read"),
        sa.CheckConstraint("authoritative_storage_changed = false", name="ck_recovery_cutover_exec_rec_no_auth"),
        sa.CheckConstraint("destructive_action_performed = false", name="ck_recovery_cutover_exec_rec_no_dest"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["execution_lease_id"], ["evidence_recovery_cutover_execution_leases.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["cutover_admission_id"], ["evidence_recovery_cutover_admissions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "receipt_hash", name="uq_recovery_cutover_exec_rec_org_hash"),
    )
    op.create_index("ix_recovery_cutover_exec_receipt_time", "evidence_recovery_cutover_execution_receipts", ["execution_lease_id", "transitioned_at"])
    op.create_index("ix_cutover_exec_rec_org", "evidence_recovery_cutover_execution_receipts", ["organization_id"])
    op.create_index("ix_cutover_exec_rec_actor", "evidence_recovery_cutover_execution_receipts", ["actor_id"])


def downgrade() -> None:
    op.drop_index("ix_cutover_exec_rec_actor", table_name="evidence_recovery_cutover_execution_receipts")
    op.drop_index("ix_cutover_exec_rec_org", table_name="evidence_recovery_cutover_execution_receipts")
    op.drop_index("ix_recovery_cutover_exec_receipt_time", table_name="evidence_recovery_cutover_execution_receipts")
    op.drop_table("evidence_recovery_cutover_execution_receipts")

    for name in (
        "ix_cutover_exec_activator",
        "ix_cutover_exec_preparer",
        "ix_cutover_exec_adm_rec",
        "ix_cutover_exec_adm",
        "ix_cutover_exec_doc",
        "ix_cutover_exec_claim",
        "ix_cutover_exec_org",
        "ix_recovery_cutover_exec_org_doc_status",
        "ix_recovery_cutover_exec_org_claim_status",
    ):
        op.drop_index(name, table_name="evidence_recovery_cutover_execution_leases")
    op.drop_table("evidence_recovery_cutover_execution_leases")
