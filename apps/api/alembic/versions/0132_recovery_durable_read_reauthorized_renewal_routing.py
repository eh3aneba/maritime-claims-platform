"""Add bounded reauthorized durable recovery read renewal routing.

Revision ID: 0132_recovery_durable_read_reauthorized_renewal_routing
Revises: 0131_recovery_durable_read_renewal_reauthorization
"""

from alembic import op
import sqlalchemy as sa

revision = "0132_recovery_durable_read_reauthorized_renewal_routing"
down_revision = "0131_recovery_durable_read_renewal_reauthorization"
branch_labels = None
depends_on = None

LEASE = "evidence_recovery_drr_reauthorized_renewal_leases"
RECEIPT = "evidence_recovery_drr_reauthorized_renewal_receipts"
ROUTE = "evidence_recovery_read_path_routes"


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


def _old_route_binding() -> str:
    return (
        "((route_class = 'local_source' AND durable_authority_active = false AND active_lease_id IS NULL AND active_durable_lease_id IS NULL AND active_durable_renewal_lease_id IS NULL AND active_replica_id IS NULL AND read_path_switched = false) OR "
        "(route_class = 'recovery_replica' AND durable_authority_active = false AND active_lease_id IS NOT NULL AND active_durable_lease_id IS NULL AND active_durable_renewal_lease_id IS NULL AND active_replica_id IS NOT NULL AND read_path_switched = true) OR "
        "(route_class = 'recovery_replica' AND durable_authority_active = true AND active_lease_id IS NULL AND active_durable_lease_id IS NOT NULL AND active_durable_renewal_lease_id IS NULL AND active_replica_id IS NOT NULL AND read_path_switched = true) OR "
        "(route_class = 'recovery_replica' AND durable_authority_active = true AND active_lease_id IS NULL AND active_durable_lease_id IS NULL AND active_durable_renewal_lease_id IS NOT NULL AND active_replica_id IS NOT NULL AND read_path_switched = true))"
    )


def _new_route_binding() -> str:
    return (
        "((route_class = 'local_source' AND durable_authority_active = false AND active_lease_id IS NULL AND active_durable_lease_id IS NULL AND active_durable_renewal_lease_id IS NULL AND active_durable_reauthorized_renewal_lease_id IS NULL AND active_replica_id IS NULL AND read_path_switched = false) OR "
        "(route_class = 'recovery_replica' AND durable_authority_active = false AND active_lease_id IS NOT NULL AND active_durable_lease_id IS NULL AND active_durable_renewal_lease_id IS NULL AND active_durable_reauthorized_renewal_lease_id IS NULL AND active_replica_id IS NOT NULL AND read_path_switched = true) OR "
        "(route_class = 'recovery_replica' AND durable_authority_active = true AND active_lease_id IS NULL AND active_durable_lease_id IS NOT NULL AND active_durable_renewal_lease_id IS NULL AND active_durable_reauthorized_renewal_lease_id IS NULL AND active_replica_id IS NOT NULL AND read_path_switched = true) OR "
        "(route_class = 'recovery_replica' AND durable_authority_active = true AND active_lease_id IS NULL AND active_durable_lease_id IS NULL AND active_durable_renewal_lease_id IS NOT NULL AND active_durable_reauthorized_renewal_lease_id IS NULL AND active_replica_id IS NOT NULL AND read_path_switched = true) OR "
        "(route_class = 'recovery_replica' AND durable_authority_active = true AND active_lease_id IS NULL AND active_durable_lease_id IS NULL AND active_durable_renewal_lease_id IS NULL AND active_durable_reauthorized_renewal_lease_id IS NOT NULL AND active_replica_id IS NOT NULL AND read_path_switched = true))"
    )


