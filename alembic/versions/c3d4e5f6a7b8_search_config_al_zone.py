"""search_config al-zone-felder

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-06-04
"""
from alembic import op
import sqlalchemy as sa

revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("search_config", sa.Column("al_zone_status", sa.String(length=40), nullable=True))
    op.add_column("search_config", sa.Column("al_zone_label", sa.String(length=200), nullable=True))


def downgrade() -> None:
    op.drop_column("search_config", "al_zone_label")
    op.drop_column("search_config", "al_zone_status")
