# global.py

app = None  # Initialize as None to avoid premature instantiation

def with_app_context(func):
    """Decorator to wrap a function with Flask app context."""
    def wrapper(*args, **kwargs):
        global app  # Use the global app
        if app is None:
            raise RuntimeError("App context is not initialized in global_ctx.app")
        with app.app_context():
            return func(*args, **kwargs)
    return wrapper

scheduler = None  # Placeholder for APScheduler
