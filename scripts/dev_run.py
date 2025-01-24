import os
import subprocess
from typing import Optional

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer


# pipenv run python scripts/dev_run.py
#
# This script will restart the server every time a file in the src directory is modified
# workaround some bug in flask dev server causing incompatibility with SQLAlchemy
class ChangeHandler(FileSystemEventHandler):
    def __init__(self, cmd: str) -> None:
        self.cmd: str = cmd
        self.process: Optional[subprocess.Popen] = None  # type: ignore[type-arg]
        self.start_process()

    def start_process(self) -> None:
        print("start process")
        if self.process:
            print("Terminating existing process")
            self.process.terminate()
            self.process.wait()  # Ensure the process has terminated
        self.process = subprocess.Popen(  # pylint: disable=consider-using-with
            self.cmd, shell=True
        )
        print(f"Process started with PID: {self.process.pid}")

    def on_any_event(self, event: FileSystemEvent) -> None:
        if "src/instance" not in event.src_path:
            self.start_process()


if __name__ == "__main__":
    command: str = "pipenv run python src/main.py"
    event_handler: ChangeHandler = ChangeHandler(command)
    observer: Observer = Observer()  # type: ignore
    src_path = os.path.abspath("src")
    print(f"Watching directory: {src_path}")
    observer.schedule(event_handler, path=src_path, recursive=True)  # type: ignore
    observer.start()  # type: ignore
    try:
        while True:
            pass
    except KeyboardInterrupt:
        observer.stop()  # type: ignore
    observer.join()  # type: ignore
