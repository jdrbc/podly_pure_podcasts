from app import db


# mypy typing issue https://github.com/python/mypy/issues/17918
class Feed(db.Model):  # type: ignore[name-defined, misc]
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    title = db.Column(db.Text, nullable=False)
    description = db.Column(db.Text)
    author = db.Column(db.Text)
    rss_url = db.Column(db.Text, unique=True, nullable=False)

    posts = db.relationship("Post", backref="feed", lazy=True)

    def __repr__(self) -> str:
        return f"<Feed {self.title}>"


class Post(db.Model):  # type: ignore[name-defined, misc]
    feed_id = db.Column(db.Integer, db.ForeignKey("feed.id"), nullable=False)
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    guid = db.Column(db.Text, unique=True, nullable=False)
    download_url = db.Column(db.Text, unique=True, nullable=False)
    title = db.Column(db.Text, nullable=False)
    description = db.Column(db.Text)
    release_date = db.Column(db.Date)
    duration = db.Column(db.Integer)

    transcript = db.relationship("Transcript", uselist=False, backref="post")


class Transcript(db.Model):  # type: ignore[name-defined, misc]
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    post_id = db.Column(
        db.Integer, db.ForeignKey("post.id"), nullable=False, unique=True
    )
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime)
