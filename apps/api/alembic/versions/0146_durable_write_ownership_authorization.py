"""Add Phase AG governance authorization for durable recovery write ownership.

Revision ID: 0146_durable_write_ownership_authorization
Revises: 0145_write_ownership_transition_health
"""

from alembic import op
import sqlalchemy as sa

revision = "0146_durable_write_ownership_authorization"
down_revision = "0145_write_ownership_transition_health"
branch_labels = None
depends_on = None

AUTH = "evidence_recovery_durable_write_authorizations"
RECEIPT = "evidence_recovery_durable_write_authorization_receipts"


def _safety_columns() -> list[sa.Column]:
    return [
        sa.Column("local_authoritative", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("storage_write_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("write_route_lease_created", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("write_route_reactivated", sa.Boolean(), nullable=False, server_default=sa.false()),
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
        sa.CheckConstraint("write_route_lease_created = false", name=f"ck_{prefix}_no_lease"),
        sa.CheckConstraint("write_route_reactivated = false", name=f"ck_{prefix}_no_reactivate"),
        sa.CheckConstraint("durable_write_authority_created = false", name=f"ck_{prefix}_no_durable"),
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
    op.create_table(
        AUTH,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("phase_af_health_qualification_id", sa.Uuid(), nullable=False),
        sa.Column("phase_af_health_receipt_id", sa.Uuid(), nullable=False),
        sa.Column("transition_lease_id", sa.Uuid(), nullable=False),
        sa.Column("phase_ad_authorization_id", sa.Uuid(), nullable=False),
        sa.Column("replica_id", sa.Uuid(), nullable=False),
        sa.Column("phase_af_health_qualification_hash", sa.String(64), nullable=False),
        sa.Column("phase_af_health_receipt_hash", sa.String(64), nullable=False),
        sa.Column("phase_af_request_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("phase_af_integrity_proof_hash", sa.String(64), nullable=False),
        sa.Column("transition_lease_hash", sa.String(64), nullable=False),
        sa.Column("phase_ad_authorization_hash", sa.String(64), nullable=False),
        sa.Column("replica_hash", sa.String(64), nullable=False),
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
        sa.Column("write_route_version_at_request", sa.Integer(), nullable=False),
        sa.Column("request_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("authorization_hash", sa.String(64), nullable=False),
        sa.Column("health_state", sa.String(20), nullable=False, server_default="healthy"),
        sa.Column("max_execution_windows", sa.Integer(), nullable=False, server_default="1"),
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
        sa.Column("approved_by_id", sa.Uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("authorization_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approval_reason", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["phase_af_health_qualification_id"], ["evidence_recovery_write_ownership_transition_health_qualifications.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_af_health_receipt_id"], ["evidence_recovery_write_ownership_transition_health_receipts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["transition_lease_id"], ["evidence_recovery_write_ownership_transition_leases.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_ad_authorization_id"], ["evidence_recovery_write_ownership_transition_authorizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["replica_id"], ["evidence_recovery_replicas.id"], ondelete="RESTRICT"),
        *[sa.ForeignKeyConstraint([[c]], ["users.id"], ondelete="RESTRICT") for c in [
            "phase_af_requested_by_id", "phase_af_qualified_by_id", "phase_ae_activated_by_id",
            "phase_ad_requested_by_id", "phase_ad_approved_by_id", "phase_ac_qualified_by_id",
            "phase_ab_activated_by_id", "phase_aa_requested_by_id", "phase_aa_approved_by_id",
            "phase_z_qualified_by_id", "phase_y_executed_by_id", "phase_x_approved_by_id",
            "requested_by_id", "approved_by_id", "rejected_by_id", "terminal_by_id",
        ]],
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("phase_af_health_qualification_id", name="uq_dw_auth_af_health"),
        sa.UniqueConstraint("organization_id", "authorization_hash", name="uq_dw_auth_org_hash"),
        sa.CheckConstraint("status IN ('pending_second_approval','approved','rejected','expired','invalidated')", name="ck_dw_auth_status"),
        sa.CheckConstraint("health_state = 'healthy'", name="ck_dw_auth_healthy"),
        sa.CheckConstraint("requested_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_dw_auth_four_eyes"),
        sa.CheckConstraint("phase_af_requested_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_dw_auth_afr_split"),
        sa.CheckConstraint("phase_af_qualified_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_dw_auth_afq_split"),
        sa.CheckConstraint("phase_ae_activated_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_dw_auth_ae_split"),
        sa.CheckConstraint("phase_ad_requested_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_dw_auth_adr_split"),
        sa.CheckConstraint("phase_ad_approved_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_dw_auth_ada_split"),
        sa.CheckConstraint("phase_ac_qualified_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_dw_auth_ac_split"),
        sa.CheckConstraint("phase_ab_activated_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_dw_auth_ab_split"),
        sa.CheckConstraint("phase_aa_requested_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_dw_auth_aar_split"),
        sa.CheckConstraint("phase_aa_approved_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_dw_auth_aaa_split"),
        sa.CheckConstraint("phase_z_qualified_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_dw_auth_z_split"),
        sa.CheckConstraint("phase_y_executed_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_dw_auth_y_split"),
        sa.CheckConstraint("phase_x_approved_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_dw_auth_x_split"),
        sa.CheckConstraint("source_file_size_bytes >= 0", name="ck_dw_auth_size"),
        sa.CheckConstraint("observed_local_size_bytes = source_file_size_bytes", name="ck_dw_auth_local_size"),
        sa.CheckConstraint("observed_recovery_size_bytes = source_file_size_bytes", name="ck_dw_auth_recovery_size"),
        sa.CheckConstraint("observed_local_hash = source_file_hash", name="ck_dw_auth_local_hash"),
        sa.CheckConstraint("observed_recovery_hash = source_file_hash", name="ck_dw_auth_recovery_hash"),
        sa.CheckConstraint("read_route_version_at_request >= 1", name="ck_dw_auth_read_ver"),
        sa.CheckConstraint("write_route_version_at_request >= 1", name="ck_dw_auth_write_ver"),
        sa.CheckConstraint("max_execution_windows = 1", name="ck_dw_auth_one_window"),
        sa.CheckConstraint("status <> 'approved' OR authorization_expires_at IS NOT NULL", name="ck_dw_auth_approved_exp"),
        sa.CheckConstraint("status = 'approved' OR authorization_expires_at IS NULL", name="ck_dw_auth_nonapproved_exp"),
        *_safety_constraints("dw_auth"),
    )
    op.create_index("ix_dw_auth_org_claim", AUTH, ["organization_id", "claim_id", "status"])
    op.create_index("ix_dw_auth_org_doc", AUTH, ["organization_id", "document_id", "status"])

    op.create_table(
        RECEIPT,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_id", sa.Uuid(), nullable=False),
        sa.Column("phase_af_health_qualification_id", sa.Uuid(), nullable=False),
        sa.Column("phase", sa.String(20), nullable=False),
        sa.Column("health_state", sa.String(20), nullable=False, server_default="healthy"),
        sa.Column("phase_af_health_qualification_hash", sa.String(64), nullable=False),
        sa.Column("phase_af_health_receipt_hash", sa.String(64), nullable=False),
        sa.Column("request_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("authorization_hash", sa.String(64), nullable=False),
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
        sa.ForeignKeyConstraint(["authorization_id"], [f"{AUTH}.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_af_health_qualification_id"], ["evidence_recovery_write_ownership_transition_health_qualifications.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "receipt_hash", name="uq_dw_auth_rec_org_hash"),
        sa.CheckConstraint("phase IN ('requested','approved','rejected','expired','invalidated')", name="ck_dw_auth_rec_phase"),
        sa.CheckConstraint("health_state = 'healthy'", name="ck_dw_auth_rec_healthy"),
        *_safety_constraints("dw_auth_rec"),
    )
    op.create_index("ix_dw_auth_rec_time", RECEIPT, ["authorization_id", "transitioned_at"])


def downgrade() -> None:
    op.drop_index("ix_dw_auth_rec_time", table_name=RECEIPT)
    op.drop_table(RECEIPT)
    op.drop_index("ix_dw_auth_org_doc", table_name=AUTH)
    op.drop_index("ix_dw_auth_org_claim", table_name=AUTH)
    op.drop_table(AUTH)
