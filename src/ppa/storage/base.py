"""Storage contracts."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from ppa.models import Asset, JsonValue, MediaType, Portfolio, RationalValue
from ppa.visual import AnalyzerIdentity, VisualAnalysisSnapshot, VisualResult


@dataclass(frozen=True, slots=True)
class EnrichmentTarget:
    """A unique stored asset awaiting source metadata enrichment."""

    source_id: str
    media_type: MediaType
    metadata: dict[str, JsonValue]
    exif: dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class EnrichmentStatus:
    """Current state counts for one portfolio enrichment kind."""

    pending: int
    completed: int
    failed: int


@dataclass(frozen=True, slots=True)
class VisualAnalysisRecord:
    """One normalized asset and its exact-identity visual snapshot."""

    asset: Asset
    snapshot: VisualAnalysisSnapshot


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
        *,
        focal_length_mm: float | None = None,
        focal_length_35mm: float | None = None,
        aperture_f_number: float | None = None,
        exposure_time: RationalValue | None = None,
        iso: int | None = None,
        exposure_compensation_ev: RationalValue | None = None,
        flash_fired: bool | None = None,
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


@runtime_checkable
class VisualAnalysisRepository(Protocol):
    """Persist source-agnostic visual results and per-asset attempt state."""

    def list_visual_analysis_identities(
        self,
        portfolio: Portfolio,
    ) -> tuple[AnalyzerIdentity, ...]:
        """List exact persisted identities for one normalized portfolio."""
        ...

    def list_visual_analysis_records(
        self,
        portfolio: Portfolio,
        identity: AnalyzerIdentity,
    ) -> tuple[VisualAnalysisRecord, ...]:
        """Bulk-read one exact identity in normalized portfolio asset order."""
        ...

    def visual_analysis_snapshot(
        self,
        source: str,
        portfolio_source_id: str,
        asset_source_id: str,
        identity: AnalyzerIdentity,
    ) -> VisualAnalysisSnapshot:
        """Return current attempt state and the last successful result snapshot."""
        ...

    def claim_visual_analysis(
        self,
        source: str,
        portfolio_source_id: str,
        asset_source_id: str,
        identity: AnalyzerIdentity,
        *,
        retry_failed: bool = False,
        refresh: bool = False,
        at: datetime | None = None,
    ) -> bool:
        """Atomically claim an eligible exact identity for one attempt."""
        ...

    def complete_visual_analysis(
        self,
        source: str,
        portfolio_source_id: str,
        asset_source_id: str,
        identity: AnalyzerIdentity,
        results: tuple[VisualResult, ...],
        *,
        at: datetime | None = None,
    ) -> None:
        """Atomically replace results and complete the running attempt."""
        ...

    def fail_visual_analysis(
        self,
        source: str,
        portfolio_source_id: str,
        asset_source_id: str,
        identity: AnalyzerIdentity,
        category: str,
        message: str,
        *,
        at: datetime | None = None,
    ) -> None:
        """Fail a running attempt without deleting a successful snapshot."""
        ...

    def cancel_visual_analysis(
        self,
        source: str,
        portfolio_source_id: str,
        asset_source_id: str,
        identity: AnalyzerIdentity,
        category: str = "cancelled",
        *,
        at: datetime | None = None,
    ) -> None:
        """Return a running attempt to retryable pending state."""
        ...

    def skip_visual_analysis(
        self,
        source: str,
        portfolio_source_id: str,
        asset_source_id: str,
        identity: AnalyzerIdentity,
        reason: str,
        *,
        at: datetime | None = None,
    ) -> None:
        """Skip a running attempt without creating completed results."""
        ...
