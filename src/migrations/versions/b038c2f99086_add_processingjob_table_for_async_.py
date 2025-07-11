"""Add ProcessingJob table for async episode processing

Revision ID: b038c2f99086
Revises: b92e47a03bb2
Create Date: 2025-05-25 12:18:50.783647

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "b038c2f99086"
down_revision = "b92e47a03bb2"
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "processing_job",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("post_guid", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("current_step", sa.Integer(), nullable=True),
        sa.Column("step_name", sa.String(length=100), nullable=True),
        sa.Column("total_steps", sa.Integer(), nullable=True),
        sa.Column("progress_percentage", sa.Float(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("scheduler_job_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("processing_job", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_processing_job_created_at"), ["created_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_processing_job_post_guid"), ["post_guid"], unique=False
        )

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table("processing_job", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_processing_job_post_guid"))
        batch_op.drop_index(batch_op.f("ix_processing_job_created_at"))

    op.drop_table("processing_job")
    # ### end Alembic commands ###
