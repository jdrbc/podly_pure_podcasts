import pytest
from flask import Flask

from app import create_app
from app import db as _db  # Alias db to avoid pytest conflict
from app.models import (  # Import Feed if needed for setup/teardown, added Post
    Feed,
    Post,
)


@pytest.fixture(scope="function")
def app(mocker):
    """Function-scoped test Flask application."""
    # Mock PodcastProcessor in its original module before app.routes imports it
    mocker.patch("podcast_processor.podcast_processor.PodcastProcessor", autospec=True)

    _app = create_app()
    _app.config.update(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",  # Use an in-memory SQLite DB for tests
            "WTF_CSRF_ENABLED": False,  # Disable CSRF for simpler form testing if applicable
            "DEBUG": False,
            "BACKGROUND_UPDATE_INTERVAL_MINUTE": None,  # Disable background updates
        }
    )

    with _app.app_context():
        _db.create_all()  # Create database tables

    yield _app

    with _app.app_context():
        _db.drop_all()  # Drop database tables after tests


@pytest.fixture()
def client(app: Flask):
    """A test client for the app."""
    return app.test_client()


def test_index_route(client):
    """Test the index route."""
    response = client.get("/")
    assert response.status_code == 200
    assert b"Podly" in response.data  # A general term likely to be on the index page
    assert b"Feeds" in response.data  # Assuming "Feeds" is a heading or common text


# Add a simple test for the /feeds API endpoint
def test_api_feeds_route_empty(client):
    """Test the /feeds API route when no feeds exist."""
    response = client.get("/feeds")
    assert response.status_code == 200
    assert response.json == []


def test_api_feeds_route_with_data(client, app: Flask):
    """Test the /feeds API route with some data."""
    with app.app_context():
        feed1 = Feed(title="Test Feed 1", rss_url="http://example.com/feed1.xml")
        feed2 = Feed(title="Test Feed 2", rss_url="http://example.com/feed2.xml")
        _db.session.add_all([feed1, feed2])
        _db.session.commit()
        # We need to get the IDs after they are committed
        feed1_id = feed1.id
        feed2_id = feed2.id

    response = client.get("/feeds")
    assert response.status_code == 200
    expected_data = [
        {
            "id": feed1_id,
            "rss_url": "http://example.com/feed1.xml",
            "title": "Test Feed 1",
        },
        {
            "id": feed2_id,
            "rss_url": "http://example.com/feed2.xml",
            "title": "Test Feed 2",
        },
    ]
    # The order might not be guaranteed by the query, so check contents
    assert len(response.json) == len(expected_data)
    for item in expected_data:
        assert item in response.json


# Tests for POST /feed
def test_add_feed_success(client, mocker):
    """Test successfully adding a new feed."""
    # Mock add_or_refresh_feed to simulate successful feed addition
    mocked_add_feed = mocker.patch("app.routes.add_or_refresh_feed")
    new_feed = Feed(
        id=3, title="Newly Added Feed", rss_url="http://new.example.com/feed.xml"
    )
    mocked_add_feed.return_value = new_feed

    response = client.post(
        "/feed", data={"url": "http://new.example.com/feed.xml"}, follow_redirects=False
    )

    assert response.status_code == 302  # Expect a redirect to index
    assert response.location == "/"  # Check if it redirects to the root/index
    mocked_add_feed.assert_called_once_with("http://new.example.com/feed.xml")
    # We could also query the DB if we weren't fully mocking add_or_refresh_feed
    # but since it handles DB commit, mocking its outcome is cleaner here.


def test_add_feed_invalid_url(client, mocker):
    """Test adding a feed with an invalid URL format (mocking ValueError)."""
    mocker.patch(
        "app.routes.add_or_refresh_feed", side_effect=ValueError("Invalid feed URL")
    )

    response = client.post("/feed", data={"url": "not_a_valid_url"})

    assert response.status_code == 400
    assert response.json == {"error": "Invalid feed URL"}


def test_add_feed_missing_url(client):
    """Test adding a feed with no URL provided."""
    response = client.post("/feed", data={})

    assert response.status_code == 400
    assert response.json == {"error": "URL is required"}


# Tests for GET /post/<string:p_guid>.html
def test_get_post_page_success(client, app):
    """Test getting an existing post page."""
    with app.app_context():
        # Create a dummy feed first
        dummy_feed = Feed(
            title="Dummy Feed for Post", rss_url="http://dummy.com/feed.xml"
        )
        _db.session.add(dummy_feed)
        _db.session.commit()  # Commit to get dummy_feed.id

        test_post = Post(
            feed_id=dummy_feed.id,
            guid="test-guid-123",
            title="Test Post Title",
            description="<p>Hello</p>",
            download_url="http://dummy.com/episode.mp3",
        )
        _db.session.add(test_post)
        _db.session.commit()
        post_guid = test_post.guid  # Store guid after commit, just in case

    response = client.get(f"/post/{post_guid}.html")
    assert response.status_code == 200
    assert b"Test Post Title" in response.data
    assert (
        b"&lt;p&gt;Hello&lt;/p&gt;" not in response.data
    )  # Ensure description is cleaned or rendered, not raw with unescaped html
    assert b"<p>Hello</p>" in response.data


