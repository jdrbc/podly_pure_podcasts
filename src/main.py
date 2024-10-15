from waitress import serve

from app import config, create_app

app = create_app()


def main() -> None:
    serve(
        app,
        host="0.0.0.0",
        threads=config.threads,
        port=config.server_port,
    )


if __name__ == "__main__":
    main()
