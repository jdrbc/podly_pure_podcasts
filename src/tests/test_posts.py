from pathlib import Path
from unittest.mock import patch

from app.models import Post
from app.posts import remove_associated_files


class TestPostsFunctions:
    """Test class for functions in the app.posts module."""

    @patch("app.posts._remove_file_if_exists")
    @patch("app.posts._dedupe_and_find_existing")
    @patch("app.posts._collect_processed_paths")
    @patch("app.posts.get_and_make_download_path")
    @patch("app.posts.logger")
    def test_remove_associated_files_files_dont_exist(
        self,
        mock_logger,
        mock_get_download_path,
        mock_collect_paths,
        mock_dedupe,
        mock_remove_file,
        app,
    ):
        """Test remove_associated_files when files don't exist."""
        with app.app_context():
            # Set up mocks
            mock_collect_paths.return_value = [Path("/path/to/processed.mp3")]
            mock_dedupe.return_value = (
                [Path("/path/to/processed.mp3")],
                None,  # No existing file found
            )
            mock_get_download_path.return_value = "/path/to/unprocessed.mp3"

            # Create test post
            post = Post(id=1, title="Test Post")

            # Call the function
            remove_associated_files(post)

            # Verify _remove_file_if_exists was called for unprocessed path
            assert mock_remove_file.call_count >= 1

            # Verify debug logging for no processed file
            mock_logger.debug.assert_called()
