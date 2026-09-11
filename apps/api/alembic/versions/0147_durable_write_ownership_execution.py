"""Add Phase AH durable recovery write ownership execution.

Revision ID: 0147_durable_write_ownership_execution
Revises: 0146_durable_write_ownership_authorization
"""

from alembic import op
import sqlalchemy as sa

revision = "0147_durable_write_ownership_execution"
down_revision = "0146_durable_write_ownership_authorization"
branch_labels = None
depends_on = None

LEASE = "evidence_recovery_durable_write_ownership_leases"
ROUTE = "evidence_recovery_durable_write_ownership_routes"
RECEIPT = "evidence_recovery_durable_write_ownership_receipts"


def _safety_columns() -> list[sa.Column]:
    return [
        sa.Column("local_authoritative", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("storage_write_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("read_path_switched", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("document_storage_key_mutated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("authoritative_storage_changed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("destructive_action_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("s3_put_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("s3_copy_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("s3_delete_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("local_overwrite_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("local_move_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("local_delete_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
    ]


def _safety_constraints(prefix: str) -> list[sa.CheckConstraint]:
    return [
        sa.CheckConstraint("local_authoritative = true", name=f"ck_{prefix}_local_auth"),
        sa.CheckConstraint("storage_write_performed = false", name=f"ck_{prefix}_no_write"),
        sa.CheckConstraint("read_path_switched = false", name=f"ck_{prefix}_no_read"),
        sa.CheckConstraint("document_storage_key_mutated = false", name=f"ck_{prefix}_no_key"),
        sa.CheckConstraint("authoritative_storage_changed = false", name=f"ck_{prefix}_no_owner"),
        sa.CheckConstraint("destructive_action_performed = false", name=f"ck_{prefix}_no_dest"),
        sa.CheckConstraint("s3_put_performed = false", name=f"ck_{prefix}_no_put"),
        sa.CheckConstraint("s3_copy_performed = false", name=f"ck_{prefix}_no_copy"),
        sa.CheckConstraint("s3_delete_performed = false", name=f"ck_{prefix}_no_s3del"),
        sa.CheckConstraint("local_overwrite_performed = false", name=f"ck_{prefix}_no_overwrite"),
        sa.CheckConstraint("local_move_performed = false", name=f"ck_{prefix}_no_move"),
        sa.CheckConstraint("local_delete_performed = false", name=f"ck_{prefix}_no_localdel"),
    ]


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.Column("phase_af_health_qualification_id", sa.Uuid(), nullable=False),
        sa.Column("transition_lease_id", sa.Uuid(), nullable=False),
        sa.Column("replica_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_hash", sa.String(64), nullable=False),
        sa.Column("authorization_request_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("authorization_approval_receipt_hash", sa.String(64), nullable=False),
        sa.Column("phase_af_health_qualification_hash", sa.String(64), nullable=False),
        sa.Column("phase_af_health_receipt_hash", sa.String(64), nullable=False),
        sa.Column("transition_lease_hash", sa.String(64), nullable=False),
        sa.Column("replica_hash", sa.String(64), nullable=False),
        sa.Column("source_file_hash", sa.String(64), nullable=False),
        sa.Column("source_file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("local_storage_key_fingerprint", sa.String(64), nullable=False),
        sa.Column("recovery_bucket_fingerprint", sa.String(64), nullable=False),
        sa.Column("candidate_storage_key_fingerprint", sa.String(64), nullable=False),
        sa.Column("source_authority_fingerprint", sa.String(64), nullable=False),
        sa.Column("candidate_authority_fingerprint", sa.String(64), nullable=False),
        sa.Column("configuration_fingerprint", sa.String(64), nullable=False),
        sa.Column("observed_local_hash", sa.String(64), nullable=False),
        sa.Column("observed_local_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("observed_recovery_hash", sa.String(64), nullable=False),
        sa.Column("observed_recovery_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("observed_recovery_etag", sa.String(255), nullable=True),
        sa.Column("read_route_version_at_activation", sa.Integer(), nullable=False),
        sa.Column("experimental_write_route_version_at_activation", sa.Integer(), nullable=False),
        sa.Column("durable_route_version_before_activation", sa.Integer(), nullable=False),
        sa.Column("durable_route_version_after_activation", sa.Integer(), nullable=False),
        sa.Column("activation_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("lease_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("durable_write_ownership_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("durable_write_authority_created", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("write_path_switched", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("activated_by_id", sa.Uuid(), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("activation_reason", sa.Text(), nullable=False),
        sa.Column("terminal_by_id", sa.Uuid(), nullable=True),
        sa.Column("terminal_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terminal_reason", sa.Text(), nullable=True),
        *_safety_columns(),
        *_timestamps(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_id"], ["evidence_recovery_durable_write_authorizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_approval_receipt_id"], ["evidence_recovery_durable_write_authorization_receipts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_af_health_qualification_id"], ["evidence_recovery_write_ownership_transition_health_qualifications.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["transition_lease_id"], ["evidence_recovery_write_ownership_transition_leases.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["replica_id"], ["evidence_recovery_replicas.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["activated_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["terminal_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("authorization_id", name="uq_dw_owner_lease_auth"),
        sa.UniqueConstraint("organization_id", "lease_hash", name="uq_dw_owner_lease_org_hash"),
        sa.CheckConstraint("status IN ('active','rolled_back','invalidated')", name="ck_dw_owner_lease_status"),
        sa.CheckConstraint("source_file_size_bytes >= 0", name="ck_dw_owner_lease_size"),
        sa.CheckConstraint("observed_local_size_bytes = source_file_size_bytes", name="ck_dw_owner_lease_local_size"),
        sa.CheckConstraint("observed_recovery_size_bytes = source_file_size_bytes", name="ck_dw_owner_lease_recovery_size"),
        sa.CheckConstraint("observed_local_hash = source_file_hash", name="ck_dw_owner_lease_local_hash"),
        sa.CheckConstraint("observed_recovery_hash = source_file_hash", name="ck_dw_owner_lease_recovery_hash"),
        sa.CheckConstraint("read_route_version_at_activation >= 1", name="ck_dw_owner_lease_read_ver"),
        sa.CheckConstraint("experimental_write_route_version_at_activation >= 1", name="ck_dw_owner_lease_exp_write_ver"),
        sa.CheckConstraint("durable_route_version_before_activation >= 0", name="ck_dw_owner_lease_before_ver"),
        sa.CheckConstraint("durable_route_version_after_activation = durable_route_version_before_activation + 1", name="ck_dw_owner_lease_after_ver"),
        sa.CheckConstraint("((status = 'active' AND durable_write_ownership_active = true AND durable_write_authority_created = true AND write_path_switched = true) OR (status <> 'active' AND durable_write_ownership_active = false AND durable_write_authority_created = false AND write_path_switched = false))", name="ck_dw_owner_lease_state"),
        *_safety_constraints("dw_owner_lease"),
    )
    op.create_index("ix_dw_owner_lease_org_claim", LEASE, ["organization_id", "claim_id", "status"])
    op.create_index("ix_dw_owner_lease_org_doc", LEASE, ["organization_id", "document_id", "status"])

    op.create_table(
        ROUTE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("write_mode", sa.String(40), nullable=False, server_default="local_only"),
        sa.Column("active_durable_write_ownership_lease_id", sa.Uuid(), nullable=True),
        sa.Column("route_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("durable_write_authority_created", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("write_path_switched", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("changed_by_id", sa.Uuid(), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        *_safety_columns(),
        *_timestamps(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["active_durable_write_ownership_lease_id"], [f"{LEASE}.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["changed_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", name="uq_dw_owner_route_document"),
        sa.CheckConstraint("write_mode IN ('local_only','recovery_primary')", name="ck_dw_owner_route_mode"),
        sa.CheckConstraint("route_version >= 1", name="ck_dw_owner_route_ver"),
        sa.CheckConstraint("((write_mode = 'local_only' AND active_durable_write_ownership_lease_id IS NULL AND durable_write_authority_created = false AND write_path_switched = false) OR (write_mode = 'recovery_primary' AND active_durable_write_ownership_lease_id IS NOT NULL AND durable_write_authority_created = true AND write_path_switched = true))", name="ck_dw_owner_route_state"),
        *_safety_constraints("dw_owner_route"),
    )
    op.create_index("ix_dw_owner_route_org_claim", ROUTE, ["organization_id", "claim_id"])

    op.create_table(
        RECEIPT,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("lease_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_id", sa.Uuid(), nullable=False),
        sa.Column("phase", sa.String(20), nullable=False),
        sa.Column("from_write_mode", sa.String(40), nullable=False),
        sa.Column("to_write_mode", sa.String(40), nullable=False),
        sa.Column("route_version", sa.Integer(), nullable=False),
        sa.Column("authorization_hash", sa.String(64), nullable=False),
        sa.Column("authorization_approval_receipt_hash", sa.String(64), nullable=False),
        sa.Column("phase_af_health_qualification_hash", sa.String(64), nullable=False),
        sa.Column("source_file_hash", sa.String(64), nullable=False),
        sa.Column("source_file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("activation_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("lease_hash", sa.String(64), nullable=False),
        sa.Column("receipt_hash", sa.String(64), nullable=False),
        sa.Column("durable_write_ownership_active", sa.Boolean(), nullable=False),
        sa.Column("durable_write_authority_created", sa.Boolean(), nullable=False),
        sa.Column("write_path_switched", sa.Boolean(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("transitioned_at", sa.DateTime(timezone=True), nullable=False),
        *_safety_columns(),
        *_timestamps(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["lease_id"], [f"{LEASE}.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_id"], ["evidence_recovery_durable_write_authorizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "receipt_hash", name="uq_dw_owner_rec_org_hash"),
        sa.CheckConstraint("phase IN ('activated','rolled_back','invalidated')", name="ck_dw_owner_rec_phase"),
        sa.CheckConstraint("from_write_mode IN ('local_only','recovery_primary')", name="ck_dw_owner_rec_from"),
        sa.CheckConstraint("to_write_mode IN ('local_only','recovery_primary')", name="ck_dw_owner_rec_to"),
        sa.CheckConstraint("route_version >= 1", name="ck_dw_owner_rec_ver"),
        sa.CheckConstraint("((phase = 'activated' AND durable_write_ownership_active = true AND durable_write_authority_created = true AND write_path_switched = true) OR (phase <> 'activated' AND durable_write_ownership_active = false AND durable_write_authority_created = false AND write_path_switched = false))", name="ck_dw_owner_rec_state"),
        *_safety_constraints("dw_owner_rec"),
    )
    op.create_index("ix_dw_owner_rec_time", RECEIPT, ["lease_id", "transitioned_at"])


def downgrade() -> None:
    op.drop_index("ix_dw_owner_rec_time", table_name=RECEIPT)
    op.drop_table(RECEIPT)
    op.drop_index("ix_dw_owner_route_org_claim", table_name=ROUTE)
    op.drop_table(ROUTE)
    op.drop_index("ix_dw_owner_lease_org_doc", table_name=LEASE)
    op.drop_index("ix_dw_owner_lease_org_claim", table_name=LEASE)
    op.drop_table(LEASE)
