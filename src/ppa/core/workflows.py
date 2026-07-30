"""Application-level workflows shared by command-line entry points."""

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ppa.models import MediaType, Portfolio
from ppa.sources import load_portfolio
from ppa.sources.smugmug import SmugMugApiClient, SmugMugExifEnricher, SmugMugSource
from ppa.sources.smugmug.enrichment import EnrichmentResult
from ppa.storage import (
    EnrichmentStatus,
    SQLitePortfolioRepository,
    UnsupportedSchemaVersionError,
)

ProgressCallback = Callable[[int, int, int], None]


class PersistenceError(RuntimeError):
    """Raised when a normalized portfolio cannot be saved transactionally."""


@dataclass(frozen=True, slots=True)
class PortfolioCounts:
    """Counts established during normalized portfolio inspection."""

    galleries: int
    media_references: int
    unique_media: int
    photographs: int
    non_photos: int
    unknown: int


@dataclass(frozen=True, slots=True)
class InspectionResult:
    """Normalized portfolio and its import-facing counts."""

    portfolio: Portfolio
    counts: PortfolioCounts


@dataclass(frozen=True, slots=True)
class EnrichmentSnapshot:
    """Current EXIF state, including completed counts by media type."""

    status: EnrichmentStatus
    photographs_complete: int
    non_photos_complete: int
    unknown_complete: int


@dataclass(frozen=True, slots=True)
class ExifWorkflowResult:
    """State before and after one resumable EXIF enrichment run."""

    before: EnrichmentSnapshot
    run: EnrichmentResult
    after: EnrichmentSnapshot


def inspect_public_portfolio(url: str, api_key: str) -> InspectionResult:
    """Inspect a public SmugMug portfolio into the normalized domain model."""
    portfolio = load_portfolio(SmugMugSource(url, api_key))
    return InspectionResult(portfolio, portfolio_counts(portfolio))


def portfolio_counts(portfolio: Portfolio) -> PortfolioCounts:
    """Count normalized media without interpreting source-specific metadata."""
    return PortfolioCounts(
        galleries=len(portfolio.galleries),
        media_references=sum(len(gallery.placements) for gallery in portfolio.galleries),
        unique_media=len(portfolio.assets),
        photographs=sum(asset.media_type is MediaType.PHOTOGRAPH for asset in portfolio.assets),
        non_photos=sum(asset.media_type is MediaType.NON_PHOTO for asset in portfolio.assets),
        unknown=sum(asset.media_type is MediaType.UNKNOWN for asset in portfolio.assets),
    )


def persist_portfolio(portfolio: Portfolio, database: Path) -> None:
    """Persist one normalized portfolio using the repository transaction boundary."""
    try:
        with SQLitePortfolioRepository(database) as repository:
            repository.save(portfolio)
    except (OSError, sqlite3.Error, UnsupportedSchemaVersionError) as error:
        raise PersistenceError(str(error)) from error


def enrichment_snapshot(portfolio: Portfolio, database: Path) -> EnrichmentSnapshot:
    """Read aggregate and media-type-specific EXIF completion state."""
    with SQLitePortfolioRepository(database) as repository:
        return _snapshot(repository, portfolio)


def enrich_portfolio_exif(
    portfolio: Portfolio,
    database: Path,
    api_key: str,
    *,
    retry_failed: bool = False,
    batch_size: int = 25,
    limit: int | None = None,
    progress: ProgressCallback | None = None,
) -> ExifWorkflowResult:
    """Enrich outstanding assets and return typed before/after state."""
    if portfolio.source_name != "smugmug":
        from ppa.sources import SourceError

        raise SourceError(f"EXIF enrichment is not implemented for source: {portfolio.source_name}")
    with SQLitePortfolioRepository(database) as repository:
        before = _snapshot(repository, portfolio)
        targets = repository.list_enrichment_targets(
            portfolio.source_name,
            portfolio.source_id,
            "exif",
            retry_failed=retry_failed,
            limit=limit,
        )
        run = SmugMugExifEnricher(
            SmugMugApiClient(portfolio.source_url, api_key),
            repository,
            batch_size=batch_size,
        ).enrich(
            portfolio.source_name,
            portfolio.source_id,
            targets,
            progress,
        )
        after = _snapshot(repository, portfolio)
    return ExifWorkflowResult(before, run, after)


def _snapshot(
    repository: SQLitePortfolioRepository,
    portfolio: Portfolio,
) -> EnrichmentSnapshot:
    status = repository.enrichment_status(
        portfolio.source_name,
        portfolio.source_id,
        "exif",
    )
    outstanding = repository.list_enrichment_targets(
        portfolio.source_name,
        portfolio.source_id,
        "exif",
        retry_failed=True,
    )
    outstanding_by_type = {
        media_type: sum(target.media_type is media_type for target in outstanding)
        for media_type in MediaType
    }
    totals = portfolio_counts(portfolio)
    return EnrichmentSnapshot(
        status=status,
        photographs_complete=totals.photographs - outstanding_by_type[MediaType.PHOTOGRAPH],
        non_photos_complete=totals.non_photos - outstanding_by_type[MediaType.NON_PHOTO],
        unknown_complete=totals.unknown - outstanding_by_type[MediaType.UNKNOWN],
    )
