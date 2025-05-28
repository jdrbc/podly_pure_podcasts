from unittest.mock import MagicMock, patch

from app.jobs import (
    clean_download_path,
    clean_download_paths,
    clean_inconsistent_posts,
    clean_post,
    process_post,
    refresh_all_feeds,
    run_refresh_all_feeds,
)
from app.models import Feed, Post
from app.timeout_decorator import TimeoutException


class TestJobFunctions:
    """Test class for job functions in the app.jobs module."""

    @patch("app.jobs.refresh_all_feeds")
    @patch("app.jobs.scheduler")
    def test_run_refresh_all_feeds(self, mock_scheduler, mock_refresh_all_feeds):
        """Test run_refresh_all_feeds calls refresh_all_feeds within app context."""
        # Create a mock app and context manager
        mock_app = MagicMock()
        mock_context = MagicMock()
        mock_app.app_context.return_value = mock_context
        mock_scheduler.app = mock_app

        # Run the function
        run_refresh_all_feeds()

        # Verify app context was used and refresh_all_feeds was called
        mock_app.app_context.assert_called_once()
        mock_refresh_all_feeds.assert_called_once()

    @patch("app.jobs.download_and_process_post")
    @patch("app.jobs.remove_associated_files")
    @patch("app.jobs.scheduler")
    def test_process_post(
        self, mock_scheduler, mock_remove_files, mock_download_process
    ):
        """Test process_post removes files and processes a post."""
        # Create a mock app and context manager
        mock_app = MagicMock()
        mock_context = MagicMock()
        mock_app.app_context.return_value = mock_context
        mock_scheduler.app = mock_app

        # Create a test post
        post = Post(id=1, title="Test Post", guid="test-guid")

        # Call the function
        process_post(post)

        # Verify app context was used
        mock_app.app_context.assert_called_once()

        # Verify functions were called correctly
        mock_remove_files.assert_called_once_with(post)
        mock_download_process.assert_called_once_with(post.guid)

    def test_clean_download_path_no_url(self, app):
        """Test clean_download_path when download_url is missing."""
        with app.app_context():
            # Create a post without download_url
            post = Post(id=1, title="Test Post", download_url=None)

            with patch("app.jobs.logger") as mock_logger:
                clean_download_path(post)
                mock_logger.error.assert_called_once()

    @patch("os.path.exists")
    @patch("os.remove")
    def test_clean_download_path_with_file(self, mock_remove, mock_exists, app):
        """Test clean_download_path with existing file."""
        with app.app_context():
            # Create a test post with processed_audio_path=None but unprocessed_audio_path exists
            post = Post(
                id=1,
                title="Test Post",
                download_url="https://example.com/audio.mp3",
                unprocessed_audio_path="/path/to/audio.mp3",
                processed_audio_path=None,
            )

            # Mock os.path.exists to return True
            mock_exists.return_value = True

            with patch("app.jobs.logger") as mock_logger:
                clean_download_path(post)

                # Verify file was deleted
                mock_remove.assert_called_once_with(post.unprocessed_audio_path)
                mock_logger.info.assert_called_once()

    @patch("os.path.exists")
    @patch("os.remove")
    def test_clean_download_path_remove_error(self, mock_remove, mock_exists, app):
        """Test clean_download_path with file removal error."""
        with app.app_context():
            # Create a test post
            post = Post(
                id=1,
                title="Test Post",
                download_url="https://example.com/audio.mp3",
                unprocessed_audio_path="/path/to/audio.mp3",
                processed_audio_path=None,
            )

            # Mock os.path.exists to return True
            mock_exists.return_value = True

            # Mock os.remove to raise an OSError
            mock_remove.side_effect = OSError("Permission denied")

            with patch("app.jobs.logger") as mock_logger:
                clean_download_path(post)

                # Verify error was logged
                mock_logger.error.assert_called_once()

    def test_clean_download_paths(self, app):
        """Test clean_download_paths calls clean_download_path for each post."""
        with app.app_context():
            # Create test posts
            post1 = Post(id=1, title="Test Post 1")
            post2 = Post(id=2, title="Test Post 2")
            posts = [post1, post2]

            with patch("app.jobs.clean_download_path") as mock_clean:
                clean_download_paths(posts)

                # Verify clean_download_path was called for each post
                assert mock_clean.call_count == 2
                mock_clean.assert_any_call(post1)
                mock_clean.assert_any_call(post2)

    @patch("os.path.exists")
    def test_clean_post_missing_processed_file(self, mock_exists, app, mock_db_session):
        """Test clean_post when processed audio file is missing."""
        with app.app_context():
            # Create a test post with processed_audio_path that doesn't exist
            post = Post(
                id=1,
                title="Test Post",
                processed_audio_path="/path/to/processed/audio.mp3",
            )

            # Mock os.path.exists to return False for processed file
            mock_exists.return_value = False

            with patch("app.jobs.db") as mock_db, patch(
                "app.jobs.logger"
            ) as mock_logger:
                mock_db.session = mock_db_session

                clean_post(post)

                # Verify post processed_audio_path was set to None
                assert post.processed_audio_path is None
                mock_db_session.commit.assert_called_once()
                mock_logger.warning.assert_called_once()

    def test_clean_inconsistent_posts(self, app):
        """Test clean_inconsistent_posts calls clean_post for each post."""
        with app.app_context():
            # Create test posts
            post1 = Post(id=1, title="Test Post 1")
            post2 = Post(id=2, title="Test Post 2")
            posts = [post1, post2]

            with patch("app.jobs.clean_post") as mock_clean:
                clean_inconsistent_posts(posts)

                # Verify clean_post was called for each post
                assert mock_clean.call_count == 2
                mock_clean.assert_any_call(post1)
                mock_clean.assert_any_call(post2)

    @patch("app.jobs.refresh_feed")
    @patch("app.models.Feed.query")
    @patch("app.models.Post.query")
    @patch("app.jobs.clean_inconsistent_posts")
    @patch("app.jobs.clean_download_paths")
    def test_refresh_all_feeds_basic(
        self,
        mock_clean_paths,
        mock_clean_inconsistent,
        mock_post_query,
        mock_feed_query,
        mock_refresh_feed,
        app,
    ):
        """Test basic functionality of refresh_all_feeds."""
        with app.app_context():
            # Create test feeds
            feed1 = Feed(id=1, title="Test Feed 1")
            feed2 = Feed(id=2, title="Test Feed 2")
            feeds = [feed1, feed2]

            # Create test posts - no new posts to process
            mock_feed_query.all.return_value = feeds
            mock_post_query.filter.return_value.all.return_value = []

            # Call the function
            refresh_all_feeds()

            # Verify refresh_feed was called for each feed
            assert mock_refresh_feed.call_count == 2
            mock_refresh_feed.assert_any_call(feed1)
            mock_refresh_feed.assert_any_call(feed2)

            # Verify clean functions were called
            mock_clean_inconsistent.assert_called_once()

            # No posts to process, so ThreadPoolExecutor shouldn't be used
            assert not mock_clean_paths.called

    @patch("app.jobs.refresh_feed")
    @patch("app.models.Feed.query")
    def test_refresh_all_feeds_timeout(self, mock_feed_query, mock_refresh_feed, app):
        """Test refresh_all_feeds handles timeout exceptions."""
        with app.app_context():
            # Make refresh_feed raise a TimeoutException
            mock_refresh_feed.side_effect = TimeoutException("Job timed out")

            # Create test feeds
            feed1 = Feed(id=1, title="Test Feed 1")
            feeds = [feed1]
            mock_feed_query.all.return_value = feeds

            with patch("app.jobs.logger") as mock_logger:
                # Call the function - it should handle the exception
                refresh_all_feeds()

                # Verify the error was logged
                mock_logger.error.assert_called_once()
                assert "Job timed out" in mock_logger.error.call_args[0][0]
