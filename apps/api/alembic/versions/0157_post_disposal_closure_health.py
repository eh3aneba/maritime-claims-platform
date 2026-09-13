"""Add Phase 17.4-C post-disposal closure health qualification.

Revision ID: 0157_post_disposal_closure_health
Revises: 0156_controlled_physical_disposal_execution
"""

from alembic import op
import sqlalchemy as sa

revision = "0157_post_disposal_closure_health"
down_revision = "0156_controlled_physical_disposal_execution"
branch_labels = None
depends_on = None

QUALIFICATION = "physical_disposal_closure_qualifications"
RECEIPT = "physical_disposal_closure_receipts"


def _safety_columns():
    return [
        sa.Column("storage_write_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("route_mutation_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("ownership_mutation_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("read_path_switched", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("write_path_switched", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("document_storage_key_mutated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("destructive_action_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("physical_disposal_authorized", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("s3_put_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("s3_copy_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("s3_delete_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("local_overwrite_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("local_move_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("local_delete_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
    ]


def _safety_constraints(prefix: str):
    return [
        sa.CheckConstraint("storage_write_performed = false", name=f"ck_{prefix}_no_write"),
        sa.CheckConstraint("route_mutation_performed = false", name=f"ck_{prefix}_no_route"),
        sa.CheckConstraint("ownership_mutation_performed = false", name=f"ck_{prefix}_no_owner"),
        sa.CheckConstraint("read_path_switched = false", name=f"ck_{prefix}_no_read"),
        sa.CheckConstraint("write_path_switched = false", name=f"ck_{prefix}_no_write_path"),
        sa.CheckConstraint("document_storage_key_mutated = false", name=f"ck_{prefix}_no_key"),
        sa.CheckConstraint("destructive_action_performed = false", name=f"ck_{prefix}_no_dest"),
        sa.CheckConstraint("physical_disposal_authorized = false", name=f"ck_{prefix}_no_authority"),
        sa.CheckConstraint("s3_put_performed = false", name=f"ck_{prefix}_no_put"),
        sa.CheckConstraint("s3_copy_performed = false", name=f"ck_{prefix}_no_copy"),
        sa.CheckConstraint("s3_delete_performed = false", name=f"ck_{prefix}_no_s3del"),
        sa.CheckConstraint("local_overwrite_performed = false", name=f"ck_{prefix}_no_overwrite"),
        sa.CheckConstraint("local_move_performed = false", name=f"ck_{prefix}_no_move"),
        sa.CheckConstraint("local_delete_performed = false", name=f"ck_{prefix}_no_localdel"),
    ]


def upgrade() -> None:
    op.create_table(
        QUALIFICATION,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_id", sa.Uuid(), nullable=False),
        sa.Column("execution_request_hash", sa.String(64), nullable=False),
        sa.Column("execution_hash", sa.String(64), nullable=False),
        sa.Column("document_bindings_hash", sa.String(64), nullable=False),
        sa.Column("execution_receipt_chain_hash", sa.String(64), nullable=False),
        sa.Column("item_outcomes_hash", sa.String(64), nullable=False),
        sa.Column("verification_snapshot", sa.JSON(), nullable=False),
        sa.Column("verification_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("separation_actor_set_hash", sa.String(64), nullable=False),
        sa.Column("document_count", sa.Integer(), nullable=False),
        sa.Column("total_file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("observed_local_targets_absent", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("observed_recovery_bytes_healthy", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("observed_document_rows_preserved", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("observed_storage_keys_preserved", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("observed_authority_kind", sa.String(40), nullable=False, server_default="recovery_storage"),
        sa.Column("observed_authority_tenure", sa.String(40), nullable=False, server_default="durable_recovery"),
        sa.Column("health_state", sa.String(20), nullable=False, server_default="healthy"),
        sa.Column("phase_17_4_b_executor_id", sa.Uuid(), nullable=False),
        sa.Column("phase_17_4_a_requested_by_id", sa.Uuid(), nullable=False),
        sa.Column("phase_17_4_a_approved_by_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_id", sa.Uuid(), nullable=False),
        sa.Column("request_reason", sa.Text(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("review_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closure_qualification_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending_second_approval"),
        sa.Column("qualified_by_id", sa.Uuid(), nullable=True),
        sa.Column("qualified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("qualification_reason", sa.Text(), nullable=True),
        sa.Column("decision_hash", sa.String(64), nullable=True),
        sa.Column("terminal_by_id", sa.Uuid(), nullable=True),
        sa.Column("terminal_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terminal_reason", sa.Text(), nullable=True),
        *_safety_columns(),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["execution_id"], ["physical_disposal_executions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_id"], ["physical_disposal_admission_authorizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_17_4_b_executor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_17_4_a_requested_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_17_4_a_approved_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["qualified_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["terminal_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("execution_id", name="uq_pd_close_execution"),
        sa.UniqueConstraint("organization_id", "closure_qualification_hash", name="uq_pd_close_org_hash"),
        sa.CheckConstraint("status IN ('pending_second_approval','qualified','rejected','expired','invalidated')", name="ck_pd_close_status"),
        sa.CheckConstraint("health_state = 'healthy'", name="ck_pd_close_health"),
        sa.CheckConstraint("document_count > 0", name="ck_pd_close_doc_count"),
        sa.CheckConstraint("total_file_size_bytes >= 0", name="ck_pd_close_total_bytes"),
        sa.CheckConstraint("observed_local_targets_absent = true", name="ck_pd_close_local_absent"),
        sa.CheckConstraint("observed_recovery_bytes_healthy = true", name="ck_pd_close_recovery_healthy"),
        sa.CheckConstraint("observed_document_rows_preserved = true", name="ck_pd_close_rows_preserved"),
        sa.CheckConstraint("observed_storage_keys_preserved = true", name="ck_pd_close_keys_preserved"),
        sa.CheckConstraint("observed_authority_kind = 'recovery_storage'", name="ck_pd_close_authority_kind"),
        sa.CheckConstraint("observed_authority_tenure = 'durable_recovery'", name="ck_pd_close_authority_tenure"),
        sa.CheckConstraint("requested_by_id <> qualified_by_id OR qualified_by_id IS NULL", name="ck_pd_close_four_eyes"),
        sa.CheckConstraint("phase_17_4_b_executor_id <> qualified_by_id OR qualified_by_id IS NULL", name="ck_pd_close_exec_split"),
        sa.CheckConstraint("phase_17_4_a_requested_by_id <> qualified_by_id OR qualified_by_id IS NULL", name="ck_pd_close_ar_split"),
        sa.CheckConstraint("phase_17_4_a_approved_by_id <> qualified_by_id OR qualified_by_id IS NULL", name="ck_pd_close_aa_split"),
        sa.CheckConstraint("review_expires_at > requested_at", name="ck_pd_close_review_window"),
        sa.CheckConstraint(
            "(status = 'pending_second_approval' AND qualified_by_id IS NULL AND qualified_at IS NULL "
            "AND qualification_reason IS NULL AND decision_hash IS NULL AND terminal_by_id IS NULL "
            "AND terminal_at IS NULL AND terminal_reason IS NULL) OR "
            "(status = 'qualified' AND qualified_by_id IS NOT NULL AND qualified_at IS NOT NULL "
            "AND qualification_reason IS NOT NULL AND decision_hash IS NOT NULL AND terminal_by_id IS NULL "
            "AND terminal_at IS NULL AND terminal_reason IS NULL) OR "
            "(status IN ('rejected','expired','invalidated') AND qualified_by_id IS NULL AND qualified_at IS NULL "
            "AND qualification_reason IS NULL AND decision_hash IS NULL AND terminal_by_id IS NOT NULL "
            "AND terminal_at IS NOT NULL AND terminal_reason IS NOT NULL)",
            name="ck_pd_close_lifecycle",
        ),
        *_safety_constraints("pd_close"),
    )
    op.create_index("ix_pd_close_org_claim_status", QUALIFICATION, ["organization_id", "claim_id", "status"])
    op.create_index("ix_pd_close_org_execution", QUALIFICATION, ["organization_id", "execution_id"])
    for name, column in (
        ("ix_pd_close_org", "organization_id"),
        ("ix_pd_close_claim", "claim_id"),
        ("ix_pd_close_exec", "execution_id"),
        ("ix_pd_close_auth", "authorization_id"),
        ("ix_pd_close_b_actor", "phase_17_4_b_executor_id"),
        ("ix_pd_close_a_req", "phase_17_4_a_requested_by_id"),
        ("ix_pd_close_a_app", "phase_17_4_a_approved_by_id"),
        ("ix_pd_close_req", "requested_by_id"),
        ("ix_pd_close_qual", "qualified_by_id"),
        ("ix_pd_close_terminal", "terminal_by_id"),
    ):
        op.create_index(name, QUALIFICATION, [column])

    op.create_table(
        RECEIPT,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("qualification_id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(24), nullable=False),
        sa.Column("status_after", sa.String(32), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("execution_hash", sa.String(64), nullable=False),
        sa.Column("verification_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("closure_qualification_hash", sa.String(64), nullable=False),
        sa.Column("decision_hash", sa.String(64), nullable=True),
        sa.Column("prior_receipt_hash", sa.String(64), nullable=True),
        sa.Column("receipt_hash", sa.String(64), nullable=False),
        *_safety_columns(),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["qualification_id"], [QUALIFICATION + ".id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["execution_id"], ["physical_disposal_executions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("qualification_id", "sequence_number", name="uq_pd_close_receipt_seq"),
        sa.UniqueConstraint("organization_id", "receipt_hash", name="uq_pd_close_receipt_org_hash"),
        sa.CheckConstraint("sequence_number > 0", name="ck_pd_close_receipt_sequence"),
        sa.CheckConstraint("event_type IN ('requested','qualified','rejected','expired','invalidated')", name="ck_pd_close_receipt_event"),
        sa.CheckConstraint(
            "(event_type = 'requested' AND status_after = 'pending_second_approval') OR "
            "(event_type = 'qualified' AND status_after = 'qualified') OR "
            "(event_type = 'rejected' AND status_after = 'rejected') OR "
            "(event_type = 'expired' AND status_after = 'expired') OR "
            "(event_type = 'invalidated' AND status_after = 'invalidated')",
            name="ck_pd_close_receipt_mapping",
        ),
        sa.CheckConstraint("(sequence_number = 1 AND prior_receipt_hash IS NULL) OR (sequence_number > 1 AND prior_receipt_hash IS NOT NULL)", name="ck_pd_close_receipt_chain"),
        *_safety_constraints("pd_close_receipt"),
    )
    op.create_index("ix_pd_close_receipt_qual_seq", RECEIPT, ["qualification_id", "sequence_number"])
    for name, column in (
        ("ix_pd_close_rcpt_org", "organization_id"),
        ("ix_pd_close_rcpt_claim", "claim_id"),
        ("ix_pd_close_rcpt_qual", "qualification_id"),
        ("ix_pd_close_rcpt_exec", "execution_id"),
        ("ix_pd_close_rcpt_actor", "actor_id"),
    ):
        op.create_index(name, RECEIPT, [column])


def downgrade() -> None:
    op.drop_table(RECEIPT)
    op.drop_table(QUALIFICATION)
