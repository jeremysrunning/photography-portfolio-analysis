"""Contracts implemented by portfolio sources."""

from typing import Protocol, runtime_checkable

from ppa.models import Portfolio


class SourceNotImplementedError(NotImplementedError):
    """Raised when a source adapter is present but cannot ingest yet."""


class SourceError(RuntimeError):
    """Raised when a portfolio source cannot be inspected."""


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
