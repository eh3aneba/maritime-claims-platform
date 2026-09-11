"""Add Phase X bounded dual-write rehearsal authorization.

Revision ID: 0137_dual_write_rehearsal_authorization
Revises: 0136_recovery_read_ownership_transition_health
"""

from alembic import op
import sqlalchemy as sa

revision = "0137_dual_write_rehearsal_authorization"
down_revision = "0136_recovery_read_ownership_transition_health"
branch_labels = None
depends_on = None

AUTH = "evidence_recovery_dual_write_rehearsal_authorizations"
RECEIPT = "evidence_recovery_dual_write_rehearsal_auth_receipts"


def _safety_columns() -> list[sa.Column]:
    return [
        sa.Column("rehearsal_executed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("dual_write_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("durable_write_authority_created", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("read_path_switched", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("write_path_switched", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("document_storage_key_mutated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("authoritative_storage_changed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("destructive_action_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("s3_copy_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("s3_delete_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("local_delete_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
    ]


def upgrade() -> None:
    op.create_table(
        AUTH,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("phase_w_health_qualification_id", sa.Uuid(), nullable=False),
        sa.Column("phase_w_health_receipt_id", sa.Uuid(), nullable=False),
        sa.Column("phase_v_transition_lease_id", sa.Uuid(), nullable=False),
        sa.Column("phase_u_authorization_id", sa.Uuid(), nullable=False),
        sa.Column("phase_t_health_qualification_id", sa.Uuid(), nullable=False),
        sa.Column("replica_id", sa.Uuid(), nullable=False),
        sa.Column("phase_w_health_qualification_hash", sa.String(64), nullable=False),
        sa.Column("phase_w_request_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("phase_w_health_receipt_hash", sa.String(64), nullable=False),
        sa.Column("operational_evidence_hash", sa.String(64), nullable=False),
        sa.Column("health_state", sa.String(20), nullable=False),
        sa.Column("phase_v_transition_lease_hash", sa.String(64), nullable=False),
        sa.Column("phase_u_authorization_hash", sa.String(64), nullable=False),
        sa.Column("phase_t_health_qualification_hash", sa.String(64), nullable=False),
        sa.Column("replica_hash", sa.String(64), nullable=False),
        sa.Column("source_file_hash", sa.String(64), nullable=False),
        sa.Column("source_file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("local_storage_key_fingerprint", sa.String(64), nullable=False),
        sa.Column("recovery_bucket_fingerprint", sa.String(64), nullable=False),
        sa.Column("candidate_storage_key_fingerprint", sa.String(64), nullable=False),
        sa.Column("source_authority_fingerprint", sa.String(64), nullable=False),
        sa.Column("candidate_authority_fingerprint", sa.String(64), nullable=False),
        sa.Column("configuration_fingerprint", sa.String(64), nullable=False),
        sa.Column("verified_read_count", sa.Integer(), nullable=False),
        sa.Column("integrity_failure_count", sa.Integer(), nullable=False),
        sa.Column("storage_unavailable_count", sa.Integer(), nullable=False),
        sa.Column("route_expired_attempt_count", sa.Integer(), nullable=False),
        sa.Column("operational_event_count", sa.Integer(), nullable=False),
        sa.Column("route_version_at_request", sa.Integer(), nullable=False),
        sa.Column("integrity_proof_hash", sa.String(64), nullable=False),
        sa.Column("request_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("authorization_hash", sa.String(64), nullable=False),
        sa.Column("max_rehearsal_writes", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("phase_w_qualified_by_id", sa.Uuid(), nullable=False),
        sa.Column("phase_v_activated_by_id", sa.Uuid(), nullable=False),
        sa.Column("phase_u_approved_by_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending_second_approval"),
        sa.Column("requested_by_id", sa.Uuid(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("review_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_reason", sa.Text(), nullable=False),
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
        sa.ForeignKeyConstraint(["phase_w_health_qualification_id"], ["evidence_recovery_read_owner_health_qualifications.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_w_health_receipt_id"], ["evidence_recovery_read_owner_health_receipts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_v_transition_lease_id"], ["evidence_recovery_read_ownership_transition_leases.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_u_authorization_id"], ["evidence_recovery_read_ownership_authorizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_t_health_qualification_id"], ["evidence_recovery_drr_reauth_renewal_health_qualifications.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["replica_id"], ["evidence_recovery_replicas.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_w_qualified_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_v_activated_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_u_approved_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["approved_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["rejected_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["terminal_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("phase_w_health_qualification_id", name="uq_dw_reh_auth_w_health"),
        sa.UniqueConstraint("organization_id", "authorization_hash", name="uq_dw_reh_auth_org_hash"),
        sa.CheckConstraint("status IN ('pending_second_approval','approved','rejected','expired','invalidated')", name="ck_dw_reh_auth_status"),
        sa.CheckConstraint("health_state = 'healthy'", name="ck_dw_reh_auth_healthy"),
        sa.CheckConstraint("requested_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_dw_reh_auth_four_eyes"),
        sa.CheckConstraint("phase_w_qualified_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_dw_reh_auth_w_split"),
        sa.CheckConstraint("phase_v_activated_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_dw_reh_auth_v_split"),
        sa.CheckConstraint("phase_u_approved_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_dw_reh_auth_u_split"),
        sa.CheckConstraint("source_file_size_bytes >= 0", name="ck_dw_reh_auth_size"),
        sa.CheckConstraint("verified_read_count >= 1", name="ck_dw_reh_auth_verified"),
        sa.CheckConstraint("integrity_failure_count = 0", name="ck_dw_reh_auth_integrity"),
        sa.CheckConstraint("storage_unavailable_count = 0", name="ck_dw_reh_auth_storage"),
        sa.CheckConstraint("route_version_at_request >= 1", name="ck_dw_reh_auth_routever"),
        sa.CheckConstraint("max_rehearsal_writes = 1", name="ck_dw_reh_auth_one_write"),
        sa.CheckConstraint("status <> 'approved' OR authorization_expires_at IS NOT NULL", name="ck_dw_reh_auth_approved_exp"),
        sa.CheckConstraint("status = 'approved' OR authorization_expires_at IS NULL", name="ck_dw_reh_auth_nonapproved_exp"),
        sa.CheckConstraint("rehearsal_executed = false", name="ck_dw_reh_auth_no_exec"),
        sa.CheckConstraint("dual_write_active = false", name="ck_dw_reh_auth_no_dual"),
        sa.CheckConstraint("durable_write_authority_created = false", name="ck_dw_reh_auth_no_durable"),
        sa.CheckConstraint("read_path_switched = false", name="ck_dw_reh_auth_no_read"),
        sa.CheckConstraint("write_path_switched = false", name="ck_dw_reh_auth_no_write"),
        sa.CheckConstraint("document_storage_key_mutated = false", name="ck_dw_reh_auth_no_key"),
        sa.CheckConstraint("authoritative_storage_changed = false", name="ck_dw_reh_auth_no_owner"),
        sa.CheckConstraint("destructive_action_performed = false", name="ck_dw_reh_auth_no_dest"),
        sa.CheckConstraint("s3_copy_performed = false", name="ck_dw_reh_auth_no_copy"),
        sa.CheckConstraint("s3_delete_performed = false", name="ck_dw_reh_auth_no_s3del"),
        sa.CheckConstraint("local_delete_performed = false", name="ck_dw_reh_auth_no_localdel"),
    )
    op.create_index("ix_dw_reh_auth_org_claim", AUTH, ["organization_id", "claim_id", "status"])
    op.create_index("ix_dw_reh_auth_org_doc", AUTH, ["organization_id", "document_id", "status"])

    op.create_table(
        RECEIPT,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_id", sa.Uuid(), nullable=False),
        sa.Column("phase_w_health_qualification_id", sa.Uuid(), nullable=False),
        sa.Column("phase", sa.String(20), nullable=False),
        sa.Column("health_state", sa.String(20), nullable=False),
        sa.Column("operational_evidence_hash", sa.String(64), nullable=False),
        sa.Column("integrity_proof_hash", sa.String(64), nullable=False),
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
        sa.ForeignKeyConstraint(["phase_w_health_qualification_id"], ["evidence_recovery_read_owner_health_qualifications.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "receipt_hash", name="uq_dw_reh_rec_org_hash"),
        sa.CheckConstraint("phase IN ('requested','approved','rejected','expired','invalidated')", name="ck_dw_reh_rec_phase"),
        sa.CheckConstraint("rehearsal_executed = false", name="ck_dw_reh_rec_no_exec"),
        sa.CheckConstraint("dual_write_active = false", name="ck_dw_reh_rec_no_dual"),
        sa.CheckConstraint("durable_write_authority_created = false", name="ck_dw_reh_rec_no_durable"),
        sa.CheckConstraint("read_path_switched = false", name="ck_dw_reh_rec_no_read"),
        sa.CheckConstraint("write_path_switched = false", name="ck_dw_reh_rec_no_write"),
        sa.CheckConstraint("document_storage_key_mutated = false", name="ck_dw_reh_rec_no_key"),
        sa.CheckConstraint("authoritative_storage_changed = false", name="ck_dw_reh_rec_no_owner"),
        sa.CheckConstraint("destructive_action_performed = false", name="ck_dw_reh_rec_no_dest"),
        sa.CheckConstraint("s3_copy_performed = false", name="ck_dw_reh_rec_no_copy"),
        sa.CheckConstraint("s3_delete_performed = false", name="ck_dw_reh_rec_no_s3del"),
        sa.CheckConstraint("local_delete_performed = false", name="ck_dw_reh_rec_no_localdel"),
    )
    op.create_index("ix_dw_reh_rec_time", RECEIPT, ["authorization_id", "transitioned_at"])


def downgrade() -> None:
    op.drop_index("ix_dw_reh_rec_time", table_name=RECEIPT)
    op.drop_table(RECEIPT)
    op.drop_index("ix_dw_reh_auth_org_doc", table_name=AUTH)
    op.drop_index("ix_dw_reh_auth_org_claim", table_name=AUTH)
    op.drop_table(AUTH)
