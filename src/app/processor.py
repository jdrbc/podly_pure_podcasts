from app import config
from podcast_processor.podcast_processor import PodcastProcessor


class ProcessorSingleton:
    """Singleton class to manage the PodcastProcessor instance."""

    _instance: PodcastProcessor | None = None

    @classmethod
    def get_instance(cls) -> PodcastProcessor:
        """Get or create the PodcastProcessor instance."""
        if cls._instance is None:
            cls._instance = PodcastProcessor(config)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance (useful for testing)."""
        cls._instance = None


def get_processor() -> PodcastProcessor:
    """Get the PodcastProcessor instance."""
    return ProcessorSingleton.get_instance()
