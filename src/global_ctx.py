from typing import Any, Callable, Optional, TypeVar

from flask import Flask
from flask_apscheduler import APScheduler  # type: ignore

# Define a generic type for decorators
F = TypeVar("F", bound=Callable[..., Any])

# Initialize global variables with type annotations
app: Optional[Flask] = None  # Initialize as None to avoid premature instantiation
scheduler: Optional[APScheduler] = None  # Placeholder for APScheduler


def with_app_context(func: F) -> Callable[..., Any]:
    """Decorator to wrap a function with Flask app context."""

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        global app  # Use the global app
        if app is None:
            raise RuntimeError("App context is not initialized in global_ctx.app")
        with app.app_context():
            return func(*args, **kwargs)

    return wrapper