def test_get_post_page_not_found(client):
    """Test getting a non-existent post page."""
    response = client.get("/post/non-existent-guid.html")
    assert response.status_code == 404
    assert b"Post not found" in response.data


# Tests for GET /post/<string:p_guid>.mp3
def test_download_post_mp3_success(client, app, mocker):
    """Test successfully downloading a processed mp3."""
    post_guid = "test-dl-guid-123"
    with app.app_context():
        dummy_feed = Feed(
            title="Dummy Feed for DL", rss_url="http://dummy-dl.com/feed.xml"
        )
        _db.session.add(dummy_feed)
        _db.session.commit()
        # Create a whitelisted post
        test_post = Post(
            feed_id=dummy_feed.id,
            guid=post_guid,
            title="Test Download Post",
            whitelisted=True,
            download_url="http://dummy-dl.com/episode.mp3",
        )
        _db.session.add(test_post)
        _db.session.commit()

    # Mock download_and_process to return success and a dummy path
    mock_dl_process = mocker.patch("app.routes.download_and_process")
    mock_dl_process.return_value = {
        "status": "success",
        "message": "/fake/path/to/audio.mp3",
    }

    # Mock send_file as we are not testing actual file sending here
    mock_send_file = mocker.patch(
        "app.routes.send_file",
        return_value=Flask("test").make_response(("fake mp3 content", 200)),
    )

    response = client.get(f"/post/{post_guid}.mp3")
    assert response.status_code == 200
    assert b"fake mp3 content" in response.data
    mock_dl_process.assert_called_once()
    # The actual Post object will be different in the call, so we check the guid
    assert mock_dl_process.call_args[0][0].guid == post_guid
    mock_send_file.assert_called_once_with(
        path_or_file=mocker.ANY
    )  # Path object comparison can be tricky


def test_download_post_mp3_not_whitelisted(client, app):
    """Test downloading an mp3 for a non-whitelisted post."""
    post_guid = "test-dl-guid-456"
    with app.app_context():
        dummy_feed = Feed(
            title="Dummy Feed for DL NW", rss_url="http://dummy-dl-nw.com/feed.xml"
        )
        _db.session.add(dummy_feed)
        _db.session.commit()
        test_post = Post(
            feed_id=dummy_feed.id,
            guid=post_guid,
            title="Test Non-Whitelist Post",
            whitelisted=False,
            download_url="http://dummy-dl-nw.com/episode.mp3",
        )
        _db.session.add(test_post)
        _db.session.commit()

    response = client.get(f"/post/{post_guid}.mp3")
    assert response.status_code == 403
    assert b"Episode not whitelisted" in response.data


def test_download_post_mp3_processing_failed(client, app, mocker):
    """Test mp3 download when download_and_process fails."""
    post_guid = "test-dl-guid-789"
    with app.app_context():
        dummy_feed = Feed(
            title="Dummy Feed for DL Fail", rss_url="http://dummy-dl-fail.com/feed.xml"
        )
        _db.session.add(dummy_feed)
        _db.session.commit()
        test_post = Post(
            feed_id=dummy_feed.id,
            guid=post_guid,
            title="Test Fail Post",
            whitelisted=True,
            download_url="http://dummy-dl-fail.com/episode.mp3",
        )
        _db.session.add(test_post)
        _db.session.commit()

    mock_dl_process = mocker.patch("app.routes.download_and_process")
    mock_dl_process.return_value = {
        "status": "failed",
        "message": "Processing error occurred",
    }

    response = client.get(f"/post/{post_guid}.mp3")
    assert response.status_code == 500
    assert b"Processing error occurred" in response.data


# Tests for DELETE /feed/<int:f_id>
def test_delete_feed_success(client, app):
    """Test successfully deleting a feed."""
    with app.app_context():
        feed_to_delete = Feed(
            title="Feed To Delete", rss_url="http://delete.me/feed.xml"
        )
        _db.session.add(feed_to_delete)
        _db.session.commit()
        feed_id = feed_to_delete.id

    response = client.delete(f"/feed/{feed_id}")
    assert response.status_code == 204

    with app.app_context():
        assert Feed.query.get(feed_id) is None


def test_delete_feed_not_found(client):
    """Test deleting a non-existent feed."""
    response = client.delete("/feed/99999")  # Assuming 99999 does not exist
    assert response.status_code == 404


