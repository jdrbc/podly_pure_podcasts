"""add counters reset timestamp to jobs_manager_run

Revision ID: 3c7f5f7640e4
Revises: c0f8893ce927
Create Date: 2026-12-01 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "3c7f5f7640e4"
down_revision = "c0f8893ce927"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    existing_tables = set(inspector.get_table_names())
    if "jobs_manager_run" not in existing_tables:
        return

    columns = {col["name"] for col in inspector.get_columns("jobs_manager_run")}
    if "counters_reset_at" not in columns:
        with op.batch_alter_table("jobs_manager_run", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column("counters_reset_at", sa.DateTime(), nullable=True)
            )

        op.execute(
            sa.text(
                "UPDATE jobs_manager_run "
                "SET counters_reset_at = COALESCE(started_at, created_at, CURRENT_TIMESTAMP) "
                "WHERE counters_reset_at IS NULL"
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    existing_tables = set(inspector.get_table_names())
    if "jobs_manager_run" not in existing_tables:
        return

    columns = {col["name"] for col in inspector.get_columns("jobs_manager_run")}
    if "counters_reset_at" in columns:
        with op.batch_alter_table("jobs_manager_run", schema=None) as batch_op:
            batch_op.drop_column("counters_reset_at")
