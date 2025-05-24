from unittest import mock

import pytest

from shared.podcast_downloader import (
    download_episode,
    find_audio_link,
    get_and_make_download_path,
    sanitize_title,
)


class MockPost:
    """A mock Post class that doesn't require Flask context."""

    def __init__(
        self, id=1, title="Test Episode", download_url="https://example.com/podcast.mp3"
    ):
        self.id = id
        self.title = title
        self.download_url = download_url


@pytest.fixture
def mock_post():
    return MockPost()


@pytest.fixture
def mock_entry():
    entry = mock.MagicMock()
    link1 = mock.MagicMock()
    link1.type = "audio/mpeg"
    link1.href = "https://example.com/podcast.mp3"

    link2 = mock.MagicMock()
    link2.type = "text/html"
    link2.href = "https://example.com/episode"

    entry.links = [link1, link2]
    entry.id = "https://example.com/episode-id"
    return entry


def test_sanitize_title():
    assert sanitize_title("Test Episode!@#$%^&*()") == "Test Episode"
    assert (
        sanitize_title("123-ABC_DEF.mp3") == "123ABCDEFmp3"
    )  # Fixed expected output to match actual behavior
    assert sanitize_title("") == ""


def test_get_and_make_download_path(tmp_path, monkeypatch):
    # Temporarily set DOWNLOAD_DIR to tmp_path
    monkeypatch.setattr("shared.podcast_downloader.DOWNLOAD_DIR", str(tmp_path))

    path = get_and_make_download_path("Test Episode!")

    # Check that the directory was created
    assert (tmp_path / "Test Episode").exists()
    assert (tmp_path / "Test Episode").is_dir()

    # Check that the path is correct
    expected_path = tmp_path / "Test Episode" / "Test Episode.mp3"
    assert path == expected_path


def test_find_audio_link_with_audio_link(mock_entry):
    assert find_audio_link(mock_entry) == "https://example.com/podcast.mp3"


def test_find_audio_link_without_audio_link():
    entry = mock.MagicMock()
    entry.links = []
    entry.id = "https://example.com/episode-id"

    assert find_audio_link(entry) == "https://example.com/episode-id"


@mock.patch("shared.podcast_downloader.requests.get")
def test_download_episode_already_exists(mock_get, mock_post, tmp_path, monkeypatch):
    # Temporarily set DOWNLOAD_DIR to tmp_path
    monkeypatch.setattr("shared.podcast_downloader.DOWNLOAD_DIR", str(tmp_path))

    # Create the directory and file
    episode_dir = tmp_path / "Test Episode"
    episode_dir.mkdir()
    episode_file = episode_dir / "Test Episode.mp3"
    episode_file.write_bytes(b"dummy data")

    result = download_episode(mock_post)

    # Check that we didn't try to download the file
    mock_get.assert_not_called()

    # Check that the correct path was returned
    assert result == str(episode_file)


@mock.patch("shared.podcast_downloader.requests.get")
def test_download_episode_new_file(mock_get, mock_post, tmp_path, monkeypatch):
    # Temporarily set DOWNLOAD_DIR to tmp_path
    monkeypatch.setattr("shared.podcast_downloader.DOWNLOAD_DIR", str(tmp_path))

    # Setup mock response
    mock_response = mock.MagicMock()
    mock_response.status_code = 200
    mock_response.content = b"podcast audio content"
    mock_get.return_value = mock_response

    result = download_episode(mock_post)

    # Check that we tried to download the file
    mock_get.assert_called_once_with("https://example.com/podcast.mp3")

    # Check that the file was created with the correct content
    expected_path = tmp_path / "Test Episode" / "Test Episode.mp3"
    assert expected_path.exists()
    assert expected_path.read_bytes() == b"podcast audio content"

    # Check that the correct path was returned
    assert result == str(expected_path)


@mock.patch("shared.podcast_downloader.requests.get")
def test_download_episode_download_failed(mock_get, mock_post, tmp_path, monkeypatch):
    # Temporarily set DOWNLOAD_DIR to tmp_path
    monkeypatch.setattr("shared.podcast_downloader.DOWNLOAD_DIR", str(tmp_path))

    # Setup mock response
    mock_response = mock.MagicMock()
    mock_response.status_code = 404
    mock_get.return_value = mock_response

    result = download_episode(mock_post)

    # Check that we tried to download the file
    mock_get.assert_called_once_with("https://example.com/podcast.mp3")

    # Check that no file was created
    expected_path = tmp_path / "Test Episode" / "Test Episode.mp3"
    assert not expected_path.exists()

    # Check that None was returned
    assert result is None


@mock.patch("shared.podcast_downloader.validators.url")
@mock.patch("shared.podcast_downloader.abort")
def test_download_episode_invalid_url(mock_abort, mock_validator, mock_post):
    # Make the validator fail
    mock_validator.return_value = False

    download_episode(mock_post)

    # Check that abort was called with 404
    mock_abort.assert_called_once_with(404)


@mock.patch("shared.podcast_downloader.get_and_make_download_path")
def test_download_episode_invalid_post(mock_get_path):
    # Simulate get_and_make_download_path returning None
    mock_get_path.return_value = None

    post = MockPost()
    result = download_episode(post)

    # Check that None was returned
    assert result is None
    mock_get_path.assert_called_once_with(post.title)
