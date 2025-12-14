import os

from waitress import serve

from app import create_web_app


def main() -> None:
    """Main entry point for the application."""
    app = create_web_app()

    # Start the application server
    threads_env = os.environ.get("SERVER_THREADS")
    try:
        threads = int(threads_env) if threads_env is not None else 1
    except ValueError:
        threads = 1

    port = os.environ.get("PORT", 5001)
    serve(
        app,
        host="0.0.0.0",
        port=port,
        threads=threads,
    )


if __name__ == "__main__":
    main()
