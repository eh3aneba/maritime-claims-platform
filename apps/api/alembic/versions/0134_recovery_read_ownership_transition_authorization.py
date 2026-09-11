"""Add bounded recovery read-ownership transition authorization.

Revision ID: 0134_recovery_read_ownership_transition_authorization
Revises: 0133_recovery_durable_read_reauthorized_renewal_health_qualification
"""

from alembic import op
import sqlalchemy as sa

revision = "0134_recovery_read_ownership_transition_authorization"
down_revision = "0133_recovery_durable_read_reauthorized_renewal_health_qualification"
branch_labels = None
depends_on = None

AUTH = "evidence_recovery_read_ownership_authorizations"
RECEIPT = "evidence_recovery_read_ownership_authorization_receipts"


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
        AUTH,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("phase_t_health_qualification_id", sa.Uuid(), nullable=False),
        sa.Column("phase_t_health_receipt_id", sa.Uuid(), nullable=False),
        sa.Column("reauthorized_renewal_lease_id", sa.Uuid(), nullable=False),
        sa.Column("activation_receipt_id", sa.Uuid(), nullable=False),
        sa.Column("terminal_receipt_id", sa.Uuid(), nullable=False),
        sa.Column("reauthorization_id", sa.Uuid(), nullable=False),
        sa.Column("phase_q_health_qualification_id", sa.Uuid(), nullable=False),
        sa.Column("prior_renewal_lease_id", sa.Uuid(), nullable=False),
        sa.Column("replica_id", sa.Uuid(), nullable=False),
        sa.Column("phase_t_health_qualification_hash", sa.String(length=64), nullable=False),
        sa.Column("phase_t_request_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("phase_t_health_receipt_hash", sa.String(length=64), nullable=False),
        sa.Column("operational_evidence_hash", sa.String(length=64), nullable=False),
        sa.Column("health_state", sa.String(length=20), nullable=False),
        sa.Column("reauthorized_renewal_lease_hash", sa.String(length=64), nullable=False),
        sa.Column("lease_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("activation_receipt_hash", sa.String(length=64), nullable=False),
        sa.Column("terminal_receipt_hash", sa.String(length=64), nullable=False),
        sa.Column("reauthorization_hash", sa.String(length=64), nullable=False),
        sa.Column("phase_q_health_qualification_hash", sa.String(length=64), nullable=False),
        sa.Column("prior_renewal_lease_hash", sa.String(length=64), nullable=False),
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
        sa.Column("route_version_at_request", sa.Integer(), nullable=False),
        sa.Column("integrity_proof_hash", sa.String(length=64), nullable=False),
        sa.Column("request_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("authorization_hash", sa.String(length=64), nullable=False),
        sa.Column("phase_t_qualified_by_id", sa.Uuid(), nullable=False),
        sa.Column("reauthorized_renewal_activated_by_id", sa.Uuid(), nullable=False),
        sa.Column("reauthorization_approved_by_id", sa.Uuid(), nullable=False),
        sa.Column("phase_q_qualified_by_id", sa.Uuid(), nullable=False),
        sa.Column("prior_renewal_activated_by_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending_second_approval"),
        sa.Column("requested_by_id", sa.Uuid(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("review_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_reason", sa.Text(), nullable=False),
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
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_t_health_qualification_id"], ["evidence_recovery_drr_reauth_renewal_health_qualifications.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_t_health_receipt_id"], ["evidence_recovery_drr_reauth_renewal_health_receipts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reauthorized_renewal_lease_id"], ["evidence_recovery_drr_reauthorized_renewal_leases.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["activation_receipt_id"], ["evidence_recovery_drr_reauthorized_renewal_receipts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["terminal_receipt_id"], ["evidence_recovery_drr_reauthorized_renewal_receipts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reauthorization_id"], ["evidence_recovery_drr_reauthorizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_q_health_qualification_id"], ["evidence_recovery_durable_read_renewal_health_qualifications.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["prior_renewal_lease_id"], ["evidence_recovery_durable_read_renewal_leases.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["replica_id"], ["evidence_recovery_replicas.id"], ondelete="RESTRICT"),
        *[
            sa.ForeignKeyConstraint([column], ["users.id"], ondelete="RESTRICT")
            for column in (
                "phase_t_qualified_by_id",
                "reauthorized_renewal_activated_by_id",
                "reauthorization_approved_by_id",
                "phase_q_qualified_by_id",
                "prior_renewal_activated_by_id",
                "requested_by_id",
                "approved_by_id",
                "rejected_by_id",
                "terminal_by_id",
            )
        ],
        sa.CheckConstraint("status IN ('pending_second_approval', 'approved', 'rejected', 'expired', 'invalidated')", name="ck_rr_owner_auth_status"),
        sa.CheckConstraint("health_state = 'healthy'", name="ck_rr_owner_auth_healthy"),
        sa.CheckConstraint("requested_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_rr_owner_auth_four_eyes"),
        sa.CheckConstraint("phase_t_qualified_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_rr_owner_auth_t_split"),
        sa.CheckConstraint("reauthorized_renewal_activated_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_rr_owner_auth_s_split"),
        sa.CheckConstraint("reauthorization_approved_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_rr_owner_auth_r_split"),
        sa.CheckConstraint("phase_q_qualified_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_rr_owner_auth_q_split"),
        sa.CheckConstraint("prior_renewal_activated_by_id <> approved_by_id OR approved_by_id IS NULL", name="ck_rr_owner_auth_p_split"),
        sa.CheckConstraint("source_file_size_bytes >= 0", name="ck_rr_owner_auth_size"),
        sa.CheckConstraint("verified_durable_read_count >= 1", name="ck_rr_owner_auth_verified"),
        sa.CheckConstraint("integrity_failure_count = 0", name="ck_rr_owner_auth_integrity"),
        sa.CheckConstraint("storage_unavailable_count = 0", name="ck_rr_owner_auth_storage"),
        sa.CheckConstraint("route_expired_attempt_count >= 0", name="ck_rr_owner_auth_expired"),
        sa.CheckConstraint("operational_event_count >= verified_durable_read_count", name="ck_rr_owner_auth_events"),
        sa.CheckConstraint("route_version_at_request >= 1", name="ck_rr_owner_auth_routever"),
        sa.CheckConstraint("status <> 'approved' OR authorization_expires_at IS NOT NULL", name="ck_rr_owner_auth_approved_exp"),
        sa.CheckConstraint("status = 'approved' OR authorization_expires_at IS NULL", name="ck_rr_owner_auth_nonapproved_exp"),
        sa.CheckConstraint("routable_authority_created = false", name="ck_rr_owner_auth_no_route"),
        sa.CheckConstraint("durable_read_route_created = false", name="ck_rr_owner_auth_no_durable"),
        sa.CheckConstraint("read_path_switched = false", name="ck_rr_owner_auth_no_read"),
        sa.CheckConstraint("write_path_switched = false", name="ck_rr_owner_auth_no_write"),
        sa.CheckConstraint("document_storage_key_mutated = false", name="ck_rr_owner_auth_no_key"),
        sa.CheckConstraint("authoritative_storage_changed = false", name="ck_rr_owner_auth_no_owner"),
        sa.CheckConstraint("destructive_action_performed = false", name="ck_rr_owner_auth_no_dest"),
        sa.CheckConstraint("s3_delete_performed = false", name="ck_rr_owner_auth_no_s3del"),
        sa.CheckConstraint("local_delete_performed = false", name="ck_rr_owner_auth_no_localdel"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("phase_t_health_qualification_id", name="uq_rr_owner_auth_t_health"),
        sa.UniqueConstraint("organization_id", "authorization_hash", name="uq_rr_owner_auth_org_hash"),
    )

    for column in (
        "organization_id", "claim_id", "document_id", "phase_t_health_qualification_id",
        "phase_t_health_receipt_id", "reauthorized_renewal_lease_id", "activation_receipt_id",
        "terminal_receipt_id", "reauthorization_id", "phase_q_health_qualification_id",
        "prior_renewal_lease_id", "replica_id", "phase_t_qualified_by_id",
        "reauthorized_renewal_activated_by_id", "reauthorization_approved_by_id",
        "phase_q_qualified_by_id", "prior_renewal_activated_by_id", "requested_by_id",
        "approved_by_id", "rejected_by_id", "terminal_by_id",
    ):
        op.create_index(f"ix_rr_owner_auth_{column[:28]}", AUTH, [column], unique=False)
    op.create_index("ix_rr_owner_auth_org_claim", AUTH, ["organization_id", "claim_id", "status"], unique=False)
    op.create_index("ix_rr_owner_auth_org_doc", AUTH, ["organization_id", "document_id", "status"], unique=False)

    op.create_table(
        RECEIPT,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_id", sa.Uuid(), nullable=False),
        sa.Column("phase_t_health_qualification_id", sa.Uuid(), nullable=False),
        sa.Column("reauthorized_renewal_lease_id", sa.Uuid(), nullable=False),
        sa.Column("phase", sa.String(length=20), nullable=False),
        sa.Column("health_state", sa.String(length=20), nullable=False),
        sa.Column("operational_evidence_hash", sa.String(length=64), nullable=False),
        sa.Column("integrity_proof_hash", sa.String(length=64), nullable=False),
        sa.Column("request_snapshot_hash", sa.String(length=64), nullable=False),
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
        sa.ForeignKeyConstraint(["authorization_id"], [f"{AUTH}.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_t_health_qualification_id"], ["evidence_recovery_drr_reauth_renewal_health_qualifications.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reauthorized_renewal_lease_id"], ["evidence_recovery_drr_reauthorized_renewal_leases.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("phase IN ('requested', 'approved', 'rejected', 'expired', 'invalidated')", name="ck_rr_owner_rec_phase"),
        sa.CheckConstraint("routable_authority_created = false", name="ck_rr_owner_rec_no_route"),
        sa.CheckConstraint("durable_read_route_created = false", name="ck_rr_owner_rec_no_durable"),
        sa.CheckConstraint("read_path_switched = false", name="ck_rr_owner_rec_no_read"),
        sa.CheckConstraint("write_path_switched = false", name="ck_rr_owner_rec_no_write"),
        sa.CheckConstraint("document_storage_key_mutated = false", name="ck_rr_owner_rec_no_key"),
        sa.CheckConstraint("authoritative_storage_changed = false", name="ck_rr_owner_rec_no_owner"),
        sa.CheckConstraint("destructive_action_performed = false", name="ck_rr_owner_rec_no_dest"),
        sa.CheckConstraint("s3_delete_performed = false", name="ck_rr_owner_rec_no_s3del"),
        sa.CheckConstraint("local_delete_performed = false", name="ck_rr_owner_rec_no_localdel"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "receipt_hash", name="uq_rr_owner_rec_org_hash"),
    )
    for column in (
        "organization_id", "claim_id", "document_id", "authorization_id",
        "phase_t_health_qualification_id", "reauthorized_renewal_lease_id", "actor_id",
    ):
        op.create_index(f"ix_rr_owner_rec_{column[:28]}", RECEIPT, [column], unique=False)
    op.create_index("ix_rr_owner_rec_time", RECEIPT, ["authorization_id", "transitioned_at"], unique=False)


def downgrade() -> None:
    op.drop_table(RECEIPT)
    op.drop_table(AUTH)
