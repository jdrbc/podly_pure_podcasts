from waitress import serve

from app import config, create_app


def main() -> None:
    """Main entry point for the application."""
    app = create_app()

    # Start the application server
    serve(
        app,
        host="0.0.0.0",
        threads=config.threads,
        port=config.server_port,
    )


if __name__ == "__main__":
    main()
