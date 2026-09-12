"""Add Phase AN durable authoritative recovery evidence-storage ratification execution.

Revision ID: 0153_authoritative_storage_ownership_ratification_execution
Revises: 0152_authoritative_storage_ownership_ratification_authorization
"""

from alembic import op
import sqlalchemy as sa

revision = "0153_authoritative_storage_ownership_ratification_execution"
down_revision = "0152_authoritative_storage_ownership_ratification_authorization"
branch_labels = None
depends_on = None

RATIFICATION = "evidence_recovery_storage_ratifications"
RECEIPT = "evidence_recovery_storage_ratification_receipts"
LEASE = "evidence_recovery_auth_storage_leases"
ROUTE = "evidence_recovery_auth_storage_routes"


def _execution_safety_columns() -> list[sa.Column]:
    return [
        sa.Column("local_evidence_preserved", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("storage_write_performed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("route_mutation_performed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("ownership_mutation_performed", sa.Boolean(), nullable=False, server_default=sa.true()),
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


def _execution_safety_constraints(prefix: str) -> list[sa.CheckConstraint]:
    return [
        sa.CheckConstraint("local_evidence_preserved = true", name=f"ck_{prefix}_local_preserved"),
        sa.CheckConstraint("storage_write_performed = false", name=f"ck_{prefix}_no_write"),
        sa.CheckConstraint("route_mutation_performed = true", name=f"ck_{prefix}_route_mut"),
        sa.CheckConstraint("ownership_mutation_performed = true", name=f"ck_{prefix}_owner_mut"),
        sa.CheckConstraint("read_path_switched = false", name=f"ck_{prefix}_no_read"),
        sa.CheckConstraint("write_path_switched = false", name=f"ck_{prefix}_no_write_path"),
        sa.CheckConstraint("document_storage_key_mutated = false", name=f"ck_{prefix}_no_key"),
        sa.CheckConstraint("destructive_action_performed = false", name=f"ck_{prefix}_no_dest"),
        sa.CheckConstraint("physical_disposal_authorized = false", name=f"ck_{prefix}_no_disposal"),
        sa.CheckConstraint("s3_put_performed = false", name=f"ck_{prefix}_no_put"),
        sa.CheckConstraint("s3_copy_performed = false", name=f"ck_{prefix}_no_copy"),
        sa.CheckConstraint("s3_delete_performed = false", name=f"ck_{prefix}_no_s3del"),
        sa.CheckConstraint("local_overwrite_performed = false", name=f"ck_{prefix}_no_overwrite"),
        sa.CheckConstraint("local_move_performed = false", name=f"ck_{prefix}_no_move"),
        sa.CheckConstraint("local_delete_performed = false", name=f"ck_{prefix}_no_localdel"),
    ]


def upgrade() -> None:
    op.create_table(
        RATIFICATION,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_approval_receipt_id", sa.Uuid(), nullable=False),
        sa.Column("phase_al_health_qualification_id", sa.Uuid(), nullable=False),
        sa.Column("authoritative_storage_ownership_lease_id", sa.Uuid(), nullable=False),
        sa.Column("phase_aj_authorization_id", sa.Uuid(), nullable=False),
        sa.Column("phase_ai_health_qualification_id", sa.Uuid(), nullable=False),
        sa.Column("durable_write_ownership_lease_id", sa.Uuid(), nullable=False),
        sa.Column("replica_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_hash", sa.String(64), nullable=False),
        sa.Column("authorization_approval_receipt_hash", sa.String(64), nullable=False),
        sa.Column("phase_al_health_qualification_hash", sa.String(64), nullable=False),
        sa.Column("phase_al_health_receipt_hash", sa.String(64), nullable=False),
        sa.Column("phase_al_integrity_proof_hash", sa.String(64), nullable=False),
        sa.Column("authoritative_storage_ownership_lease_hash", sa.String(64), nullable=False),
        sa.Column("phase_aj_authorization_hash", sa.String(64), nullable=False),
        sa.Column("phase_ai_health_qualification_hash", sa.String(64), nullable=False),
        sa.Column("durable_write_ownership_lease_hash", sa.String(64), nullable=False),
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
        sa.Column("authority_route_version_before_ratification", sa.Integer(), nullable=False),
        sa.Column("authority_route_version_after_ratification", sa.Integer(), nullable=False),
        sa.Column("read_route_version_at_ratification", sa.Integer(), nullable=False),
        sa.Column("experimental_write_route_version_at_ratification", sa.Integer(), nullable=False),
        sa.Column("durable_route_version_at_ratification", sa.Integer(), nullable=False),
        sa.Column("execution_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("ratification_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="ratified"),
        sa.Column("authority_kind", sa.String(40), nullable=False, server_default="recovery_storage"),
        sa.Column("authority_tenure", sa.String(40), nullable=False, server_default="durable_recovery"),
        sa.Column("ratification_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("durable_authority_created", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("local_authoritative", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("recovery_authoritative", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("authoritative_storage_changed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("executed_by_id", sa.Uuid(), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("execution_reason", sa.Text(), nullable=False),
        *_execution_safety_columns(),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_id"], ["evidence_recovery_storage_ratification_auths.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_approval_receipt_id"], ["evidence_recovery_storage_ratification_auth_receipts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_al_health_qualification_id"], ["evidence_recovery_auth_storage_health_qualifications.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authoritative_storage_ownership_lease_id"], ["evidence_recovery_auth_storage_leases.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_aj_authorization_id"], ["evidence_recovery_auth_storage_authorizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_ai_health_qualification_id"], ["evidence_recovery_durable_write_ownership_health_qualifications.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["durable_write_ownership_lease_id"], ["evidence_recovery_durable_write_ownership_leases.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["replica_id"], ["evidence_recovery_replicas.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["executed_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("authorization_id", name="uq_asr_exec_auth"),
        sa.UniqueConstraint("organization_id", "ratification_hash", name="uq_asr_exec_org_hash"),
        sa.CheckConstraint("status = 'ratified'", name="ck_asr_exec_status"),
        sa.CheckConstraint("authority_kind = 'recovery_storage'", name="ck_asr_exec_kind"),
        sa.CheckConstraint("authority_tenure = 'durable_recovery'", name="ck_asr_exec_tenure"),
        sa.CheckConstraint("ratification_active = true", name="ck_asr_exec_active"),
        sa.CheckConstraint("durable_authority_created = true", name="ck_asr_exec_durable"),
        sa.CheckConstraint("local_authoritative = false", name="ck_asr_exec_not_local"),
        sa.CheckConstraint("recovery_authoritative = true", name="ck_asr_exec_recovery"),
        sa.CheckConstraint("authoritative_storage_changed = true", name="ck_asr_exec_changed"),
        sa.CheckConstraint("source_file_size_bytes >= 0", name="ck_asr_exec_size"),
        sa.CheckConstraint("observed_local_size_bytes = source_file_size_bytes", name="ck_asr_exec_local_size"),
        sa.CheckConstraint("observed_recovery_size_bytes = source_file_size_bytes", name="ck_asr_exec_recovery_size"),
        sa.CheckConstraint("observed_local_hash = source_file_hash", name="ck_asr_exec_local_hash"),
        sa.CheckConstraint("observed_recovery_hash = source_file_hash", name="ck_asr_exec_recovery_hash"),
        sa.CheckConstraint("authority_route_version_before_ratification >= 1", name="ck_asr_exec_before_ver"),
        sa.CheckConstraint("authority_route_version_after_ratification = authority_route_version_before_ratification + 1", name="ck_asr_exec_after_ver"),
        *_execution_safety_constraints("asr_exec"),
    )
    op.create_index("ix_asr_exec_org_claim", RATIFICATION, ["organization_id", "claim_id"])
    op.create_index("ix_asr_exec_org_doc", RATIFICATION, ["organization_id", "document_id"])

    op.create_table(
        RECEIPT,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("ratification_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_id", sa.Uuid(), nullable=False),
        sa.Column("phase", sa.String(20), nullable=False, server_default="ratified"),
        sa.Column("from_authority_kind", sa.String(40), nullable=False, server_default="recovery_storage"),
        sa.Column("to_authority_kind", sa.String(40), nullable=False, server_default="recovery_storage"),
        sa.Column("from_authority_tenure", sa.String(40), nullable=False, server_default="bounded_recovery"),
        sa.Column("to_authority_tenure", sa.String(40), nullable=False, server_default="durable_recovery"),
        sa.Column("route_version", sa.Integer(), nullable=False),
        sa.Column("authorization_hash", sa.String(64), nullable=False),
        sa.Column("authorization_approval_receipt_hash", sa.String(64), nullable=False),
        sa.Column("phase_al_health_qualification_hash", sa.String(64), nullable=False),
        sa.Column("source_file_hash", sa.String(64), nullable=False),
        sa.Column("source_file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("execution_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("ratification_hash", sa.String(64), nullable=False),
        sa.Column("receipt_hash", sa.String(64), nullable=False),
        sa.Column("ratification_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("durable_authority_created", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("local_authoritative", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("recovery_authoritative", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("authoritative_storage_changed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("transitioned_at", sa.DateTime(timezone=True), nullable=False),
        *_execution_safety_columns(),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["ratification_id"], [f"{RATIFICATION}.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorization_id"], ["evidence_recovery_storage_ratification_auths.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "receipt_hash", name="uq_asr_exec_rec_org_hash"),
        sa.CheckConstraint("phase = 'ratified'", name="ck_asr_exec_rec_phase"),
        sa.CheckConstraint("from_authority_kind = 'recovery_storage'", name="ck_asr_exec_rec_from_kind"),
        sa.CheckConstraint("to_authority_kind = 'recovery_storage'", name="ck_asr_exec_rec_to_kind"),
        sa.CheckConstraint("from_authority_tenure = 'bounded_recovery'", name="ck_asr_exec_rec_from_tenure"),
        sa.CheckConstraint("to_authority_tenure = 'durable_recovery'", name="ck_asr_exec_rec_to_tenure"),
        sa.CheckConstraint("route_version >= 1", name="ck_asr_exec_rec_ver"),
        sa.CheckConstraint("ratification_active = true", name="ck_asr_exec_rec_active"),
        sa.CheckConstraint("durable_authority_created = true", name="ck_asr_exec_rec_durable"),
        sa.CheckConstraint("local_authoritative = false", name="ck_asr_exec_rec_not_local"),
        sa.CheckConstraint("recovery_authoritative = true", name="ck_asr_exec_rec_recovery"),
        sa.CheckConstraint("authoritative_storage_changed = true", name="ck_asr_exec_rec_changed"),
        *_execution_safety_constraints("asr_exec_rec"),
    )
    op.create_index("ix_asr_exec_rec_time", RECEIPT, ["ratification_id", "transitioned_at"])

    op.drop_constraint("ck_aso_exec_lease_status", LEASE, type_="check")
    op.drop_constraint("ck_aso_exec_lease_state", LEASE, type_="check")
    op.create_check_constraint(
        "ck_aso_exec_lease_status",
        LEASE,
        "status IN ('active','ratified','rolled_back','expired','invalidated')",
    )
    op.create_check_constraint(
        "ck_aso_exec_lease_state",
        LEASE,
        "((status = 'active' AND ownership_transition_active = true AND local_authoritative = false AND recovery_authoritative = true AND authoritative_storage_changed = true) "
        "OR (status = 'ratified' AND ownership_transition_active = false AND local_authoritative = false AND recovery_authoritative = true AND authoritative_storage_changed = true) "
        "OR (status IN ('rolled_back','expired','invalidated') AND ownership_transition_active = false AND local_authoritative = true AND recovery_authoritative = false AND authoritative_storage_changed = false))",
    )

    op.drop_constraint("ck_aso_exec_route_state", ROUTE, type_="check")
    op.add_column(ROUTE, sa.Column("authority_tenure", sa.String(40), nullable=True))
    op.add_column(ROUTE, sa.Column("durable_ratification_id", sa.Uuid(), nullable=True))
    op.execute(
        sa.text(
            "UPDATE evidence_recovery_auth_storage_routes "
            "SET authority_tenure = CASE WHEN authority_kind = 'recovery_storage' "
            "THEN 'bounded_recovery' ELSE 'local' END"
        )
    )
    op.alter_column(ROUTE, "authority_tenure", nullable=False, server_default="local")
    op.create_foreign_key(
        "fk_aso_exec_route_durable_ratification",
        ROUTE,
        RATIFICATION,
        ["durable_ratification_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_aso_exec_route_durable_ratification_id", ROUTE, ["durable_ratification_id"])
    op.create_check_constraint(
        "ck_aso_exec_route_tenure",
        ROUTE,
        "authority_tenure IN ('local','bounded_recovery','durable_recovery')",
    )
    op.create_check_constraint(
        "ck_aso_exec_route_state",
        ROUTE,
        "((authority_kind = 'local_evidence' AND authority_tenure = 'local' AND active_authority_lease_id IS NULL AND durable_ratification_id IS NULL AND local_authoritative = true AND recovery_authoritative = false AND authoritative_storage_changed = false) "
        "OR (authority_kind = 'recovery_storage' AND authority_tenure = 'bounded_recovery' AND active_authority_lease_id IS NOT NULL AND durable_ratification_id IS NULL AND local_authoritative = false AND recovery_authoritative = true AND authoritative_storage_changed = true) "
        "OR (authority_kind = 'recovery_storage' AND authority_tenure = 'durable_recovery' AND active_authority_lease_id IS NULL AND durable_ratification_id IS NOT NULL AND local_authoritative = false AND recovery_authoritative = true AND authoritative_storage_changed = true))",
    )


def downgrade() -> None:
    op.drop_constraint("ck_aso_exec_route_state", ROUTE, type_="check")
    op.drop_constraint("ck_aso_exec_route_tenure", ROUTE, type_="check")
    op.drop_index("ix_aso_exec_route_durable_ratification_id", table_name=ROUTE)
    op.drop_constraint("fk_aso_exec_route_durable_ratification", ROUTE, type_="foreignkey")
    op.drop_column(ROUTE, "durable_ratification_id")
    op.drop_column(ROUTE, "authority_tenure")
    op.create_check_constraint(
        "ck_aso_exec_route_state",
        ROUTE,
        "((authority_kind = 'local_evidence' AND active_authority_lease_id IS NULL AND local_authoritative = true AND recovery_authoritative = false AND authoritative_storage_changed = false) "
        "OR (authority_kind = 'recovery_storage' AND active_authority_lease_id IS NOT NULL AND local_authoritative = false AND recovery_authoritative = true AND authoritative_storage_changed = true))",
    )

    op.drop_constraint("ck_aso_exec_lease_state", LEASE, type_="check")
    op.drop_constraint("ck_aso_exec_lease_status", LEASE, type_="check")
    op.create_check_constraint(
        "ck_aso_exec_lease_status",
        LEASE,
        "status IN ('active','rolled_back','expired','invalidated')",
    )
    op.create_check_constraint(
        "ck_aso_exec_lease_state",
        LEASE,
        "((status = 'active' AND ownership_transition_active = true AND local_authoritative = false AND recovery_authoritative = true AND authoritative_storage_changed = true) "
        "OR (status <> 'active' AND ownership_transition_active = false AND local_authoritative = true AND recovery_authoritative = false AND authoritative_storage_changed = false))",
    )

    op.drop_index("ix_asr_exec_rec_time", table_name=RECEIPT)
    op.drop_table(RECEIPT)
    op.drop_index("ix_asr_exec_org_doc", table_name=RATIFICATION)
    op.drop_index("ix_asr_exec_org_claim", table_name=RATIFICATION)
    op.drop_table(RATIFICATION)
