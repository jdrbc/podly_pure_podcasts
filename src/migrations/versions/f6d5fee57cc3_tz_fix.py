"""tz_fix

Revision ID: f6d5fee57cc3
Revises: 0d954a44fa8e
Create Date: 2025-11-04 22:31:38.563280

"""
import datetime

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f6d5fee57cc3"
down_revision = "0d954a44fa8e"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("post", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("release_date_tmp", sa.DateTime(timezone=True), nullable=True)
        )

    bind = op.get_bind()
    metadata = sa.MetaData()
    post = sa.Table("post", metadata, autoload_with=bind)

    select_stmt = sa.select(post.c.id, post.c.release_date)
    rows = bind.execute(select_stmt).fetchall()
    for row in rows:
        if row.release_date is None:
            continue
        if isinstance(row.release_date, datetime.datetime):
            dt = row.release_date
        else:
            dt = datetime.datetime.combine(row.release_date, datetime.time())
        dt = dt.replace(tzinfo=datetime.timezone.utc)
        bind.execute(
            post.update()
            .where(post.c.id == row.id)
            .values(release_date_tmp=dt)
        )

    with op.batch_alter_table("post", schema=None) as batch_op:
        batch_op.drop_column("release_date")

    with op.batch_alter_table("post", schema=None) as batch_op:
        batch_op.rename_column("release_date_tmp", "release_date")


def downgrade():
    with op.batch_alter_table("post", schema=None) as batch_op:
        batch_op.add_column(sa.Column("release_date_date", sa.DATE(), nullable=True))

    bind = op.get_bind()
    metadata = sa.MetaData()
    post = sa.Table("post", metadata, autoload_with=bind)

    select_stmt = sa.select(post.c.id, post.c.release_date)
    rows = bind.execute(select_stmt).fetchall()
    for row in rows:
        if row.release_date is None:
            continue
        if isinstance(row.release_date, datetime.datetime):
            dt = row.release_date
        else:
            dt = datetime.datetime.combine(row.release_date, datetime.time())
        date_only = dt.astimezone(datetime.timezone.utc).date()
        bind.execute(
            post.update()
            .where(post.c.id == row.id)
            .values(release_date_date=date_only)
        )

    with op.batch_alter_table("post", schema=None) as batch_op:
        batch_op.drop_column("release_date")

    with op.batch_alter_table("post", schema=None) as batch_op:
        batch_op.rename_column("release_date_date", "release_date")
