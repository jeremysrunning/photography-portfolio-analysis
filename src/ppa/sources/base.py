"""Contracts implemented by portfolio sources."""

from collections.abc import Iterator
from typing import Protocol, runtime_checkable

from ppa.models import Asset, Gallery, Portfolio
from ppa.sources.preview import CancellationCheck, PreviewRequest, PreviewResource


class SourceNotImplementedError(NotImplementedError):
    """Raised when a source adapter is present but cannot ingest yet."""


class SourceError(RuntimeError):
    """Base class for normalized portfolio-source failures."""


class SourceAuthenticationError(SourceError):
    """Raised when a source rejects or requires credentials."""


class SourceAuthorizationError(SourceError):
    """Raised when credentials cannot access a source resource."""


class SourceNotFoundError(SourceError):
    """Raised when a requested source resource does not exist."""


class SourcePreviewUnavailableError(SourceError):
    """Raised when an asset has no accessible temporary preview."""


class SourcePreviewUnsupportedContentTypeError(SourcePreviewUnavailableError):
    """Raised when preview content is missing or uses a disallowed media type."""


class SourcePreviewPayloadTooLargeError(SourcePreviewUnavailableError):
    """Raised when encoded preview content exceeds the requested byte limit."""


class SourcePreviewDimensionsTooLargeError(SourcePreviewUnavailableError):
    """Raised when reported or decoded dimensions exceed a safety bound."""


class SourcePreviewOriginalRejectedError(SourcePreviewUnavailableError):
    """Raised when a provider offers or redirects to original-resolution media."""


class SourcePreviewDimensionMismatchError(SourcePreviewUnavailableError):
    """Raised when provider-reported and decoded dimensions materially disagree."""


class SourcePreviewDecodeError(SourcePreviewUnavailableError):
    """Raised when preview bytes cannot be decoded safely."""


class SourcePreviewCancelledError(SourceError):
    """Raised after cancellation requests stop temporary preview access."""


class SourceRateLimitError(SourceError):
    """Raised when a source asks the client to pause requests."""

    def __init__(self, retry_after: int | None = None) -> None:
        self.retry_after = retry_after
        message = "The portfolio source rate-limited the request."
        if retry_after is not None:
            message += f" Retry after {retry_after} seconds."
        super().__init__(message)


class SourceTransientError(SourceError):
    """A temporary provider or network failure that may be retried."""


@runtime_checkable
class GallerySource(Protocol):
    """Discover and read a portfolio through normalized records.

    Sources own every preview handle they open. A preview handle is valid only
    inside its context manager and must be closed, and any temporary backing
    file removed, when that context exits.
    """

    @property
    def source_name(self) -> str:
        """Return the stable source type identifier."""
        ...

    def discover_portfolio(self) -> Portfolio:
        """Discover portfolio identity and metadata without enumerating children."""
        ...

    def iter_galleries(self, portfolio: Portfolio) -> Iterator[Gallery]:
        """Yield normalized galleries belonging to a discovered portfolio."""
        ...

    def iter_assets(self, gallery: Gallery) -> Iterator[Asset]:
        """Yield normalized assets belonging to a discovered gallery."""
        ...

    def enrich_asset_metadata(self, asset: Asset) -> Asset:
        """Return an asset with available source metadata added.

        Metadata unavailable from the source remains missing.
        """
        ...

    def open_preview(
        self,
        asset: Asset,
        request: PreviewRequest,
        *,
        is_cancelled: CancellationCheck | None = None,
    ) -> PreviewResource:
        """Return one bounded, validated preview with explicit ownership."""
        ...
