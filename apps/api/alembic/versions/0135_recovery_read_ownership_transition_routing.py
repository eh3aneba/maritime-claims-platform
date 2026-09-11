"""Add bounded recovery read-ownership transition routing.

Revision ID: 0135_recovery_read_ownership_transition_routing
Revises: 0134_recovery_read_ownership_transition_authorization
"""

from alembic import op
import sqlalchemy as sa

revision = "0135_recovery_read_ownership_transition_routing"
down_revision = "0134_recovery_read_ownership_transition_authorization"
branch_labels = None
depends_on = None

LEASE = "evidence_recovery_read_ownership_transition_leases"
RECEIPT = "evidence_recovery_read_ownership_transition_receipts"
ROUTE = "evidence_recovery_read_path_routes"


def _safety_columns() -> list[sa.Column]:
    return [
        sa.Column("routable_authority_created", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("durable_read_route_created", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("read_ownership_authority_created", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("read_path_switched", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("write_path_switched", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("document_storage_key_mutated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("authoritative_storage_changed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("destructive_action_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("s3_delete_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("local_delete_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
    ]


def _route_binding_with_v() -> str:
    return (
        "((route_class = 'local_source' AND durable_authority_active = false "
        "AND active_lease_id IS NULL AND active_durable_lease_id IS NULL "
        "AND active_durable_renewal_lease_id IS NULL "
        "AND active_durable_reauthorized_renewal_lease_id IS NULL "
        "AND active_read_ownership_transition_lease_id IS NULL "
        "AND active_replica_id IS NULL AND read_path_switched = false) OR "
        "(route_class = 'recovery_replica' AND durable_authority_active = false "
        "AND active_lease_id IS NOT NULL AND active_durable_lease_id IS NULL "
        "AND active_durable_renewal_lease_id IS NULL "
        "AND active_durable_reauthorized_renewal_lease_id IS NULL "
        "AND active_read_ownership_transition_lease_id IS NULL "
        "AND active_replica_id IS NOT NULL AND read_path_switched = true) OR "
        "(route_class = 'recovery_replica' AND durable_authority_active = true "
        "AND active_lease_id IS NULL AND active_durable_lease_id IS NOT NULL "
        "AND active_durable_renewal_lease_id IS NULL "
        "AND active_durable_reauthorized_renewal_lease_id IS NULL "
        "AND active_read_ownership_transition_lease_id IS NULL "
        "AND active_replica_id IS NOT NULL AND read_path_switched = true) OR "
        "(route_class = 'recovery_replica' AND durable_authority_active = true "
        "AND active_lease_id IS NULL AND active_durable_lease_id IS NULL "
        "AND active_durable_renewal_lease_id IS NOT NULL "
        "AND active_durable_reauthorized_renewal_lease_id IS NULL "
        "AND active_read_ownership_transition_lease_id IS NULL "
        "AND active_replica_id IS NOT NULL AND read_path_switched = true) OR "
        "(route_class = 'recovery_replica' AND durable_authority_active = true "
        "AND active_lease_id IS NULL AND active_durable_lease_id IS NULL "
        "AND active_durable_renewal_lease_id IS NULL "
        "AND active_durable_reauthorized_renewal_lease_id IS NOT NULL "
        "AND active_read_ownership_transition_lease_id IS NULL "
        "AND active_replica_id IS NOT NULL AND read_path_switched = true) OR "
        "(route_class = 'recovery_replica' AND durable_authority_active = true "
        "AND active_lease_id IS NULL AND active_durable_lease_id IS NULL "
        "AND active_durable_renewal_lease_id IS NULL "
        "AND active_durable_reauthorized_renewal_lease_id IS NULL "
        "AND active_read_ownership_transition_lease_id IS NOT NULL "
        "AND active_replica_id IS NOT NULL AND read_path_switched = true))"
    )


def _route_binding_pre_v() -> str:
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
        sa.Column("authorization_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_approval_receipt_id", sa.Uuid(), nullable=False),
        sa.Column("phase_t_health_qualification_id", sa.Uuid(), nullable=False),
        sa.Column("replica_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_hash", sa.String(length=64), nullable=False),
        sa.Column("authorization_request_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("authorization_integrity_proof_hash", sa.String(length=64), nullable=False),
        sa.Column("authorization_approval_receipt_hash", sa.String(length=64), nullable=False),
        sa.Column("phase_t_health_qualification_hash", sa.String(length=64), nullable=False),
        sa.Column("operational_evidence_hash", sa.String(length=64), nullable=False),
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
        sa.Column("route_expired_attempt_count", sa.Integer(), nullable=False),
        sa.Column("operational_event_count", sa.Integer(), nullable=False),
        sa.Column("route_version_at_prepare", sa.Integer(), nullable=False),
        sa.Column("integrity_proof_hash", sa.String(length=64), nullable=False),
        sa.Column("lease_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("lease_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="prepared"),
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
        *_safety_columns(),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_id"], ["evidence_recovery_read_ownership_authorizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_approval_receipt_id"], ["evidence_recovery_read_ownership_authorization_receipts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_t_health_qualification_id"], ["evidence_recovery_drr_reauth_renewal_health_qualifications.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["replica_id"], ["evidence_recovery_replicas.id"], ondelete="RESTRICT"),
        *[
            sa.ForeignKeyConstraint([column], ["users.id"], ondelete="RESTRICT")
            for column in (
                "authorization_approved_by_id", "prepared_by_id", "activated_by_id",
                "rolled_back_by_id", "terminal_by_id",
            )
        ],
        sa.CheckConstraint("status IN ('prepared', 'activated', 'rolled_back', 'expired', 'invalidated')", name="ck_rr_owner_transition_status"),
        sa.CheckConstraint("prepared_by_id <> activated_by_id OR activated_by_id IS NULL", name="ck_rr_owner_transition_four_eyes"),
        sa.CheckConstraint("authorization_approved_by_id <> activated_by_id OR activated_by_id IS NULL", name="ck_rr_owner_transition_u_approver_split"),
        sa.CheckConstraint("((status = 'activated' AND routable_authority_created = true AND durable_read_route_created = true AND read_ownership_authority_created = true AND read_path_switched = true) OR (status <> 'activated' AND routable_authority_created = false AND durable_read_route_created = false AND read_ownership_authority_created = false AND read_path_switched = false))", name="ck_rr_owner_transition_state_flags"),
        sa.CheckConstraint("source_file_size_bytes >= 0", name="ck_rr_owner_transition_size"),
        sa.CheckConstraint("verified_durable_read_count >= 1", name="ck_rr_owner_transition_verified"),
        sa.CheckConstraint("integrity_failure_count = 0", name="ck_rr_owner_transition_integrity"),
        sa.CheckConstraint("storage_unavailable_count = 0", name="ck_rr_owner_transition_storage"),
        sa.CheckConstraint("route_version_at_prepare >= 1", name="ck_rr_owner_transition_routever"),
        sa.CheckConstraint("write_path_switched = false", name="ck_rr_owner_transition_no_write"),
        sa.CheckConstraint("document_storage_key_mutated = false", name="ck_rr_owner_transition_no_key"),
        sa.CheckConstraint("authoritative_storage_changed = false", name="ck_rr_owner_transition_no_owner"),
        sa.CheckConstraint("destructive_action_performed = false", name="ck_rr_owner_transition_no_dest"),
        sa.CheckConstraint("s3_delete_performed = false", name="ck_rr_owner_transition_no_s3del"),
        sa.CheckConstraint("local_delete_performed = false", name="ck_rr_owner_transition_no_localdel"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("authorization_id", name="uq_rr_owner_transition_authorization"),
        sa.UniqueConstraint("organization_id", "lease_hash", name="uq_rr_owner_transition_org_hash"),
    )

    for column in (
        "organization_id", "claim_id", "document_id", "authorization_id",
        "authorization_approval_receipt_id", "phase_t_health_qualification_id", "replica_id",
        "authorization_approved_by_id", "prepared_by_id", "activated_by_id",
        "rolled_back_by_id", "terminal_by_id",
    ):
        op.create_index(f"ix_rr_owner_transition_{column[:24]}", LEASE, [column], unique=False)
    op.create_index("ix_rr_owner_transition_org_claim", LEASE, ["organization_id", "claim_id", "status"], unique=False)
    op.create_index("ix_rr_owner_transition_org_doc", LEASE, ["organization_id", "document_id", "status"], unique=False)

    op.create_table(
        RECEIPT,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("transition_lease_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_id", sa.Uuid(), nullable=False),
        sa.Column("phase", sa.String(length=20), nullable=False),
        sa.Column("from_route_class", sa.String(length=24), nullable=False),
        sa.Column("to_route_class", sa.String(length=24), nullable=False),
        sa.Column("route_authority_kind", sa.String(length=40), nullable=False),
        sa.Column("route_version", sa.Integer(), nullable=False),
        sa.Column("lease_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("lease_hash", sa.String(length=64), nullable=False),
        sa.Column("authorization_hash", sa.String(length=64), nullable=False),
        sa.Column("receipt_hash", sa.String(length=64), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("transitioned_at", sa.DateTime(timezone=True), nullable=False),
        *_safety_columns(),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["transition_lease_id"], [f"{LEASE}.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_id"], ["evidence_recovery_read_ownership_authorizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("phase IN ('prepared', 'activated', 'rolled_back', 'expired', 'invalidated')", name="ck_rr_owner_transition_rec_phase"),
        sa.CheckConstraint("from_route_class IN ('local_source', 'recovery_replica') AND to_route_class IN ('local_source', 'recovery_replica')", name="ck_rr_owner_transition_rec_route"),
        sa.CheckConstraint("route_version >= 1", name="ck_rr_owner_transition_rec_version"),
        sa.CheckConstraint("write_path_switched = false", name="ck_rr_owner_transition_rec_no_write"),
        sa.CheckConstraint("document_storage_key_mutated = false", name="ck_rr_owner_transition_rec_no_key"),
        sa.CheckConstraint("authoritative_storage_changed = false", name="ck_rr_owner_transition_rec_no_owner"),
        sa.CheckConstraint("destructive_action_performed = false", name="ck_rr_owner_transition_rec_no_dest"),
        sa.CheckConstraint("s3_delete_performed = false", name="ck_rr_owner_transition_rec_no_s3del"),
        sa.CheckConstraint("local_delete_performed = false", name="ck_rr_owner_transition_rec_no_localdel"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "receipt_hash", name="uq_rr_owner_transition_rec_org_hash"),
    )
    for column in ("organization_id", "claim_id", "document_id", "transition_lease_id", "authorization_id", "actor_id"):
        op.create_index(f"ix_rr_owner_transition_rec_{column[:20]}", RECEIPT, [column], unique=False)
    op.create_index("ix_rr_owner_transition_rec_time", RECEIPT, ["transition_lease_id", "transitioned_at"], unique=False)

    op.drop_constraint("ck_recovery_read_route_binding", ROUTE, type_="check")
    op.add_column(ROUTE, sa.Column("active_read_ownership_transition_lease_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_recovery_read_route_owner_transition",
        ROUTE,
        LEASE,
        ["active_read_ownership_transition_lease_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_recovery_read_route_owner_transition",
        ROUTE,
        ["active_read_ownership_transition_lease_id"],
        unique=False,
    )
    op.create_check_constraint("ck_recovery_read_route_binding", ROUTE, _route_binding_with_v())


def downgrade() -> None:
    op.drop_constraint("ck_recovery_read_route_binding", ROUTE, type_="check")
    op.drop_index("ix_recovery_read_route_owner_transition", table_name=ROUTE)
    op.drop_constraint("fk_recovery_read_route_owner_transition", ROUTE, type_="foreignkey")
    op.drop_column(ROUTE, "active_read_ownership_transition_lease_id")
    op.create_check_constraint("ck_recovery_read_route_binding", ROUTE, _route_binding_pre_v())
    op.drop_table(RECEIPT)
    op.drop_table(LEASE)
