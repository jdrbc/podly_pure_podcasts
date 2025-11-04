from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable


@runtime_checkable
class Post(Protocol):
    """Interface for post objects to break cyclic dependencies."""

    id: int
    guid: str
    download_url: Optional[str]
    title: str

    @property
    def whitelisted(self) -> bool:
        """Whether this post is whitelisted for processing."""
