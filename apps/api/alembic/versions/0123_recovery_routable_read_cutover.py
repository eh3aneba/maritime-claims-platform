"""add reversible routable recovery read-path cutover

Revision ID: 0123_recovery_routable_read_cutover
Revises: 0122_recovery_read_path_cutover_authorization
"""

from alembic import op
import sqlalchemy as sa

revision = "0123_recovery_routable_read_cutover"
down_revision = "0122_recovery_read_path_cutover_authorization"
branch_labels = None
depends_on = None

LEASE_TABLE = "evidence_recovery_read_path_cutover_leases"
ROUTE_TABLE = "evidence_recovery_read_path_routes"
RECEIPT_TABLE = "evidence_recovery_read_path_cutover_receipts"


def upgrade() -> None:
    op.create_table(
        LEASE_TABLE,
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_approval_receipt_id", sa.Uuid(), nullable=False),
        sa.Column("replica_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_hash", sa.String(length=64), nullable=False),
        sa.Column("authorization_request_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("authorization_approval_receipt_hash", sa.String(length=64), nullable=False),
        sa.Column("execution_transition_proof_hash", sa.String(length=64), nullable=False),
        sa.Column("replica_hash", sa.String(length=64), nullable=False),
        sa.Column("source_file_hash", sa.String(length=64), nullable=False),
        sa.Column("source_file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("recovery_bucket_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("candidate_storage_key_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("source_authority_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("candidate_authority_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("configuration_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("lease_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("lease_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="prepared", nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.Column("routable_authority_created", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("read_path_switched", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("write_path_switched", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("document_storage_key_mutated", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("authoritative_storage_changed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("destructive_action_performed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("s3_delete_performed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("local_delete_performed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('prepared', 'activated', 'rolled_back', 'expired', 'invalidated')", name="ck_recovery_route_lease_status"),
        sa.CheckConstraint("prepared_by_id <> activated_by_id OR activated_by_id IS NULL", name="ck_recovery_route_lease_four_eyes"),
        sa.CheckConstraint("authorization_approved_by_id <> activated_by_id OR activated_by_id IS NULL", name="ck_recovery_route_lease_approver_split"),
        sa.CheckConstraint("((status = 'activated' AND read_path_switched = true AND routable_authority_created = true) OR (status <> 'activated' AND read_path_switched = false AND routable_authority_created = false))", name="ck_recovery_route_lease_state_flags"),
        sa.CheckConstraint("write_path_switched = false", name="ck_recovery_route_lease_no_write_switch"),
        sa.CheckConstraint("document_storage_key_mutated = false", name="ck_recovery_route_lease_no_key_mut"),
        sa.CheckConstraint("authoritative_storage_changed = false", name="ck_recovery_route_lease_no_authority"),
        sa.CheckConstraint("destructive_action_performed = false", name="ck_recovery_route_lease_no_destructive"),
        sa.CheckConstraint("s3_delete_performed = false", name="ck_recovery_route_lease_no_s3_del"),
        sa.CheckConstraint("local_delete_performed = false", name="ck_recovery_route_lease_no_local_del"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_id"], ["evidence_recovery_read_path_cutover_authorizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_approval_receipt_id"], ["evidence_recovery_read_path_cutover_authorization_receipts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["replica_id"], ["evidence_recovery_replicas.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_approved_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["prepared_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["activated_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["rolled_back_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["terminal_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("authorization_id", name="uq_recovery_route_lease_authorization"),
        sa.UniqueConstraint("organization_id", "lease_hash", name="uq_recovery_route_lease_org_hash"),
    )
    op.create_index("ix_recovery_route_lease_org_claim_status", LEASE_TABLE, ["organization_id", "claim_id", "status"])
    op.create_index("ix_recovery_route_lease_org_doc_status", LEASE_TABLE, ["organization_id", "document_id", "status"])
    for name, column in (
        ("ix_route_lease_org", "organization_id"),
        ("ix_route_lease_claim", "claim_id"),
        ("ix_route_lease_doc", "document_id"),
        ("ix_route_lease_auth", "authorization_id"),
        ("ix_route_lease_auth_receipt", "authorization_approval_receipt_id"),
        ("ix_route_lease_replica", "replica_id"),
        ("ix_route_lease_preparer", "prepared_by_id"),
        ("ix_route_lease_activator", "activated_by_id"),
    ):
        op.create_index(name, LEASE_TABLE, [column])

    op.create_table(
        ROUTE_TABLE,
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("route_class", sa.String(length=24), server_default="local_source", nullable=False),
        sa.Column("active_lease_id", sa.Uuid(), nullable=True),
        sa.Column("active_replica_id", sa.Uuid(), nullable=True),
        sa.Column("source_authority_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("candidate_authority_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("configuration_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("route_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("changed_by_id", sa.Uuid(), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_path_switched", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("write_path_switched", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("document_storage_key_mutated", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("authoritative_storage_changed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("destructive_action_performed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("route_class IN ('local_source', 'recovery_replica')", name="ck_recovery_read_route_class"),
        sa.CheckConstraint("((route_class = 'local_source' AND active_lease_id IS NULL AND active_replica_id IS NULL AND read_path_switched = false) OR (route_class = 'recovery_replica' AND active_lease_id IS NOT NULL AND active_replica_id IS NOT NULL AND read_path_switched = true))", name="ck_recovery_read_route_binding"),
        sa.CheckConstraint("route_version >= 1", name="ck_recovery_read_route_version"),
        sa.CheckConstraint("write_path_switched = false", name="ck_recovery_read_route_no_write"),
        sa.CheckConstraint("document_storage_key_mutated = false", name="ck_recovery_read_route_no_key_mut"),
        sa.CheckConstraint("authoritative_storage_changed = false", name="ck_recovery_read_route_no_authority"),
        sa.CheckConstraint("destructive_action_performed = false", name="ck_recovery_read_route_no_destructive"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["active_lease_id"], [f"{LEASE_TABLE}.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["active_replica_id"], ["evidence_recovery_replicas.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["changed_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", name="uq_recovery_read_route_document"),
    )
    op.create_index("ix_recovery_read_route_org_claim", ROUTE_TABLE, ["organization_id", "claim_id"])
    for name, column in (
        ("ix_read_route_org", "organization_id"),
        ("ix_read_route_claim", "claim_id"),
        ("ix_read_route_doc", "document_id"),
        ("ix_read_route_lease", "active_lease_id"),
        ("ix_read_route_replica", "active_replica_id"),
        ("ix_read_route_actor", "changed_by_id"),
    ):
        op.create_index(name, ROUTE_TABLE, [column])

    op.create_table(
        RECEIPT_TABLE,
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("cutover_lease_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_id", sa.Uuid(), nullable=False),
        sa.Column("phase", sa.String(length=20), nullable=False),
        sa.Column("from_route_class", sa.String(length=24), nullable=False),
        sa.Column("to_route_class", sa.String(length=24), nullable=False),
        sa.Column("route_version", sa.Integer(), nullable=False),
        sa.Column("lease_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("lease_hash", sa.String(length=64), nullable=False),
        sa.Column("authorization_hash", sa.String(length=64), nullable=False),
        sa.Column("receipt_hash", sa.String(length=64), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("transitioned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("routable_authority_created", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("read_path_switched", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("write_path_switched", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("document_storage_key_mutated", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("authoritative_storage_changed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("destructive_action_performed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("phase IN ('prepared', 'activated', 'rolled_back', 'expired', 'invalidated')", name="ck_recovery_route_receipt_phase"),
        sa.CheckConstraint("from_route_class IN ('local_source', 'recovery_replica') AND to_route_class IN ('local_source', 'recovery_replica')", name="ck_recovery_route_receipt_route_class"),
        sa.CheckConstraint("write_path_switched = false", name="ck_recovery_route_receipt_no_write"),
        sa.CheckConstraint("document_storage_key_mutated = false", name="ck_recovery_route_receipt_no_key_mut"),
        sa.CheckConstraint("authoritative_storage_changed = false", name="ck_recovery_route_receipt_no_authority"),
        sa.CheckConstraint("destructive_action_performed = false", name="ck_recovery_route_receipt_no_dest"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["cutover_lease_id"], [f"{LEASE_TABLE}.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_id"], ["evidence_recovery_read_path_cutover_authorizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "receipt_hash", name="uq_recovery_route_receipt_org_hash"),
    )
    op.create_index("ix_recovery_route_receipt_time", RECEIPT_TABLE, ["cutover_lease_id", "transitioned_at"])
    op.create_index("ix_route_receipt_org", RECEIPT_TABLE, ["organization_id"])
    op.create_index("ix_route_receipt_actor", RECEIPT_TABLE, ["actor_id"])


def downgrade() -> None:
    op.drop_index("ix_route_receipt_actor", table_name=RECEIPT_TABLE)
    op.drop_index("ix_route_receipt_org", table_name=RECEIPT_TABLE)
    op.drop_index("ix_recovery_route_receipt_time", table_name=RECEIPT_TABLE)
    op.drop_table(RECEIPT_TABLE)

    for name in (
        "ix_read_route_actor",
        "ix_read_route_replica",
        "ix_read_route_lease",
        "ix_read_route_doc",
        "ix_read_route_claim",
        "ix_read_route_org",
        "ix_recovery_read_route_org_claim",
    ):
        op.drop_index(name, table_name=ROUTE_TABLE)
    op.drop_table(ROUTE_TABLE)

    for name in (
        "ix_route_lease_activator",
        "ix_route_lease_preparer",
        "ix_route_lease_replica",
        "ix_route_lease_auth_receipt",
        "ix_route_lease_auth",
        "ix_route_lease_doc",
        "ix_route_lease_claim",
        "ix_route_lease_org",
        "ix_recovery_route_lease_org_doc_status",
        "ix_recovery_route_lease_org_claim_status",
    ):
        op.drop_index(name, table_name=LEASE_TABLE)
    op.drop_table(LEASE_TABLE)
