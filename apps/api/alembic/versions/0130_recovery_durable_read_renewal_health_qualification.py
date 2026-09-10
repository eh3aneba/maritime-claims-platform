"""Add durable recovery read renewal health qualification.

Revision ID: 0130_recovery_durable_read_renewal_health_qualification
Revises: 0129_recovery_durable_read_renewal_routing
"""

from alembic import op
import sqlalchemy as sa

revision = "0130_recovery_durable_read_renewal_health_qualification"
down_revision = "0129_recovery_durable_read_renewal_routing"
branch_labels = None
depends_on = None

QUAL_TABLE = "evidence_recovery_durable_read_renewal_health_qualifications"
RECEIPT_TABLE = "evidence_recovery_durable_read_renewal_health_qualification_receipts"


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
        QUAL_TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("renewal_lease_id", sa.Uuid(), nullable=False),
        sa.Column("activation_receipt_id", sa.Uuid(), nullable=False),
        sa.Column("terminal_receipt_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_id", sa.Uuid(), nullable=False),
        sa.Column("phase_n_health_qualification_id", sa.Uuid(), nullable=False),
        sa.Column("prior_durable_lease_id", sa.Uuid(), nullable=False),
        sa.Column("replica_id", sa.Uuid(), nullable=False),
        sa.Column("renewal_lease_hash", sa.String(length=64), nullable=False),
        sa.Column("lease_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("activation_receipt_hash", sa.String(length=64), nullable=False),
        sa.Column("terminal_receipt_hash", sa.String(length=64), nullable=False),
        sa.Column("authorization_hash", sa.String(length=64), nullable=False),
        sa.Column("phase_n_health_qualification_hash", sa.String(length=64), nullable=False),
        sa.Column("prior_durable_lease_hash", sa.String(length=64), nullable=False),
        sa.Column("replica_hash", sa.String(length=64), nullable=False),
        sa.Column("source_file_hash", sa.String(length=64), nullable=False),
        sa.Column("source_file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("local_storage_key_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("recovery_bucket_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("candidate_storage_key_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("source_authority_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("candidate_authority_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("configuration_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("terminal_phase", sa.String(length=20), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_durable_read_count", sa.Integer(), nullable=False),
        sa.Column("integrity_failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("storage_unavailable_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("route_expired_attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("operational_event_count", sa.Integer(), nullable=False),
        sa.Column("health_state", sa.String(length=20), nullable=False),
        sa.Column("operational_evidence_hash", sa.String(length=64), nullable=False),
        sa.Column("route_version_at_request", sa.Integer(), nullable=False),
        sa.Column("request_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("health_qualification_hash", sa.String(length=64), nullable=False),
        sa.Column("renewal_activated_by_id", sa.Uuid(), nullable=False),
        sa.Column("renewal_authorization_approved_by_id", sa.Uuid(), nullable=False),
        sa.Column("prior_durable_activated_by_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_id", sa.Uuid(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("review_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending_second_approval"),
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
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["renewal_lease_id"], ["evidence_recovery_durable_read_renewal_leases.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["activation_receipt_id"], ["evidence_recovery_durable_read_renewal_receipts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["terminal_receipt_id"], ["evidence_recovery_durable_read_renewal_receipts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_id"], ["evidence_recovery_durable_read_renewal_authorizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_n_health_qualification_id"], ["evidence_recovery_durable_read_health_qualifications.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["prior_durable_lease_id"], ["evidence_recovery_durable_read_promotion_leases.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["replica_id"], ["evidence_recovery_replicas.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["renewal_activated_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["renewal_authorization_approved_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["prior_durable_activated_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["qualified_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["rejected_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["terminal_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("status IN ('pending_second_approval', 'qualified', 'degraded', 'rejected', 'expired', 'invalidated')", name="ck_drr_health_status"),
        sa.CheckConstraint("health_state IN ('healthy', 'degraded', 'failed')", name="ck_drr_health_state"),
        sa.CheckConstraint("terminal_phase IN ('rolled_back', 'expired')", name="ck_drr_health_terminal_phase"),
        sa.CheckConstraint("requested_by_id <> qualified_by_id OR qualified_by_id IS NULL", name="ck_drr_health_four_eyes"),
        sa.CheckConstraint("renewal_activated_by_id <> qualified_by_id OR qualified_by_id IS NULL", name="ck_drr_health_renewal_activator_split"),
        sa.CheckConstraint("renewal_authorization_approved_by_id <> qualified_by_id OR qualified_by_id IS NULL", name="ck_drr_health_auth_approver_split"),
        sa.CheckConstraint("prior_durable_activated_by_id <> qualified_by_id OR qualified_by_id IS NULL", name="ck_drr_health_prior_activator_split"),
        sa.CheckConstraint("verified_durable_read_count >= 1", name="ck_drr_health_verified_reads"),
        sa.CheckConstraint("integrity_failure_count >= 0", name="ck_drr_health_integrity_failures"),
        sa.CheckConstraint("storage_unavailable_count >= 0", name="ck_drr_health_storage_failures"),
        sa.CheckConstraint("route_expired_attempt_count >= 0", name="ck_drr_health_expired_attempts"),
        sa.CheckConstraint("operational_event_count >= verified_durable_read_count", name="ck_drr_health_event_count"),
        sa.CheckConstraint("route_version_at_request >= 1", name="ck_drr_health_route_version"),
        sa.CheckConstraint("status <> 'qualified' OR health_state = 'healthy'", name="ck_drr_health_qualified_only_healthy"),
        sa.CheckConstraint("status <> 'degraded' OR health_state <> 'healthy'", name="ck_drr_health_degraded_not_healthy"),
        sa.CheckConstraint("routable_authority_created = false", name="ck_drr_health_no_route_auth"),
        sa.CheckConstraint("durable_read_route_created = false", name="ck_drr_health_no_durable_route"),
        sa.CheckConstraint("read_path_switched = false", name="ck_drr_health_no_read_switch"),
        sa.CheckConstraint("write_path_switched = false", name="ck_drr_health_no_write_switch"),
        sa.CheckConstraint("document_storage_key_mutated = false", name="ck_drr_health_no_key_mut"),
        sa.CheckConstraint("authoritative_storage_changed = false", name="ck_drr_health_no_authority"),
        sa.CheckConstraint("destructive_action_performed = false", name="ck_drr_health_no_destructive"),
        sa.CheckConstraint("s3_delete_performed = false", name="ck_drr_health_no_s3_delete"),
        sa.CheckConstraint("local_delete_performed = false", name="ck_drr_health_no_local_delete"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("renewal_lease_id", name="uq_drr_health_renewal_lease"),
        sa.UniqueConstraint("organization_id", "health_qualification_hash", name="uq_drr_health_org_hash"),
    )
    indexes = {
        "organization_id": "ix_drr_health_org",
        "claim_id": "ix_drr_health_claim",
        "document_id": "ix_drr_health_doc",
        "renewal_lease_id": "ix_drr_health_renewal_lease",
        "activation_receipt_id": "ix_drr_health_activation_receipt",
        "terminal_receipt_id": "ix_drr_health_terminal_receipt",
        "authorization_id": "ix_drr_health_authorization",
        "phase_n_health_qualification_id": "ix_drr_health_phase_n",
        "prior_durable_lease_id": "ix_drr_health_prior_lease",
        "replica_id": "ix_drr_health_replica",
        "renewal_activated_by_id": "ix_drr_health_renewal_activator",
        "renewal_authorization_approved_by_id": "ix_drr_health_auth_approver",
        "prior_durable_activated_by_id": "ix_drr_health_prior_activator",
        "requested_by_id": "ix_drr_health_requester",
        "qualified_by_id": "ix_drr_health_qualifier",
        "rejected_by_id": "ix_drr_health_rejector",
        "terminal_by_id": "ix_drr_health_terminal_actor",
    }
    for column, name in indexes.items():
        op.create_index(name, QUAL_TABLE, [column], unique=False)
    op.create_index("ix_drr_health_org_claim", QUAL_TABLE, ["organization_id", "claim_id", "status"], unique=False)
    op.create_index("ix_drr_health_org_doc", QUAL_TABLE, ["organization_id", "document_id", "status"], unique=False)

    op.create_table(
        RECEIPT_TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("health_qualification_id", sa.Uuid(), nullable=False),
        sa.Column("renewal_lease_id", sa.Uuid(), nullable=False),
        sa.Column("phase", sa.String(length=20), nullable=False),
        sa.Column("health_state", sa.String(length=20), nullable=False),
        sa.Column("operational_evidence_hash", sa.String(length=64), nullable=False),
        sa.Column("request_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("health_qualification_hash", sa.String(length=64), nullable=False),
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
        sa.ForeignKeyConstraint(["health_qualification_id"], [f"{QUAL_TABLE}.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["renewal_lease_id"], ["evidence_recovery_durable_read_renewal_leases.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("phase IN ('requested', 'qualified', 'degraded', 'rejected', 'expired', 'invalidated')", name="ck_drr_health_receipt_phase"),
        sa.CheckConstraint("routable_authority_created = false", name="ck_drr_health_rec_no_route"),
        sa.CheckConstraint("durable_read_route_created = false", name="ck_drr_health_rec_no_durable"),
        sa.CheckConstraint("read_path_switched = false", name="ck_drr_health_rec_no_read"),
        sa.CheckConstraint("write_path_switched = false", name="ck_drr_health_rec_no_write"),
        sa.CheckConstraint("document_storage_key_mutated = false", name="ck_drr_health_rec_no_key"),
        sa.CheckConstraint("authoritative_storage_changed = false", name="ck_drr_health_rec_no_auth"),
        sa.CheckConstraint("destructive_action_performed = false", name="ck_drr_health_rec_no_dest"),
        sa.CheckConstraint("s3_delete_performed = false", name="ck_drr_health_rec_no_s3del"),
        sa.CheckConstraint("local_delete_performed = false", name="ck_drr_health_rec_no_localdel"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "receipt_hash", name="uq_drr_health_rec_org_hash"),
    )
    receipt_indexes = {
        "organization_id": "ix_drr_health_rec_org",
        "claim_id": "ix_drr_health_rec_claim",
        "document_id": "ix_drr_health_rec_doc",
        "health_qualification_id": "ix_drr_health_rec_health",
        "renewal_lease_id": "ix_drr_health_rec_renewal",
        "actor_id": "ix_drr_health_rec_actor",
    }
    for column, name in receipt_indexes.items():
        op.create_index(name, RECEIPT_TABLE, [column], unique=False)
    op.create_index("ix_drr_health_receipt_time", RECEIPT_TABLE, ["health_qualification_id", "transitioned_at"], unique=False)


def downgrade() -> None:
    op.drop_table(RECEIPT_TABLE)
    op.drop_table(QUAL_TABLE)
