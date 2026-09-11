"""Add Phase AD recovery write-ownership transition authorization.

Revision ID: 0143_recovery_write_ownership_transition_authorization
Revises: 0142_routable_dual_write_canary_health
"""

from alembic import op
import sqlalchemy as sa

revision = "0143_recovery_write_ownership_transition_authorization"
down_revision = "0142_routable_dual_write_canary_health"
branch_labels = None
depends_on = None

AUTH = "evidence_recovery_write_ownership_transition_authorizations"
RECEIPT = "evidence_recovery_write_ownership_transition_auth_receipts"


def _safety_columns() -> list[sa.Column]:
    return [
        sa.Column("local_authoritative", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("storage_write_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("write_route_lease_created", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("routable_dual_write_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("durable_write_authority_created", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("read_path_switched", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("write_path_switched", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("document_storage_key_mutated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("authoritative_storage_changed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("destructive_action_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("s3_put_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("s3_copy_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("s3_delete_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("local_delete_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
    ]


def _safety_constraints(prefix: str) -> list[sa.CheckConstraint]:
    return [
        sa.CheckConstraint("local_authoritative = true", name=f"ck_{prefix}_local_auth"),
        sa.CheckConstraint("storage_write_performed = false", name=f"ck_{prefix}_no_write"),
        sa.CheckConstraint("write_route_lease_created = false", name=f"ck_{prefix}_no_lease"),
        sa.CheckConstraint("routable_dual_write_active = false", name=f"ck_{prefix}_no_dual"),
        sa.CheckConstraint("durable_write_authority_created = false", name=f"ck_{prefix}_no_durable"),
        sa.CheckConstraint("read_path_switched = false", name=f"ck_{prefix}_no_read"),
        sa.CheckConstraint("write_path_switched = false", name=f"ck_{prefix}_no_switch"),
        sa.CheckConstraint("document_storage_key_mutated = false", name=f"ck_{prefix}_no_key"),
        sa.CheckConstraint("authoritative_storage_changed = false", name=f"ck_{prefix}_no_owner"),
        sa.CheckConstraint("destructive_action_performed = false", name=f"ck_{prefix}_no_dest"),
        sa.CheckConstraint("s3_put_performed = false", name=f"ck_{prefix}_no_put"),
        sa.CheckConstraint("s3_copy_performed = false", name=f"ck_{prefix}_no_copy"),
        sa.CheckConstraint("s3_delete_performed = false", name=f"ck_{prefix}_no_s3del"),
        sa.CheckConstraint("local_delete_performed = false", name=f"ck_{prefix}_no_localdel"),
    ]


def upgrade() -> None:
    op.create_table(
        AUTH,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("phase_ac_health_qualification_id", sa.Uuid(), nullable=False),
        sa.Column("phase_ac_health_receipt_id", sa.Uuid(), nullable=False),
        sa.Column("canary_lease_id", sa.Uuid(), nullable=False),
        sa.Column("phase_aa_authorization_id", sa.Uuid(), nullable=False),
        sa.Column("phase_aa_approval_receipt_id", sa.Uuid(), nullable=False),
        sa.Column("phase_z_health_qualification_id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("phase_x_authorization_id", sa.Uuid(), nullable=False),
        sa.Column("replica_id", sa.Uuid(), nullable=False),
        sa.Column("phase_ac_health_qualification_hash", sa.String(64), nullable=False),
        sa.Column("phase_ac_health_receipt_hash", sa.String(64), nullable=False),
        sa.Column("phase_ac_request_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("phase_ac_integrity_proof_hash", sa.String(64), nullable=False),
        sa.Column("lease_hash", sa.String(64), nullable=False),
        sa.Column("lease_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("verification_hash", sa.String(64), nullable=False),
        sa.Column("activation_receipt_hash", sa.String(64), nullable=False),
        sa.Column("terminal_receipt_hash", sa.String(64), nullable=False),
        sa.Column("phase_aa_authorization_hash", sa.String(64), nullable=False),
        sa.Column("phase_aa_approval_receipt_hash", sa.String(64), nullable=False),
        sa.Column("phase_z_health_qualification_hash", sa.String(64), nullable=False),
        sa.Column("execution_hash", sa.String(64), nullable=False),
        sa.Column("phase_x_authorization_hash", sa.String(64), nullable=False),
        sa.Column("replica_hash", sa.String(64), nullable=False),
        sa.Column("source_file_hash", sa.String(64), nullable=False),
        sa.Column("source_file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("local_storage_key_fingerprint", sa.String(64), nullable=False),
        sa.Column("recovery_bucket_fingerprint", sa.String(64), nullable=False),
        sa.Column("candidate_storage_key_fingerprint", sa.String(64), nullable=False),
        sa.Column("source_authority_fingerprint", sa.String(64), nullable=False),
        sa.Column("candidate_authority_fingerprint", sa.String(64), nullable=False),
        sa.Column("configuration_fingerprint", sa.String(64), nullable=False),
        sa.Column("canary_object_key_fingerprint", sa.String(64), nullable=False),
        sa.Column("observed_file_hash", sa.String(64), nullable=False),
        sa.Column("observed_file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("remote_etag", sa.String(255), nullable=True),
        sa.Column("read_route_version_at_request", sa.Integer(), nullable=False),
        sa.Column("write_route_version_at_request", sa.Integer(), nullable=False),
        sa.Column("request_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("authorization_hash", sa.String(64), nullable=False),
        sa.Column("health_state", sa.String(20), nullable=False, server_default="healthy"),
        sa.Column("max_transition_windows", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("phase_ac_qualified_by_id", sa.Uuid(), nullable=False),
        sa.Column("phase_ab_activated_by_id", sa.Uuid(), nullable=False),
        sa.Column("phase_aa_requested_by_id", sa.Uuid(), nullable=False),
        sa.Column("phase_aa_approved_by_id", sa.Uuid(), nullable=False),
        sa.Column("phase_z_qualified_by_id", sa.Uuid(), nullable=False),
        sa.Column("phase_y_executed_by_id", sa.Uuid(), nullable=False),
        sa.Column("phase_x_approved_by_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_id", sa.Uuid(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("review_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending_second_approval"),
        sa.Column("approved_by_id", sa.Uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("authorization_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approval_reason", sa.Text(), nullable=True),
        sa.Column("rejected_by_id", sa.Uuid(), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("terminal_by_id", sa.Uuid(), nullable=True),
        sa.Column("terminal_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terminal_reason", sa.Text(), nullable=True),
        *_safety_columns(),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_ac_health_qualification_id"], ["evidence_recovery_routable_dual_write_canary_health_qualifications.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_ac_health_receipt_id"], ["evidence_recovery_routable_dual_write_canary_health_receipts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["canary_lease_id"], ["evidence_recovery_routable_dual_write_canary_leases.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_aa_authorization_id"], ["evidence_recovery_routable_dual_write_canary_authorizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_aa_approval_receipt_id"], ["evidence_recovery_routable_dual_write_canary_auth_receipts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_z_health_qualification_id"], ["evidence_recovery_dual_write_rehearsal_health_qualifications.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["execution_id"], ["evidence_recovery_dual_write_rehearsal_executions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_x_authorization_id"], ["evidence_recovery_dual_write_rehearsal_authorizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["replica_id"], ["evidence_recovery_replicas.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_ac_qualified_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_ab_activated_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_aa_requested_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_aa_approved_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_z_qualified_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_y_executed_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_x_approved_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["approved_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["rejected_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["terminal_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("phase_ac_health_qualification_id", name="uq_wr_own_auth_ac_health"),
        sa.UniqueConstraint("organization_id", "authorization_hash", name="uq_wr_own_auth_org_hash"),
        sa.CheckConstraint("status IN ('pending_second_approval','approved','rejected','expired','invalidated')", name="ck_wr_own_auth_status"),
        sa.CheckConstraint("health_state = 'healthy'", name="ck_wr_own_auth_healthy"),
        sa.CheckConstraint("requested_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_wr_own_auth_four_eyes"),
        sa.CheckConstraint("phase_ac_qualified_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_wr_own_auth_ac_split"),
        sa.CheckConstraint("phase_ab_activated_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_wr_own_auth_ab_split"),
        sa.CheckConstraint("phase_aa_requested_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_wr_own_auth_aar_split"),
        sa.CheckConstraint("phase_aa_approved_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_wr_own_auth_aaa_split"),
        sa.CheckConstraint("phase_z_qualified_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_wr_own_auth_z_split"),
        sa.CheckConstraint("phase_y_executed_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_wr_own_auth_y_split"),
        sa.CheckConstraint("phase_x_approved_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_wr_own_auth_x_split"),
        sa.CheckConstraint("source_file_size_bytes >= 0", name="ck_wr_own_auth_size"),
        sa.CheckConstraint("observed_file_size_bytes = source_file_size_bytes", name="ck_wr_own_auth_obs_size"),
        sa.CheckConstraint("read_route_version_at_request >= 1", name="ck_wr_own_auth_read_ver"),
        sa.CheckConstraint("write_route_version_at_request >= 1", name="ck_wr_own_auth_write_ver"),
        sa.CheckConstraint("max_transition_windows = 1", name="ck_wr_own_auth_one_window"),
        sa.CheckConstraint("status <> 'approved' OR authorization_expires_at IS NOT NULL", name="ck_wr_own_auth_approved_exp"),
        sa.CheckConstraint("status = 'approved' OR authorization_expires_at IS NULL", name="ck_wr_own_auth_nonapproved_exp"),
        *_safety_constraints("wr_own_auth"),
    )
    op.create_index("ix_wr_own_auth_org_claim", AUTH, ["organization_id", "claim_id", "status"])
    op.create_index("ix_wr_own_auth_org_doc", AUTH, ["organization_id", "document_id", "status"])

    op.create_table(
        RECEIPT,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_id", sa.Uuid(), nullable=False),
        sa.Column("phase_ac_health_qualification_id", sa.Uuid(), nullable=False),
        sa.Column("phase", sa.String(20), nullable=False),
        sa.Column("health_state", sa.String(20), nullable=False, server_default="healthy"),
        sa.Column("phase_ac_health_qualification_hash", sa.String(64), nullable=False),
        sa.Column("phase_ac_health_receipt_hash", sa.String(64), nullable=False),
        sa.Column("request_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("authorization_hash", sa.String(64), nullable=False),
        sa.Column("receipt_hash", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("transitioned_at", sa.DateTime(timezone=True), nullable=False),
        *_safety_columns(),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_id"], [f"{AUTH}.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_ac_health_qualification_id"], ["evidence_recovery_routable_dual_write_canary_health_qualifications.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "receipt_hash", name="uq_wr_own_rec_org_hash"),
        sa.CheckConstraint("phase IN ('requested','approved','rejected','expired','invalidated')", name="ck_wr_own_rec_phase"),
        sa.CheckConstraint("health_state = 'healthy'", name="ck_wr_own_rec_healthy"),
        *_safety_constraints("wr_own_rec"),
    )
    op.create_index("ix_wr_own_rec_time", RECEIPT, ["authorization_id", "transitioned_at"])


def downgrade() -> None:
    op.drop_index("ix_wr_own_rec_time", table_name=RECEIPT)
    op.drop_table(RECEIPT)
    op.drop_index("ix_wr_own_auth_org_doc", table_name=AUTH)
    op.drop_index("ix_wr_own_auth_org_claim", table_name=AUTH)
    op.drop_table(AUTH)
