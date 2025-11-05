from __future__ import annotations

import base64
from urllib.parse import urlparse

import pytest
from flask import Flask, Response, g, jsonify

from app.auth import AuthSettings
from app.auth.middleware import init_auth_middleware
from app.auth.state import failure_rate_limiter
from app.extensions import db
from app.models import Feed, Post, User
from app.routes.auth_routes import auth_bp
from app.routes.feed_routes import feed_bp


@pytest.fixture
def auth_app() -> Flask:
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY="test-secret",
        SESSION_COOKIE_NAME="podly_session",
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )

    settings = AuthSettings(
        require_auth=True,
        admin_username="admin",
        admin_password="password",
    )
    app.config["AUTH_SETTINGS"] = settings
    app.config["REQUIRE_AUTH"] = True

    db.init_app(app)
    with app.app_context():
        db.create_all()
        user = User(username="admin", role="admin")
        user.set_password("password")
        db.session.add(user)
        db.session.commit()

    failure_rate_limiter._storage.clear()

    init_auth_middleware(app)
    app.register_blueprint(auth_bp)
    app.register_blueprint(feed_bp)

    @app.route("/api/protected", methods=["GET"])
    def protected() -> Response:
        current = getattr(g, "current_user", None)
        if current is None:
            return jsonify({"error": "missing user"}), 500
        return jsonify({"status": "ok", "user": current.username})

    @app.route("/feed/1", methods=["GET"])
    def feed() -> Response:
        current = getattr(g, "current_user", None)
        if current is None:
            return Response("missing user", status=500)
        return Response("ok", mimetype="text/plain")

    @app.route("/api/posts/<string:guid>/download", methods=["GET"])
    def download(guid: str) -> Response:
        del guid
        current = getattr(g, "current_user", None)
        if current is None:
            return Response("missing user", status=500)
        return Response("download", mimetype="text/plain")

    yield app

    with app.app_context():
        db.session.remove()
        db.drop_all()


def _encode_basic(username: str, password: str) -> str:
    encoded = base64.b64encode(f"{username}:{password}".encode("utf-8"))
    return f"Basic {encoded.decode('utf-8')}"


def test_login_sets_session_cookie_and_allows_authenticated_requests(
    auth_app: Flask,
) -> None:
    client = auth_app.test_client()

    response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "password"},
    )
    assert response.status_code == 200
    set_cookie = response.headers.get("Set-Cookie", "")
    assert "podly_session" in set_cookie

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.get_json()["user"]["username"] == "admin"

    protected = client.get("/api/protected")
    assert protected.status_code == 200
    assert protected.get_json()["status"] == "ok"


def test_logout_clears_session(auth_app: Flask) -> None:
    client = auth_app.test_client()
    client.post("/api/auth/login", json={"username": "admin", "password": "password"})

    response = client.post("/api/auth/logout")
    assert response.status_code == 204

    protected = client.get("/api/protected")
    assert protected.status_code == 401
    assert protected.headers.get("WWW-Authenticate") is None


def test_protected_route_without_session_returns_json_401(auth_app: Flask) -> None:
    client = auth_app.test_client()
    response = client.get("/api/protected")
    assert response.status_code == 401
    assert response.get_json()["error"] == "Authentication required."
    assert response.headers.get("WWW-Authenticate") is None


def test_feed_allows_basic_auth_when_no_session(auth_app: Flask) -> None:
    client = auth_app.test_client()

    unauthorized = client.get("/feed/1")
    assert unauthorized.status_code == 401
    assert unauthorized.headers.get("WWW-Authenticate", "").startswith("Basic ")

    authorized = client.get(
        "/feed/1",
        headers={"Authorization": _encode_basic("admin", "password")},
    )
    assert authorized.status_code == 200
    assert authorized.data == b"ok"


def test_share_link_generates_token_and_allows_basic_access(auth_app: Flask) -> None:
    client = auth_app.test_client()
    with auth_app.app_context():
        feed = Feed(title="Example", rss_url="https://example.com/feed.xml")
        db.session.add(feed)
        db.session.commit()
        feed_id = feed.id

        post = Post(
            feed_id=feed_id,
            guid="episode-1",
            download_url="https://example.com/audio.mp3",
            title="Episode",
            whitelisted=True,
        )
        db.session.add(post)
        db.session.commit()

    client.post("/api/auth/login", json={"username": "admin", "password": "password"})
    share = client.post(f"/api/feeds/{feed_id}/share-link")
    assert share.status_code == 201
    payload = share.get_json()
    assert payload["feed_id"] == feed_id

    parsed = urlparse(payload["url"])
    assert parsed.username and parsed.username.startswith("feed-")
    assert parsed.password

    header = "Basic " + base64.b64encode(
        f"{parsed.username}:{parsed.password}".encode("utf-8")
    ).decode("utf-8")

    feed_response = client.get(f"/feed/{feed_id}", headers={"Authorization": header})
    assert feed_response.status_code == 200

    download_response = client.get(
        "/api/posts/episode-1/download", headers={"Authorization": header}
    )
    assert download_response.status_code == 200
