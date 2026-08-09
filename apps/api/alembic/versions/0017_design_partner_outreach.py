"""design partner outreach system

Revision ID: 0017_design_partner_outreach
Revises: 0016_commercial_validation
"""
from alembic import op
import sqlalchemy as sa

revision = "0017_design_partner_outreach"
down_revision = "0016_commercial_validation"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("design_partner_accounts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False), sa.Column("account_type", sa.String(40), nullable=False),
        sa.Column("country", sa.String(100)), sa.Column("region", sa.String(100)), sa.Column("website", sa.String(500)),
        sa.Column("stage", sa.String(30), nullable=False, server_default="prospect"), sa.Column("source", sa.String(100)), sa.Column("notes", sa.Text()),
        sa.Column("machinery_claim_volume_score", sa.Integer(), nullable=False, server_default="0"), sa.Column("pain_intensity_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("buyer_access_score", sa.Integer(), nullable=False, server_default="0"), sa.Column("data_availability_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("security_fit_score", sa.Integer(), nullable=False, server_default="0"), sa.Column("pilot_willingness_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("qualification_score", sa.Integer(), nullable=False, server_default="0"), sa.Column("qualification_rationale", sa.Text()),
        sa.Column("next_step", sa.Text()), sa.Column("next_step_due_date", sa.Date()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id","name",name="uq_design_partner_org_name"),
        sa.CheckConstraint("account_type IN ('marine_insurer','ship_manager','p_and_i_correspondent','average_adjuster','broker','other')",name="ck_design_partner_account_type"),
        sa.CheckConstraint("stage IN ('prospect','contacted','discovery','demo','pilot_qualified','pilot_proposed','pilot_active','paid_pilot','customer','no_fit')",name="ck_design_partner_stage"),
        sa.CheckConstraint("machinery_claim_volume_score BETWEEN 0 AND 5",name="ck_design_partner_volume_score"), sa.CheckConstraint("pain_intensity_score BETWEEN 0 AND 5",name="ck_design_partner_pain_score"), sa.CheckConstraint("buyer_access_score BETWEEN 0 AND 5",name="ck_design_partner_buyer_score"), sa.CheckConstraint("data_availability_score BETWEEN 0 AND 5",name="ck_design_partner_data_score"), sa.CheckConstraint("security_fit_score BETWEEN 0 AND 5",name="ck_design_partner_security_score"), sa.CheckConstraint("pilot_willingness_score BETWEEN 0 AND 5",name="ck_design_partner_willingness_score"), sa.CheckConstraint("qualification_score BETWEEN 0 AND 100",name="ck_design_partner_qualification_score"))
    op.create_index("ix_design_partner_org_score","design_partner_accounts",["organization_id","qualification_score"]); op.create_index("ix_design_partner_org_stage","design_partner_accounts",["organization_id","stage"])
    op.create_table("design_partner_contacts",
        sa.Column("id",sa.Uuid(),primary_key=True), sa.Column("organization_id",sa.Uuid(),sa.ForeignKey("organizations.id",ondelete="RESTRICT"),nullable=False), sa.Column("account_id",sa.Uuid(),sa.ForeignKey("design_partner_accounts.id",ondelete="CASCADE"),nullable=False), sa.Column("name",sa.String(200),nullable=False), sa.Column("title",sa.String(200)), sa.Column("email",sa.String(320)), sa.Column("linkedin_url",sa.String(500)), sa.Column("role_type",sa.String(30),nullable=False,server_default="unknown"), sa.Column("notes",sa.Text()), sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()), sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()), sa.CheckConstraint("role_type IN ('buyer','champion','influencer','security','procurement','user','unknown')",name="ck_design_partner_contact_role"))
    op.create_table("outreach_touches",
        sa.Column("id",sa.Uuid(),primary_key=True), sa.Column("organization_id",sa.Uuid(),sa.ForeignKey("organizations.id",ondelete="RESTRICT"),nullable=False), sa.Column("account_id",sa.Uuid(),sa.ForeignKey("design_partner_accounts.id",ondelete="CASCADE"),nullable=False), sa.Column("contact_id",sa.Uuid(),sa.ForeignKey("design_partner_contacts.id",ondelete="SET NULL")), sa.Column("created_by_id",sa.Uuid(),sa.ForeignKey("users.id",ondelete="SET NULL")), sa.Column("channel",sa.String(30),nullable=False), sa.Column("status",sa.String(30),nullable=False,server_default="planned"), sa.Column("subject",sa.String(500)), sa.Column("message_summary",sa.Text()), sa.Column("occurred_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()), sa.Column("next_step",sa.Text()), sa.Column("next_step_due_date",sa.Date()), sa.CheckConstraint("channel IN ('email','linkedin','warm_intro','call','meeting','other')",name="ck_outreach_touch_channel"), sa.CheckConstraint("status IN ('planned','sent','replied','no_response','meeting_booked','declined')",name="ck_outreach_touch_status"))
    op.create_table("paid_pilot_offers",
        sa.Column("id",sa.Uuid(),primary_key=True), sa.Column("organization_id",sa.Uuid(),sa.ForeignKey("organizations.id",ondelete="RESTRICT"),nullable=False), sa.Column("account_id",sa.Uuid(),sa.ForeignKey("design_partner_accounts.id",ondelete="CASCADE"),nullable=False), sa.Column("created_by_id",sa.Uuid(),sa.ForeignKey("users.id",ondelete="SET NULL")), sa.Column("version",sa.Integer(),nullable=False,server_default="1"), sa.Column("status",sa.String(20),nullable=False,server_default="draft"), sa.Column("duration_days",sa.Integer(),nullable=False,server_default="30"), sa.Column("fee",sa.Numeric(14,2)), sa.Column("currency",sa.String(3),nullable=False,server_default="USD"), sa.Column("scope",sa.Text(),nullable=False), sa.Column("deliverables",sa.JSON()), sa.Column("customer_responsibilities",sa.JSON()), sa.Column("success_criteria",sa.JSON()), sa.Column("exclusions",sa.JSON()), sa.Column("notes",sa.Text()), sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()), sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()), sa.UniqueConstraint("organization_id","account_id","version",name="uq_paid_pilot_offer_version"), sa.CheckConstraint("status IN ('draft','shared','accepted','rejected','expired')",name="ck_paid_pilot_offer_status"), sa.CheckConstraint("fee IS NULL OR fee >= 0",name="ck_paid_pilot_offer_fee_nonnegative"), sa.CheckConstraint("duration_days >= 1",name="ck_paid_pilot_offer_duration_positive"))


def downgrade():
    op.drop_table("paid_pilot_offers"); op.drop_table("outreach_touches"); op.drop_table("design_partner_contacts"); op.drop_index("ix_design_partner_org_stage",table_name="design_partner_accounts"); op.drop_index("ix_design_partner_org_score",table_name="design_partner_accounts"); op.drop_table("design_partner_accounts")
