import os
import subprocess
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler


# workaround some bug in flask dev server causing incompatibility with SQLAlchemy
class ChangeHandler(FileSystemEventHandler):
    def __init__(self, command):
        self.command = command
        self.process = None
        self.start_process()

    def start_process(self):
        if self.process:
            self.process.terminate()
        self.process = subprocess.Popen(self.command, shell=True)

    def on_any_event(self, event):
        if "src/instance" in event.src_path:
            print("Ignoring event from srv/instance directory")
            return
        else:
            self.start_process()


if __name__ == "__main__":
    command = "pipenv run python src/main.py"
    event_handler = ChangeHandler(command)
    observer = Observer()
    observer.schedule(event_handler, path="src", recursive=True)
    observer.start()
    try:
        while True:
            pass
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
