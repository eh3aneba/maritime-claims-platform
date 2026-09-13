"""Add Phase 17.4-B controlled physical disposal execution.

Revision ID: 0156_controlled_physical_disposal_execution
Revises: 0155_physical_disposal_admission_authorization
"""

from alembic import op
import sqlalchemy as sa

revision = "0156_controlled_physical_disposal_execution"
down_revision = "0155_physical_disposal_admission_authorization"
branch_labels = None
depends_on = None

EXECUTION = "physical_disposal_executions"
ITEM = "physical_disposal_execution_items"
RECEIPT = "physical_disposal_execution_receipts"


def upgrade() -> None:
    op.create_table(
        EXECUTION,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_hash", sa.String(64), nullable=False),
        sa.Column("approval_hash", sa.String(64), nullable=False),
        sa.Column("document_bindings_hash", sa.String(64), nullable=False),
        sa.Column("execution_request_hash", sa.String(64), nullable=False),
        sa.Column("executor_id", sa.Uuid(), nullable=False),
        sa.Column("execution_reason", sa.Text(), nullable=False),
        sa.Column("prepared_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="prepared"),
        sa.Column("document_count", sa.Integer(), nullable=False),
        sa.Column("deleted_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("execution_hash", sa.String(64), nullable=True),
        sa.Column("destructive_action_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("local_delete_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("s3_delete_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("recovery_bytes_preserved", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("document_row_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("document_storage_key_mutated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_id"], ["physical_disposal_admission_authorizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["executor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("authorization_id", name="uq_pd_exec_authorization"),
        sa.UniqueConstraint("organization_id", "request_id", name="uq_pd_exec_org_request"),
        sa.UniqueConstraint("organization_id", "execution_request_hash", name="uq_pd_exec_org_req_hash"),
        sa.CheckConstraint("status IN ('prepared','partial','succeeded')", name="ck_pd_exec_status"),
        sa.CheckConstraint("document_count > 0", name="ck_pd_exec_document_count"),
        sa.CheckConstraint("deleted_count >= 0 AND deleted_count <= document_count", name="ck_pd_exec_deleted_count"),
        sa.CheckConstraint("s3_delete_performed = false", name="ck_pd_exec_no_s3_delete"),
        sa.CheckConstraint("document_row_deleted = false", name="ck_pd_exec_no_row_delete"),
        sa.CheckConstraint("document_storage_key_mutated = false", name="ck_pd_exec_no_key_mutation"),
        sa.CheckConstraint(
            "(status = 'prepared' AND completed_at IS NULL AND execution_hash IS NULL) OR "
            "(status = 'partial' AND completed_at IS NULL AND execution_hash IS NULL AND local_delete_performed = true) OR "
            "(status = 'succeeded' AND completed_at IS NOT NULL AND execution_hash IS NOT NULL "
            "AND deleted_count = document_count AND destructive_action_performed = true "
            "AND local_delete_performed = true AND recovery_bytes_preserved = true)",
            name="ck_pd_exec_lifecycle",
        ),
    )
    op.create_index("ix_pd_exec_org_claim_status", EXECUTION, ["organization_id", "claim_id", "status"])
    for name, col in (("ix_pd_exec_org", "organization_id"), ("ix_pd_exec_claim", "claim_id"), ("ix_pd_exec_auth", "authorization_id"), ("ix_pd_exec_req", "request_id"), ("ix_pd_exec_actor", "executor_id")):
        op.create_index(name, EXECUTION, [col])

    op.create_table(
        ITEM,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("ao_health_qualification_id", sa.Uuid(), nullable=False),
        sa.Column("binding_hash", sa.String(64), nullable=False),
        sa.Column("file_hash", sa.String(64), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("local_storage_key_fingerprint", sa.String(64), nullable=False),
        sa.Column("recovery_read_source", sa.String(80), nullable=False),
        sa.Column("target_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="prepared"),
        sa.Column("local_existed_before", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("local_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("local_absent_after", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("recovery_verified_before", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("recovery_verified_after", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome_hash", sa.String(64), nullable=True),
        sa.Column("s3_delete_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("document_row_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("document_storage_key_mutated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["execution_id"], [EXECUTION + ".id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["ao_health_qualification_id"], ["evidence_recovery_durable_auth_storage_health_qualifications.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("execution_id", "document_id", name="uq_pd_exec_item_document"),
        sa.UniqueConstraint("organization_id", "target_hash", name="uq_pd_exec_item_org_target"),
        sa.CheckConstraint("status IN ('prepared','deleted','verified')", name="ck_pd_exec_item_status"),
        sa.CheckConstraint("file_size_bytes >= 0", name="ck_pd_exec_item_size"),
        sa.CheckConstraint("recovery_verified_before = true", name="ck_pd_exec_item_recovery_before"),
        sa.CheckConstraint("s3_delete_performed = false", name="ck_pd_exec_item_no_s3_delete"),
        sa.CheckConstraint("document_row_deleted = false", name="ck_pd_exec_item_no_row_delete"),
        sa.CheckConstraint("document_storage_key_mutated = false", name="ck_pd_exec_item_no_key_mutation"),
        sa.CheckConstraint(
            "(status = 'prepared' AND local_deleted = false AND local_absent_after = false AND recovery_verified_after = false AND outcome_hash IS NULL) OR "
            "(status = 'deleted' AND local_deleted = true AND local_absent_after = true AND outcome_hash IS NULL) OR "
            "(status = 'verified' AND local_deleted = true AND local_absent_after = true AND recovery_verified_after = true AND outcome_hash IS NOT NULL)",
            name="ck_pd_exec_item_lifecycle",
        ),
    )
    op.create_index("ix_pd_exec_item_exec_status", ITEM, ["execution_id", "status"])
    for name, col in (("ix_pd_item_org", "organization_id"), ("ix_pd_item_claim", "claim_id"), ("ix_pd_item_exec", "execution_id"), ("ix_pd_item_doc", "document_id"), ("ix_pd_item_ao", "ao_health_qualification_id")):
        op.create_index(name, ITEM, [col])

    op.create_table(
        RECEIPT,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(24), nullable=False),
        sa.Column("status_after", sa.String(20), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("execution_request_hash", sa.String(64), nullable=False),
        sa.Column("execution_hash", sa.String(64), nullable=True),
        sa.Column("prior_receipt_hash", sa.String(64), nullable=True),
        sa.Column("receipt_hash", sa.String(64), nullable=False),
        sa.Column("destructive_action_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("local_delete_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("s3_delete_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("recovery_bytes_preserved", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("document_row_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("document_storage_key_mutated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["execution_id"], [EXECUTION + ".id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("execution_id", "sequence_number", name="uq_pd_exec_receipt_sequence"),
        sa.UniqueConstraint("organization_id", "receipt_hash", name="uq_pd_exec_receipt_org_hash"),
        sa.CheckConstraint("sequence_number > 0", name="ck_pd_exec_receipt_sequence"),
        sa.CheckConstraint("event_type IN ('prepared','local_deleted','reconciled','succeeded')", name="ck_pd_exec_receipt_event"),
        sa.CheckConstraint("status_after IN ('prepared','partial','succeeded')", name="ck_pd_exec_receipt_status"),
        sa.CheckConstraint("s3_delete_performed = false", name="ck_pd_exec_receipt_no_s3_delete"),
        sa.CheckConstraint("document_row_deleted = false", name="ck_pd_exec_receipt_no_row_delete"),
        sa.CheckConstraint("document_storage_key_mutated = false", name="ck_pd_exec_receipt_no_key_mutation"),
        sa.CheckConstraint("(sequence_number = 1 AND prior_receipt_hash IS NULL) OR (sequence_number > 1 AND prior_receipt_hash IS NOT NULL)", name="ck_pd_exec_receipt_chain"),
    )
    op.create_index("ix_pd_exec_receipt_exec_seq", RECEIPT, ["execution_id", "sequence_number"])
    for name, col in (("ix_pd_rcpt_org", "organization_id"), ("ix_pd_rcpt_claim", "claim_id"), ("ix_pd_rcpt_exec", "execution_id"), ("ix_pd_rcpt_actor", "actor_id")):
        op.create_index(name, RECEIPT, [col])


def downgrade() -> None:
    op.drop_table(RECEIPT)
    op.drop_table(ITEM)
    op.drop_table(EXECUTION)
