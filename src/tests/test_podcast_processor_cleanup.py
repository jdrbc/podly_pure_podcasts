from types import SimpleNamespace
from unittest.mock import MagicMock

from podcast_processor.podcast_processor import PodcastProcessor


def test_remove_unprocessed_audio_deletes_file(tmp_path) -> None:
    file_path = tmp_path / "raw.mp3"
    file_path.write_text("audio")

    processor = PodcastProcessor(
        config=MagicMock(),
        transcription_manager=MagicMock(),
        ad_classifier=MagicMock(),
        audio_processor=MagicMock(),
        status_manager=MagicMock(),
        db_session=MagicMock(),
        downloader=MagicMock(),
    )

    post = SimpleNamespace(unprocessed_audio_path=str(file_path))

    processor._remove_unprocessed_audio(post)

    assert post.unprocessed_audio_path is None
    assert not file_path.exists()
