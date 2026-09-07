"""add governed external identity provider registry and account bindings

Revision ID: 0088_external_identity_registry_binding
Revises: 0087_auth_session_assurance
"""

from alembic import op
import sqlalchemy as sa

revision = "0088_external_identity_registry_binding"
down_revision = "0087_auth_session_assurance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "enterprise_identity_providers",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("provider_key", sa.String(length=80), nullable=False),
        sa.Column("display_name", sa.String(length=160), nullable=False),
        sa.Column("protocol", sa.String(length=20), nullable=False),
        sa.Column("issuer_identifier", sa.String(length=500), nullable=False),
        sa.Column(
            "is_enabled",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "provider_key",
            name="uq_enterprise_identity_providers_org_key",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "protocol",
            "issuer_identifier",
            name="uq_enterprise_identity_providers_org_protocol_issuer",
        ),
    )
    op.create_index(
        op.f("ix_enterprise_identity_providers_organization_id"),
        "enterprise_identity_providers",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        "ix_enterprise_identity_providers_org_enabled",
        "enterprise_identity_providers",
        ["organization_id", "is_enabled"],
        unique=False,
    )

    op.create_table(
        "external_identity_bindings",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("subject_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by_id", sa.Uuid(), nullable=True),
        sa.Column("revocation_reason", sa.String(length=200), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["enterprise_identity_providers.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["revoked_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider_id",
            "subject_fingerprint",
            name="uq_external_identity_bindings_provider_subject",
        ),
    )
    op.create_index(
        op.f("ix_external_identity_bindings_organization_id"),
        "external_identity_bindings",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_external_identity_bindings_provider_id"),
        "external_identity_bindings",
        ["provider_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_external_identity_bindings_user_id"),
        "external_identity_bindings",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_external_identity_bindings_revoked_by_id"),
        "external_identity_bindings",
        ["revoked_by_id"],
        unique=False,
    )
    op.create_index(
        "uq_external_identity_bindings_provider_user_active",
        "external_identity_bindings",
        ["provider_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
        sqlite_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index(
        "ix_external_identity_bindings_org_lifecycle",
        "external_identity_bindings",
        ["organization_id", "revoked_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_external_identity_bindings_org_lifecycle",
        table_name="external_identity_bindings",
    )
    op.drop_index(
        "uq_external_identity_bindings_provider_user_active",
        table_name="external_identity_bindings",
    )
    op.drop_index(
        op.f("ix_external_identity_bindings_revoked_by_id"),
        table_name="external_identity_bindings",
    )
    op.drop_index(
        op.f("ix_external_identity_bindings_user_id"),
        table_name="external_identity_bindings",
    )
    op.drop_index(
        op.f("ix_external_identity_bindings_provider_id"),
        table_name="external_identity_bindings",
    )
    op.drop_index(
        op.f("ix_external_identity_bindings_organization_id"),
        table_name="external_identity_bindings",
    )
    op.drop_table("external_identity_bindings")

    op.drop_index(
        "ix_enterprise_identity_providers_org_enabled",
        table_name="enterprise_identity_providers",
    )
    op.drop_index(
        op.f("ix_enterprise_identity_providers_organization_id"),
        table_name="enterprise_identity_providers",
    )
    op.drop_table("enterprise_identity_providers")
