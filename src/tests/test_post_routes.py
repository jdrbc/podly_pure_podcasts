from app.extensions import db
from app.models import Feed, Post
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

        response = client.get(f"/api/posts/{post.guid}/download")
        assert response.status_code == 200
        db.session.refresh(post)
        assert post.download_count == 1

        response = client.get(f"/api/posts/{post.guid}/download/original")
        assert response.status_code == 200
        db.session.refresh(post)
        assert post.download_count == 2
