"""episode whitelist

Revision ID: 770771437280
Revises: fa3a95ecd67d
Create Date: 2024-11-16 08:27:46.081562

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "770771437280"
down_revision = "fa3a95ecd67d"
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table("post", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "whitelisted", sa.Boolean(), nullable=False, server_default=sa.false()
            )
        )

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table("post", schema=None) as batch_op:
        batch_op.drop_column("whitelisted")

    op.create_table(
        "ad_identification",
        sa.Column("id", sa.INTEGER(), nullable=False),
        sa.Column("post_id", sa.INTEGER(), nullable=False),
        sa.Column("content", sa.TEXT(), nullable=False),
        sa.Column("timestamp", sa.DATETIME(), nullable=True),
        sa.ForeignKeyConstraint(
            ["post_id"],
            ["post.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("post_id"),
    )
    op.create_table(
        "identification",
        sa.Column("id", sa.INTEGER(), nullable=False),
        sa.Column("post_id", sa.INTEGER(), nullable=False),
        sa.Column("content", sa.TEXT(), nullable=False),
        sa.Column("timestamp", sa.DATETIME(), nullable=True),
        sa.ForeignKeyConstraint(
            ["post_id"],
            ["post.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("post_id"),
    )
    # ### end Alembic commands ###
