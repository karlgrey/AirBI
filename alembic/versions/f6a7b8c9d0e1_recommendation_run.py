"""recommendation_run (Empfehlungs-Changelog + Hysterese, SmartTasks #151)

Revision ID: f6a7b8c9d0e1
Revises: d4e5f6a7b8c9
Create Date: 2026-08-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'recommendation_run',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('search_config_id', sa.Integer(), sa.ForeignKey('search_config.id'), nullable=False),
        sa.Column('crawl_run_id', sa.Integer(), sa.ForeignKey('crawl_run.id'), nullable=False),
        sa.Column('raw_size_class', sa.String(length=20), nullable=False),
        sa.Column('raw_luxury_class', sa.String(length=20), nullable=False),
        sa.Column('raw_score', sa.Float(), nullable=True),
        sa.Column('raw_multiplier', sa.Float(), nullable=True),
        sa.Column('used_velocity', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('displayed_size_class', sa.String(length=20), nullable=False),
        sa.Column('displayed_luxury_class', sa.String(length=20), nullable=False),
        sa.Column('confidence', sa.String(length=40), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint('search_config_id', 'crawl_run_id', name='uq_recommendation_run_config_run'),
    )


def downgrade() -> None:
    op.drop_table('recommendation_run')
