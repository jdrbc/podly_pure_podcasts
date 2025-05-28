import os
import uuid
from datetime import datetime

from app import db


def generate_job_id() -> str:
    """Generate a unique job ID."""
    return str(uuid.uuid4())


# mypy typing issue https://github.com/python/mypy/issues/17918
class Feed(db.Model):  # type: ignore[name-defined, misc]
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    alt_id = db.Column(
        db.Text, nullable=True
    )  # used for backwards compatibility with feeds defined in config.yml
    title = db.Column(db.Text, nullable=False)
    description = db.Column(db.Text)
    author = db.Column(db.Text)
    rss_url = db.Column(db.Text, unique=True, nullable=False)
    image_url = db.Column(db.Text)

    posts = db.relationship(
        "Post", backref="feed", lazy=True, order_by="Post.release_date.desc()"
    )

    def __repr__(self) -> str:
        return f"<Feed {self.title}>"


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
    release_date = db.Column(db.Date)
    duration = db.Column(db.Integer)
    whitelisted = db.Column(db.Boolean, default=False, nullable=False)
    image_url = db.Column(db.Text)  # Episode thumbnail URL

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


class ProcessingJob(db.Model):  # type: ignore[name-defined, misc]
    __tablename__ = "processing_job"

    id = db.Column(db.String(36), primary_key=True, default=generate_job_id)
    post_guid = db.Column(db.String(255), nullable=False, index=True)
    status = db.Column(
        db.String(50), nullable=False
    )  # pending, running, completed, failed, cancelled
    current_step = db.Column(db.Integer, default=0)  # 0-4 (0=not started, 4=completed)
    step_name = db.Column(db.String(100))
    total_steps = db.Column(db.Integer, default=4)
    progress_percentage = db.Column(db.Float, default=0.0)
    started_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)
    error_message = db.Column(db.Text)
    scheduler_job_id = db.Column(db.String(255))  # APScheduler job ID
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    # Relationships
    post = db.relationship(
        "Post",
        backref="processing_jobs",
        primaryjoin="ProcessingJob.post_guid == Post.guid",
        foreign_keys=[post_guid],
    )

    def __repr__(self) -> str:
        return f"<ProcessingJob {self.id} Post:{self.post_guid} Status:{self.status} Step:{self.current_step}/{self.total_steps}>"
