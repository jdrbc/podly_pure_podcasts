from unittest.mock import MagicMock

from app.extensions import db
from app.models import Feed, Post
from podcast_processor.ad_classifier import AdClassifier
from podcast_processor.audio_processor import AudioProcessor
from podcast_processor.podcast_downloader import PodcastDownloader
from podcast_processor.podcast_processor import PodcastProcessor
from podcast_processor.processing_status_manager import ProcessingStatusManager
from podcast_processor.transcription_manager import TranscriptionManager
from shared.test_utils import create_standard_test_config


def test_remove_unprocessed_audio_deletes_file(app, tmp_path) -> None:
    file_path = tmp_path / "raw.mp3"
    file_path.write_text("audio")

    with app.app_context():
        # Create a real Post object
        feed = Feed(
            title="Test Feed",
            description="Test Description",
            author="Test Author",
            rss_url="https://example.com/feed.xml",
        )
        db.session.add(feed)
        db.session.commit()

        post = Post(
            guid="test-guid",
            title="Test Episode",
            download_url="https://example.com/episode.mp3",
            feed_id=feed.id,
            unprocessed_audio_path=str(file_path),
        )
        db.session.add(post)
        db.session.commit()

        processor = PodcastProcessor(
            config=create_standard_test_config(),
            transcription_manager=MagicMock(spec=TranscriptionManager),
            ad_classifier=MagicMock(spec=AdClassifier),
            audio_processor=MagicMock(spec=AudioProcessor),
            status_manager=MagicMock(spec=ProcessingStatusManager),
            db_session=db.session,
            downloader=MagicMock(spec=PodcastDownloader),
        )

        processor._remove_unprocessed_audio(post)

        assert post.unprocessed_audio_path is None
        assert not file_path.exists()
