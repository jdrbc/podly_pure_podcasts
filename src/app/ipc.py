import multiprocessing
import os
from multiprocessing.managers import BaseManager
from queue import Queue
from typing import Any


class QueueManager(BaseManager):
    pass


# Define the queue globally so it can be registered
_command_queue: Queue[Any] = Queue()


def _get_default_authkey() -> bytes:
    # This key is only used for localhost IPC between the web and writer processes.
    # It must be identical across processes, otherwise Manager proxy calls can fail
    # with AuthenticationError ('digest sent was rejected').
    raw = os.environ.get("PODLY_IPC_AUTHKEY", "podly_secret")
    return raw.encode("utf-8")


def _ensure_process_authkey(authkey: bytes) -> None:
    try:
        multiprocessing.current_process().authkey = authkey
    except Exception:
        # Best-effort: if we can't set it, the explicit authkey passed to the
        # manager will still be used for direct manager connections.
        pass


def get_queue() -> Queue[Any]:
    return _command_queue


def make_server_manager(
    address: tuple[str, int] = ("127.0.0.1", 50001),
    authkey: bytes | None = None,
) -> QueueManager:
    if authkey is None:
        authkey = _get_default_authkey()
    _ensure_process_authkey(authkey)
    QueueManager.register("get_command_queue", callable=get_queue)
    # Register Queue so we can pass it around for replies
    QueueManager.register("Queue", callable=Queue)
    manager = QueueManager(address=address, authkey=authkey)
    return manager


def make_client_manager(
    address: tuple[str, int] = ("127.0.0.1", 50001),
    authkey: bytes | None = None,
) -> QueueManager:
    if authkey is None:
        authkey = _get_default_authkey()
    _ensure_process_authkey(authkey)
    QueueManager.register("get_command_queue")
    QueueManager.register("Queue")
    manager = QueueManager(address=address, authkey=authkey)
    manager.connect()
    return manager
