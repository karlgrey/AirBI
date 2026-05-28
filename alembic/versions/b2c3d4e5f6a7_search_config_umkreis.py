"""search_config umkreis-felder

Revision ID: b2c3d4e5f6a7
Revises: e15724acc87a
Create Date: 2026-05-28
"""
from alembic import op
import sqlalchemy as sa

revision = "b2c3d4e5f6a7"
down_revision = "e15724acc87a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("search_config", sa.Column("center_lat", sa.Float(), nullable=True))
    op.add_column("search_config", sa.Column("center_lng", sa.Float(), nullable=True))
    op.add_column(
        "search_config",
        sa.Column("center_label", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "search_config",
        sa.Column(
            "band_radii_km",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[1, 2, 3, 5, 10]'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("search_config", "band_radii_km")
    op.drop_column("search_config", "center_label")
    op.drop_column("search_config", "center_lng")
    op.drop_column("search_config", "center_lat")
