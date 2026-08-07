"""financial intelligence and reserve history
Revision ID: 0011_financial_intelligence
Revises: 0010_maintenance_workshop_intelligence
Create Date: 2026-08-07
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision="0011_financial_intelligence"
down_revision="0010_maintenance_workshop_intelligence"
branch_labels=None
depends_on=None

def upgrade():
    op.execute("ALTER TYPE processing_job_type ADD VALUE IF NOT EXISTS 'ai_extract_quotation'")
    op.execute("ALTER TYPE processing_job_type ADD VALUE IF NOT EXISTS 'ai_extract_invoice'")
    cost=postgresql.ENUM('claimed','under_review','potentially_recoverable','potentially_non_recoverable','accepted','rejected','paid',name='cost_review_status',create_type=False)
    ft=postgresql.ENUM('possible_duplicate','invoice_predates_incident','potential_betterment','potential_ordinary_maintenance','quote_scope_difference','total_mismatch',name='financial_flag_type',create_type=False)
    fs=postgresql.ENUM('open','explained','resolved','irrelevant',name='financial_flag_status',create_type=False)
    cost.create(op.get_bind(),checkfirst=True);ft.create(op.get_bind(),checkfirst=True);fs.create(op.get_bind(),checkfirst=True)
    op.create_table('cost_items',sa.Column('id',sa.Uuid(),primary_key=True),sa.Column('organization_id',sa.Uuid(),sa.ForeignKey('organizations.id',ondelete='RESTRICT'),nullable=False),sa.Column('claim_id',sa.Uuid(),sa.ForeignKey('claims.id',ondelete='RESTRICT'),nullable=False),sa.Column('document_id',sa.Uuid(),sa.ForeignKey('documents.id',ondelete='RESTRICT'),nullable=False),sa.Column('ai_run_id',sa.Uuid(),sa.ForeignKey('ai_runs.id',ondelete='RESTRICT'),nullable=False),sa.Column('line_index',sa.Integer(),nullable=False),sa.Column('document_kind',sa.String(20),nullable=False),sa.Column('supplier',sa.String(255)),sa.Column('document_number',sa.String(120)),sa.Column('document_date',sa.Date()),sa.Column('description',sa.Text(),nullable=False),sa.Column('quantity',sa.Numeric(18,4)),sa.Column('unit',sa.String(50)),sa.Column('unit_price',sa.Numeric(18,2)),sa.Column('amount',sa.Numeric(18,2),nullable=False),sa.Column('currency',sa.String(3),nullable=False),sa.Column('category',sa.String(80)),sa.Column('review_status',cost,nullable=False,server_default='under_review'),sa.Column('source_field_prefix',sa.String(220),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),sa.CheckConstraint('amount >= 0',name='ck_cost_items_amount_nonnegative'))
    op.create_index('ix_cost_items_org_claim','cost_items',['organization_id','claim_id'])
    op.create_table('financial_flags',sa.Column('id',sa.Uuid(),primary_key=True),sa.Column('organization_id',sa.Uuid(),sa.ForeignKey('organizations.id',ondelete='RESTRICT'),nullable=False),sa.Column('claim_id',sa.Uuid(),sa.ForeignKey('claims.id',ondelete='RESTRICT'),nullable=False),sa.Column('flag_type',ft,nullable=False),sa.Column('fingerprint',sa.String(180),nullable=False),sa.Column('severity',sa.String(20),nullable=False),sa.Column('title',sa.String(200),nullable=False),sa.Column('explanation',sa.Text(),nullable=False),sa.Column('evidence',sa.JSON()),sa.Column('status',fs,nullable=False,server_default='open'),sa.Column('resolution_note',sa.Text()),sa.Column('resolved_by_id',sa.Uuid(),sa.ForeignKey('users.id',ondelete='SET NULL')),sa.Column('resolved_at',sa.DateTime(timezone=True)),sa.Column('created_at',sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False))
    op.create_index('ix_financial_flags_org_claim','financial_flags',['organization_id','claim_id','status'])
    op.create_table('reserve_history',sa.Column('id',sa.Uuid(),primary_key=True),sa.Column('organization_id',sa.Uuid(),sa.ForeignKey('organizations.id',ondelete='RESTRICT'),nullable=False),sa.Column('claim_id',sa.Uuid(),sa.ForeignKey('claims.id',ondelete='RESTRICT'),nullable=False),sa.Column('amount',sa.Numeric(18,2),nullable=False),sa.Column('currency',sa.String(3),nullable=False),sa.Column('reason',sa.Text(),nullable=False),sa.Column('created_by_id',sa.Uuid(),sa.ForeignKey('users.id',ondelete='SET NULL')),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.CheckConstraint('amount >= 0',name='ck_reserve_history_amount_nonnegative'))
    op.create_index('ix_reserve_history_org_claim_created','reserve_history',['organization_id','claim_id','created_at'])

def downgrade():
    op.drop_table('reserve_history');op.drop_table('financial_flags');op.drop_table('cost_items')
    op.execute('DROP TYPE financial_flag_status');op.execute('DROP TYPE financial_flag_type');op.execute('DROP TYPE cost_review_status')
    op.execute("DELETE FROM document_processing_jobs WHERE job_type IN ('ai_extract_quotation','ai_extract_invoice')")
    op.execute("ALTER TABLE document_processing_jobs ALTER COLUMN job_type DROP DEFAULT")
    op.execute("ALTER TABLE document_processing_jobs ALTER COLUMN job_type TYPE VARCHAR(50) USING job_type::text")
    op.execute("DROP TYPE processing_job_type")
    op.execute("CREATE TYPE processing_job_type AS ENUM ('extract_text','ai_extract_ce_report','ai_extract_engine_log','ai_extract_running_hours','ai_extract_pms_history','ai_extract_workshop_report')")
    op.execute("ALTER TABLE document_processing_jobs ALTER COLUMN job_type TYPE processing_job_type USING job_type::processing_job_type")
    op.execute("ALTER TABLE document_processing_jobs ALTER COLUMN job_type SET DEFAULT 'extract_text'")
