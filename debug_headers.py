#!/usr/bin/env python3
"""
Debug script to check what headers the Flask app is receiving.
This will help diagnose reverse proxy header issues.
"""

from flask import Flask, Response, jsonify, request

app = Flask(__name__)


@app.route("/debug/headers")
def debug_headers() -> Response:
    """Return all request headers for debugging."""
    return jsonify(
        {
            "all_headers": dict(request.headers),
            "remote_addr": request.remote_addr,
            "host": request.host,
            "url": request.url,
            "base_url": request.base_url,
            "url_root": request.url_root,
            "is_secure": request.is_secure,
            "scheme": request.scheme,
            "forwarded_headers": {
                "X-Forwarded-Host": request.headers.get("X-Forwarded-Host"),
                "X-Forwarded-Proto": request.headers.get("X-Forwarded-Proto"),
                "X-Forwarded-Port": request.headers.get("X-Forwarded-Port"),
                "X-Forwarded-For": request.headers.get("X-Forwarded-For"),
                "X-Real-IP": request.headers.get("X-Real-IP"),
                "Host": request.headers.get("Host"),
            },
        }
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
