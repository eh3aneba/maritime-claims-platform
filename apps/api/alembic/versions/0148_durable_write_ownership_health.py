"""Add Phase AI health qualification for durable recovery write ownership.

Revision ID: 0148_durable_write_ownership_health
Revises: 0147_durable_write_ownership_execution
"""

from alembic import op
import sqlalchemy as sa

revision = "0148_durable_write_ownership_health"
down_revision = "0147_durable_write_ownership_execution"
branch_labels = None
depends_on = None

QUAL = "evidence_recovery_durable_write_ownership_health_qualifications"
RECEIPT = "evidence_recovery_durable_write_ownership_health_receipts"


def _safety_columns() -> list[sa.Column]:
    return [
        sa.Column("local_authoritative", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("storage_write_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("route_mutation_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("durable_write_authority_created", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("read_path_switched", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("write_path_switched", sa.Boolean(), nullable=False, server_default=sa.false()),
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
        sa.CheckConstraint("route_mutation_performed = false", name=f"ck_{prefix}_no_route_mut"),
        sa.CheckConstraint("durable_write_authority_created = false", name=f"ck_{prefix}_no_create"),
        sa.CheckConstraint("read_path_switched = false", name=f"ck_{prefix}_no_read"),
        sa.CheckConstraint("write_path_switched = false", name=f"ck_{prefix}_no_switch"),
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


def upgrade() -> None:
    actor_columns = [
        "phase_ah_activated_by_id", "phase_ag_requested_by_id", "phase_ag_approved_by_id",
        "phase_af_requested_by_id", "phase_af_qualified_by_id", "phase_ae_activated_by_id",
        "phase_ad_requested_by_id", "phase_ad_approved_by_id", "phase_ac_qualified_by_id",
        "phase_ab_activated_by_id", "phase_aa_requested_by_id", "phase_aa_approved_by_id",
        "phase_z_qualified_by_id", "phase_y_executed_by_id", "phase_x_approved_by_id",
        "requested_by_id", "qualified_by_id", "rejected_by_id", "terminal_by_id",
    ]
    op.create_table(
        QUAL,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("durable_write_ownership_lease_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_approval_receipt_id", sa.Uuid(), nullable=False),
        sa.Column("phase_af_health_qualification_id", sa.Uuid(), nullable=False),
        sa.Column("transition_lease_id", sa.Uuid(), nullable=False),
        sa.Column("replica_id", sa.Uuid(), nullable=False),
        sa.Column("activation_receipt_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_hash", sa.String(64), nullable=False),
        sa.Column("authorization_approval_receipt_hash", sa.String(64), nullable=False),
        sa.Column("phase_af_health_qualification_hash", sa.String(64), nullable=False),
        sa.Column("phase_af_health_receipt_hash", sa.String(64), nullable=False),
        sa.Column("transition_lease_hash", sa.String(64), nullable=False),
        sa.Column("replica_hash", sa.String(64), nullable=False),
        sa.Column("activation_receipt_hash", sa.String(64), nullable=False),
        sa.Column("activation_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("lease_hash", sa.String(64), nullable=False),
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
        sa.Column("read_route_version_at_request", sa.Integer(), nullable=False),
        sa.Column("experimental_write_route_version_at_request", sa.Integer(), nullable=False),
        sa.Column("durable_route_version_at_request", sa.Integer(), nullable=False),
        sa.Column("observed_durable_write_mode", sa.String(40), nullable=False, server_default="recovery_primary"),
        sa.Column("observed_durable_write_ownership_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("integrity_proof_hash", sa.String(64), nullable=False),
        sa.Column("request_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("health_qualification_hash", sa.String(64), nullable=False),
        sa.Column("health_state", sa.String(20), nullable=False, server_default="healthy"),
        sa.Column("phase_ah_activated_by_id", sa.Uuid(), nullable=False),
        sa.Column("phase_ag_requested_by_id", sa.Uuid(), nullable=False),
        sa.Column("phase_ag_approved_by_id", sa.Uuid(), nullable=False),
        sa.Column("phase_af_requested_by_id", sa.Uuid(), nullable=False),
        sa.Column("phase_af_qualified_by_id", sa.Uuid(), nullable=False),
        sa.Column("phase_ae_activated_by_id", sa.Uuid(), nullable=False),
        sa.Column("phase_ad_requested_by_id", sa.Uuid(), nullable=False),
        sa.Column("phase_ad_approved_by_id", sa.Uuid(), nullable=False),
        sa.Column("phase_ac_qualified_by_id", sa.Uuid(), nullable=False),
        sa.Column("phase_ab_activated_by_id", sa.Uuid(), nullable=False),
        sa.Column("phase_aa_requested_by_id", sa.Uuid(), nullable=False),
        sa.Column("phase_aa_approved_by_id", sa.Uuid(), nullable=False),
        sa.Column("phase_z_qualified_by_id", sa.Uuid(), nullable=False),
        sa.Column("phase_y_executed_by_id", sa.Uuid(), nullable=False),
        sa.Column("phase_x_approved_by_id", sa.Uuid(), nullable=False),
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
        sa.ForeignKeyConstraint(["durable_write_ownership_lease_id"], ["evidence_recovery_durable_write_ownership_leases.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_id"], ["evidence_recovery_durable_write_authorizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_approval_receipt_id"], ["evidence_recovery_durable_write_authorization_receipts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_af_health_qualification_id"], ["evidence_recovery_write_ownership_transition_health_qualifications.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["transition_lease_id"], ["evidence_recovery_write_ownership_transition_leases.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["replica_id"], ["evidence_recovery_replicas.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["activation_receipt_id"], ["evidence_recovery_durable_write_ownership_receipts.id"], ondelete="RESTRICT"),
        *[sa.ForeignKeyConstraint([c], ["users.id"], ondelete="RESTRICT") for c in actor_columns],
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("durable_write_ownership_lease_id", name="uq_dw_health_lease"),
        sa.UniqueConstraint("organization_id", "health_qualification_hash", name="uq_dw_health_org_hash"),
        sa.CheckConstraint("status IN ('pending_second_approval','qualified','rejected','expired','invalidated')", name="ck_dw_health_status"),
        sa.CheckConstraint("health_state = 'healthy'", name="ck_dw_health_healthy"),
        sa.CheckConstraint("observed_durable_write_ownership_active = true", name="ck_dw_health_active"),
        sa.CheckConstraint("observed_durable_write_mode = 'recovery_primary'", name="ck_dw_health_mode"),
        sa.CheckConstraint("requested_by_id <> qualified_by_id OR qualified_by_id IS NULL", name="ck_dw_health_four_eyes"),
        sa.CheckConstraint("phase_ah_activated_by_id <> qualified_by_id OR qualified_by_id IS NULL", name="ck_dw_health_ah_split"),
        sa.CheckConstraint("phase_ag_requested_by_id <> qualified_by_id OR qualified_by_id IS NULL", name="ck_dw_health_agr_split"),
        sa.CheckConstraint("phase_ag_approved_by_id <> qualified_by_id OR qualified_by_id IS NULL", name="ck_dw_health_aga_split"),
        sa.CheckConstraint("phase_af_requested_by_id <> qualified_by_id OR qualified_by_id IS NULL", name="ck_dw_health_afr_split"),
        sa.CheckConstraint("phase_af_qualified_by_id <> qualified_by_id OR qualified_by_id IS NULL", name="ck_dw_health_afq_split"),
        sa.CheckConstraint("phase_ae_activated_by_id <> qualified_by_id OR qualified_by_id IS NULL", name="ck_dw_health_ae_split"),
        sa.CheckConstraint("phase_ad_requested_by_id <> qualified_by_id OR qualified_by_id IS NULL", name="ck_dw_health_adr_split"),
        sa.CheckConstraint("phase_ad_approved_by_id <> qualified_by_id OR qualified_by_id IS NULL", name="ck_dw_health_ada_split"),
        sa.CheckConstraint("source_file_size_bytes >= 0", name="ck_dw_health_size"),
        sa.CheckConstraint("observed_local_size_bytes = source_file_size_bytes", name="ck_dw_health_local_size"),
        sa.CheckConstraint("observed_recovery_size_bytes = source_file_size_bytes", name="ck_dw_health_recovery_size"),
        sa.CheckConstraint("observed_local_hash = source_file_hash", name="ck_dw_health_local_hash"),
        sa.CheckConstraint("observed_recovery_hash = source_file_hash", name="ck_dw_health_recovery_hash"),
        sa.CheckConstraint("read_route_version_at_request >= 1", name="ck_dw_health_read_ver"),
        sa.CheckConstraint("experimental_write_route_version_at_request >= 1", name="ck_dw_health_exp_ver"),
        sa.CheckConstraint("durable_route_version_at_request >= 1", name="ck_dw_health_durable_ver"),
        *_safety_constraints("dw_health"),
    )
    op.create_index("ix_dw_health_org_claim", QUAL, ["organization_id", "claim_id", "status"])
    op.create_index("ix_dw_health_org_doc", QUAL, ["organization_id", "document_id", "status"])

    op.create_table(
        RECEIPT,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("health_qualification_id", sa.Uuid(), nullable=False),
        sa.Column("durable_write_ownership_lease_id", sa.Uuid(), nullable=False),
        sa.Column("phase", sa.String(20), nullable=False),
        sa.Column("health_state", sa.String(20), nullable=False, server_default="healthy"),
        sa.Column("observed_durable_write_mode", sa.String(40), nullable=False, server_default="recovery_primary"),
        sa.Column("observed_durable_write_ownership_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("durable_route_version", sa.Integer(), nullable=False),
        sa.Column("integrity_proof_hash", sa.String(64), nullable=False),
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
        sa.ForeignKeyConstraint(["durable_write_ownership_lease_id"], ["evidence_recovery_durable_write_ownership_leases.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "receipt_hash", name="uq_dw_health_rec_org_hash"),
        sa.CheckConstraint("phase IN ('requested','qualified','rejected','expired','invalidated')", name="ck_dw_health_rec_phase"),
        sa.CheckConstraint("health_state = 'healthy'", name="ck_dw_health_rec_healthy"),
        sa.CheckConstraint("observed_durable_write_ownership_active = true", name="ck_dw_health_rec_active"),
        sa.CheckConstraint("observed_durable_write_mode = 'recovery_primary'", name="ck_dw_health_rec_mode"),
        *_safety_constraints("dw_health_rec"),
    )
    op.create_index("ix_dw_health_rec_time", RECEIPT, ["health_qualification_id", "transitioned_at"])


def downgrade() -> None:
    op.drop_index("ix_dw_health_rec_time", table_name=RECEIPT)
    op.drop_table(RECEIPT)
    op.drop_index("ix_dw_health_org_doc", table_name=QUAL)
    op.drop_index("ix_dw_health_org_claim", table_name=QUAL)
    op.drop_table(QUAL)
