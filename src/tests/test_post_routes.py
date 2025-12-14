from types import SimpleNamespace
from unittest import mock

from flask import g

from app.extensions import db
from app.models import Feed, Post, User
from app.routes.post_routes import post_bp


def test_download_endpoints_increment_counter(app, tmp_path):
    """Ensure both processed and original downloads increment the counter."""
    app.testing = True
    app.register_blueprint(post_bp)

    with app.app_context():
        feed = Feed(title="Test Feed", rss_url="https://example.com/feed.xml")
        db.session.add(feed)
        db.session.commit()

        processed_audio = tmp_path / "processed.mp3"
        processed_audio.write_bytes(b"processed audio")

        original_audio = tmp_path / "original.mp3"
        original_audio.write_bytes(b"original audio")

        post = Post(
            feed_id=feed.id,
            guid="test-guid",
            download_url="https://example.com/audio.mp3",
            title="Test Episode",
            processed_audio_path=str(processed_audio),
            unprocessed_audio_path=str(original_audio),
            whitelisted=True,
        )
        db.session.add(post)
        db.session.commit()

        client = app.test_client()

        # Mock writer_client to simulate DB update
        with mock.patch("app.routes.post_routes.writer_client") as mock_writer:

            def side_effect(action, params, wait=False):
                if action == "increment_download_count":
                    post_id = params["post_id"]
                    Post.query.filter_by(id=post_id).update(
                        {Post.download_count: (Post.download_count or 0) + 1}
                    )
                    db.session.commit()

            mock_writer.action.side_effect = side_effect

            response = client.get(f"/api/posts/{post.guid}/download")
            assert response.status_code == 200
            db.session.refresh(post)
            assert post.download_count == 1

            response = client.get(f"/api/posts/{post.guid}/download/original")
            assert response.status_code == 200
            db.session.refresh(post)
            assert post.download_count == 2


def test_toggle_whitelist_all_requires_admin(app):
    """Ensure bulk whitelist actions are limited to admins."""
    app.testing = True
    app.register_blueprint(post_bp)
    app.config["AUTH_SETTINGS"] = SimpleNamespace(require_auth=True)

    with app.app_context():
        admin_user = User(username="admin", password_hash="hash", role="admin")
        regular_user = User(username="user", password_hash="hash", role="user")
        feed = Feed(title="Admin Feed", rss_url="https://example.com/feed.xml")
        db.session.add_all([admin_user, regular_user, feed])
        db.session.commit()

        posts = [
            Post(
                feed_id=feed.id,
                guid=f"guid-{idx}",
                download_url=f"https://example.com/{idx}.mp3",
                title=f"Episode {idx}",
                whitelisted=False,
            )
            for idx in range(2)
        ]
        db.session.add_all(posts)
        db.session.commit()

        admin_id = admin_user.id
        regular_id = regular_user.id
        feed_id = feed.id

    current_user = {"id": admin_id}

    @app.before_request
    def _mock_auth() -> None:
        g.current_user = SimpleNamespace(id=current_user["id"])

    client = app.test_client()
    current_user["id"] = regular_id
    response = client.post(f"/api/feeds/{feed_id}/toggle-whitelist-all")
    assert response.status_code == 403
    assert response.get_json()["error"].startswith("Only admins")

    current_user["id"] = admin_id
    response = client.post(f"/api/feeds/{feed_id}/toggle-whitelist-all")
    assert response.status_code == 200
    with app.app_context():
        whitelisted = Post.query.filter_by(feed_id=feed_id, whitelisted=True).count()
        assert whitelisted == 2
