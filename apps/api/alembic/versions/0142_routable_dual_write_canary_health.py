"""Add Phase AC independent health qualification for completed AB canary windows.

Revision ID: 0142_routable_dual_write_canary_health
Revises: 0141_routable_dual_write_canary_execution
"""

from alembic import op
import sqlalchemy as sa

revision = "0142_routable_dual_write_canary_health"
down_revision = "0141_routable_dual_write_canary_execution"
branch_labels = None
depends_on = None

QUAL = "evidence_recovery_routable_dual_write_canary_health_qualifications"
RECEIPT = "evidence_recovery_routable_dual_write_canary_health_receipts"


def _safety_columns() -> list[sa.Column]:
    return [
        sa.Column("local_authoritative", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("storage_write_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("canary_reactivated", sa.Boolean(), nullable=False, server_default=sa.false()),
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
        sa.CheckConstraint("canary_reactivated = false", name=f"ck_{prefix}_no_reactivate"),
        sa.CheckConstraint("routable_dual_write_active = false", name=f"ck_{prefix}_no_active"),
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
        QUAL,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("canary_lease_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_approval_receipt_id", sa.Uuid(), nullable=False),
        sa.Column("phase_z_health_qualification_id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("phase_x_authorization_id", sa.Uuid(), nullable=False),
        sa.Column("replica_id", sa.Uuid(), nullable=False),
        sa.Column("activation_receipt_id", sa.Uuid(), nullable=False),
        sa.Column("terminal_receipt_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_hash", sa.String(64), nullable=False),
        sa.Column("authorization_approval_receipt_hash", sa.String(64), nullable=False),
        sa.Column("phase_z_health_qualification_hash", sa.String(64), nullable=False),
        sa.Column("execution_hash", sa.String(64), nullable=False),
        sa.Column("phase_x_authorization_hash", sa.String(64), nullable=False),
        sa.Column("replica_hash", sa.String(64), nullable=False),
        sa.Column("activation_receipt_hash", sa.String(64), nullable=False),
        sa.Column("terminal_receipt_hash", sa.String(64), nullable=False),
        sa.Column("verification_hash", sa.String(64), nullable=False),
        sa.Column("lease_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("lease_hash", sa.String(64), nullable=False),
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
        sa.Column("integrity_proof_hash", sa.String(64), nullable=False),
        sa.Column("request_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("health_qualification_hash", sa.String(64), nullable=False),
        sa.Column("health_state", sa.String(20), nullable=False, server_default="healthy"),
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
        sa.Column("qualified_by_id", sa.Uuid(), nullable=True),
        sa.Column("qualified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("qualification_reason", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["canary_lease_id"], ["evidence_recovery_routable_dual_write_canary_leases.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_id"], ["evidence_recovery_routable_dual_write_canary_authorizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_approval_receipt_id"], ["evidence_recovery_routable_dual_write_canary_auth_receipts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_z_health_qualification_id"], ["evidence_recovery_dual_write_rehearsal_health_qualifications.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["execution_id"], ["evidence_recovery_dual_write_rehearsal_executions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_x_authorization_id"], ["evidence_recovery_dual_write_rehearsal_authorizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["replica_id"], ["evidence_recovery_replicas.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["activation_receipt_id"], ["evidence_recovery_routable_dual_write_canary_receipts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["terminal_receipt_id"], ["evidence_recovery_routable_dual_write_canary_receipts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_ab_activated_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_aa_requested_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_aa_approved_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_z_qualified_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_y_executed_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_x_approved_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["qualified_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["rejected_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["terminal_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("canary_lease_id", name="uq_dw_can_health_lease"),
        sa.UniqueConstraint("organization_id", "health_qualification_hash", name="uq_dw_can_health_org_hash"),
        sa.CheckConstraint("status IN ('pending_second_approval','qualified','rejected','expired','invalidated')", name="ck_dw_can_health_status"),
        sa.CheckConstraint("health_state = 'healthy'", name="ck_dw_can_health_healthy"),
        sa.CheckConstraint("requested_by_id <> qualified_by_id OR qualified_by_id IS NULL", name="ck_dw_can_health_four_eyes"),
        sa.CheckConstraint("phase_ab_activated_by_id <> qualified_by_id OR qualified_by_id IS NULL", name="ck_dw_can_health_ab_split"),
        sa.CheckConstraint("phase_aa_requested_by_id <> qualified_by_id OR qualified_by_id IS NULL", name="ck_dw_can_health_aar_split"),
        sa.CheckConstraint("phase_aa_approved_by_id <> qualified_by_id OR qualified_by_id IS NULL", name="ck_dw_can_health_aaa_split"),
        sa.CheckConstraint("phase_z_qualified_by_id <> qualified_by_id OR qualified_by_id IS NULL", name="ck_dw_can_health_z_split"),
        sa.CheckConstraint("phase_y_executed_by_id <> qualified_by_id OR qualified_by_id IS NULL", name="ck_dw_can_health_y_split"),
        sa.CheckConstraint("phase_x_approved_by_id <> qualified_by_id OR qualified_by_id IS NULL", name="ck_dw_can_health_x_split"),
        sa.CheckConstraint("source_file_size_bytes >= 0", name="ck_dw_can_health_size"),
        sa.CheckConstraint("observed_file_size_bytes = source_file_size_bytes", name="ck_dw_can_health_obs_size"),
        sa.CheckConstraint("read_route_version_at_request >= 1", name="ck_dw_can_health_read_ver"),
        sa.CheckConstraint("write_route_version_at_request >= 1", name="ck_dw_can_health_write_ver"),
        *_safety_constraints("dw_can_health"),
    )
    op.create_index("ix_dw_can_health_org_claim", QUAL, ["organization_id", "claim_id", "status"])
    op.create_index("ix_dw_can_health_org_doc", QUAL, ["organization_id", "document_id", "status"])

    op.create_table(
        RECEIPT,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("health_qualification_id", sa.Uuid(), nullable=False),
        sa.Column("canary_lease_id", sa.Uuid(), nullable=False),
        sa.Column("phase", sa.String(20), nullable=False),
        sa.Column("health_state", sa.String(20), nullable=False, server_default="healthy"),
        sa.Column("integrity_proof_hash", sa.String(64), nullable=False),
        sa.Column("request_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("health_qualification_hash", sa.String(64), nullable=False),
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
        sa.ForeignKeyConstraint(["health_qualification_id"], [f"{QUAL}.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["canary_lease_id"], ["evidence_recovery_routable_dual_write_canary_leases.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "receipt_hash", name="uq_dw_can_health_rec_org_hash"),
        sa.CheckConstraint("phase IN ('requested','qualified','rejected','expired','invalidated')", name="ck_dw_can_health_rec_phase"),
        sa.CheckConstraint("health_state = 'healthy'", name="ck_dw_can_health_rec_healthy"),
        *_safety_constraints("dw_can_health_rec"),
    )
    op.create_index("ix_dw_can_health_rec_time", RECEIPT, ["health_qualification_id", "transitioned_at"])


def downgrade() -> None:
    op.drop_index("ix_dw_can_health_rec_time", table_name=RECEIPT)
    op.drop_table(RECEIPT)
    op.drop_index("ix_dw_can_health_org_doc", table_name=QUAL)
    op.drop_index("ix_dw_can_health_org_claim", table_name=QUAL)
    op.drop_table(QUAL)
