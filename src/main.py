from waitress import serve

from app import config, create_app


def main() -> None:
    """Main entry point for the application."""
    app = create_app()

    # Start the application server
    serve(
        app,
        host=config.host,
        threads=config.threads,
        port=config.port,
    )


if __name__ == "__main__":
    main()
