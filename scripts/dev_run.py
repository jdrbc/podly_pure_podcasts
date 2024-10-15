import subprocess
from typing import Optional

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer


# workaround some bug in flask dev server causing incompatibility with SQLAlchemy
class ChangeHandler(FileSystemEventHandler):
    def __init__(self, cmd: str) -> None:  #
        self.cmd: str = cmd
        self.process: Optional[subprocess.Popen] = None  # type: ignore
        self.start_process()

    def start_process(self) -> None:
        if self.process:
            self.process.terminate()
        with subprocess.Popen(self.cmd, shell=True) as process:
            self.process = process

    def on_any_event(self, event: FileSystemEvent) -> None:
        if "src/instance" not in event.src_path:
            self.start_process()


if __name__ == "__main__":
    command: str = "pipenv run python src/main.py"
    event_handler: ChangeHandler = ChangeHandler(command)
    observer: Observer = Observer()  # type: ignore
    observer.schedule(event_handler, path="src", recursive=True)  # type: ignore
    observer.start()  # type: ignore
    try:
        while True:
            pass
    except KeyboardInterrupt:
        observer.stop()  # type: ignore
    observer.join()  # type: ignore
