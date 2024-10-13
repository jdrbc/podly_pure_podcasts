from flask_sqlalchemy import SQLAlchemy

from app import db

assert isinstance(db, SQLAlchemy)


class Feed(db.Model):
    # TODO FIXME
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)

    posts = db.relationship("Post", backref="author", lazy=True)

    def __repr__(self) -> str:
        return f"<User {self.username}>"
