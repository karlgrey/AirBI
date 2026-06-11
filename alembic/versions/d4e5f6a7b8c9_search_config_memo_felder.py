"""search_config memo felder (home_radius_km, comparison_markets)

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-06-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('search_config', sa.Column('home_radius_km', sa.Float(), nullable=True))
    op.add_column('search_config', sa.Column('comparison_markets', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('search_config', 'comparison_markets')
    op.drop_column('search_config', 'home_radius_km')
