"""initial assessment builder
Revision ID: 0012_initial_assessment_builder
Revises: 0011_financial_intelligence
Create Date: 2026-08-07
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision="0012_initial_assessment_builder"
down_revision="0011_financial_intelligence"
branch_labels=None
depends_on=None


def upgrade():
    ast=postgresql.ENUM('draft','under_review','approved',name='initial_assessment_status',create_type=False)
    sst=postgresql.ENUM('pending','approved','edited',name='assessment_section_status',create_type=False)
    ast.create(op.get_bind(),checkfirst=True);sst.create(op.get_bind(),checkfirst=True)
    op.create_table('initial_assessments',
        sa.Column('id',sa.Uuid(),primary_key=True),
        sa.Column('organization_id',sa.Uuid(),sa.ForeignKey('organizations.id',ondelete='RESTRICT'),nullable=False),
        sa.Column('claim_id',sa.Uuid(),sa.ForeignKey('claims.id',ondelete='RESTRICT'),nullable=False),
        sa.Column('version',sa.Integer(),nullable=False),
        sa.Column('status',ast,nullable=False,server_default='draft'),
        sa.Column('readiness_score',sa.Integer(),nullable=False),
        sa.Column('readiness_state',sa.String(30),nullable=False),
        sa.Column('blocking_items',sa.JSON(),nullable=False),
        sa.Column('is_preliminary',sa.Boolean(),nullable=False,server_default=sa.false()),
        sa.Column('generation_override_reason',sa.Text()),
        sa.Column('generated_by_id',sa.Uuid(),sa.ForeignKey('users.id',ondelete='SET NULL')),
        sa.Column('approved_by_id',sa.Uuid(),sa.ForeignKey('users.id',ondelete='SET NULL')),
        sa.Column('approved_at',sa.DateTime(timezone=True)),
        sa.Column('created_at',sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),
        sa.Column('updated_at',sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),
        sa.UniqueConstraint('organization_id','claim_id','version',name='uq_initial_assessment_version'))
    op.create_index('ix_initial_assessment_org_claim','initial_assessments',['organization_id','claim_id','created_at'])
    op.create_table('assessment_sections',
        sa.Column('id',sa.Uuid(),primary_key=True),
        sa.Column('organization_id',sa.Uuid(),sa.ForeignKey('organizations.id',ondelete='RESTRICT'),nullable=False),
        sa.Column('claim_id',sa.Uuid(),sa.ForeignKey('claims.id',ondelete='RESTRICT'),nullable=False),
        sa.Column('assessment_id',sa.Uuid(),sa.ForeignKey('initial_assessments.id',ondelete='CASCADE'),nullable=False),
        sa.Column('section_key',sa.String(80),nullable=False),
        sa.Column('title',sa.String(180),nullable=False),
        sa.Column('sort_order',sa.Integer(),nullable=False),
        sa.Column('draft_text',sa.Text(),nullable=False),
        sa.Column('approved_text',sa.Text()),
        sa.Column('status',sst,nullable=False,server_default='pending'),
        sa.Column('source_manifest',sa.JSON(),nullable=False),
        sa.Column('reviewed_by_id',sa.Uuid(),sa.ForeignKey('users.id',ondelete='SET NULL')),
        sa.Column('reviewed_at',sa.DateTime(timezone=True)),
        sa.Column('created_at',sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),
        sa.Column('updated_at',sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),
        sa.UniqueConstraint('assessment_id','section_key',name='uq_assessment_section_key'))
    op.create_index('ix_assessment_sections_assessment_order','assessment_sections',['assessment_id','sort_order'])


def downgrade():
    op.drop_table('assessment_sections');op.drop_table('initial_assessments')
    op.execute('DROP TYPE assessment_section_status');op.execute('DROP TYPE initial_assessment_status')
