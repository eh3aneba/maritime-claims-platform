"""add reversible durable recovery read routing

Revision ID: 0126_recovery_durable_read_routing
Revises: 0125_recovery_durable_read_promotion_authorization
"""

from alembic import op
import sqlalchemy as sa

revision = "0126_recovery_durable_read_routing"
down_revision = "0125_recovery_durable_read_promotion_authorization"
branch_labels = None
depends_on = None

LEASE_TABLE = "evidence_recovery_durable_read_promotion_leases"
RECEIPT_TABLE = "evidence_recovery_durable_read_promotion_receipts"
ROUTE_TABLE = "evidence_recovery_read_path_routes"


def upgrade() -> None:
    op.create_table(
        LEASE_TABLE,
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_approval_receipt_id", sa.Uuid(), nullable=False),
        sa.Column("qualification_id", sa.Uuid(), nullable=False),
        sa.Column("replica_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_hash", sa.String(length=64), nullable=False),
        sa.Column("authorization_request_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("authorization_integrity_proof_hash", sa.String(length=64), nullable=False),
        sa.Column("authorization_approval_receipt_hash", sa.String(length=64), nullable=False),
        sa.Column("qualification_hash", sa.String(length=64), nullable=False),
        sa.Column("qualification_bundle_hash", sa.String(length=64), nullable=False),
        sa.Column("replica_hash", sa.String(length=64), nullable=False),
        sa.Column("source_file_hash", sa.String(length=64), nullable=False),
        sa.Column("source_file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("local_storage_key_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("recovery_bucket_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("candidate_storage_key_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("source_authority_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("candidate_authority_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("configuration_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("route_version_at_prepare", sa.Integer(), nullable=False),
        sa.Column("lease_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("lease_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="prepared", nullable=False),
        sa.Column("activation_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("route_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("authorization_approved_by_id", sa.Uuid(), nullable=False),
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
        sa.Column("routable_authority_created", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("durable_read_route_created", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("read_path_switched", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("write_path_switched", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("document_storage_key_mutated", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("authoritative_storage_changed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("destructive_action_performed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("s3_delete_performed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("local_delete_performed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('prepared', 'activated', 'rolled_back', 'expired', 'invalidated')", name="ck_recovery_durable_route_lease_status"),
        sa.CheckConstraint("prepared_by_id <> activated_by_id OR activated_by_id IS NULL", name="ck_recovery_durable_route_lease_four_eyes"),
        sa.CheckConstraint("authorization_approved_by_id <> activated_by_id OR activated_by_id IS NULL", name="ck_recovery_durable_route_lease_approver_split"),
        sa.CheckConstraint("((status = 'activated' AND routable_authority_created = true AND durable_read_route_created = true AND read_path_switched = true) OR (status <> 'activated' AND routable_authority_created = false AND durable_read_route_created = false AND read_path_switched = false))", name="ck_recovery_durable_route_lease_state_flags"),
        sa.CheckConstraint("source_file_size_bytes >= 0", name="ck_recovery_durable_route_lease_source_size"),
        sa.CheckConstraint("write_path_switched = false", name="ck_recovery_durable_route_lease_no_write"),
        sa.CheckConstraint("document_storage_key_mutated = false", name="ck_recovery_durable_route_lease_no_key"),
        sa.CheckConstraint("authoritative_storage_changed = false", name="ck_recovery_durable_route_lease_no_authority"),
        sa.CheckConstraint("destructive_action_performed = false", name="ck_recovery_durable_route_lease_no_destructive"),
        sa.CheckConstraint("s3_delete_performed = false", name="ck_recovery_durable_route_lease_no_s3_delete"),
        sa.CheckConstraint("local_delete_performed = false", name="ck_recovery_durable_route_lease_no_local_delete"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_id"], ["evidence_recovery_durable_read_promotion_authorizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_approval_receipt_id"], ["evidence_recovery_durable_read_promotion_authorization_receipts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["qualification_id"], ["evidence_recovery_routable_read_qualifications.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["replica_id"], ["evidence_recovery_replicas.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_approved_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["prepared_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["activated_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["rolled_back_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["terminal_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("authorization_id", name="uq_recovery_durable_route_lease_authorization"),
        sa.UniqueConstraint("organization_id", "lease_hash", name="uq_recovery_durable_route_lease_org_hash"),
    )
    op.create_index("ix_drrl_org_claim_status", LEASE_TABLE, ["organization_id", "claim_id", "status"], unique=False)
    op.create_index("ix_drrl_org_doc_status", LEASE_TABLE, ["organization_id", "document_id", "status"], unique=False)
    op.create_index("ix_drrl_auth_receipt", LEASE_TABLE, ["authorization_approval_receipt_id"], unique=False)
    op.create_index("ix_drrl_qualification", LEASE_TABLE, ["qualification_id"], unique=False)
    op.create_index("ix_drrl_replica", LEASE_TABLE, ["replica_id"], unique=False)
    op.create_index("ix_drrl_approver", LEASE_TABLE, ["authorization_approved_by_id"], unique=False)
    op.create_index("ix_drrl_preparer", LEASE_TABLE, ["prepared_by_id"], unique=False)
    op.create_index("ix_drrl_activator", LEASE_TABLE, ["activated_by_id"], unique=False)
    op.create_index("ix_drrl_rollback_actor", LEASE_TABLE, ["rolled_back_by_id"], unique=False)
    op.create_index("ix_drrl_terminal_actor", LEASE_TABLE, ["terminal_by_id"], unique=False)

    op.create_table(
        RECEIPT_TABLE,
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("durable_lease_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_id", sa.Uuid(), nullable=False),
        sa.Column("phase", sa.String(length=20), nullable=False),
        sa.Column("from_route_class", sa.String(length=24), nullable=False),
        sa.Column("to_route_class", sa.String(length=24), nullable=False),
        sa.Column("route_authority_kind", sa.String(length=24), nullable=False),
        sa.Column("route_version", sa.Integer(), nullable=False),
        sa.Column("lease_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("lease_hash", sa.String(length=64), nullable=False),
        sa.Column("authorization_hash", sa.String(length=64), nullable=False),
        sa.Column("receipt_hash", sa.String(length=64), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("transitioned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("routable_authority_created", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("durable_read_route_created", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("read_path_switched", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("write_path_switched", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("document_storage_key_mutated", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("authoritative_storage_changed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("destructive_action_performed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("s3_delete_performed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("local_delete_performed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("phase IN ('prepared', 'activated', 'rolled_back', 'expired', 'invalidated')", name="ck_recovery_durable_route_receipt_phase"),
        sa.CheckConstraint("from_route_class IN ('local_source', 'recovery_replica') AND to_route_class IN ('local_source', 'recovery_replica')", name="ck_recovery_durable_route_receipt_route_class"),
        sa.CheckConstraint("route_version >= 1", name="ck_recovery_durable_route_receipt_version"),
        sa.CheckConstraint("write_path_switched = false", name="ck_recovery_durable_route_receipt_no_write"),
        sa.CheckConstraint("document_storage_key_mutated = false", name="ck_recovery_durable_route_receipt_no_key"),
        sa.CheckConstraint("authoritative_storage_changed = false", name="ck_recovery_durable_route_receipt_no_authority"),
        sa.CheckConstraint("destructive_action_performed = false", name="ck_recovery_durable_route_receipt_no_destructive"),
        sa.CheckConstraint("s3_delete_performed = false", name="ck_recovery_durable_route_receipt_no_s3_delete"),
        sa.CheckConstraint("local_delete_performed = false", name="ck_recovery_durable_route_receipt_no_local_delete"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["durable_lease_id"], [f"{LEASE_TABLE}.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_id"], ["evidence_recovery_durable_read_promotion_authorizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "receipt_hash", name="uq_recovery_durable_route_receipt_org_hash"),
    )
    op.create_index("ix_drrr_lease_time", RECEIPT_TABLE, ["durable_lease_id", "transitioned_at"], unique=False)
    op.create_index("ix_drrr_authorization", RECEIPT_TABLE, ["authorization_id"], unique=False)
    op.create_index("ix_drrr_actor", RECEIPT_TABLE, ["actor_id"], unique=False)

    op.drop_constraint("ck_recovery_read_route_binding", ROUTE_TABLE, type_="check")
    op.add_column(ROUTE_TABLE, sa.Column("durable_authority_active", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column(ROUTE_TABLE, sa.Column("active_durable_lease_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_recovery_read_route_active_durable_lease",
        ROUTE_TABLE,
        LEASE_TABLE,
        ["active_durable_lease_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_evidence_recovery_read_path_routes_active_durable_lease_id", ROUTE_TABLE, ["active_durable_lease_id"], unique=False)
    op.create_check_constraint(
        "ck_recovery_read_route_binding",
        ROUTE_TABLE,
        "((route_class = 'local_source' AND durable_authority_active = false AND active_lease_id IS NULL AND active_durable_lease_id IS NULL AND active_replica_id IS NULL AND read_path_switched = false) OR "
        "(route_class = 'recovery_replica' AND durable_authority_active = false AND active_lease_id IS NOT NULL AND active_durable_lease_id IS NULL AND active_replica_id IS NOT NULL AND read_path_switched = true) OR "
        "(route_class = 'recovery_replica' AND durable_authority_active = true AND active_lease_id IS NULL AND active_durable_lease_id IS NOT NULL AND active_replica_id IS NOT NULL AND read_path_switched = true))",
    )


def downgrade() -> None:
    op.drop_constraint("ck_recovery_read_route_binding", ROUTE_TABLE, type_="check")
    op.drop_index("ix_evidence_recovery_read_path_routes_active_durable_lease_id", table_name=ROUTE_TABLE)
    op.drop_constraint("fk_recovery_read_route_active_durable_lease", ROUTE_TABLE, type_="foreignkey")
    op.drop_column(ROUTE_TABLE, "active_durable_lease_id")
    op.drop_column(ROUTE_TABLE, "durable_authority_active")
    op.create_check_constraint(
        "ck_recovery_read_route_binding",
        ROUTE_TABLE,
        "((route_class = 'local_source' AND active_lease_id IS NULL AND active_replica_id IS NULL AND read_path_switched = false) OR "
        "(route_class = 'recovery_replica' AND active_lease_id IS NOT NULL AND active_replica_id IS NOT NULL AND read_path_switched = true))",
    )
    op.drop_table(RECEIPT_TABLE)
    op.drop_table(LEASE_TABLE)
