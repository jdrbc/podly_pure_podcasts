"""Add image metadata to feed

Revision ID: ded4b70feadb
Revises: 6e0e16299dcb
Create Date: 2025-03-01 14:30:20.177608

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "ded4b70feadb"
down_revision = "6e0e16299dcb"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("feed", schema=None) as batch_op:
        batch_op.add_column(sa.Column("image_url", sa.Text(), nullable=True))
    pass


def downgrade():
    with op.batch_alter_table("feed", schema=None) as batch_op:
        batch_op.drop_column("image_url")
    pass
