"""Add bounded durable recovery read renewal routing lease.

Revision ID: 0129_recovery_durable_read_renewal_routing
Revises: 0128_recovery_durable_read_renewal_authorization
"""

from alembic import op
import sqlalchemy as sa

revision = "0129_recovery_durable_read_renewal_routing"
down_revision = "0128_recovery_durable_read_renewal_authorization"
branch_labels = None
depends_on = None


def _safety_columns() -> list[sa.Column]:
    return [
        sa.Column("routable_authority_created", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("durable_read_route_created", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("read_path_switched", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("write_path_switched", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("document_storage_key_mutated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("authoritative_storage_changed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("destructive_action_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("s3_delete_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("local_delete_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
    ]


def upgrade() -> None:
    op.create_table(
        "evidence_recovery_durable_read_renewal_leases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_approval_receipt_id", sa.Uuid(), nullable=False),
        sa.Column("health_qualification_id", sa.Uuid(), nullable=False),
        sa.Column("prior_durable_lease_id", sa.Uuid(), nullable=False),
        sa.Column("replica_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_hash", sa.String(length=64), nullable=False),
        sa.Column("authorization_request_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("authorization_integrity_proof_hash", sa.String(length=64), nullable=False),
        sa.Column("authorization_approval_receipt_hash", sa.String(length=64), nullable=False),
        sa.Column("health_qualification_hash", sa.String(length=64), nullable=False),
        sa.Column("operational_evidence_hash", sa.String(length=64), nullable=False),
        sa.Column("prior_durable_lease_hash", sa.String(length=64), nullable=False),
        sa.Column("prior_lease_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("replica_hash", sa.String(length=64), nullable=False),
        sa.Column("source_file_hash", sa.String(length=64), nullable=False),
        sa.Column("source_file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("local_storage_key_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("recovery_bucket_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("candidate_storage_key_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("source_authority_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("candidate_authority_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("configuration_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("verified_durable_read_count", sa.Integer(), nullable=False),
        sa.Column("integrity_failure_count", sa.Integer(), nullable=False),
        sa.Column("storage_unavailable_count", sa.Integer(), nullable=False),
        sa.Column("route_version_at_prepare", sa.Integer(), nullable=False),
        sa.Column("integrity_proof_hash", sa.String(length=64), nullable=False),
        sa.Column("lease_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("lease_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="prepared"),
        sa.Column("activation_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("route_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("authorization_approved_by_id", sa.Uuid(), nullable=False),
        sa.Column("prior_durable_activated_by_id", sa.Uuid(), nullable=False),
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
        *_safety_columns(),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_id"], ["evidence_recovery_durable_read_renewal_authorizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_approval_receipt_id"], ["evidence_recovery_durable_read_renewal_authorization_receipts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["health_qualification_id"], ["evidence_recovery_durable_read_health_qualifications.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["prior_durable_lease_id"], ["evidence_recovery_durable_read_promotion_leases.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["replica_id"], ["evidence_recovery_replicas.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_approved_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["prior_durable_activated_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["prepared_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["activated_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["rolled_back_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["terminal_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("status IN ('prepared', 'activated', 'rolled_back', 'expired', 'invalidated')", name="ck_durable_read_renewal_lease_status"),
        sa.CheckConstraint("prepared_by_id <> activated_by_id OR activated_by_id IS NULL", name="ck_durable_read_renewal_lease_four_eyes"),
        sa.CheckConstraint("authorization_approved_by_id <> activated_by_id OR activated_by_id IS NULL", name="ck_durable_read_renewal_lease_approver_split"),
        sa.CheckConstraint("prior_durable_activated_by_id <> activated_by_id OR activated_by_id IS NULL", name="ck_durable_read_renewal_lease_prior_activator_split"),
        sa.CheckConstraint("((status = 'activated' AND routable_authority_created = true AND durable_read_route_created = true AND read_path_switched = true) OR (status <> 'activated' AND routable_authority_created = false AND durable_read_route_created = false AND read_path_switched = false))", name="ck_durable_read_renewal_lease_state_flags"),
        sa.CheckConstraint("source_file_size_bytes >= 0", name="ck_durable_read_renewal_lease_source_size"),
        sa.CheckConstraint("verified_durable_read_count >= 1", name="ck_durable_read_renewal_lease_verified_reads"),
        sa.CheckConstraint("integrity_failure_count = 0", name="ck_durable_read_renewal_lease_no_integrity_failures"),
        sa.CheckConstraint("storage_unavailable_count = 0", name="ck_durable_read_renewal_lease_no_storage_failures"),
        sa.CheckConstraint("write_path_switched = false", name="ck_durable_read_renewal_lease_no_write"),
        sa.CheckConstraint("document_storage_key_mutated = false", name="ck_durable_read_renewal_lease_no_key"),
        sa.CheckConstraint("authoritative_storage_changed = false", name="ck_durable_read_renewal_lease_no_authority"),
        sa.CheckConstraint("destructive_action_performed = false", name="ck_durable_read_renewal_lease_no_destructive"),
        sa.CheckConstraint("s3_delete_performed = false", name="ck_durable_read_renewal_lease_no_s3_delete"),
        sa.CheckConstraint("local_delete_performed = false", name="ck_durable_read_renewal_lease_no_local_delete"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("authorization_id", name="uq_durable_read_renewal_lease_authorization"),
        sa.UniqueConstraint("organization_id", "lease_hash", name="uq_durable_read_renewal_lease_org_hash"),
    )
    for column in ("organization_id", "claim_id", "document_id", "authorization_id", "authorization_approval_receipt_id", "health_qualification_id", "prior_durable_lease_id", "replica_id", "authorization_approved_by_id", "prior_durable_activated_by_id", "prepared_by_id", "activated_by_id", "rolled_back_by_id", "terminal_by_id"):
        op.create_index(f"ix_evidence_recovery_durable_read_renewal_leases_{column}", "evidence_recovery_durable_read_renewal_leases", [column], unique=False)
    op.create_index("ix_durable_read_renewal_lease_org_claim_status", "evidence_recovery_durable_read_renewal_leases", ["organization_id", "claim_id", "status"], unique=False)
    op.create_index("ix_durable_read_renewal_lease_org_doc_status", "evidence_recovery_durable_read_renewal_leases", ["organization_id", "document_id", "status"], unique=False)

    op.create_table(
        "evidence_recovery_durable_read_renewal_receipts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("renewal_lease_id", sa.Uuid(), nullable=False),
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
        *_safety_columns(),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["renewal_lease_id"], ["evidence_recovery_durable_read_renewal_leases.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_id"], ["evidence_recovery_durable_read_renewal_authorizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("phase IN ('prepared', 'activated', 'rolled_back', 'expired', 'invalidated')", name="ck_durable_read_renewal_receipt_phase"),
        sa.CheckConstraint("from_route_class IN ('local_source', 'recovery_replica') AND to_route_class IN ('local_source', 'recovery_replica')", name="ck_durable_read_renewal_receipt_route_class"),
        sa.CheckConstraint("route_version >= 1", name="ck_durable_read_renewal_receipt_version"),
        sa.CheckConstraint("write_path_switched = false", name="ck_durable_read_renewal_receipt_no_write"),
        sa.CheckConstraint("document_storage_key_mutated = false", name="ck_durable_read_renewal_receipt_no_key"),
        sa.CheckConstraint("authoritative_storage_changed = false", name="ck_durable_read_renewal_receipt_no_authority"),
        sa.CheckConstraint("destructive_action_performed = false", name="ck_durable_read_renewal_receipt_no_destructive"),
        sa.CheckConstraint("s3_delete_performed = false", name="ck_durable_read_renewal_receipt_no_s3_delete"),
        sa.CheckConstraint("local_delete_performed = false", name="ck_durable_read_renewal_receipt_no_local_delete"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "receipt_hash", name="uq_durable_read_renewal_receipt_org_hash"),
    )
    for column in ("organization_id", "claim_id", "document_id", "renewal_lease_id", "authorization_id", "actor_id"):
        op.create_index(f"ix_evidence_recovery_durable_read_renewal_receipts_{column}", "evidence_recovery_durable_read_renewal_receipts", [column], unique=False)
    op.create_index("ix_durable_read_renewal_receipt_time", "evidence_recovery_durable_read_renewal_receipts", ["renewal_lease_id", "transitioned_at"], unique=False)

    op.add_column("evidence_recovery_read_path_routes", sa.Column("active_durable_renewal_lease_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_recovery_read_route_active_durable_renewal_lease",
        "evidence_recovery_read_path_routes",
        "evidence_recovery_durable_read_renewal_leases",
        ["active_durable_renewal_lease_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_evidence_recovery_read_path_routes_active_durable_renewal_lease_id", "evidence_recovery_read_path_routes", ["active_durable_renewal_lease_id"], unique=False)
    op.drop_constraint("ck_recovery_read_route_binding", "evidence_recovery_read_path_routes", type_="check")
    op.create_check_constraint(
        "ck_recovery_read_route_binding",
        "evidence_recovery_read_path_routes",
        "((route_class = 'local_source' AND durable_authority_active = false AND active_lease_id IS NULL AND active_durable_lease_id IS NULL AND active_durable_renewal_lease_id IS NULL AND active_replica_id IS NULL AND read_path_switched = false) OR "
        "(route_class = 'recovery_replica' AND durable_authority_active = false AND active_lease_id IS NOT NULL AND active_durable_lease_id IS NULL AND active_durable_renewal_lease_id IS NULL AND active_replica_id IS NOT NULL AND read_path_switched = true) OR "
        "(route_class = 'recovery_replica' AND durable_authority_active = true AND active_lease_id IS NULL AND active_durable_lease_id IS NOT NULL AND active_durable_renewal_lease_id IS NULL AND active_replica_id IS NOT NULL AND read_path_switched = true) OR "
        "(route_class = 'recovery_replica' AND durable_authority_active = true AND active_lease_id IS NULL AND active_durable_lease_id IS NULL AND active_durable_renewal_lease_id IS NOT NULL AND active_replica_id IS NOT NULL AND read_path_switched = true))",
    )


def downgrade() -> None:
    op.drop_constraint("ck_recovery_read_route_binding", "evidence_recovery_read_path_routes", type_="check")
    op.create_check_constraint(
        "ck_recovery_read_route_binding",
        "evidence_recovery_read_path_routes",
        "((route_class = 'local_source' AND durable_authority_active = false AND active_lease_id IS NULL AND active_durable_lease_id IS NULL AND active_replica_id IS NULL AND read_path_switched = false) OR "
        "(route_class = 'recovery_replica' AND durable_authority_active = false AND active_lease_id IS NOT NULL AND active_durable_lease_id IS NULL AND active_replica_id IS NOT NULL AND read_path_switched = true) OR "
        "(route_class = 'recovery_replica' AND durable_authority_active = true AND active_lease_id IS NULL AND active_durable_lease_id IS NOT NULL AND active_replica_id IS NOT NULL AND read_path_switched = true))",
    )
    op.drop_index("ix_evidence_recovery_read_path_routes_active_durable_renewal_lease_id", table_name="evidence_recovery_read_path_routes")
    op.drop_constraint("fk_recovery_read_route_active_durable_renewal_lease", "evidence_recovery_read_path_routes", type_="foreignkey")
    op.drop_column("evidence_recovery_read_path_routes", "active_durable_renewal_lease_id")
    op.drop_table("evidence_recovery_durable_read_renewal_receipts")
    op.drop_table("evidence_recovery_durable_read_renewal_leases")
