from app.models import Post
from unittest.mock import patch


def test_get_len_file() -> None:
    post = Post()
    post.processed_audio_path = "/fake/path/to/file"
    mock_file_len = 14780

    with patch("os.path.getsize", return_value=mock_file_len), patch(
        "os.path.isfile", return_value=True
    ):
        assert post.audio_len_bytes() == mock_file_len


def test_get_len_file_not_processed() -> None:
    post = Post()

    assert post.audio_len_bytes() == 0
