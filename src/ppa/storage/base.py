"""Storage contracts."""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ppa.models import JsonValue, MediaType, Portfolio


@dataclass(frozen=True, slots=True)
class EnrichmentTarget:
    """A unique stored asset awaiting source metadata enrichment."""

    source_id: str
    media_type: MediaType
    metadata: dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class EnrichmentStatus:
    """Current state counts for one portfolio enrichment kind."""

    pending: int
    completed: int
    failed: int


@runtime_checkable
class PortfolioRepository(Protocol):
    """Persist normalized datasets without storing original image content."""

    def initialize(self) -> None:
        """Create or update the datastore schema."""
        ...

    def save(self, portfolio: Portfolio) -> None:
        """Persist a complete normalized portfolio dataset."""
        ...

    def get(self, source: str, source_id: str) -> Portfolio | None:
        """Retrieve a normalized portfolio by source-scoped identity."""
        ...

    def exists(self, source: str, source_id: str) -> bool:
        """Return whether a source-scoped portfolio is present."""
        ...

    def list_keys(self) -> tuple[tuple[str, str], ...]:
        """List source-scoped portfolio identities in the datastore."""
        ...

    def list_enrichment_targets(
        self,
        source: str,
        portfolio_source_id: str,
        kind: str,
        *,
        retry_failed: bool = False,
        limit: int | None = None,
    ) -> tuple[EnrichmentTarget, ...]:
        """List unique assets that still need an enrichment."""
        ...

    def save_asset_enrichment(
        self,
        source: str,
        portfolio_source_id: str,
        asset_source_id: str,
        kind: str,
        values: dict[str, JsonValue],
    ) -> None:
        """Save derived source metadata and mark the enrichment complete."""
        ...

    def fail_asset_enrichment(
        self,
        source: str,
        portfolio_source_id: str,
        asset_source_id: str,
        kind: str,
        error: str,
    ) -> None:
        """Record a failed enrichment attempt without losing prior data."""
        ...

    def enrichment_status(
        self,
        source: str,
        portfolio_source_id: str,
        kind: str,
    ) -> EnrichmentStatus:
        """Return pending, completed, and failed unique-asset counts."""
        ...

    def close(self) -> None:
        """Close datastore resources cleanly."""
        ...
