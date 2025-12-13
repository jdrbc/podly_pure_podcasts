"""add start_from_step to processing_job

Revision ID: 860b8569a410
Revises: eb51923af483
Create Date: 2025-12-11 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = "860b8569a410"
down_revision = "eb51923af483"
branch_labels = None
depends_on = None


def _column_exists(table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table."""
    connection = op.get_bind()
    inspector = inspect(connection)
    columns = [col["name"] for col in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade():
    # Add start_from_step column to processing_job table if it doesn't exist
    if not _column_exists("processing_job", "start_from_step"):
        with op.batch_alter_table("processing_job", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column("start_from_step", sa.Integer(), nullable=True, server_default="1")
            )


def downgrade():
    # Remove start_from_step column from processing_job table
    with op.batch_alter_table("processing_job", schema=None) as batch_op:
        batch_op.drop_column("start_from_step")
