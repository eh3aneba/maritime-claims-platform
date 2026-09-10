"""add governed recovery read-path cutover authorization

Revision ID: 0122_recovery_read_path_cutover_authorization
Revises: 0121_recovery_cutover_execution_lease
"""

from alembic import op
import sqlalchemy as sa

revision = "0122_recovery_read_path_cutover_authorization"
down_revision = "0121_recovery_cutover_execution_lease"
branch_labels = None
depends_on = None


AUTH_TABLE = "evidence_recovery_read_path_cutover_authorizations"
RECEIPT_TABLE = "evidence_recovery_read_path_cutover_authorization_receipts"


def upgrade() -> None:
    op.create_table(
        AUTH_TABLE,
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("execution_lease_id", sa.Uuid(), nullable=False),
        sa.Column("execution_activation_receipt_id", sa.Uuid(), nullable=False),
        sa.Column("execution_rollback_receipt_id", sa.Uuid(), nullable=False),
        sa.Column("cutover_admission_id", sa.Uuid(), nullable=False),
        sa.Column("admission_approval_receipt_id", sa.Uuid(), nullable=False),
        sa.Column("authority_switch_rehearsal_id", sa.Uuid(), nullable=False),
        sa.Column("shadow_promotion_id", sa.Uuid(), nullable=False),
        sa.Column("attestation_id", sa.Uuid(), nullable=False),
        sa.Column("replica_id", sa.Uuid(), nullable=False),
        sa.Column("restore_rehearsal_id", sa.Uuid(), nullable=False),
        sa.Column("restore_verification_id", sa.Uuid(), nullable=False),
        sa.Column("shadow_verification_id", sa.Uuid(), nullable=False),
        sa.Column("lease_hash", sa.String(length=64), nullable=False),
        sa.Column("execution_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("execution_activation_receipt_hash", sa.String(length=64), nullable=False),
        sa.Column("execution_rollback_receipt_hash", sa.String(length=64), nullable=False),
        sa.Column("execution_transition_proof_hash", sa.String(length=64), nullable=False),
        sa.Column("admission_hash", sa.String(length=64), nullable=False),
        sa.Column("admission_approval_receipt_hash", sa.String(length=64), nullable=False),
        sa.Column("rehearsal_contract_hash", sa.String(length=64), nullable=False),
        sa.Column("rehearsal_lineage_hash", sa.String(length=64), nullable=False),
        sa.Column("source_authority_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("candidate_authority_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("configuration_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("request_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("authorization_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="pending_second_approval", nullable=False),
        sa.Column("authorization_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("execution_activated_by_id", sa.Uuid(), nullable=False),
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
        sa.Column("routable_authority_created", sa.Boolean(), server_default=sa.text("false"), nullable=False),
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
        sa.CheckConstraint("status IN ('pending_second_approval', 'approved', 'rejected', 'expired', 'invalidated')", name="ck_recovery_read_cut_auth_status"),
        sa.CheckConstraint("requested_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_recovery_read_cut_auth_four_eyes"),
        sa.CheckConstraint("execution_activated_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_recovery_read_cut_auth_activator_split"),
        sa.CheckConstraint("routable_authority_created = false", name="ck_recovery_read_cut_auth_no_route_auth"),
        sa.CheckConstraint("read_path_switched = false", name="ck_recovery_read_cut_auth_no_read_switch"),
        sa.CheckConstraint("document_storage_key_mutated = false", name="ck_recovery_read_cut_auth_no_key_mut"),
        sa.CheckConstraint("active_backend_changed = false", name="ck_recovery_read_cut_auth_no_backend"),
        sa.CheckConstraint("authoritative_storage_changed = false", name="ck_recovery_read_cut_auth_no_authority"),
        sa.CheckConstraint("destructive_action_performed = false", name="ck_recovery_read_cut_auth_no_destructive"),
        sa.CheckConstraint("s3_delete_performed = false", name="ck_recovery_read_cut_auth_no_s3_del"),
        sa.CheckConstraint("local_delete_performed = false", name="ck_recovery_read_cut_auth_no_local_del"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["execution_lease_id"], ["evidence_recovery_cutover_execution_leases.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["execution_activation_receipt_id"], ["evidence_recovery_cutover_execution_receipts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["execution_rollback_receipt_id"], ["evidence_recovery_cutover_execution_receipts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["cutover_admission_id"], ["evidence_recovery_cutover_admissions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["admission_approval_receipt_id"], ["evidence_recovery_cutover_admission_receipts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authority_switch_rehearsal_id"], ["evidence_recovery_authority_switch_rehearsals.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["shadow_promotion_id"], ["evidence_recovery_shadow_promotions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["attestation_id"], ["evidence_recovery_promotion_attestations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["replica_id"], ["evidence_recovery_replicas.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["restore_rehearsal_id"], ["evidence_recovery_restore_rehearsals.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["restore_verification_id"], ["evidence_recovery_restore_verifications.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["shadow_verification_id"], ["evidence_recovery_shadow_verifications.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["execution_activated_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["approved_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["rejected_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["terminal_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("execution_lease_id", name="uq_recovery_read_cut_auth_lease"),
        sa.UniqueConstraint("organization_id", "authorization_hash", name="uq_recovery_read_cut_auth_org_hash"),
    )
    op.create_index("ix_recovery_read_cut_auth_org_claim_status", AUTH_TABLE, ["organization_id", "claim_id", "status"])
    op.create_index("ix_recovery_read_cut_auth_org_doc_status", AUTH_TABLE, ["organization_id", "document_id", "status"])
    for name, column in (
        ("ix_read_cut_auth_org", "organization_id"),
        ("ix_read_cut_auth_claim", "claim_id"),
        ("ix_read_cut_auth_doc", "document_id"),
        ("ix_read_cut_auth_lease", "execution_lease_id"),
        ("ix_read_cut_auth_activator", "execution_activated_by_id"),
        ("ix_read_cut_auth_requester", "requested_by_id"),
        ("ix_read_cut_auth_approver", "approved_by_id"),
    ):
        op.create_index(name, AUTH_TABLE, [column])

    op.create_table(
        RECEIPT_TABLE,
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_id", sa.Uuid(), nullable=False),
        sa.Column("execution_lease_id", sa.Uuid(), nullable=False),
        sa.Column("phase", sa.String(length=20), nullable=False),
        sa.Column("request_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("authorization_hash", sa.String(length=64), nullable=False),
        sa.Column("execution_transition_proof_hash", sa.String(length=64), nullable=False),
        sa.Column("receipt_hash", sa.String(length=64), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("transitioned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("routable_authority_created", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("read_path_switched", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("authoritative_storage_changed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("destructive_action_performed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("phase IN ('requested', 'approved', 'rejected', 'expired', 'invalidated')", name="ck_recovery_read_cut_auth_receipt_phase"),
        sa.CheckConstraint("routable_authority_created = false", name="ck_recovery_read_cut_auth_rec_no_route"),
        sa.CheckConstraint("read_path_switched = false", name="ck_recovery_read_cut_auth_rec_no_read"),
        sa.CheckConstraint("authoritative_storage_changed = false", name="ck_recovery_read_cut_auth_rec_no_auth"),
        sa.CheckConstraint("destructive_action_performed = false", name="ck_recovery_read_cut_auth_rec_no_dest"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_id"], [f"{AUTH_TABLE}.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["execution_lease_id"], ["evidence_recovery_cutover_execution_leases.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "receipt_hash", name="uq_recovery_read_cut_auth_rec_org_hash"),
    )
    op.create_index("ix_recovery_read_cut_auth_receipt_time", RECEIPT_TABLE, ["authorization_id", "transitioned_at"])
    op.create_index("ix_read_cut_auth_rec_org", RECEIPT_TABLE, ["organization_id"])
    op.create_index("ix_read_cut_auth_rec_actor", RECEIPT_TABLE, ["actor_id"])


def downgrade() -> None:
    op.drop_index("ix_read_cut_auth_rec_actor", table_name=RECEIPT_TABLE)
    op.drop_index("ix_read_cut_auth_rec_org", table_name=RECEIPT_TABLE)
    op.drop_index("ix_recovery_read_cut_auth_receipt_time", table_name=RECEIPT_TABLE)
    op.drop_table(RECEIPT_TABLE)

    for name in (
        "ix_read_cut_auth_approver",
        "ix_read_cut_auth_requester",
        "ix_read_cut_auth_activator",
        "ix_read_cut_auth_lease",
        "ix_read_cut_auth_doc",
        "ix_read_cut_auth_claim",
        "ix_read_cut_auth_org",
        "ix_recovery_read_cut_auth_org_doc_status",
        "ix_recovery_read_cut_auth_org_claim_status",
    ):
        op.drop_index(name, table_name=AUTH_TABLE)
    op.drop_table(AUTH_TABLE)
