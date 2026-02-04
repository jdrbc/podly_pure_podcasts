from types import SimpleNamespace
from unittest import mock

from app.routes.feed_utils import whitelist_latest_for_first_member


def test_whitelist_latest_for_first_member_skips_when_auto_whitelist_disabled(
    monkeypatch,
):
    monkeypatch.setattr(
        "app.feeds._should_auto_whitelist_new_posts", lambda feed: False
    )
    mock_writer = mock.MagicMock()
    monkeypatch.setattr("app.routes.feed_utils.writer_client", mock_writer)

    whitelist_latest_for_first_member(SimpleNamespace(id=1), 7)

    mock_writer.action.assert_not_called()


def test_whitelist_latest_for_first_member_enqueues_when_enabled(monkeypatch):
    monkeypatch.setattr("app.feeds._should_auto_whitelist_new_posts", lambda feed: True)
    mock_writer = mock.MagicMock()
    mock_writer.action.return_value = SimpleNamespace(
        success=True, data={"updated": True, "post_guid": "abc-123"}
    )
    monkeypatch.setattr("app.routes.feed_utils.writer_client", mock_writer)
    mock_jobs = mock.MagicMock()
    monkeypatch.setattr("app.routes.feed_utils.get_jobs_manager", lambda: mock_jobs)

    whitelist_latest_for_first_member(SimpleNamespace(id=5), 11)

    mock_writer.action.assert_called_once_with(
        "whitelist_latest_post_for_feed", {"feed_id": 5}, wait=True
    )
    mock_jobs.start_post_processing.assert_called_once_with(
        "abc-123",
        priority="interactive",
        requested_by_user_id=11,
        billing_user_id=11,
    )
