import os
from pathlib import Path
from unittest.mock import patch

import pytest

from app.models import Feed, Post
from app.posts import PostException, download_and_process_post, remove_associated_files
from podcast_processor.podcast_processor import ProcessingPaths


class TestPostsFunctions:
    """Test class for functions in the app.posts module."""

    @patch("app.posts.Path.exists")
    @patch("app.posts.Path.unlink")
    @patch("app.posts.get_and_make_download_path")
    @patch("app.posts.get_post_processed_audio_path")
    @patch("app.posts.logger")
    def test_remove_associated_files_files_dont_exist(
        self,
        mock_logger,
        mock_get_processed_path,
        mock_get_download_path,
        mock_unlink,
        mock_exists,
        app,
    ):
        """Test remove_associated_files when files don't exist."""
        with app.app_context():
            # Set up mocks
            mock_exists.return_value = False  # Make all paths not exist
            mock_processed_paths = ProcessingPaths(
                post_processed_audio_path=Path("/path/to/processed.mp3")
            )
            mock_get_processed_path.return_value = mock_processed_paths
            mock_get_download_path.return_value = "/path/to/unprocessed.mp3"

            # Create test post
            post = Post(id=1, title="Test Post")

            # Call the function
            remove_associated_files(post)

            # Verify no files were deleted
            mock_unlink.assert_not_called()

            # Verify debug logging for skipped files
            assert (
                mock_logger.debug.call_count >= 2
            ), f"Debug was called {mock_logger.debug.call_count} times"

    def test_download_and_process_post_not_found(self, app):
        """Test download_and_process_post when post is not found."""
        with app.app_context():
            # Mock Post.query.filter_by() to return None
            with patch("app.posts.Post.query") as mock_query:
                mock_query.filter_by.return_value.first.return_value = None

                # Call the function with a non-existent guid
                with pytest.raises(PostException) as exc_info:
                    download_and_process_post("non-existent-guid")

                # Verify the error message
                assert "not found" in str(exc_info.value)

    def test_download_and_process_post_not_whitelisted(self, app):
        """Test download_and_process_post when post is not whitelisted."""
        with app.app_context():
            # Create a test post
            post = Post(id=1, guid="test-guid", title="Test Post", whitelisted=False)

            # Mock Post.query.filter_by() to return our post
            with patch("app.posts.Post.query") as mock_query:
                mock_query.filter_by.return_value.first.return_value = post

                # Call the function
                with pytest.raises(PostException) as exc_info:
                    download_and_process_post("test-guid")

                # Verify the error message
                assert "not whitelisted" in str(exc_info.value)

    @patch("app.posts.download_episode")
    def test_download_and_process_post_download_needed(
        self, mock_download, app, mock_db_session
    ):
        """Test download_and_process_post when download is needed."""
        with app.app_context():
            # Create a test post
            feed = Feed(id=1, title="Test Feed")
            post = Post(
                id=1,
                guid="test-guid",
                title="Test Post",
                whitelisted=True,
                unprocessed_audio_path=None,
                processed_audio_path="/path/to/processed.mp3",
                feed=feed,
            )

            # Mock the Path.exists and Path.stat methods directly
            with patch("pathlib.Path.exists") as mock_exists, patch(
                "pathlib.Path.stat"
            ), patch("app.posts.Post.query") as mock_query, patch(
                "app.posts.db"
            ) as mock_db, patch(
                "app.posts.sanitize_title"
            ) as mock_sanitize:

                # Configure mocks
                mock_exists.return_value = False  # File doesn't exist
                mock_sanitize.return_value = "test_post.mp3"

                # Set up mock query
                mock_query.filter_by.return_value.first.return_value = post
                mock_db.session = mock_db_session

                # Configure download to succeed
                mock_download.return_value = "/path/to/downloaded.mp3"

                # Call the function
                result = download_and_process_post("test-guid")

                # Verify download was called
                mock_download.assert_called_once_with(post)

                # Verify post was updated
                assert post.unprocessed_audio_path == "/path/to/downloaded.mp3"
                mock_db_session.commit.assert_called()

                # Verify the function returned the processed audio path
                assert result == "/path/to/processed.mp3"

    def test_download_and_process_post_existing_unprocessed(self, app, mock_db_session):
        """Test download_and_process_post when unprocessed file already exists."""
        with app.app_context():
            # Create a test post
            feed = Feed(id=1, title="Test Feed")
            post = Post(
                id=1,
                guid="test-guid",
                title="Test Post",
                whitelisted=True,
                unprocessed_audio_path=None,
                processed_audio_path="/path/to/processed.mp3",
                feed=feed,
            )

            # Create a stat result with non-zero size
            stat_result = os.stat_result((0, 0, 0, 0, 0, 0, 10000, 0, 0, 0))

            # Mock operations
            with patch("pathlib.Path.exists") as mock_exists, patch(
                "pathlib.Path.stat"
            ) as mock_stat, patch("pathlib.Path.resolve") as mock_resolve, patch(
                "app.posts.Post.query"
            ) as mock_query, patch(
                "app.posts.db"
            ) as mock_db, patch(
                "app.posts.sanitize_title"
            ) as mock_sanitize:

                # Configure mocks
                mock_exists.return_value = True  # File exists
                mock_stat.return_value = stat_result  # Non-zero size
                mock_resolve.return_value = Path("/path/to/existing.mp3")
                mock_sanitize.return_value = "test_post.mp3"

                # Set up mock query
                mock_query.filter_by.return_value.first.return_value = post
                mock_db.session = mock_db_session

                # Call the function
                result = download_and_process_post("test-guid")

                # Verify post was updated with existing file path
                assert post.unprocessed_audio_path == "/path/to/existing.mp3"
                mock_db_session.commit.assert_called()

                # Verify the function returned the processed audio path
                assert result == "/path/to/processed.mp3"

    @patch("app.processor.PodcastProcessor")
    def test_download_and_process_post_processing_needed(
        self, mock_processor_class, app, mock_db_session, test_config
    ):
        """Test download_and_process_post when processing is needed."""
        with app.app_context():
            # Create a test post
            feed = Feed(id=1, title="Test Feed")
            post = Post(
                id=1,
                guid="test-guid",
                title="Test Post",
                whitelisted=True,
                unprocessed_audio_path="/path/to/unprocessed.mp3",
                processed_audio_path=None,
                feed=feed,
            )

            # Setup the processor mock
            mock_processor_instance = mock_processor_class.return_value
            mock_processor_instance.process.return_value = "/path/to/processed.mp3"

            # Mock operations
            with patch("pathlib.Path.exists") as mock_exists, patch(
                "pathlib.Path.stat"
            ), patch("app.posts.Post.query") as mock_query, patch(
                "app.posts.db"
            ) as mock_db, patch(
                "app.posts.sanitize_title"
            ) as mock_sanitize, patch(
                "app.processor.config", test_config
            ):
                # Configure mocks
                mock_exists.return_value = False  # File doesn't exist
                mock_sanitize.return_value = "test_post.mp3"

                # Set up mock query
                mock_query.filter_by.return_value.first.return_value = post
                mock_db.session = mock_db_session

                # Call the function
                result = download_and_process_post("test-guid")

                # Verify post was updated
                assert post.processed_audio_path == "/path/to/processed.mp3"
                mock_db_session.commit.assert_called()

                # Verify the function returned the processed audio path
                assert result == "/path/to/processed.mp3"

    def test_download_and_process_post_existing_processed(self, app, mock_db_session):
        """Test download_and_process_post when processed file already exists on disk."""
        with app.app_context():
            # Create a test post
            feed = Feed(id=1, title="Test Feed")
            post = Post(
                id=1,
                guid="test-guid",
                title="Test Post",
                whitelisted=True,
                unprocessed_audio_path="/path/to/unprocessed.mp3",
                processed_audio_path=None,
                feed=feed,
            )

            # Create a stat result with non-zero size
            stat_result = os.stat_result((0, 0, 0, 0, 0, 0, 10000, 0, 0, 0))

            # Mock operations
            with patch("pathlib.Path.exists") as mock_exists, patch(
                "pathlib.Path.stat"
            ) as mock_stat, patch("pathlib.Path.resolve") as mock_resolve, patch(
                "app.posts.Post.query"
            ) as mock_query, patch(
                "app.posts.db"
            ) as mock_db, patch(
                "app.posts.sanitize_title"
            ) as mock_sanitize:

                # Configure mocks
                mock_exists.return_value = True  # File exists
                mock_stat.return_value = stat_result  # Non-zero size
                mock_resolve.return_value = Path("/path/to/existing_processed.mp3")
                mock_sanitize.side_effect = lambda t: f"{t.lower()}.mp3"

                # Set up mock query
                mock_query.filter_by.return_value.first.return_value = post
                mock_db.session = mock_db_session

                # Call the function
                result = download_and_process_post("test-guid")

                # Verify post was updated with existing file path
                assert post.processed_audio_path == "/path/to/existing_processed.mp3"
                mock_db_session.commit.assert_called()

                # Verify the function returned the processed audio path
                assert result == "/path/to/existing_processed.mp3"
