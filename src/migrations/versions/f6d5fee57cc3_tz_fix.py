"""tz_fix

Revision ID: f6d5fee57cc3
Revises: 0d954a44fa8e
Create Date: 2025-11-04 22:31:38.563280

"""
import datetime

import sqlalchemy as sa

from alembic import op


# revision identifiers, used by Alembic.
revision = "f6d5fee57cc3"
down_revision = "0d954a44fa8e"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    column_names = {col["name"] for col in inspector.get_columns("post")}

    if "release_date" not in column_names and "release_date_tmp" in column_names:
        with op.batch_alter_table("post", schema=None) as batch_op:
            batch_op.alter_column("release_date_tmp", new_column_name="release_date")
        return

    if "release_date" not in column_names:
        # Nothing to migrate (already applied manually, or table missing column)
        return

    if "release_date_tmp" not in column_names:
        with op.batch_alter_table("post", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column("release_date_tmp", sa.DateTime(timezone=True), nullable=True)
            )

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

    inspector = sa.inspect(bind)
    column_names = {col["name"] for col in inspector.get_columns("post")}
    if "release_date" in column_names:
        with op.batch_alter_table("post", schema=None) as batch_op:
            batch_op.drop_column("release_date")

    inspector = sa.inspect(bind)
    column_names = {col["name"] for col in inspector.get_columns("post")}
    if "release_date_tmp" in column_names:
        with op.batch_alter_table("post", schema=None) as batch_op:
            batch_op.alter_column("release_date_tmp", new_column_name="release_date")


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    column_names = {col["name"] for col in inspector.get_columns("post")}

    if "release_date" not in column_names and "release_date_date" in column_names:
        with op.batch_alter_table("post", schema=None) as batch_op:
            batch_op.alter_column("release_date_date", new_column_name="release_date")
        return

    if "release_date" not in column_names:
        # Nothing to revert
        return

    if "release_date_date" not in column_names:
        with op.batch_alter_table("post", schema=None) as batch_op:
            batch_op.add_column(sa.Column("release_date_date", sa.DATE(), nullable=True))

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

    inspector = sa.inspect(bind)
    column_names = {col["name"] for col in inspector.get_columns("post")}
    if "release_date" in column_names:
        with op.batch_alter_table("post", schema=None) as batch_op:
            batch_op.drop_column("release_date")

    inspector = sa.inspect(bind)
    column_names = {col["name"] for col in inspector.get_columns("post")}
    if "release_date_date" in column_names:
        with op.batch_alter_table("post", schema=None) as batch_op:
            batch_op.alter_column("release_date_date", new_column_name="release_date")
