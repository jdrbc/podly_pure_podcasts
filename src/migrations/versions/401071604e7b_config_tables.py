"""Create settings tables and seed defaults

Revision ID: 401071604e7b
Revises: 611dcb5d7f12
Create Date: 2025-09-28 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "401071604e7b"
down_revision = "611dcb5d7f12"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "llm_settings" not in existing_tables:
        op.create_table(
            "llm_settings",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("llm_api_key", sa.Text(), nullable=True),
            sa.Column(
                "llm_model",
                sa.Text(),
                nullable=False,
                server_default="groq/openai/gpt-oss-120b",
            ),
            sa.Column("openai_base_url", sa.Text(), nullable=True),
            sa.Column(
                "openai_timeout", sa.Integer(), nullable=False, server_default="300"
            ),
            sa.Column(
                "openai_max_tokens", sa.Integer(), nullable=False, server_default="4096"
            ),
            sa.Column(
                "llm_max_concurrent_calls",
                sa.Integer(),
                nullable=False,
                server_default="3",
            ),
            sa.Column(
                "llm_max_retry_attempts",
                sa.Integer(),
                nullable=False,
                server_default="5",
            ),
            sa.Column("llm_max_input_tokens_per_call", sa.Integer(), nullable=True),
            sa.Column(
                "llm_enable_token_rate_limiting",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column("llm_max_input_tokens_per_minute", sa.Integer(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.current_timestamp(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.current_timestamp(),
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    if "whisper_settings" not in existing_tables:
        op.create_table(
            "whisper_settings",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("whisper_type", sa.Text(), nullable=False, server_default="groq"),
            sa.Column(
                "local_model", sa.Text(), nullable=False, server_default="base.en"
            ),
            sa.Column(
                "remote_model", sa.Text(), nullable=False, server_default="whisper-1"
            ),
            sa.Column("remote_api_key", sa.Text(), nullable=True),
            sa.Column(
                "remote_base_url",
                sa.Text(),
                nullable=False,
                server_default="https://api.openai.com/v1",
            ),
            sa.Column(
                "remote_language", sa.Text(), nullable=False, server_default="en"
            ),
            sa.Column(
                "remote_timeout_sec", sa.Integer(), nullable=False, server_default="600"
            ),
            sa.Column(
                "remote_chunksize_mb", sa.Integer(), nullable=False, server_default="24"
            ),
            sa.Column("groq_api_key", sa.Text(), nullable=True),
            sa.Column(
                "groq_model",
                sa.Text(),
                nullable=False,
                server_default="whisper-large-v3-turbo",
            ),
            sa.Column("groq_language", sa.Text(), nullable=False, server_default="en"),
            sa.Column(
                "groq_max_retries", sa.Integer(), nullable=False, server_default="3"
            ),
            sa.Column(
                "groq_initial_backoff", sa.Float(), nullable=False, server_default="1.0"
            ),
            sa.Column(
                "groq_backoff_factor", sa.Float(), nullable=False, server_default="2.0"
            ),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.current_timestamp(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.current_timestamp(),
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    if "processing_settings" not in existing_tables:
        op.create_table(
            "processing_settings",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column(
                "system_prompt_path",
                sa.Text(),
                nullable=False,
                server_default="src/system_prompt.txt",
            ),
            sa.Column(
                "user_prompt_template_path",
                sa.Text(),
                nullable=False,
                server_default="src/user_prompt.jinja",
            ),
            sa.Column(
                "num_segments_to_input_to_prompt",
                sa.Integer(),
                nullable=False,
                server_default="60",
            ),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.current_timestamp(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.current_timestamp(),
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    if "output_settings" not in existing_tables:
        op.create_table(
            "output_settings",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("fade_ms", sa.Integer(), nullable=False, server_default="3000"),
            sa.Column(
                "min_ad_segement_separation_seconds",
                sa.Integer(),
                nullable=False,
                server_default="60",
            ),
            sa.Column(
                "min_ad_segment_length_seconds",
                sa.Integer(),
                nullable=False,
                server_default="14",
            ),
            sa.Column(
                "min_confidence", sa.Float(), nullable=False, server_default="0.8"
            ),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.current_timestamp(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.current_timestamp(),
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    if "app_settings" not in existing_tables:
        op.create_table(
            "app_settings",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("background_update_interval_minute", sa.Integer(), nullable=True),
            sa.Column(
                "automatically_whitelist_new_episodes",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("1"),
            ),
            sa.Column(
                "number_of_episodes_to_whitelist_from_archive_of_new_feed",
                sa.Integer(),
                nullable=False,
                server_default="1",
            ),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.current_timestamp(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.current_timestamp(),
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    # Seed singleton rows (id=1) - SQLite requires one statement per execute
    op.execute(
        sa.text("INSERT INTO llm_settings (id) VALUES (1) ON CONFLICT(id) DO NOTHING")
    )
    op.execute(
        sa.text(
            "INSERT INTO whisper_settings (id) VALUES (1) ON CONFLICT(id) DO NOTHING"
        )
    )
    op.execute(
        sa.text(
            "INSERT INTO processing_settings (id) VALUES (1) ON CONFLICT(id) DO NOTHING"
        )
    )
    op.execute(
        sa.text(
            "INSERT INTO output_settings (id) VALUES (1) ON CONFLICT(id) DO NOTHING"
        )
    )
    op.execute(
        sa.text("INSERT INTO app_settings (id) VALUES (1) ON CONFLICT(id) DO NOTHING")
    )


def downgrade():
    op.drop_table("app_settings")
    op.drop_table("output_settings")
    op.drop_table("processing_settings")
    op.drop_table("whisper_settings")
    op.drop_table("llm_settings")
