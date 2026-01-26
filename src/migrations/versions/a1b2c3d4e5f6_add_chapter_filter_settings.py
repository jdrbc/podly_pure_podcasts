"""add chapter filter settings

Revision ID: a1b2c3d4e5f6
Revises: 2e25a15d11de
Create Date: 2026-01-07 12:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "2e25a15d11de"
branch_labels = None
depends_on = None


def table_exists(table_name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=:name"
        ),
        {"name": table_name},
    )
    return result.fetchone() is not None


def column_exists(table_name: str, column_name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(sa.text(f"PRAGMA table_info({table_name})"))
    columns = [row[1] for row in result.fetchall()]
    return column_name in columns


def upgrade():
    # Create chapter_filter_settings table if it doesn't exist
    if not table_exists("chapter_filter_settings"):
        op.create_table(
            "chapter_filter_settings",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column(
                "default_filter_strings",
                sa.Text(),
                nullable=False,
                server_default="sponsor,advertisement,ad break,promo,brought to you by",
            ),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )

    # Add columns to feed table if they don't exist
    if not column_exists("feed", "ad_detection_strategy"):
        op.add_column(
            "feed",
            sa.Column(
                "ad_detection_strategy",
                sa.String(20),
                nullable=False,
                server_default="llm",
            ),
        )
    if not column_exists("feed", "chapter_filter_strings"):
        op.add_column(
            "feed",
            sa.Column("chapter_filter_strings", sa.Text(), nullable=True),
        )

    # Add chapter_data column to post table if it doesn't exist
    if not column_exists("post", "chapter_data"):
        op.add_column(
            "post",
            sa.Column("chapter_data", sa.Text(), nullable=True),
        )


def downgrade():
    op.drop_column("post", "chapter_data")
    op.drop_column("feed", "chapter_filter_strings")
    op.drop_column("feed", "ad_detection_strategy")
    op.drop_table("chapter_filter_settings")
