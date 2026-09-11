"""Add Phase Y bounded reversible dual-write rehearsal execution.

Revision ID: 0138_dual_write_rehearsal_execution
Revises: 0137_dual_write_rehearsal_authorization
"""

from alembic import op
import sqlalchemy as sa

revision = "0138_dual_write_rehearsal_execution"
down_revision = "0137_dual_write_rehearsal_authorization"
branch_labels = None
depends_on = None

EXECUTION = "evidence_recovery_dual_write_rehearsal_executions"
RECEIPT = "evidence_recovery_dual_write_rehearsal_execution_receipts"


def _safety_columns() -> list[sa.Column]:
    return [
        sa.Column("rehearsal_executed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("rehearsal_write_verified", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("rehearsal_object_routable", sa.Boolean(), nullable=False, server_default=sa.false()),
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


def _safety_constraints(prefix: str) -> list[sa.CheckConstraint]:
    return [
        sa.CheckConstraint("rehearsal_executed = true", name=f"ck_{prefix}_exec"),
        sa.CheckConstraint("rehearsal_write_verified = true", name=f"ck_{prefix}_verified"),
        sa.CheckConstraint("rehearsal_object_routable = false", name=f"ck_{prefix}_nonroute"),
        sa.CheckConstraint("dual_write_active = false", name=f"ck_{prefix}_no_dual"),
        sa.CheckConstraint("durable_write_authority_created = false", name=f"ck_{prefix}_no_durable"),
        sa.CheckConstraint("read_path_switched = false", name=f"ck_{prefix}_no_read"),
        sa.CheckConstraint("write_path_switched = false", name=f"ck_{prefix}_no_write"),
        sa.CheckConstraint("document_storage_key_mutated = false", name=f"ck_{prefix}_no_key"),
        sa.CheckConstraint("authoritative_storage_changed = false", name=f"ck_{prefix}_no_owner"),
        sa.CheckConstraint("destructive_action_performed = false", name=f"ck_{prefix}_no_dest"),
        sa.CheckConstraint("s3_copy_performed = false", name=f"ck_{prefix}_no_copy"),
        sa.CheckConstraint("s3_delete_performed = false", name=f"ck_{prefix}_no_s3del"),
        sa.CheckConstraint("local_delete_performed = false", name=f"ck_{prefix}_no_localdel"),
    ]


def upgrade() -> None:
    op.create_table(
        EXECUTION,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("phase_x_authorization_id", sa.Uuid(), nullable=False),
        sa.Column("phase_x_approval_receipt_id", sa.Uuid(), nullable=False),
        sa.Column("phase_w_health_qualification_id", sa.Uuid(), nullable=False),
        sa.Column("phase_v_transition_lease_id", sa.Uuid(), nullable=False),
        sa.Column("phase_u_authorization_id", sa.Uuid(), nullable=False),
        sa.Column("phase_t_health_qualification_id", sa.Uuid(), nullable=False),
        sa.Column("replica_id", sa.Uuid(), nullable=False),
        sa.Column("phase_x_authorization_hash", sa.String(64), nullable=False),
        sa.Column("phase_x_approval_receipt_hash", sa.String(64), nullable=False),
        sa.Column("phase_w_health_qualification_hash", sa.String(64), nullable=False),
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
        sa.Column("route_version_at_execution", sa.Integer(), nullable=False),
        sa.Column("rehearsal_object_key_fingerprint", sa.String(64), nullable=False),
        sa.Column("observed_file_hash", sa.String(64), nullable=False),
        sa.Column("observed_file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("remote_etag", sa.String(255), nullable=True),
        sa.Column("verification_hash", sa.String(64), nullable=False),
        sa.Column("execution_hash", sa.String(64), nullable=False),
        sa.Column("max_rehearsal_writes", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("conditional_write_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(20), nullable=False, server_default="executed"),
        sa.Column("executed_by_id", sa.Uuid(), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("execution_reason", sa.Text(), nullable=False),
        *_safety_columns(),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_x_authorization_id"], ["evidence_recovery_dual_write_rehearsal_authorizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_x_approval_receipt_id"], ["evidence_recovery_dual_write_rehearsal_auth_receipts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_w_health_qualification_id"], ["evidence_recovery_read_owner_health_qualifications.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_v_transition_lease_id"], ["evidence_recovery_read_ownership_transition_leases.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_u_authorization_id"], ["evidence_recovery_read_ownership_authorizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_t_health_qualification_id"], ["evidence_recovery_drr_reauth_renewal_health_qualifications.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["replica_id"], ["evidence_recovery_replicas.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["executed_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("phase_x_authorization_id", name="uq_dw_reh_exec_x_auth"),
        sa.UniqueConstraint("phase_x_approval_receipt_id", name="uq_dw_reh_exec_x_receipt"),
        sa.UniqueConstraint("organization_id", "execution_hash", name="uq_dw_reh_exec_org_hash"),
        sa.CheckConstraint("status = 'executed'", name="ck_dw_reh_exec_status"),
        sa.CheckConstraint("source_file_size_bytes >= 0", name="ck_dw_reh_exec_size"),
        sa.CheckConstraint("observed_file_size_bytes = source_file_size_bytes", name="ck_dw_reh_exec_obs_size"),
        sa.CheckConstraint("max_rehearsal_writes = 1", name="ck_dw_reh_exec_one_write"),
        sa.CheckConstraint("route_version_at_execution >= 1", name="ck_dw_reh_exec_routever"),
        *_safety_constraints("dw_reh_exec"),
    )
    op.create_index("ix_dw_reh_exec_org_claim", EXECUTION, ["organization_id", "claim_id", "status"])
    op.create_index("ix_dw_reh_exec_org_doc", EXECUTION, ["organization_id", "document_id", "status"])

    op.create_table(
        RECEIPT,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("phase_x_authorization_id", sa.Uuid(), nullable=False),
        sa.Column("phase", sa.String(20), nullable=False),
        sa.Column("phase_x_authorization_hash", sa.String(64), nullable=False),
        sa.Column("phase_x_approval_receipt_hash", sa.String(64), nullable=False),
        sa.Column("rehearsal_object_key_fingerprint", sa.String(64), nullable=False),
        sa.Column("source_file_hash", sa.String(64), nullable=False),
        sa.Column("source_file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("verification_hash", sa.String(64), nullable=False),
        sa.Column("execution_hash", sa.String(64), nullable=False),
        sa.Column("receipt_hash", sa.String(64), nullable=False),
        sa.Column("conditional_write_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("transitioned_at", sa.DateTime(timezone=True), nullable=False),
        *_safety_columns(),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["execution_id"], [f"{EXECUTION}.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_x_authorization_id"], ["evidence_recovery_dual_write_rehearsal_authorizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("execution_id", name="uq_dw_reh_exec_rec_execution"),
        sa.UniqueConstraint("organization_id", "receipt_hash", name="uq_dw_reh_exec_rec_org_hash"),
        sa.CheckConstraint("phase = 'executed'", name="ck_dw_reh_exec_rec_phase"),
        *_safety_constraints("dw_reh_exec_rec"),
    )
    op.create_index("ix_dw_reh_exec_rec_time", RECEIPT, ["execution_id", "transitioned_at"])


def downgrade() -> None:
    op.drop_index("ix_dw_reh_exec_rec_time", table_name=RECEIPT)
    op.drop_table(RECEIPT)
    op.drop_index("ix_dw_reh_exec_org_doc", table_name=EXECUTION)
    op.drop_index("ix_dw_reh_exec_org_claim", table_name=EXECUTION)
    op.drop_table(EXECUTION)
