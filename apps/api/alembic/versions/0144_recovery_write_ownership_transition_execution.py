"""Execute bounded reversible recovery write-ownership transition.

Revision ID: 0144_recovery_write_ownership_transition_execution
Revises: 0143_recovery_write_ownership_transition_authorization
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0144_recovery_write_ownership_transition_execution"
down_revision = "0143_recovery_write_ownership_transition_authorization"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "evidence_recovery_write_ownership_transition_leases",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("authorization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("authorization_approval_receipt_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("phase_ac_health_qualification_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("canary_lease_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("replica_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("authorization_hash", sa.String(length=64), nullable=False),
        sa.Column("authorization_request_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("authorization_approval_receipt_hash", sa.String(length=64), nullable=False),
        sa.Column("phase_ac_health_qualification_hash", sa.String(length=64), nullable=False),
        sa.Column("phase_ac_health_receipt_hash", sa.String(length=64), nullable=False),
        sa.Column("canary_lease_hash", sa.String(length=64), nullable=False),
        sa.Column("replica_hash", sa.String(length=64), nullable=False),
        sa.Column("source_file_hash", sa.String(length=64), nullable=False),
        sa.Column("source_file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("local_storage_key_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("recovery_bucket_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("candidate_storage_key_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("source_authority_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("candidate_authority_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("configuration_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("observed_replica_hash", sa.String(length=64), nullable=False),
        sa.Column("observed_replica_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("observed_replica_etag", sa.String(length=255), nullable=True),
        sa.Column("read_route_version_at_activation", sa.Integer(), nullable=False),
        sa.Column("write_route_version_before_activation", sa.Integer(), nullable=False),
        sa.Column("write_route_version_after_activation", sa.Integer(), nullable=False),
        sa.Column("activation_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("lease_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("bounded_write_ownership_transition_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("write_path_switched", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("activated_by_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("route_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("activation_reason", sa.Text(), nullable=False),
        sa.Column("terminal_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("terminal_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terminal_reason", sa.Text(), nullable=True),
        sa.Column("local_authoritative", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("storage_write_performed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("durable_write_authority_created", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("read_path_switched", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("document_storage_key_mutated", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("authoritative_storage_changed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("destructive_action_performed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("s3_put_performed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("s3_copy_performed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("s3_delete_performed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("local_overwrite_performed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("local_move_performed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("local_delete_performed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('active','rolled_back','expired','invalidated')", name="ck_wr_owner_lease_status"),
        sa.CheckConstraint("source_file_size_bytes >= 0", name="ck_wr_owner_lease_source_size"),
        sa.CheckConstraint("observed_replica_size_bytes = source_file_size_bytes", name="ck_wr_owner_lease_replica_size"),
        sa.CheckConstraint("observed_replica_hash = source_file_hash", name="ck_wr_owner_lease_replica_hash"),
        sa.CheckConstraint("read_route_version_at_activation >= 1", name="ck_wr_owner_lease_read_ver"),
        sa.CheckConstraint("write_route_version_before_activation >= 1", name="ck_wr_owner_lease_write_before"),
        sa.CheckConstraint("write_route_version_after_activation = write_route_version_before_activation + 1", name="ck_wr_owner_lease_write_after"),
        sa.CheckConstraint("route_expires_at > activated_at", name="ck_wr_owner_lease_window"),
        sa.CheckConstraint("((status = 'active' AND bounded_write_ownership_transition_active = true AND write_path_switched = true) OR (status <> 'active' AND bounded_write_ownership_transition_active = false AND write_path_switched = false))", name="ck_wr_owner_lease_state_flags"),
        sa.CheckConstraint("local_authoritative = true", name="ck_wr_owner_lease_local_auth"),
        sa.CheckConstraint("storage_write_performed = false", name="ck_wr_owner_lease_no_storage_write"),
        sa.CheckConstraint("durable_write_authority_created = false", name="ck_wr_owner_lease_no_durable"),
        sa.CheckConstraint("read_path_switched = false", name="ck_wr_owner_lease_no_read"),
        sa.CheckConstraint("document_storage_key_mutated = false", name="ck_wr_owner_lease_no_key"),
        sa.CheckConstraint("authoritative_storage_changed = false", name="ck_wr_owner_lease_no_owner"),
        sa.CheckConstraint("destructive_action_performed = false", name="ck_wr_owner_lease_no_dest"),
        sa.CheckConstraint("s3_put_performed = false", name="ck_wr_owner_lease_no_put"),
        sa.CheckConstraint("s3_copy_performed = false", name="ck_wr_owner_lease_no_copy"),
        sa.CheckConstraint("s3_delete_performed = false", name="ck_wr_owner_lease_no_s3del"),
        sa.CheckConstraint("local_overwrite_performed = false", name="ck_wr_owner_lease_no_overwrite"),
        sa.CheckConstraint("local_move_performed = false", name="ck_wr_owner_lease_no_move"),
        sa.CheckConstraint("local_delete_performed = false", name="ck_wr_owner_lease_no_localdel"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_id"], ["evidence_recovery_write_ownership_transition_authorizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_approval_receipt_id"], ["evidence_recovery_write_ownership_transition_auth_receipts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_ac_health_qualification_id"], ["evidence_recovery_routable_dual_write_canary_health_qualifications.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["canary_lease_id"], ["evidence_recovery_routable_dual_write_canary_leases.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["replica_id"], ["evidence_recovery_replicas.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["activated_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["terminal_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("authorization_id", name="uq_wr_owner_lease_authorization"),
        sa.UniqueConstraint("organization_id", "lease_hash", name="uq_wr_owner_lease_org_hash"),
    )
    op.create_index("ix_wr_owner_lease_org_claim", "evidence_recovery_write_ownership_transition_leases", ["organization_id", "claim_id", "status"])
    op.create_index("ix_wr_owner_lease_org_doc", "evidence_recovery_write_ownership_transition_leases", ["organization_id", "document_id", "status"])

    op.create_table(
        "evidence_recovery_write_ownership_transition_receipts",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("transition_lease_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("authorization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("phase", sa.String(length=20), nullable=False),
        sa.Column("from_write_mode", sa.String(length=40), nullable=False),
        sa.Column("to_write_mode", sa.String(length=40), nullable=False),
        sa.Column("route_version", sa.Integer(), nullable=False),
        sa.Column("authorization_hash", sa.String(length=64), nullable=False),
        sa.Column("authorization_approval_receipt_hash", sa.String(length=64), nullable=False),
        sa.Column("phase_ac_health_qualification_hash", sa.String(length=64), nullable=False),
        sa.Column("source_file_hash", sa.String(length=64), nullable=False),
        sa.Column("source_file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("observed_replica_hash", sa.String(length=64), nullable=False),
        sa.Column("observed_replica_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("activation_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("lease_hash", sa.String(length=64), nullable=False),
        sa.Column("receipt_hash", sa.String(length=64), nullable=False),
        sa.Column("bounded_write_ownership_transition_active", sa.Boolean(), nullable=False),
        sa.Column("write_path_switched", sa.Boolean(), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("transitioned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("local_authoritative", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("storage_write_performed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("durable_write_authority_created", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("read_path_switched", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("document_storage_key_mutated", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("authoritative_storage_changed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("destructive_action_performed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("s3_put_performed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("s3_copy_performed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("s3_delete_performed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("local_overwrite_performed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("local_move_performed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("local_delete_performed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("phase IN ('activated','rolled_back','expired','invalidated')", name="ck_wr_owner_rec_phase"),
        sa.CheckConstraint("from_write_mode IN ('local_only','recovery_primary') AND to_write_mode IN ('local_only','recovery_primary')", name="ck_wr_owner_rec_modes"),
        sa.CheckConstraint("route_version >= 1", name="ck_wr_owner_rec_route_ver"),
        sa.CheckConstraint("((phase = 'activated' AND bounded_write_ownership_transition_active = true AND write_path_switched = true) OR (phase <> 'activated' AND bounded_write_ownership_transition_active = false AND write_path_switched = false))", name="ck_wr_owner_rec_state_flags"),
        sa.CheckConstraint("local_authoritative = true", name="ck_wr_owner_rec_local_auth"),
        sa.CheckConstraint("storage_write_performed = false", name="ck_wr_owner_rec_no_storage_write"),
        sa.CheckConstraint("durable_write_authority_created = false", name="ck_wr_owner_rec_no_durable"),
        sa.CheckConstraint("read_path_switched = false", name="ck_wr_owner_rec_no_read"),
        sa.CheckConstraint("document_storage_key_mutated = false", name="ck_wr_owner_rec_no_key"),
        sa.CheckConstraint("authoritative_storage_changed = false", name="ck_wr_owner_rec_no_owner"),
        sa.CheckConstraint("destructive_action_performed = false", name="ck_wr_owner_rec_no_dest"),
        sa.CheckConstraint("s3_put_performed = false", name="ck_wr_owner_rec_no_put"),
        sa.CheckConstraint("s3_copy_performed = false", name="ck_wr_owner_rec_no_copy"),
        sa.CheckConstraint("s3_delete_performed = false", name="ck_wr_owner_rec_no_s3del"),
        sa.CheckConstraint("local_overwrite_performed = false", name="ck_wr_owner_rec_no_overwrite"),
        sa.CheckConstraint("local_move_performed = false", name="ck_wr_owner_rec_no_move"),
        sa.CheckConstraint("local_delete_performed = false", name="ck_wr_owner_rec_no_localdel"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["transition_lease_id"], ["evidence_recovery_write_ownership_transition_leases.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_id"], ["evidence_recovery_write_ownership_transition_authorizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "receipt_hash", name="uq_wr_owner_rec_org_hash"),
    )
    op.create_index("ix_wr_owner_rec_time", "evidence_recovery_write_ownership_transition_receipts", ["transition_lease_id", "transitioned_at"])

    op.add_column(
        "evidence_recovery_routable_dual_write_canary_routes",
        sa.Column("active_write_ownership_transition_lease_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_dw_can_route_write_owner_lease",
        "evidence_recovery_routable_dual_write_canary_routes",
        "evidence_recovery_write_ownership_transition_leases",
        ["active_write_ownership_transition_lease_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint("ck_dw_can_route_mode", "evidence_recovery_routable_dual_write_canary_routes", type_="check")
    op.drop_constraint("ck_dw_can_route_binding", "evidence_recovery_routable_dual_write_canary_routes", type_="check")
    op.drop_constraint("ck_dw_can_route_no_write_switch", "evidence_recovery_routable_dual_write_canary_routes", type_="check")
    op.create_check_constraint("ck_dw_can_route_mode", "evidence_recovery_routable_dual_write_canary_routes", "write_mode IN ('local_only','local_plus_recovery_canary','recovery_primary')")
    op.create_check_constraint(
        "ck_dw_can_route_binding",
        "evidence_recovery_routable_dual_write_canary_routes",
        "((write_mode = 'local_only' AND active_canary_lease_id IS NULL AND active_write_ownership_transition_lease_id IS NULL) OR (write_mode = 'local_plus_recovery_canary' AND active_canary_lease_id IS NOT NULL AND active_write_ownership_transition_lease_id IS NULL) OR (write_mode = 'recovery_primary' AND active_canary_lease_id IS NULL AND active_write_ownership_transition_lease_id IS NOT NULL))",
    )
    op.create_check_constraint(
        "ck_dw_can_route_write_switch",
        "evidence_recovery_routable_dual_write_canary_routes",
        "((write_mode = 'recovery_primary' AND write_path_switched = true) OR (write_mode <> 'recovery_primary' AND write_path_switched = false))",
    )


def downgrade() -> None:
    op.execute(sa.text("UPDATE evidence_recovery_routable_dual_write_canary_routes SET write_mode = 'local_only', active_canary_lease_id = NULL, active_write_ownership_transition_lease_id = NULL, write_path_switched = false, route_version = route_version + 1 WHERE write_mode = 'recovery_primary'"))
    op.drop_constraint("ck_dw_can_route_write_switch", "evidence_recovery_routable_dual_write_canary_routes", type_="check")
    op.drop_constraint("ck_dw_can_route_binding", "evidence_recovery_routable_dual_write_canary_routes", type_="check")
    op.drop_constraint("ck_dw_can_route_mode", "evidence_recovery_routable_dual_write_canary_routes", type_="check")
    op.create_check_constraint("ck_dw_can_route_mode", "evidence_recovery_routable_dual_write_canary_routes", "write_mode IN ('local_only','local_plus_recovery_canary')")
    op.create_check_constraint("ck_dw_can_route_binding", "evidence_recovery_routable_dual_write_canary_routes", "((write_mode = 'local_only' AND active_canary_lease_id IS NULL) OR (write_mode = 'local_plus_recovery_canary' AND active_canary_lease_id IS NOT NULL))")
    op.create_check_constraint("ck_dw_can_route_no_write_switch", "evidence_recovery_routable_dual_write_canary_routes", "write_path_switched = false")
    op.drop_constraint("fk_dw_can_route_write_owner_lease", "evidence_recovery_routable_dual_write_canary_routes", type_="foreignkey")
    op.drop_column("evidence_recovery_routable_dual_write_canary_routes", "active_write_ownership_transition_lease_id")
    op.drop_index("ix_wr_owner_rec_time", table_name="evidence_recovery_write_ownership_transition_receipts")
    op.drop_table("evidence_recovery_write_ownership_transition_receipts")
    op.drop_index("ix_wr_owner_lease_org_doc", table_name="evidence_recovery_write_ownership_transition_leases")
    op.drop_index("ix_wr_owner_lease_org_claim", table_name="evidence_recovery_write_ownership_transition_leases")
    op.drop_table("evidence_recovery_write_ownership_transition_leases")
