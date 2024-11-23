import json
from typing import List

from app import db
from podcast_processor.transcribe import Segment


# mypy typing issue https://github.com/python/mypy/issues/17918
class Feed(db.Model):  # type: ignore[name-defined, misc]
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
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
    download_url = db.Column(db.Text, unique=True, nullable=False)
    title = db.Column(db.Text, nullable=False)
    unprocessed_audio_path = db.Column(db.Text)
    processed_audio_path = db.Column(db.Text)
    description = db.Column(db.Text)
    release_date = db.Column(db.Date)
    duration = db.Column(db.Integer)
    whitelisted = db.Column(db.Boolean, default=False, nullable=False)

    transcript = db.relationship("Transcript", uselist=False, backref="post")
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
        return [
            Segment.from_dict(json.loads(segment))
            for segment in json.loads(self.content)
        ]

    def get_human_readable_content(self) -> str:
        segments = self.get_segments()
        return "\n".join(
            f"{segment.start} - {segment.end}: {segment.text}" for segment in segments
        )


# class Identification(db.Model):  # type: ignore[name-defined, misc]
#     id = db.Column(db.Integer, primary_key=True, autoincrement=True)
#     post_id = db.Column(
#         db.Integer, db.ForeignKey("post.id"), nullable=False, unique=True
#     )
