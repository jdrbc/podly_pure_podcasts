import os
import subprocess
import threading
import time
from typing import Dict, Optional

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer


# pipenv run python scripts/dev_run.py
#
# This script will run both the backend Flask server and frontend React dev server
# It watches for changes in both src/ and frontend/src/ directories and restarts appropriately
class ProcessManager:
    def __init__(self):
        self.processes: Dict[str, Optional[subprocess.Popen]] = {
            "backend": None,
            "frontend": None,
        }

    def start_backend(self) -> None:
        print("Starting backend process...")
        if self.processes["backend"]:
            print("Terminating existing backend process")
            self.processes["backend"].terminate()
            self.processes["backend"].wait()

        # Set up environment with CORS origins for development (allow all origins)
        env = os.environ.copy()
        env["CORS_ORIGINS"] = "*"

        self.processes["backend"] = subprocess.Popen(
            "pipenv run python src/main.py", shell=True, cwd=os.getcwd(), env=env
        )
        print(f"Backend started with PID: {self.processes['backend'].pid}")
        print("CORS configured for: all origins")

    def start_frontend(self) -> None:
        print("Starting frontend process...")
        if self.processes["frontend"]:
            print("Terminating existing frontend process")
            self.processes["frontend"].terminate()
            self.processes["frontend"].wait()

        frontend_dir = os.path.join(os.getcwd(), "frontend")
        if os.path.exists(frontend_dir):
            # Set up environment for frontend
            env = os.environ.copy()
            env["VITE_API_URL"] = "http://localhost:5002"

            self.processes["frontend"] = subprocess.Popen(
                "npm run dev -- --host 0.0.0.0 --port 5001",
                shell=True,
                cwd=frontend_dir,
                env=env,
            )
            print(f"Frontend started with PID: {self.processes['frontend'].pid}")
            print("Frontend accessible on all network interfaces (0.0.0.0:5001)")
        else:
            print("Frontend directory not found, skipping frontend server")

    def stop_all(self) -> None:
        print("Stopping all processes...")
        for name, process in self.processes.items():
            if process:
                print(f"Terminating {name} process")
                process.terminate()
                process.wait()


class BackendChangeHandler(FileSystemEventHandler):
    def __init__(self, process_manager: ProcessManager) -> None:
        self.process_manager = process_manager

    def on_any_event(self, event: FileSystemEvent) -> None:
        # Ignore database files and other non-source files
        if any(
            ignore in event.src_path
            for ignore in ["src/instance", ".pyc", "__pycache__", ".git"]
        ):
            return

        print(f"Backend file changed: {event.src_path}")
        self.process_manager.start_backend()


def main():
    process_manager = ProcessManager()

    # Start both servers
    process_manager.start_backend()
    time.sleep(2)  # Give backend a moment to start
    process_manager.start_frontend()

    # Set up file watchers
    backend_handler = BackendChangeHandler(process_manager)

    observer = Observer()

    # Watch backend source directory
    backend_src_path = os.path.abspath("src")
    if os.path.exists(backend_src_path):
        print(f"Watching backend directory: {backend_src_path}")
        observer.schedule(backend_handler, path=backend_src_path, recursive=True)

    observer.start()

    try:
        print("\n" + "=" * 60)
        print("🚀 Development servers started!")
        print("📱 Frontend (React): http://localhost:5001")
        print("🔧 Backend (Flask): http://localhost:5002")
        print("📁 Watching for file changes...")
        print("Press Ctrl+C to stop all servers")
        print("=" * 60 + "\n")

        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down...")
        observer.stop()
        process_manager.stop_all()

    observer.join()


if __name__ == "__main__":
    main()
