"""add repeated routable read cutover qualification

Revision ID: 0124_recovery_routable_read_qualification
Revises: 0123_recovery_routable_read_cutover
"""

from alembic import op
import sqlalchemy as sa

revision = "0124_recovery_routable_read_qualification"
down_revision = "0123_recovery_routable_read_cutover"
branch_labels = None
depends_on = None

QUALIFICATION_TABLE = "evidence_recovery_routable_read_qualifications"
RECEIPT_TABLE = "evidence_recovery_routable_read_qualification_receipts"


def upgrade() -> None:
    op.create_table(
        QUALIFICATION_TABLE,
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("replica_id", sa.Uuid(), nullable=False),
        sa.Column("first_cutover_lease_id", sa.Uuid(), nullable=False),
        sa.Column("second_cutover_lease_id", sa.Uuid(), nullable=False),
        sa.Column("first_authorization_id", sa.Uuid(), nullable=False),
        sa.Column("second_authorization_id", sa.Uuid(), nullable=False),
        sa.Column("first_activation_receipt_id", sa.Uuid(), nullable=False),
        sa.Column("first_rollback_receipt_id", sa.Uuid(), nullable=False),
        sa.Column("second_activation_receipt_id", sa.Uuid(), nullable=False),
        sa.Column("second_rollback_receipt_id", sa.Uuid(), nullable=False),
        sa.Column("first_lease_hash", sa.String(length=64), nullable=False),
        sa.Column("second_lease_hash", sa.String(length=64), nullable=False),
        sa.Column("first_activation_receipt_hash", sa.String(length=64), nullable=False),
        sa.Column("first_rollback_receipt_hash", sa.String(length=64), nullable=False),
        sa.Column("second_activation_receipt_hash", sa.String(length=64), nullable=False),
        sa.Column("second_rollback_receipt_hash", sa.String(length=64), nullable=False),
        sa.Column("first_cycle_proof_hash", sa.String(length=64), nullable=False),
        sa.Column("second_cycle_proof_hash", sa.String(length=64), nullable=False),
        sa.Column("qualification_bundle_hash", sa.String(length=64), nullable=False),
        sa.Column("replica_hash", sa.String(length=64), nullable=False),
        sa.Column("source_file_hash", sa.String(length=64), nullable=False),
        sa.Column("source_file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("recovery_bucket_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("candidate_storage_key_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("source_authority_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("candidate_authority_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("configuration_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("route_version_at_request", sa.Integer(), nullable=False),
        sa.Column("request_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("qualification_hash", sa.String(length=64), nullable=False),
        sa.Column("successful_cycle_count", sa.Integer(), server_default="2", nullable=False),
        sa.Column("first_activated_by_id", sa.Uuid(), nullable=False),
        sa.Column("second_activated_by_id", sa.Uuid(), nullable=False),
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
        sa.CheckConstraint("status IN ('pending_second_approval', 'qualified', 'rejected', 'invalidated')", name="ck_recovery_read_qual_status"),
        sa.CheckConstraint("first_cutover_lease_id <> second_cutover_lease_id", name="ck_recovery_read_qual_distinct_leases"),
        sa.CheckConstraint("first_authorization_id <> second_authorization_id", name="ck_recovery_read_qual_distinct_auths"),
        sa.CheckConstraint("requested_by_id <> qualified_by_id OR qualified_by_id IS NULL", name="ck_recovery_read_qual_four_eyes"),
        sa.CheckConstraint("first_activated_by_id <> qualified_by_id OR qualified_by_id IS NULL", name="ck_recovery_read_qual_first_activator_split"),
        sa.CheckConstraint("second_activated_by_id <> qualified_by_id OR qualified_by_id IS NULL", name="ck_recovery_read_qual_second_activator_split"),
        sa.CheckConstraint("successful_cycle_count = 2", name="ck_recovery_read_qual_two_cycles"),
        sa.CheckConstraint("route_version_at_request >= 1", name="ck_recovery_read_qual_route_version"),
        sa.CheckConstraint("routable_authority_created = false", name="ck_recovery_read_qual_no_route_auth"),
        sa.CheckConstraint("read_path_switched = false", name="ck_recovery_read_qual_no_read_switch"),
        sa.CheckConstraint("write_path_switched = false", name="ck_recovery_read_qual_no_write_switch"),
        sa.CheckConstraint("document_storage_key_mutated = false", name="ck_recovery_read_qual_no_key_mut"),
        sa.CheckConstraint("authoritative_storage_changed = false", name="ck_recovery_read_qual_no_authority"),
        sa.CheckConstraint("destructive_action_performed = false", name="ck_recovery_read_qual_no_destructive"),
        sa.CheckConstraint("s3_delete_performed = false", name="ck_recovery_read_qual_no_s3_del"),
        sa.CheckConstraint("local_delete_performed = false", name="ck_recovery_read_qual_no_local_del"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["replica_id"], ["evidence_recovery_replicas.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["first_cutover_lease_id"], ["evidence_recovery_read_path_cutover_leases.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["second_cutover_lease_id"], ["evidence_recovery_read_path_cutover_leases.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["first_authorization_id"], ["evidence_recovery_read_path_cutover_authorizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["second_authorization_id"], ["evidence_recovery_read_path_cutover_authorizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["first_activation_receipt_id"], ["evidence_recovery_read_path_cutover_receipts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["first_rollback_receipt_id"], ["evidence_recovery_read_path_cutover_receipts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["second_activation_receipt_id"], ["evidence_recovery_read_path_cutover_receipts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["second_rollback_receipt_id"], ["evidence_recovery_read_path_cutover_receipts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["first_activated_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["second_activated_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["qualified_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["rejected_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["terminal_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "document_id", "qualification_bundle_hash", name="uq_recovery_read_qual_bundle"),
        sa.UniqueConstraint("organization_id", "qualification_hash", name="uq_recovery_read_qual_org_hash"),
    )
    op.create_index("ix_recovery_read_qual_org_claim_status", QUALIFICATION_TABLE, ["organization_id", "claim_id", "status"])
    op.create_index("ix_recovery_read_qual_org_doc_status", QUALIFICATION_TABLE, ["organization_id", "document_id", "status"])
    for name, column in (
        ("ix_read_qual_org", "organization_id"),
        ("ix_read_qual_claim", "claim_id"),
        ("ix_read_qual_doc", "document_id"),
        ("ix_read_qual_replica", "replica_id"),
        ("ix_read_qual_first_lease", "first_cutover_lease_id"),
        ("ix_read_qual_second_lease", "second_cutover_lease_id"),
        ("ix_read_qual_requester", "requested_by_id"),
        ("ix_read_qual_approver", "qualified_by_id"),
    ):
        op.create_index(name, QUALIFICATION_TABLE, [column])

    op.create_table(
        RECEIPT_TABLE,
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("qualification_id", sa.Uuid(), nullable=False),
        sa.Column("phase", sa.String(length=20), nullable=False),
        sa.Column("qualification_bundle_hash", sa.String(length=64), nullable=False),
        sa.Column("request_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("qualification_hash", sa.String(length=64), nullable=False),
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
        sa.Column("s3_delete_performed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("local_delete_performed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("phase IN ('requested', 'qualified', 'rejected', 'invalidated')", name="ck_recovery_read_qual_receipt_phase"),
        sa.CheckConstraint("routable_authority_created = false", name="ck_recovery_read_qual_rec_no_route"),
        sa.CheckConstraint("read_path_switched = false", name="ck_recovery_read_qual_rec_no_read"),
        sa.CheckConstraint("write_path_switched = false", name="ck_recovery_read_qual_rec_no_write"),
        sa.CheckConstraint("document_storage_key_mutated = false", name="ck_recovery_read_qual_rec_no_key"),
        sa.CheckConstraint("authoritative_storage_changed = false", name="ck_recovery_read_qual_rec_no_auth"),
        sa.CheckConstraint("destructive_action_performed = false", name="ck_recovery_read_qual_rec_no_dest"),
        sa.CheckConstraint("s3_delete_performed = false", name="ck_recovery_read_qual_rec_no_s3_del"),
        sa.CheckConstraint("local_delete_performed = false", name="ck_recovery_read_qual_rec_no_local_del"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["qualification_id"], [f"{QUALIFICATION_TABLE}.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "receipt_hash", name="uq_recovery_read_qual_rec_org_hash"),
    )
    op.create_index("ix_recovery_read_qual_receipt_time", RECEIPT_TABLE, ["qualification_id", "transitioned_at"])
    for name, column in (
        ("ix_read_qual_rec_org", "organization_id"),
        ("ix_read_qual_rec_claim", "claim_id"),
        ("ix_read_qual_rec_doc", "document_id"),
        ("ix_read_qual_rec_qualification", "qualification_id"),
        ("ix_read_qual_rec_actor", "actor_id"),
    ):
        op.create_index(name, RECEIPT_TABLE, [column])


def downgrade() -> None:
    op.drop_table(RECEIPT_TABLE)
    op.drop_table(QUALIFICATION_TABLE)
