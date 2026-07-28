"""Contracts implemented by portfolio sources."""

from typing import Protocol, runtime_checkable

from ppa.models import Portfolio


class SourceNotImplementedError(NotImplementedError):
    """Raised when a source adapter is present but cannot ingest yet."""


class SourceError(RuntimeError):
    """Raised when a portfolio source cannot be inspected."""


class SourceRateLimitError(SourceError):
    """Raised when a source asks the client to pause requests."""

    def __init__(self, retry_after: int | None = None) -> None:
        self.retry_after = retry_after
        message = "SmugMug rate-limited the request."
        if retry_after is not None:
            message += f" Retry after {retry_after} seconds."
        super().__init__(message)


@runtime_checkable
class GallerySource(Protocol):
    """Load a portfolio into the source-agnostic normalized model."""

    @property
    def source_name(self) -> str:
        """Return the stable source type identifier."""
        ...

    def load_portfolio(self) -> Portfolio:
        """Discover and normalize a portfolio without retaining original images."""
        ...