def upgrade() -> None:
    op.create_table(
        LEASE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("reauthorization_id", sa.Uuid(), nullable=False),
        sa.Column("reauthorization_approval_receipt_id", sa.Uuid(), nullable=False),
        sa.Column("phase_q_health_qualification_id", sa.Uuid(), nullable=False),
        sa.Column("prior_renewal_lease_id", sa.Uuid(), nullable=False),
        sa.Column("replica_id", sa.Uuid(), nullable=False),
        sa.Column("reauthorization_hash", sa.String(64), nullable=False),
        sa.Column("reauthorization_request_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("reauthorization_integrity_proof_hash", sa.String(64), nullable=False),
        sa.Column("reauthorization_approval_receipt_hash", sa.String(64), nullable=False),
        sa.Column("phase_q_health_qualification_hash", sa.String(64), nullable=False),
        sa.Column("operational_evidence_hash", sa.String(64), nullable=False),
        sa.Column("prior_renewal_lease_hash", sa.String(64), nullable=False),
        sa.Column("prior_lease_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("replica_hash", sa.String(64), nullable=False),
        sa.Column("source_file_hash", sa.String(64), nullable=False),
        sa.Column("source_file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("local_storage_key_fingerprint", sa.String(64), nullable=False),
        sa.Column("recovery_bucket_fingerprint", sa.String(64), nullable=False),
        sa.Column("candidate_storage_key_fingerprint", sa.String(64), nullable=False),
        sa.Column("source_authority_fingerprint", sa.String(64), nullable=False),
        sa.Column("candidate_authority_fingerprint", sa.String(64), nullable=False),
        sa.Column("configuration_fingerprint", sa.String(64), nullable=False),
        sa.Column("verified_durable_read_count", sa.Integer(), nullable=False),
        sa.Column("integrity_failure_count", sa.Integer(), nullable=False),
        sa.Column("storage_unavailable_count", sa.Integer(), nullable=False),
        sa.Column("route_version_at_prepare", sa.Integer(), nullable=False),
        sa.Column("integrity_proof_hash", sa.String(64), nullable=False),
        sa.Column("lease_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("lease_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="prepared"),
        sa.Column("activation_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("route_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reauthorization_approved_by_id", sa.Uuid(), nullable=False),
        sa.Column("phase_q_qualified_by_id", sa.Uuid(), nullable=False),
        sa.Column("prior_renewal_activated_by_id", sa.Uuid(), nullable=False),
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
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reauthorization_id"], ["evidence_recovery_drr_reauthorizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reauthorization_approval_receipt_id"], ["evidence_recovery_drr_reauthorization_receipts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_q_health_qualification_id"], ["evidence_recovery_durable_read_renewal_health_qualifications.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["prior_renewal_lease_id"], ["evidence_recovery_durable_read_renewal_leases.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["replica_id"], ["evidence_recovery_replicas.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reauthorization_approved_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_q_qualified_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["prior_renewal_activated_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["prepared_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["activated_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["rolled_back_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["terminal_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("status IN ('prepared', 'activated', 'rolled_back', 'expired', 'invalidated')", name="ck_drr_reauth_renew_status"),
        sa.CheckConstraint("prepared_by_id <> activated_by_id OR activated_by_id IS NULL", name="ck_drr_reauth_renew_four_eyes"),
        sa.CheckConstraint("reauthorization_approved_by_id <> activated_by_id OR activated_by_id IS NULL", name="ck_drr_reauth_renew_r_approver_split"),
        sa.CheckConstraint("phase_q_qualified_by_id <> activated_by_id OR activated_by_id IS NULL", name="ck_drr_reauth_renew_q_qualifier_split"),
        sa.CheckConstraint("prior_renewal_activated_by_id <> activated_by_id OR activated_by_id IS NULL", name="ck_drr_reauth_renew_p_activator_split"),
        sa.CheckConstraint("((status = 'activated' AND routable_authority_created = true AND durable_read_route_created = true AND read_path_switched = true) OR (status <> 'activated' AND routable_authority_created = false AND durable_read_route_created = false AND read_path_switched = false))", name="ck_drr_reauth_renew_state_flags"),
        sa.CheckConstraint("source_file_size_bytes >= 0", name="ck_drr_reauth_renew_source_size"),
        sa.CheckConstraint("verified_durable_read_count >= 1", name="ck_drr_reauth_renew_verified_reads"),
        sa.CheckConstraint("integrity_failure_count = 0", name="ck_drr_reauth_renew_no_integrity"),
        sa.CheckConstraint("storage_unavailable_count = 0", name="ck_drr_reauth_renew_no_storage_fail"),
        sa.CheckConstraint("route_version_at_prepare >= 1", name="ck_drr_reauth_renew_route_version"),
        sa.CheckConstraint("write_path_switched = false", name="ck_drr_reauth_renew_no_write"),
        sa.CheckConstraint("document_storage_key_mutated = false", name="ck_drr_reauth_renew_no_key"),
        sa.CheckConstraint("authoritative_storage_changed = false", name="ck_drr_reauth_renew_no_authority"),
        sa.CheckConstraint("destructive_action_performed = false", name="ck_drr_reauth_renew_no_destructive"),
        sa.CheckConstraint("s3_delete_performed = false", name="ck_drr_reauth_renew_no_s3_delete"),
        sa.CheckConstraint("local_delete_performed = false", name="ck_drr_reauth_renew_no_local_delete"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reauthorization_id", name="uq_drr_reauth_renew_reauthorization"),
        sa.UniqueConstraint("organization_id", "lease_hash", name="uq_drr_reauth_renew_org_hash"),
    )
    for column, name in {
        "organization_id": "ix_drr_s_lease_org",
        "claim_id": "ix_drr_s_lease_claim",
        "document_id": "ix_drr_s_lease_doc",
        "reauthorization_id": "ix_drr_s_lease_reauth",
        "reauthorization_approval_receipt_id": "ix_drr_s_lease_approval",
        "phase_q_health_qualification_id": "ix_drr_s_lease_qhealth",
        "prior_renewal_lease_id": "ix_drr_s_lease_prior",
        "replica_id": "ix_drr_s_lease_replica",
        "reauthorization_approved_by_id": "ix_drr_s_lease_approver",
        "phase_q_qualified_by_id": "ix_drr_s_lease_qqualifier",
        "prior_renewal_activated_by_id": "ix_drr_s_lease_prioract",
        "prepared_by_id": "ix_drr_s_lease_preparer",
        "activated_by_id": "ix_drr_s_lease_activator",
        "rolled_back_by_id": "ix_drr_s_lease_rollback",
        "terminal_by_id": "ix_drr_s_lease_terminal",
    }.items():
        op.create_index(name, LEASE, [column], unique=False)
    op.create_index("ix_drr_s_lease_org_claim", LEASE, ["organization_id", "claim_id", "status"], unique=False)
    op.create_index("ix_drr_s_lease_org_doc", LEASE, ["organization_id", "document_id", "status"], unique=False)

    op.create_table(
        RECEIPT,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("reauthorized_renewal_lease_id", sa.Uuid(), nullable=False),
        sa.Column("reauthorization_id", sa.Uuid(), nullable=False),
        sa.Column("phase", sa.String(20), nullable=False),
        sa.Column("from_route_class", sa.String(24), nullable=False),
        sa.Column("to_route_class", sa.String(24), nullable=False),
        sa.Column("route_authority_kind", sa.String(32), nullable=False),
        sa.Column("route_version", sa.Integer(), nullable=False),
        sa.Column("lease_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("lease_hash", sa.String(64), nullable=False),
        sa.Column("reauthorization_hash", sa.String(64), nullable=False),
        sa.Column("receipt_hash", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("transitioned_at", sa.DateTime(timezone=True), nullable=False),
        *_safety_columns(),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reauthorized_renewal_lease_id"], [f"{LEASE}.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reauthorization_id"], ["evidence_recovery_drr_reauthorizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("phase IN ('prepared', 'activated', 'rolled_back', 'expired', 'invalidated')", name="ck_drr_reauth_renew_rec_phase"),
        sa.CheckConstraint("from_route_class IN ('local_source', 'recovery_replica') AND to_route_class IN ('local_source', 'recovery_replica')", name="ck_drr_reauth_renew_rec_route"),
        sa.CheckConstraint("route_version >= 1", name="ck_drr_reauth_renew_rec_version"),
        sa.CheckConstraint("write_path_switched = false", name="ck_drr_reauth_renew_rec_no_write"),
        sa.CheckConstraint("document_storage_key_mutated = false", name="ck_drr_reauth_renew_rec_no_key"),
        sa.CheckConstraint("authoritative_storage_changed = false", name="ck_drr_reauth_renew_rec_no_auth"),
        sa.CheckConstraint("destructive_action_performed = false", name="ck_drr_reauth_renew_rec_no_dest"),
        sa.CheckConstraint("s3_delete_performed = false", name="ck_drr_reauth_renew_rec_no_s3del"),
        sa.CheckConstraint("local_delete_performed = false", name="ck_drr_reauth_renew_rec_no_localdel"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "receipt_hash", name="uq_drr_reauth_renew_rec_org_hash"),
    )
    for column, name in {
        "organization_id": "ix_drr_s_rcpt_org",
        "claim_id": "ix_drr_s_rcpt_claim",
        "document_id": "ix_drr_s_rcpt_doc",
        "reauthorized_renewal_lease_id": "ix_drr_s_rcpt_lease",
        "reauthorization_id": "ix_drr_s_rcpt_reauth",
        "actor_id": "ix_drr_s_rcpt_actor",
    }.items():
        op.create_index(name, RECEIPT, [column], unique=False)
    op.create_index("ix_drr_s_rcpt_time", RECEIPT, ["reauthorized_renewal_lease_id", "transitioned_at"], unique=False)

    op.drop_constraint("ck_recovery_read_route_binding", ROUTE, type_="check")
    op.add_column(ROUTE, sa.Column("active_durable_reauthorized_renewal_lease_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_route_active_drr_s_lease",
        ROUTE,
        LEASE,
        ["active_durable_reauthorized_renewal_lease_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_route_active_drr_s_lease", ROUTE, ["active_durable_reauthorized_renewal_lease_id"], unique=False)
    op.create_check_constraint("ck_recovery_read_route_binding", ROUTE, _new_route_binding())


def downgrade() -> None:
    op.drop_constraint("ck_recovery_read_route_binding", ROUTE, type_="check")
    op.drop_index("ix_route_active_drr_s_lease", table_name=ROUTE)
    op.drop_constraint("fk_route_active_drr_s_lease", ROUTE, type_="foreignkey")
    op.drop_column(ROUTE, "active_durable_reauthorized_renewal_lease_id")
    op.create_check_constraint("ck_recovery_read_route_binding", ROUTE, _old_route_binding())
    op.drop_table(RECEIPT)
    op.drop_table(LEASE)
