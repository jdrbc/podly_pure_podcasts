import json
import os
from typing import List

from markupsafe import Markup

from app import db
from podcast_processor.transcribe import Segment


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

    transcript = db.relationship("Transcript", uselist=False, backref="post")

    def audio_len_bytes(self) -> int:
        audio_len_bytes = 0
        if self.processed_audio_path is not None and os.path.isfile(
            self.processed_audio_path
        ):
            audio_len_bytes = os.path.getsize(self.processed_audio_path)

        return audio_len_bytes

    # identifications = db.relationship(
    #     "Identification",
    #     backref="feed",
    #     lazy=True,
    #     order_by="Identification.release_date.desc()",
    # )


class Transcript(db.Model):  # type: ignore[name-defined, misc]
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    post_id = db.Column(
        db.Integer, db.ForeignKey("post.id"), nullable=False, unique=True
    )
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime)

    def get_segments(self) -> List[Segment]:
        return [Segment(**json.loads(segment)) for segment in json.loads(self.content)]

    def get_human_readable_content(self) -> str:
        segments = self.get_segments()
        return "\n".join(
            f"{segment.start} - {segment.end}: {segment.text}" for segment in segments
        )

    def render_segments_as_html(self) -> str:
        """Create an HTML representation of the transcript segments."""
        segments = self.get_segments()
        rendered_segments = "".join(
            f"<p><strong>{segment.start} - {segment.end}:</strong> {segment.text}</p>"
            for segment in segments
        )
        # Use Markup to mark the string as safe so the HTML renders correctly
        return Markup(rendered_segments)


# class Identification(db.Model):  # type: ignore[name-defined, misc]
#     id = db.Column(db.Integer, primary_key=True, autoincrement=True)
#     post_id = db.Column(
#         db.Integer, db.ForeignKey("post.id"), nullable=False, unique=True
#     )
