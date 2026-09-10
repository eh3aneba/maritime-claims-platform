"""add durable recovery read health qualification

Revision ID: 0127_recovery_durable_read_health_qualification
Revises: 0126_recovery_durable_read_routing
"""

from alembic import op
import sqlalchemy as sa

revision = "0127_recovery_durable_read_health_qualification"
down_revision = "0126_recovery_durable_read_routing"
branch_labels = None
depends_on = None

QUAL_TABLE = "evidence_recovery_durable_read_health_qualifications"
RECEIPT_TABLE = "evidence_recovery_durable_read_health_qualification_receipts"


def upgrade() -> None:
    op.create_table(
        QUAL_TABLE,
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("durable_lease_id", sa.Uuid(), nullable=False),
        sa.Column("activation_receipt_id", sa.Uuid(), nullable=False),
        sa.Column("terminal_receipt_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_id", sa.Uuid(), nullable=False),
        sa.Column("qualification_id", sa.Uuid(), nullable=False),
        sa.Column("replica_id", sa.Uuid(), nullable=False),
        sa.Column("durable_lease_hash", sa.String(length=64), nullable=False),
        sa.Column("lease_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("activation_receipt_hash", sa.String(length=64), nullable=False),
        sa.Column("terminal_receipt_hash", sa.String(length=64), nullable=False),
        sa.Column("authorization_hash", sa.String(length=64), nullable=False),
        sa.Column("phase_k_qualification_hash", sa.String(length=64), nullable=False),
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
        sa.Column("integrity_failure_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("storage_unavailable_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("route_expired_attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("operational_event_count", sa.Integer(), nullable=False),
        sa.Column("health_state", sa.String(length=20), nullable=False),
        sa.Column("operational_evidence_hash", sa.String(length=64), nullable=False),
        sa.Column("route_version_at_request", sa.Integer(), nullable=False),
        sa.Column("request_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("health_qualification_hash", sa.String(length=64), nullable=False),
        sa.Column("activated_by_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_id", sa.Uuid(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="pending_second_approval", nullable=False),
        sa.Column("qualified_by_id", sa.Uuid(), nullable=True),
        sa.Column("qualified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("qualification_reason", sa.Text(), nullable=True),
        sa.Column("rejected_by_id", sa.Uuid(), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
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
        sa.CheckConstraint("status IN ('pending_second_approval', 'qualified', 'degraded', 'rejected', 'invalidated')", name="ck_durable_read_health_status"),
        sa.CheckConstraint("health_state IN ('healthy', 'degraded', 'failed')", name="ck_durable_read_health_state"),
        sa.CheckConstraint("terminal_phase IN ('rolled_back', 'expired')", name="ck_durable_read_health_terminal_phase"),
        sa.CheckConstraint("requested_by_id <> qualified_by_id OR qualified_by_id IS NULL", name="ck_durable_read_health_four_eyes"),
        sa.CheckConstraint("activated_by_id <> qualified_by_id OR qualified_by_id IS NULL", name="ck_durable_read_health_activator_split"),
        sa.CheckConstraint("verified_durable_read_count >= 1", name="ck_durable_read_health_verified_reads"),
        sa.CheckConstraint("integrity_failure_count >= 0", name="ck_durable_read_health_integrity_failures"),
        sa.CheckConstraint("storage_unavailable_count >= 0", name="ck_durable_read_health_storage_failures"),
        sa.CheckConstraint("route_expired_attempt_count >= 0", name="ck_durable_read_health_expired_attempts"),
        sa.CheckConstraint("operational_event_count >= verified_durable_read_count", name="ck_durable_read_health_event_count"),
        sa.CheckConstraint("route_version_at_request >= 1", name="ck_durable_read_health_route_version"),
        sa.CheckConstraint("status <> 'qualified' OR health_state = 'healthy'", name="ck_durable_read_health_qualified_only_healthy"),
        sa.CheckConstraint("status <> 'degraded' OR health_state <> 'healthy'", name="ck_durable_read_health_degraded_not_healthy"),
        sa.CheckConstraint("routable_authority_created = false", name="ck_durable_read_health_no_route_auth"),
        sa.CheckConstraint("durable_read_route_created = false", name="ck_durable_read_health_no_durable_route"),
        sa.CheckConstraint("read_path_switched = false", name="ck_durable_read_health_no_read_switch"),
        sa.CheckConstraint("write_path_switched = false", name="ck_durable_read_health_no_write_switch"),
        sa.CheckConstraint("document_storage_key_mutated = false", name="ck_durable_read_health_no_key_mut"),
        sa.CheckConstraint("authoritative_storage_changed = false", name="ck_durable_read_health_no_authority"),
        sa.CheckConstraint("destructive_action_performed = false", name="ck_durable_read_health_no_destructive"),
        sa.CheckConstraint("s3_delete_performed = false", name="ck_durable_read_health_no_s3_delete"),
        sa.CheckConstraint("local_delete_performed = false", name="ck_durable_read_health_no_local_delete"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["durable_lease_id"], ["evidence_recovery_durable_read_promotion_leases.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["activation_receipt_id"], ["evidence_recovery_durable_read_promotion_receipts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["terminal_receipt_id"], ["evidence_recovery_durable_read_promotion_receipts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_id"], ["evidence_recovery_durable_read_promotion_authorizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["qualification_id"], ["evidence_recovery_routable_read_qualifications.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["replica_id"], ["evidence_recovery_replicas.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["activated_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["qualified_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["rejected_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["terminal_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("durable_lease_id", name="uq_durable_read_health_lease"),
        sa.UniqueConstraint("organization_id", "health_qualification_hash", name="uq_durable_read_health_org_hash"),
    )
    op.create_index("ix_drh_org_claim", QUAL_TABLE, ["organization_id", "claim_id", "status"], unique=False)
    op.create_index("ix_drh_org_doc", QUAL_TABLE, ["organization_id", "document_id", "status"], unique=False)
    op.create_index("ix_drh_lease", QUAL_TABLE, ["durable_lease_id"], unique=False)
    op.create_index("ix_drh_activation_receipt", QUAL_TABLE, ["activation_receipt_id"], unique=False)
    op.create_index("ix_drh_terminal_receipt", QUAL_TABLE, ["terminal_receipt_id"], unique=False)
    op.create_index("ix_drh_authorization", QUAL_TABLE, ["authorization_id"], unique=False)
    op.create_index("ix_drh_qualification", QUAL_TABLE, ["qualification_id"], unique=False)
    op.create_index("ix_drh_replica", QUAL_TABLE, ["replica_id"], unique=False)
    op.create_index("ix_drh_activator", QUAL_TABLE, ["activated_by_id"], unique=False)
    op.create_index("ix_drh_requester", QUAL_TABLE, ["requested_by_id"], unique=False)
    op.create_index("ix_drh_qualifier", QUAL_TABLE, ["qualified_by_id"], unique=False)
    op.create_index("ix_drh_rejector", QUAL_TABLE, ["rejected_by_id"], unique=False)
    op.create_index("ix_drh_terminal_actor", QUAL_TABLE, ["terminal_by_id"], unique=False)

    op.create_table(
        RECEIPT_TABLE,
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("health_qualification_id", sa.Uuid(), nullable=False),
        sa.Column("durable_lease_id", sa.Uuid(), nullable=False),
        sa.Column("phase", sa.String(length=20), nullable=False),
        sa.Column("health_state", sa.String(length=20), nullable=False),
        sa.Column("operational_evidence_hash", sa.String(length=64), nullable=False),
        sa.Column("request_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("health_qualification_hash", sa.String(length=64), nullable=False),
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
        sa.CheckConstraint("phase IN ('requested', 'qualified', 'degraded', 'rejected', 'invalidated')", name="ck_durable_read_health_receipt_phase"),
        sa.CheckConstraint("routable_authority_created = false", name="ck_durable_read_health_rec_no_route"),
        sa.CheckConstraint("durable_read_route_created = false", name="ck_durable_read_health_rec_no_durable"),
        sa.CheckConstraint("read_path_switched = false", name="ck_durable_read_health_rec_no_read"),
        sa.CheckConstraint("write_path_switched = false", name="ck_durable_read_health_rec_no_write"),
        sa.CheckConstraint("document_storage_key_mutated = false", name="ck_durable_read_health_rec_no_key"),
        sa.CheckConstraint("authoritative_storage_changed = false", name="ck_durable_read_health_rec_no_auth"),
        sa.CheckConstraint("destructive_action_performed = false", name="ck_durable_read_health_rec_no_dest"),
        sa.CheckConstraint("s3_delete_performed = false", name="ck_durable_read_health_rec_no_s3del"),
        sa.CheckConstraint("local_delete_performed = false", name="ck_durable_read_health_rec_no_localdel"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["health_qualification_id"], [f"{QUAL_TABLE}.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["durable_lease_id"], ["evidence_recovery_durable_read_promotion_leases.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "receipt_hash", name="uq_durable_read_health_rec_org_hash"),
    )
    op.create_index("ix_drhr_qual_time", RECEIPT_TABLE, ["health_qualification_id", "transitioned_at"], unique=False)
    op.create_index("ix_drhr_lease", RECEIPT_TABLE, ["durable_lease_id"], unique=False)
    op.create_index("ix_drhr_actor", RECEIPT_TABLE, ["actor_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_drhr_actor", table_name=RECEIPT_TABLE)
    op.drop_index("ix_drhr_lease", table_name=RECEIPT_TABLE)
    op.drop_index("ix_drhr_qual_time", table_name=RECEIPT_TABLE)
    op.drop_table(RECEIPT_TABLE)

    op.drop_index("ix_drh_terminal_actor", table_name=QUAL_TABLE)
    op.drop_index("ix_drh_rejector", table_name=QUAL_TABLE)
    op.drop_index("ix_drh_qualifier", table_name=QUAL_TABLE)
    op.drop_index("ix_drh_requester", table_name=QUAL_TABLE)
    op.drop_index("ix_drh_activator", table_name=QUAL_TABLE)
    op.drop_index("ix_drh_replica", table_name=QUAL_TABLE)
    op.drop_index("ix_drh_qualification", table_name=QUAL_TABLE)
    op.drop_index("ix_drh_authorization", table_name=QUAL_TABLE)
    op.drop_index("ix_drh_terminal_receipt", table_name=QUAL_TABLE)
    op.drop_index("ix_drh_activation_receipt", table_name=QUAL_TABLE)
    op.drop_index("ix_drh_lease", table_name=QUAL_TABLE)
    op.drop_index("ix_drh_org_doc", table_name=QUAL_TABLE)
    op.drop_index("ix_drh_org_claim", table_name=QUAL_TABLE)
    op.drop_table(QUAL_TABLE)