# Tests for fix_url utility function
@pytest.mark.parametrize(
    "input_url, expected_url",
    [
        ("example.com", "https://example.com"),
        ("http:/example.com", "http://example.com"),
        ("https:/example.com", "https://example.com"),
        ("http://example.com", "http://example.com"),
        ("https://example.com", "https://example.com"),
        (
            "badprotocol:/test.com",
            "https://badprotocol:/test.com",
        ),  # Keeps existing if not http/https prefix needed
        ("http:/www.example.com/feed", "http://www.example.com/feed"),
        ("https:/www.example.com/feed", "https://www.example.com/feed"),
    ],
)
def test_fix_url(input_url, expected_url):
    from app.routes import (  # Import locally to avoid context error during collection
        fix_url,
    )

    assert fix_url(input_url) == expected_url


def test_whitelist_all_feed_not_found(client):
    """Test toggle-whitelist-all for a non-existent feed."""
    response = client.post("/feed/99999/toggle-whitelist-all/true")
    assert response.status_code == 404


# Tests for GET /set_whitelist/<string:p_guid>/<val>
def test_set_whitelist_for_post(client, app):
    """Test setting whitelist status for a single post."""
    with app.app_context():
        feed = Feed(
            title="Test Feed for Set Whitelist", rss_url="http://setwhitelist.com/f.xml"
        )
        _db.session.add(feed)
        _db.session.commit()
        post = Post(
            feed_id=feed.id,
            guid="set_wl_post1",
            title="Set WL Post",
            whitelisted=False,
            download_url="http://setwl.com/p1.mp3",
        )
        _db.session.add(post)
        _db.session.commit()
        post_id = post.id
        post_guid = post.guid

    # Set to true
    response_true = client.get(f"/set_whitelist/{post_guid}/true")
    assert response_true.status_code == 200  # Returns index
    assert b"Podly" in response_true.data  # Check if index page content is present
    with app.app_context():
        assert Post.query.get(post_id).whitelisted is True

    # Set to false
    response_false = client.get(f"/set_whitelist/{post_guid}/false")
    assert response_false.status_code == 200
    with app.app_context():
        assert Post.query.get(post_id).whitelisted is False


def test_set_whitelist_post_not_found(client):
    """Test set_whitelist for a non-existent post."""
    response = client.get("/set_whitelist/non-existent-guid/true")
    assert response.status_code == 404  # Expects post not found from the route
    assert b"Post not found" in response.data


# Tests for GET /post/<string:p_guid>/original.mp3
def test_download_original_post_success(client, app, mocker):
    """Test successfully downloading an original mp3."""
    post_guid = "orig-dl-guid-123"
    fake_path = "/fake/path/to/original_audio.mp3"
    with app.app_context():
        dummy_feed = Feed(
            title="Dummy Feed for Orig DL", rss_url="http://dummy-orig-dl.com/feed.xml"
        )
        _db.session.add(dummy_feed)
        _db.session.commit()
        test_post = Post(
            feed_id=dummy_feed.id,
            guid=post_guid,
            title="Test Original Download Post",
            whitelisted=True,
            unprocessed_audio_path=fake_path,
            download_url="http://dummy-orig-dl.com/ep.mp3",
        )
        _db.session.add(test_post)
        _db.session.commit()

    # Mock Path.exists() and Path.resolve() as we are not working with real files
    mocker.patch("app.routes.Path.exists", return_value=True)
    mocker.patch("app.routes.Path.resolve", return_value=fake_path)
    mock_send_file = mocker.patch(
        "app.routes.send_file",
        return_value=Flask("test").make_response(("fake original mp3 content", 200)),
    )

    response = client.get(f"/post/{post_guid}/original.mp3")
    assert response.status_code == 200
    assert b"fake original mp3 content" in response.data
    mock_send_file.assert_called_once_with(path_or_file=fake_path)


def test_download_original_post_not_whitelisted(client, app):
    """Test downloading an original mp3 for a non-whitelisted post."""
    post_guid = "orig-dl-guid-456"
    with app.app_context():
        dummy_feed = Feed(
            title="Dummy Feed for Orig DL NW",
            rss_url="http://dummy-orig-dl-nw.com/f.xml",
        )
        _db.session.add(dummy_feed)
        _db.session.commit()
        test_post = Post(
            feed_id=dummy_feed.id,
            guid=post_guid,
            title="Test Orig Non-Whitelist Post",
            whitelisted=False,
            download_url="http://dummy-orig-dl-nw.com/ep.mp3",
        )
        _db.session.add(test_post)
        _db.session.commit()

    response = client.get(f"/post/{post_guid}/original.mp3")
    assert response.status_code == 403
    assert b"Episode not whitelisted" in response.data
