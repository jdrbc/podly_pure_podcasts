from waitress import serve

from app import config, create_app


def main() -> None:
    app = create_app()

    serve(
        app,
        host="0.0.0.0",
        threads=config.threads,
        port=config.server_port,
    )


if __name__ == "__main__":
    main()
