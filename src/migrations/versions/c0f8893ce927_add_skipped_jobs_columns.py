"""add skipped jobs counters

Revision ID: c0f8893ce927
Revises: 999b921ffc58
Create Date: 2026-11-27 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "c0f8893ce927"
down_revision = "999b921ffc58"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    existing_tables = set(inspector.get_table_names())
    if "jobs_manager_run" not in existing_tables:
        return

    columns = {col["name"] for col in inspector.get_columns("jobs_manager_run")}
    if "skipped_jobs" not in columns:
        with op.batch_alter_table("jobs_manager_run", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "skipped_jobs",
                    sa.Integer(),
                    nullable=False,
                    server_default="0",
                )
            )

        # Align existing rows to default value
        op.execute(
            sa.text(
                "UPDATE jobs_manager_run SET skipped_jobs = 0 WHERE skipped_jobs IS NULL"
            )
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    existing_tables = set(inspector.get_table_names())
    if "jobs_manager_run" not in existing_tables:
        return

    columns = {col["name"] for col in inspector.get_columns("jobs_manager_run")}
    if "skipped_jobs" in columns:
        with op.batch_alter_table("jobs_manager_run", schema=None) as batch_op:
            batch_op.drop_column("skipped_jobs")
