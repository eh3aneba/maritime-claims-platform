"""Add Phase W recovery read-ownership health qualification.

Revision ID: 0136_recovery_read_ownership_transition_health
Revises: 0135_recovery_read_ownership_transition_routing
"""

from alembic import op
import sqlalchemy as sa

revision = "0136_recovery_read_ownership_transition_health"
down_revision = "0135_recovery_read_ownership_transition_routing"
branch_labels = None
depends_on = None

QUAL = "evidence_recovery_read_owner_health_qualifications"
RECEIPT = "evidence_recovery_read_owner_health_receipts"


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


def upgrade() -> None:
    op.create_table(
        QUAL,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("transition_lease_id", sa.Uuid(), nullable=False),
        sa.Column("activation_receipt_id", sa.Uuid(), nullable=False),
        sa.Column("terminal_receipt_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_id", sa.Uuid(), nullable=False),
        sa.Column("phase_t_health_qualification_id", sa.Uuid(), nullable=False),
        sa.Column("replica_id", sa.Uuid(), nullable=False),
        sa.Column("transition_lease_hash", sa.String(64), nullable=False),
        sa.Column("lease_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("activation_receipt_hash", sa.String(64), nullable=False),
        sa.Column("terminal_receipt_hash", sa.String(64), nullable=False),
        sa.Column("authorization_hash", sa.String(64), nullable=False),
        sa.Column("phase_t_health_qualification_hash", sa.String(64), nullable=False),
        sa.Column("replica_hash", sa.String(64), nullable=False),
        sa.Column("source_file_hash", sa.String(64), nullable=False),
        sa.Column("source_file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("local_storage_key_fingerprint", sa.String(64), nullable=False),
        sa.Column("recovery_bucket_fingerprint", sa.String(64), nullable=False),
        sa.Column("candidate_storage_key_fingerprint", sa.String(64), nullable=False),
        sa.Column("source_authority_fingerprint", sa.String(64), nullable=False),
        sa.Column("candidate_authority_fingerprint", sa.String(64), nullable=False),
        sa.Column("configuration_fingerprint", sa.String(64), nullable=False),
        sa.Column("terminal_phase", sa.String(20), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_read_count", sa.Integer(), nullable=False),
        sa.Column("integrity_failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("storage_unavailable_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("route_expired_attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("operational_event_count", sa.Integer(), nullable=False),
        sa.Column("health_state", sa.String(20), nullable=False),
        sa.Column("operational_evidence_hash", sa.String(64), nullable=False),
        sa.Column("route_version_at_request", sa.Integer(), nullable=False),
        sa.Column("request_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("health_qualification_hash", sa.String(64), nullable=False),
        sa.Column("transition_activated_by_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_approved_by_id", sa.Uuid(), nullable=False),
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
        sa.ForeignKeyConstraint(["transition_lease_id"], ["evidence_recovery_read_ownership_transition_leases.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["activation_receipt_id"], ["evidence_recovery_read_ownership_transition_receipts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["terminal_receipt_id"], ["evidence_recovery_read_ownership_transition_receipts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_id"], ["evidence_recovery_read_ownership_authorizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_t_health_qualification_id"], ["evidence_recovery_drr_reauth_renewal_health_qualifications.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["replica_id"], ["evidence_recovery_replicas.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["transition_activated_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_approved_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["qualified_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["rejected_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["terminal_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("transition_lease_id", name="uq_rr_owner_health_v_lease"),
        sa.UniqueConstraint("organization_id", "health_qualification_hash", name="uq_rr_owner_health_org_hash"),
        sa.CheckConstraint("status IN ('pending_second_approval','qualified','degraded','rejected','expired','invalidated')", name="ck_rr_owner_health_status"),
        sa.CheckConstraint("health_state IN ('healthy','degraded','failed')", name="ck_rr_owner_health_state"),
        sa.CheckConstraint("terminal_phase IN ('rolled_back','expired')", name="ck_rr_owner_health_terminal"),
        sa.CheckConstraint("requested_by_id <> qualified_by_id OR qualified_by_id IS NULL", name="ck_rr_owner_health_four_eyes"),
        sa.CheckConstraint("transition_activated_by_id <> qualified_by_id OR qualified_by_id IS NULL", name="ck_rr_owner_health_v_split"),
        sa.CheckConstraint("authorization_approved_by_id <> qualified_by_id OR qualified_by_id IS NULL", name="ck_rr_owner_health_u_split"),
        sa.CheckConstraint("verified_read_count >= 1", name="ck_rr_owner_health_verified"),
        sa.CheckConstraint("integrity_failure_count >= 0", name="ck_rr_owner_health_integrity"),
        sa.CheckConstraint("storage_unavailable_count >= 0", name="ck_rr_owner_health_storage"),
        sa.CheckConstraint("route_expired_attempt_count >= 0", name="ck_rr_owner_health_expired"),
        sa.CheckConstraint("operational_event_count >= verified_read_count", name="ck_rr_owner_health_events"),
        sa.CheckConstraint("route_version_at_request >= 1", name="ck_rr_owner_health_routever"),
        sa.CheckConstraint("status <> 'qualified' OR health_state = 'healthy'", name="ck_rr_owner_health_qualified"),
        sa.CheckConstraint("status <> 'degraded' OR health_state <> 'healthy'", name="ck_rr_owner_health_degraded"),
        sa.CheckConstraint("routable_authority_created = false", name="ck_rr_owner_health_no_route"),
        sa.CheckConstraint("durable_read_route_created = false", name="ck_rr_owner_health_no_durable"),
        sa.CheckConstraint("read_ownership_authority_created = false", name="ck_rr_owner_health_no_read_owner"),
        sa.CheckConstraint("read_path_switched = false", name="ck_rr_owner_health_no_read"),
        sa.CheckConstraint("write_path_switched = false", name="ck_rr_owner_health_no_write"),
        sa.CheckConstraint("document_storage_key_mutated = false", name="ck_rr_owner_health_no_key"),
        sa.CheckConstraint("authoritative_storage_changed = false", name="ck_rr_owner_health_no_auth"),
        sa.CheckConstraint("destructive_action_performed = false", name="ck_rr_owner_health_no_dest"),
        sa.CheckConstraint("s3_delete_performed = false", name="ck_rr_owner_health_no_s3del"),
        sa.CheckConstraint("local_delete_performed = false", name="ck_rr_owner_health_no_localdel"),
    )
    op.create_index("ix_rr_owner_health_org_claim", QUAL, ["organization_id", "claim_id", "status"])
    op.create_index("ix_rr_owner_health_org_doc", QUAL, ["organization_id", "document_id", "status"])

    op.create_table(
        RECEIPT,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("health_qualification_id", sa.Uuid(), nullable=False),
        sa.Column("transition_lease_id", sa.Uuid(), nullable=False),
        sa.Column("phase", sa.String(20), nullable=False),
        sa.Column("health_state", sa.String(20), nullable=False),
        sa.Column("operational_evidence_hash", sa.String(64), nullable=False),
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
        sa.ForeignKeyConstraint(["transition_lease_id"], ["evidence_recovery_read_ownership_transition_leases.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "receipt_hash", name="uq_rr_owner_health_rec_org_hash"),
        sa.CheckConstraint("phase IN ('requested','qualified','degraded','rejected','expired','invalidated')", name="ck_rr_owner_health_rec_phase"),
        sa.CheckConstraint("routable_authority_created = false", name="ck_rr_owner_health_rec_route"),
        sa.CheckConstraint("durable_read_route_created = false", name="ck_rr_owner_health_rec_durable"),
        sa.CheckConstraint("read_ownership_authority_created = false", name="ck_rr_owner_health_rec_read_owner"),
        sa.CheckConstraint("read_path_switched = false", name="ck_rr_owner_health_rec_read"),
        sa.CheckConstraint("write_path_switched = false", name="ck_rr_owner_health_rec_write"),
        sa.CheckConstraint("document_storage_key_mutated = false", name="ck_rr_owner_health_rec_key"),
        sa.CheckConstraint("authoritative_storage_changed = false", name="ck_rr_owner_health_rec_auth"),
        sa.CheckConstraint("destructive_action_performed = false", name="ck_rr_owner_health_rec_dest"),
        sa.CheckConstraint("s3_delete_performed = false", name="ck_rr_owner_health_rec_s3del"),
        sa.CheckConstraint("local_delete_performed = false", name="ck_rr_owner_health_rec_localdel"),
    )
    op.create_index("ix_rr_owner_health_rec_time", RECEIPT, ["health_qualification_id", "transitioned_at"])


def downgrade() -> None:
    op.drop_index("ix_rr_owner_health_rec_time", table_name=RECEIPT)
    op.drop_table(RECEIPT)
    op.drop_index("ix_rr_owner_health_org_doc", table_name=QUAL)
    op.drop_index("ix_rr_owner_health_org_claim", table_name=QUAL)
    op.drop_table(QUAL)
