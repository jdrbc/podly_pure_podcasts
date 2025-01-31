import functools
import threading
from typing import Callable, TypeVar

T = TypeVar("T")


class TimeoutException(Exception):
    """Custom exception to indicate a timeout."""


def timeout_decorator(timeout: int) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Decorator to enforce a timeout on a function.
    If the function execution exceeds the timeout, a TimeoutException is raised.
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            # This flag will indicate if the function has timed out
            timeout_flag = threading.Event()

            def target() -> None:
                try:
                    func(*args, **kwargs)
                except Exception as e:
                    # Optionally, handle exceptions within the thread
                    print(f"Exception in thread: {e}")
                finally:
                    timeout_flag.set()

            thread = threading.Thread(target=target)
            thread.start()
            thread.join(timeout)
            if not timeout_flag.is_set():
                raise TimeoutException(
                    f"Function '{func.__name__}' exceeded timeout of {timeout} seconds."
                )
            return

        return wrapper

    return decorator
