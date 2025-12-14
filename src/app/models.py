import os
import uuid
from datetime import datetime

from sqlalchemy.orm import validates

from app.auth.passwords import hash_password, verify_password
from app.extensions import db
from shared import defaults as DEFAULTS


def generate_uuid() -> str:
    """Generate a UUID4 string."""
    return str(uuid.uuid4())


def generate_job_id() -> str:
    """Generate a unique job ID."""
    return generate_uuid()


# mypy typing issue https://github.com/python/mypy/issues/17918
class Feed(db.Model):  # type: ignore[name-defined, misc]
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    alt_id = db.Column(
        db.Text, nullable=True
    )  # used for backwards compatibility with legacy YAML-based feed definitions
    title = db.Column(db.Text, nullable=False)
    description = db.Column(db.Text)
    author = db.Column(db.Text)
    rss_url = db.Column(db.Text, unique=True, nullable=False)
    image_url = db.Column(db.Text)

    posts = db.relationship(
        "Post", backref="feed", lazy=True, order_by="Post.release_date.desc()"
    )
    user_feeds = db.relationship(
        "UserFeed",
        back_populates="feed",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Feed {self.title}>"


class FeedAccessToken(db.Model):  # type: ignore[name-defined, misc]
    __tablename__ = "feed_access_token"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    token_id = db.Column(db.String(32), unique=True, nullable=False, index=True)
    token_hash = db.Column(db.String(64), nullable=False)
    token_secret = db.Column(db.String(128), nullable=True)
    feed_id = db.Column(db.Integer, db.ForeignKey("feed.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_used_at = db.Column(db.DateTime, nullable=True)
    revoked = db.Column(db.Boolean, default=False, nullable=False)

    feed = db.relationship("Feed", backref=db.backref("access_tokens", lazy="dynamic"))
    user = db.relationship(
        "User", backref=db.backref("feed_access_tokens", lazy="dynamic")
    )

    def __repr__(self) -> str:
        return (
            f"<FeedAccessToken feed={self.feed_id} user={self.user_id}"
            f" revoked={self.revoked}>"
        )


class Post(db.Model):  # type: ignore[name-defined, misc]
    feed_id = db.Column(db.Integer, db.ForeignKey("feed.id"), nullable=False)
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    guid = db.Column(db.Text, unique=True, nullable=False)
    download_url = db.Column(
        db.Text, unique=True, nullable=False
    )  # remote download URL, not podly url
    title = db.Column(db.Text, nullable=False)
    unprocessed_audio_path = db.Column(db.Text)
    processed_audio_path = db.Column(db.Text)
    description = db.Column(db.Text)
    release_date = db.Column(db.DateTime(timezone=True))
    duration = db.Column(db.Integer)
    whitelisted = db.Column(db.Boolean, default=False, nullable=False)
    image_url = db.Column(db.Text)  # Episode thumbnail URL
    download_count = db.Column(db.Integer, nullable=True, default=0)

    segments = db.relationship(
        "TranscriptSegment",
        backref="post",
        lazy="dynamic",
        order_by="TranscriptSegment.sequence_num",
    )

    def audio_len_bytes(self) -> int:
        audio_len_bytes = 0
        if self.processed_audio_path is not None and os.path.isfile(
            self.processed_audio_path
        ):
            audio_len_bytes = os.path.getsize(self.processed_audio_path)

        return audio_len_bytes


class TranscriptSegment(db.Model):  # type: ignore[name-defined, misc]
    __tablename__ = "transcript_segment"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    post_id = db.Column(db.Integer, db.ForeignKey("post.id"), nullable=False)
    sequence_num = db.Column(db.Integer, nullable=False)
    start_time = db.Column(db.Float, nullable=False)
    end_time = db.Column(db.Float, nullable=False)
    text = db.Column(db.Text, nullable=False)

    identifications = db.relationship(
        "Identification", backref="transcript_segment", lazy="dynamic"
    )

    __table_args__ = (
        db.Index(
            "ix_transcript_segment_post_id_sequence_num",
            "post_id",
            "sequence_num",
            unique=True,
        ),
    )

    def __repr__(self) -> str:
        return f"<TranscriptSegment {self.id} P:{self.post_id} S:{self.sequence_num} T:{self.start_time:.1f}-{self.end_time:.1f}>"


class User(db.Model):  # type: ignore[name-defined, misc]
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    username = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(50), nullable=False, default="user")
    feed_allowance = db.Column(db.Integer, nullable=False, default=0)
    feed_subscription_status = db.Column(
        db.String(32), nullable=False, default="inactive"
    )
    stripe_customer_id = db.Column(db.String(64), nullable=True)
    stripe_subscription_id = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    # Discord SSO fields
    discord_id = db.Column(db.String(32), unique=True, nullable=True, index=True)
    discord_username = db.Column(db.String(100), nullable=True)

    # Admin override for feed allowance (if set, overrides plan-based allowance)
    manual_feed_allowance = db.Column(db.Integer, nullable=True)

    user_feeds = db.relationship(
        "UserFeed",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    @validates("username")
    def _normalize_username(self, key: str, value: str) -> str:
        del key
        return value.strip().lower()

    def set_password(self, password: str) -> None:
        self.password_hash = hash_password(password)

    def verify_password(self, password: str) -> bool:
        return verify_password(password, self.password_hash)

    def __repr__(self) -> str:
        return f"<User {self.username} role={self.role}>"


class ModelCall(db.Model):  # type: ignore[name-defined, misc]
    __tablename__ = "model_call"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    post_id = db.Column(db.Integer, db.ForeignKey("post.id"), nullable=False)

    first_segment_sequence_num = db.Column(db.Integer, nullable=False)
    last_segment_sequence_num = db.Column(db.Integer, nullable=False)

    model_name = db.Column(db.String, nullable=False)
    prompt = db.Column(db.Text, nullable=False)
    response = db.Column(db.Text, nullable=True)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    status = db.Column(db.String, nullable=False, default="pending")
    error_message = db.Column(db.Text, nullable=True)
    retry_attempts = db.Column(db.Integer, nullable=False, default=0)

    identifications = db.relationship(
        "Identification", backref="model_call", lazy="dynamic"
    )
    post = db.relationship("Post", backref=db.backref("model_calls", lazy="dynamic"))

    __table_args__ = (
        db.Index(
            "ix_model_call_post_chunk_model",
            "post_id",
            "first_segment_sequence_num",
            "last_segment_sequence_num",
            "model_name",
            unique=True,
        ),
    )

    def __repr__(self) -> str:
        return f"<ModelCall {self.id} P:{self.post_id} Segs:{self.first_segment_sequence_num}-{self.last_segment_sequence_num} M:{self.model_name} S:{self.status}>"


class Identification(db.Model):  # type: ignore[name-defined, misc]
    __tablename__ = "identification"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    transcript_segment_id = db.Column(
        db.Integer, db.ForeignKey("transcript_segment.id"), nullable=False
    )
    model_call_id = db.Column(
        db.Integer, db.ForeignKey("model_call.id"), nullable=False
    )
    confidence = db.Column(db.Float, nullable=True)
    label = db.Column(db.String, nullable=False)

    __table_args__ = (
        db.Index(
            "ix_identification_segment_call_label",
            "transcript_segment_id",
            "model_call_id",
            "label",
            unique=True,
        ),
    )

    def __repr__(self) -> str:
        # Ensure confidence is handled if None for f-string formatting
        confidence_str = (
            f"{self.confidence:.2f}" if self.confidence is not None else "N/A"
        )
        return f"<Identification {self.id} TS:{self.transcript_segment_id} MC:{self.model_call_id} L:{self.label} C:{confidence_str}>"


class JobsManagerRun(db.Model):  # type: ignore[name-defined, misc]
    __tablename__ = "jobs_manager_run"

    id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    status = db.Column(db.String(50), nullable=False, default="pending", index=True)
    trigger = db.Column(db.String(100), nullable=False)
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    total_jobs = db.Column(db.Integer, nullable=False, default=0)
    queued_jobs = db.Column(db.Integer, nullable=False, default=0)
    running_jobs = db.Column(db.Integer, nullable=False, default=0)
    completed_jobs = db.Column(db.Integer, nullable=False, default=0)
    failed_jobs = db.Column(db.Integer, nullable=False, default=0)
    skipped_jobs = db.Column(db.Integer, nullable=False, default=0)
    context_json = db.Column(db.JSON, nullable=True)
    counters_reset_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    processing_jobs = db.relationship(
        "ProcessingJob", back_populates="run", lazy="dynamic"
    )

    def __repr__(self) -> str:
        return (
            f"<JobsManagerRun {self.id} status={self.status} "
            f"trigger={self.trigger} total={self.total_jobs}>"
        )


class ProcessingJob(db.Model):  # type: ignore[name-defined, misc]
    __tablename__ = "processing_job"

    id = db.Column(db.String(36), primary_key=True, default=generate_job_id)
    jobs_manager_run_id = db.Column(
        db.String(36), db.ForeignKey("jobs_manager_run.id"), index=True
    )
    post_guid = db.Column(db.String(255), nullable=False, index=True)
    status = db.Column(
        db.String(50), nullable=False
    )  # pending, running, completed, failed, cancelled, skipped
    current_step = db.Column(db.Integer, default=0)  # 0-4 (0=not started, 4=completed)
    step_name = db.Column(db.String(100))
    total_steps = db.Column(db.Integer, default=4)
    progress_percentage = db.Column(db.Float, default=0.0)
    started_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)
    error_message = db.Column(db.Text)
    scheduler_job_id = db.Column(db.String(255))  # APScheduler job ID
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    requested_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    billing_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    # Relationships
    post = db.relationship(
        "Post",
        backref="processing_jobs",
        primaryjoin="ProcessingJob.post_guid == Post.guid",
        foreign_keys=[post_guid],
    )
    run = db.relationship("JobsManagerRun", back_populates="processing_jobs")
    requested_by_user = db.relationship(
        "User",
        foreign_keys=[requested_by_user_id],
        backref=db.backref("requested_jobs", lazy="dynamic"),
    )
    billing_user = db.relationship(
        "User",
        foreign_keys=[billing_user_id],
        backref=db.backref("billed_jobs", lazy="dynamic"),
    )

    def __repr__(self) -> str:
        return f"<ProcessingJob {self.id} Post:{self.post_guid} Status:{self.status} Step:{self.current_step}/{self.total_steps}>"


class UserFeed(db.Model):  # type: ignore[name-defined, misc]
    __tablename__ = "feed_supporter"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    feed_id = db.Column(db.Integer, db.ForeignKey("feed.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("feed_id", "user_id", name="uq_feed_supporter_feed_user"),
    )

    feed = db.relationship("Feed", back_populates="user_feeds")
    user = db.relationship("User", back_populates="user_feeds")

    def __repr__(self) -> str:
        return f"<UserFeed feed={self.feed_id} user={self.user_id}>"


# ----- Application Settings (Singleton Tables) -----


class LLMSettings(db.Model):  # type: ignore[name-defined, misc]
    __tablename__ = "llm_settings"

    id = db.Column(db.Integer, primary_key=True, default=1)
    llm_api_key = db.Column(db.Text, nullable=True)
    llm_model = db.Column(db.Text, nullable=False, default=DEFAULTS.LLM_DEFAULT_MODEL)
    openai_base_url = db.Column(db.Text, nullable=True)
    openai_timeout = db.Column(
        db.Integer, nullable=False, default=DEFAULTS.OPENAI_DEFAULT_TIMEOUT_SEC
    )
    openai_max_tokens = db.Column(
        db.Integer, nullable=False, default=DEFAULTS.OPENAI_DEFAULT_MAX_TOKENS
    )
    llm_max_concurrent_calls = db.Column(
        db.Integer, nullable=False, default=DEFAULTS.LLM_DEFAULT_MAX_CONCURRENT_CALLS
    )
    llm_max_retry_attempts = db.Column(
        db.Integer, nullable=False, default=DEFAULTS.LLM_DEFAULT_MAX_RETRY_ATTEMPTS
    )
    llm_max_input_tokens_per_call = db.Column(db.Integer, nullable=True)
    llm_enable_token_rate_limiting = db.Column(
        db.Boolean, nullable=False, default=DEFAULTS.LLM_ENABLE_TOKEN_RATE_LIMITING
    )
    llm_max_input_tokens_per_minute = db.Column(db.Integer, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class WhisperSettings(db.Model):  # type: ignore[name-defined, misc]
    __tablename__ = "whisper_settings"

    id = db.Column(db.Integer, primary_key=True, default=1)
    whisper_type = db.Column(
        db.Text, nullable=False, default=DEFAULTS.WHISPER_DEFAULT_TYPE
    )  # local|remote|groq|test

    # Local
    local_model = db.Column(
        db.Text, nullable=False, default=DEFAULTS.WHISPER_LOCAL_MODEL
    )

    # Remote
    remote_model = db.Column(
        db.Text, nullable=False, default=DEFAULTS.WHISPER_REMOTE_MODEL
    )
    remote_api_key = db.Column(db.Text, nullable=True)
    remote_base_url = db.Column(
        db.Text, nullable=False, default=DEFAULTS.WHISPER_REMOTE_BASE_URL
    )
    remote_language = db.Column(
        db.Text, nullable=False, default=DEFAULTS.WHISPER_REMOTE_LANGUAGE
    )
    remote_timeout_sec = db.Column(
        db.Integer, nullable=False, default=DEFAULTS.WHISPER_REMOTE_TIMEOUT_SEC
    )
    remote_chunksize_mb = db.Column(
        db.Integer, nullable=False, default=DEFAULTS.WHISPER_REMOTE_CHUNKSIZE_MB
    )

    # Groq
    groq_api_key = db.Column(db.Text, nullable=True)
    groq_model = db.Column(db.Text, nullable=False, default=DEFAULTS.WHISPER_GROQ_MODEL)
    groq_language = db.Column(
        db.Text, nullable=False, default=DEFAULTS.WHISPER_GROQ_LANGUAGE
    )
    groq_max_retries = db.Column(
        db.Integer, nullable=False, default=DEFAULTS.WHISPER_GROQ_MAX_RETRIES
    )

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class ProcessingSettings(db.Model):  # type: ignore[name-defined, misc]
    __tablename__ = "processing_settings"

    id = db.Column(db.Integer, primary_key=True, default=1)
    # Deprecated: paths are now hardcoded; keep columns for migration compatibility
    system_prompt_path = db.Column(
        db.Text, nullable=False, default="src/system_prompt.txt"
    )
    user_prompt_template_path = db.Column(
        db.Text, nullable=False, default="src/user_prompt.jinja"
    )
    num_segments_to_input_to_prompt = db.Column(
        db.Integer,
        nullable=False,
        default=DEFAULTS.PROCESSING_NUM_SEGMENTS_TO_INPUT_TO_PROMPT,
    )

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class OutputSettings(db.Model):  # type: ignore[name-defined, misc]
    __tablename__ = "output_settings"

    id = db.Column(db.Integer, primary_key=True, default=1)
    fade_ms = db.Column(db.Integer, nullable=False, default=DEFAULTS.OUTPUT_FADE_MS)
    min_ad_segement_separation_seconds = db.Column(
        db.Integer,
        nullable=False,
        default=DEFAULTS.OUTPUT_MIN_AD_SEGMENT_SEPARATION_SECONDS,
    )
    min_ad_segment_length_seconds = db.Column(
        db.Integer,
        nullable=False,
        default=DEFAULTS.OUTPUT_MIN_AD_SEGMENT_LENGTH_SECONDS,
    )
    min_confidence = db.Column(
        db.Float, nullable=False, default=DEFAULTS.OUTPUT_MIN_CONFIDENCE
    )

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class AppSettings(db.Model):  # type: ignore[name-defined, misc]
    __tablename__ = "app_settings"

    id = db.Column(db.Integer, primary_key=True, default=1)
    background_update_interval_minute = db.Column(
        db.Integer, nullable=True
    )  # intentionally nullable; default applied in config store/runtime
    automatically_whitelist_new_episodes = db.Column(
        db.Boolean,
        nullable=False,
        default=DEFAULTS.APP_AUTOMATICALLY_WHITELIST_NEW_EPISODES,
    )
    post_cleanup_retention_days = db.Column(
        db.Integer,
        nullable=True,
        default=DEFAULTS.APP_POST_CLEANUP_RETENTION_DAYS,
    )
    number_of_episodes_to_whitelist_from_archive_of_new_feed = db.Column(
        db.Integer,
        nullable=False,
        default=DEFAULTS.APP_NUM_EPISODES_TO_WHITELIST_FROM_ARCHIVE_OF_NEW_FEED,
    )
    enable_public_landing_page = db.Column(
        db.Boolean,
        nullable=False,
        default=DEFAULTS.APP_ENABLE_PUBLIC_LANDING_PAGE,
    )

    # Hash of the environment variables used to seed configuration.
    # Used to detect changes in environment variables between restarts.
    env_config_hash = db.Column(db.String(64), nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class DiscordSettings(db.Model):  # type: ignore[name-defined, misc]
    __tablename__ = "discord_settings"

    id = db.Column(db.Integer, primary_key=True, default=1)
    client_id = db.Column(db.Text, nullable=True)
    client_secret = db.Column(db.Text, nullable=True)
    redirect_uri = db.Column(db.Text, nullable=True)
    guild_ids = db.Column(db.Text, nullable=True)  # Comma-separated list
    allow_registration = db.Column(db.Boolean, nullable=False, default=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
