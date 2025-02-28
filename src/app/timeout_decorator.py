import functools
import threading
from typing import Any, Callable, List, Optional, TypeVar

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
        def wrapper(*args: Any, **kwargs: Any) -> T:
            timeout_flag = threading.Event()
            result: List[Optional[T]] = [None]

            def target() -> None:
                try:
                    result[0] = func(*args, **kwargs)
                except Exception as e:  # pylint: disable=broad-exception-caught
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
            return result[0]  # type: ignore

        return wrapper

    return decorator
