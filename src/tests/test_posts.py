from pathlib import Path
from unittest.mock import patch

from app.models import Post
from app.posts import remove_associated_files
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
