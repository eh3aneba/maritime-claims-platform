"""Add Phase AB bounded routable dual-write canary execution.

Revision ID: 0141_routable_dual_write_canary_execution
Revises: 0140_routable_dual_write_canary_authorization
"""

from alembic import op
import sqlalchemy as sa

revision = "0141_routable_dual_write_canary_execution"
down_revision = "0140_routable_dual_write_canary_authorization"
branch_labels = None
depends_on = None

LEASE = "evidence_recovery_routable_dual_write_canary_leases"
ROUTE = "evidence_recovery_routable_dual_write_canary_routes"
RECEIPT = "evidence_recovery_routable_dual_write_canary_receipts"


def _immutable_safety_columns() -> list[sa.Column]:
    return [
        sa.Column("local_authoritative", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("durable_write_authority_created", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("rehearsal_object_routable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("read_path_switched", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("write_path_switched", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("document_storage_key_mutated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("authoritative_storage_changed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("destructive_action_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("s3_copy_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("s3_delete_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("local_delete_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
    ]


def _immutable_safety_constraints(prefix: str) -> list[sa.CheckConstraint]:
    return [
        sa.CheckConstraint("local_authoritative = true", name=f"ck_{prefix}_local_auth"),
        sa.CheckConstraint("durable_write_authority_created = false", name=f"ck_{prefix}_no_durable"),
        sa.CheckConstraint("rehearsal_object_routable = false", name=f"ck_{prefix}_reh_nonroute"),
        sa.CheckConstraint("read_path_switched = false", name=f"ck_{prefix}_no_read"),
        sa.CheckConstraint("write_path_switched = false", name=f"ck_{prefix}_no_write_switch"),
        sa.CheckConstraint("document_storage_key_mutated = false", name=f"ck_{prefix}_no_key"),
        sa.CheckConstraint("authoritative_storage_changed = false", name=f"ck_{prefix}_no_owner"),
        sa.CheckConstraint("destructive_action_performed = false", name=f"ck_{prefix}_no_dest"),
        sa.CheckConstraint("s3_copy_performed = false", name=f"ck_{prefix}_no_copy"),
        sa.CheckConstraint("s3_delete_performed = false", name=f"ck_{prefix}_no_s3del"),
        sa.CheckConstraint("local_delete_performed = false", name=f"ck_{prefix}_no_localdel"),
    ]


def upgrade() -> None:
    op.create_table(
        LEASE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_approval_receipt_id", sa.Uuid(), nullable=False),
        sa.Column("phase_z_health_qualification_id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("phase_x_authorization_id", sa.Uuid(), nullable=False),
        sa.Column("replica_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_hash", sa.String(64), nullable=False),
        sa.Column("authorization_request_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("authorization_approval_receipt_hash", sa.String(64), nullable=False),
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
        sa.Column("read_route_version_at_activation", sa.Integer(), nullable=False),
        sa.Column("write_route_version_at_activation", sa.Integer(), nullable=False),
        sa.Column("canary_object_key_fingerprint", sa.String(64), nullable=False),
        sa.Column("observed_file_hash", sa.String(64), nullable=False),
        sa.Column("observed_file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("remote_etag", sa.String(255), nullable=True),
        sa.Column("verification_hash", sa.String(64), nullable=False),
        sa.Column("lease_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("lease_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("max_canary_writes", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("storage_write_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("canary_executed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("canary_write_verified", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("routable_dual_write_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("activated_by_id", sa.Uuid(), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("activation_reason", sa.Text(), nullable=False),
        sa.Column("terminal_by_id", sa.Uuid(), nullable=True),
        sa.Column("terminal_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terminal_reason", sa.Text(), nullable=True),
        *_immutable_safety_columns(),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_id"], ["evidence_recovery_routable_dual_write_canary_authorizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_approval_receipt_id"], ["evidence_recovery_routable_dual_write_canary_auth_receipts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_z_health_qualification_id"], ["evidence_recovery_dual_write_rehearsal_health_qualifications.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["execution_id"], ["evidence_recovery_dual_write_rehearsal_executions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_x_authorization_id"], ["evidence_recovery_dual_write_rehearsal_authorizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["replica_id"], ["evidence_recovery_replicas.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["activated_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["terminal_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("authorization_id", name="uq_dw_can_lease_auth"),
        sa.UniqueConstraint("organization_id", "lease_hash", name="uq_dw_can_lease_org_hash"),
        sa.CheckConstraint("status IN ('active','rolled_back','expired','invalidated')", name="ck_dw_can_lease_status"),
        sa.CheckConstraint("source_file_size_bytes >= 0", name="ck_dw_can_lease_size"),
        sa.CheckConstraint("observed_file_size_bytes = source_file_size_bytes", name="ck_dw_can_lease_obs_size"),
        sa.CheckConstraint("read_route_version_at_activation >= 1", name="ck_dw_can_lease_read_ver"),
        sa.CheckConstraint("write_route_version_at_activation >= 1", name="ck_dw_can_lease_write_ver"),
        sa.CheckConstraint("max_canary_writes = 1", name="ck_dw_can_lease_one_write"),
        sa.CheckConstraint("canary_executed = true", name="ck_dw_can_lease_exec"),
        sa.CheckConstraint("canary_write_verified = true", name="ck_dw_can_lease_verified"),
        sa.CheckConstraint("((status = 'active' AND routable_dual_write_active = true) OR (status <> 'active' AND routable_dual_write_active = false))", name="ck_dw_can_lease_active_flag"),
        *_immutable_safety_constraints("dw_can_lease"),
    )
    op.create_index("ix_dw_can_lease_org_claim", LEASE, ["organization_id", "claim_id", "status"])
    op.create_index("ix_dw_can_lease_org_doc", LEASE, ["organization_id", "document_id", "status"])

    op.create_table(
        ROUTE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("write_mode", sa.String(40), nullable=False, server_default="local_only"),
        sa.Column("active_canary_lease_id", sa.Uuid(), nullable=True),
        sa.Column("route_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("changed_by_id", sa.Uuid(), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        *_immutable_safety_columns(),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["active_canary_lease_id"], [f"{LEASE}.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["changed_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", name="uq_dw_can_route_document"),
        sa.CheckConstraint("write_mode IN ('local_only','local_plus_recovery_canary')", name="ck_dw_can_route_mode"),
        sa.CheckConstraint("route_version >= 1", name="ck_dw_can_route_version"),
        sa.CheckConstraint("((write_mode = 'local_only' AND active_canary_lease_id IS NULL) OR (write_mode = 'local_plus_recovery_canary' AND active_canary_lease_id IS NOT NULL))", name="ck_dw_can_route_binding"),
        *_immutable_safety_constraints("dw_can_route"),
    )
    op.create_index("ix_dw_can_route_org_claim", ROUTE, ["organization_id", "claim_id"])

    op.create_table(
        RECEIPT,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("canary_lease_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_id", sa.Uuid(), nullable=False),
        sa.Column("phase", sa.String(20), nullable=False),
        sa.Column("from_write_mode", sa.String(40), nullable=False),
        sa.Column("to_write_mode", sa.String(40), nullable=False),
        sa.Column("authorization_hash", sa.String(64), nullable=False),
        sa.Column("authorization_approval_receipt_hash", sa.String(64), nullable=False),
        sa.Column("canary_object_key_fingerprint", sa.String(64), nullable=False),
        sa.Column("source_file_hash", sa.String(64), nullable=False),
        sa.Column("source_file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("verification_hash", sa.String(64), nullable=False),
        sa.Column("lease_hash", sa.String(64), nullable=False),
        sa.Column("receipt_hash", sa.String(64), nullable=False),
        sa.Column("storage_write_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("canary_executed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("canary_write_verified", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("routable_dual_write_active", sa.Boolean(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("transitioned_at", sa.DateTime(timezone=True), nullable=False),
        *_immutable_safety_columns(),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["canary_lease_id"], [f"{LEASE}.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_id"], ["evidence_recovery_routable_dual_write_canary_authorizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "receipt_hash", name="uq_dw_can_exec_rec_org_hash"),
        sa.CheckConstraint("phase IN ('activated','rolled_back','expired','invalidated')", name="ck_dw_can_exec_rec_phase"),
        sa.CheckConstraint("from_write_mode IN ('local_only','local_plus_recovery_canary') AND to_write_mode IN ('local_only','local_plus_recovery_canary')", name="ck_dw_can_exec_rec_modes"),
        sa.CheckConstraint("canary_executed = true", name="ck_dw_can_exec_rec_exec"),
        sa.CheckConstraint("canary_write_verified = true", name="ck_dw_can_exec_rec_verified"),
        sa.CheckConstraint("((phase = 'activated' AND routable_dual_write_active = true) OR (phase <> 'activated' AND routable_dual_write_active = false))", name="ck_dw_can_exec_rec_active"),
        *_immutable_safety_constraints("dw_can_exec_rec"),
    )
    op.create_index("ix_dw_can_exec_rec_time", RECEIPT, ["canary_lease_id", "transitioned_at"])


def downgrade() -> None:
    op.drop_index("ix_dw_can_exec_rec_time", table_name=RECEIPT)
    op.drop_table(RECEIPT)
    op.drop_index("ix_dw_can_route_org_claim", table_name=ROUTE)
    op.drop_table(ROUTE)
    op.drop_index("ix_dw_can_lease_org_doc", table_name=LEASE)
    op.drop_index("ix_dw_can_lease_org_claim", table_name=LEASE)
    op.drop_table(LEASE)
