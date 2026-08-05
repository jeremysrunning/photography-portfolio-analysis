"""Resumable application orchestration for one visual analyzer."""

from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from threading import Event

from ppa.analysis.visual import VisualAnalyzer, allows_empty_results
from ppa.models import Asset, MediaType, Portfolio
from ppa.sources import (
    GallerySource,
    SourceAuthenticationError,
    SourceAuthorizationError,
    SourcePreviewCancelledError,
    SourcePreviewDecodeError,
    SourcePreviewDimensionMismatchError,
    SourcePreviewDimensionsTooLargeError,
    SourcePreviewOriginalRejectedError,
    SourcePreviewPayloadTooLargeError,
    SourcePreviewUnavailableError,
    SourcePreviewUnsupportedContentTypeError,
    SourceRateLimitError,
    SourceTransientError,
)
from ppa.sources.smugmug import SmugMugSource
from ppa.storage import SQLitePortfolioRepository, VisualAnalysisOwnershipLostError
from ppa.visual import VisualRunStatus

ProgressCallback = Callable[["VisualProgress"], None]
SourceFactory = Callable[[Portfolio, str], GallerySource]
RepositoryFactory = Callable[[Path], SQLitePortfolioRepository]
Clock = Callable[[], float]
Sleeper = Callable[[float], None]


class VisualWorkflowError(RuntimeError):
    """Raised when visual analysis cannot safely begin."""


class _UnexpectedEmptyResults(RuntimeError):
    """Raised when an analyzer violates its declared output contract."""


class VisualOutcomeKind(StrEnum):
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RUNNING = "running"
    AUTHENTICATION = "authentication"
    RATE_LIMITED = "rate_limited"
    ALREADY_COMPLETED = "already_completed"
    EXISTING_FAILED = "existing_failed"
    EXISTING_SKIPPED = "existing_skipped"
    OWNERSHIP_LOST = "ownership_lost"


@dataclass(frozen=True, slots=True)
class VisualAnalysisOptions:
    """Targeting and execution controls for one exact analyzer identity."""

    limit: int | None = None
    workers: int = 1
    refresh: bool = False
    retry_failed: bool = False
    only_failed: bool = False
    gallery_source_id: str | None = None
    capture_year: int | None = None
    preview_attempts: int = 3
    maximum_retry_delay: float = 30.0

    def __post_init__(self) -> None:
        if self.limit is not None and self.limit < 1:
            raise ValueError("limit must be greater than zero")
        if not 1 <= self.workers <= 4:
            raise ValueError("workers must be between 1 and 4")
        if self.capture_year is not None and self.capture_year < 1:
            raise ValueError("year must be greater than zero")
        if self.only_failed and self.refresh:
            raise ValueError("only-failed and refresh cannot be combined")
        if self.preview_attempts < 1:
            raise ValueError("preview_attempts must be positive")
        if self.maximum_retry_delay < 0:
            raise ValueError("maximum_retry_delay must not be negative")


@dataclass(frozen=True, slots=True)
class VisualProgress:
    """Aggregate progress without asset identifiers or source details."""

    selected: int
    processed: int
    completed: int
    skipped: int
    failed: int
    cancelled: int
    running: int
    remaining: int
    elapsed_seconds: float
    processing_rate: float | None
    estimated_seconds_remaining: float | None
    downloaded_bytes: int
    ownership_lost: int = 0


@dataclass(frozen=True, slots=True)
class VisualWorkflowResult:
    """Final state for one visual-analysis command."""

    eligible_photographs: int
    filter_matched_photographs: int
    selected_work_items: int
    processed_work_items: int
    already_completed_excluded: int
    skipped_excluded: int
    failed_excluded: int
    pending_excluded: int
    running_excluded: int
    completed: int
    skipped: int
    failed: int
    cancelled: int
    remaining_selected_work: int
    elapsed_seconds: float
    processing_rate: float | None
    downloaded_bytes: int
    ownership_lost: int = 0
    rate_limited: bool = False
    configuration_failed: bool = False
    cancelled_by_user: bool = False


@dataclass(frozen=True, slots=True)
class _Outcome:
    kind: VisualOutcomeKind
    downloaded_bytes: int = 0


@dataclass(frozen=True, slots=True)
class _Target:
    asset: Asset
    status: VisualRunStatus
    attempts: int
    interruption_category: str | None


_PERMANENT_PREVIEW_FAILURES = (
    SourcePreviewDecodeError,
    SourcePreviewDimensionMismatchError,
    SourcePreviewDimensionsTooLargeError,
    SourcePreviewOriginalRejectedError,
    SourcePreviewPayloadTooLargeError,
    SourcePreviewUnsupportedContentTypeError,
)


def run_visual_analysis(
    portfolio: Portfolio,
    database: Path,
    api_key: str,
    analyzer: VisualAnalyzer,
    *,
    options: VisualAnalysisOptions | None = None,
    progress: ProgressCallback | None = None,
    cancellation: Event | None = None,
    source_factory: SourceFactory | None = None,
    repository_factory: RepositoryFactory = SQLitePortfolioRepository,
    clock: Clock = time.perf_counter,
    sleeper: Sleeper = time.sleep,
) -> VisualWorkflowResult:
    """Run one analyzer resumably over selected persisted photographs."""
    options = options or VisualAnalysisOptions()
    if not api_key:
        raise VisualWorkflowError("visual analysis requires source credentials")
    if portfolio.source_name != "smugmug" and source_factory is None:
        raise VisualWorkflowError(
            f"visual preview access is not implemented for source: {portfolio.source_name}"
        )
    if analyzer.preview_request.storage_mode.value != "memory":
        raise VisualWorkflowError("visual analyzers require memory-backed previews")
    event = cancellation or Event()
    source_factory = source_factory or _smugmug_source
    started = clock()
    photographs = tuple(
        sorted(
            (asset for asset in portfolio.assets if asset.media_type is MediaType.PHOTOGRAPH),
            key=lambda asset: asset.source_id,
        )
    )
    selected = _filter_assets(portfolio, photographs, options)

    pending: list[_Target] = []
    already_completed = existing_skipped = existing_failed = excluded_pending = running = 0
    with repository_factory(database) as repository:
        for asset in selected:
            snapshot = repository.visual_analysis_snapshot(
                portfolio.source_name,
                portfolio.source_id,
                asset.source_id,
                analyzer.identity,
            )
            status = snapshot.state.status
            interrupted = snapshot.state.interruption_category is not None
            target = _Target(
                asset,
                status,
                snapshot.state.attempts,
                snapshot.state.interruption_category,
            )
            if status is VisualRunStatus.RUNNING:
                running += 1
            elif options.only_failed:
                if status is VisualRunStatus.FAILED:
                    pending.append(target)
                elif status is VisualRunStatus.COMPLETED:
                    already_completed += 1
                elif status is VisualRunStatus.SKIPPED:
                    existing_skipped += 1
                else:
                    excluded_pending += 1
            elif status is VisualRunStatus.COMPLETED and not options.refresh:
                already_completed += 1
            elif status is VisualRunStatus.SKIPPED and not options.refresh:
                existing_skipped += 1
            elif status is VisualRunStatus.FAILED and not options.retry_failed:
                existing_failed += 1
            elif status is VisualRunStatus.PENDING and interrupted and not options.retry_failed:
                excluded_pending += 1
            else:
                pending.append(target)

    counters: dict[str, int] = {
        "completed": 0,
        "skipped": 0,
        "failed": 0,
        "cancelled": 0,
        "running": 0,
        "downloaded_bytes": 0,
        "already_completed": 0,
        "existing_failed": 0,
        "existing_skipped": 0,
        "ownership_lost": 0,
    }
    rate_limited = False
    configuration_failed = False
    cancelled_by_user = False
    futures: set[Future[_Outcome]] = set()
    iterator = iter(pending)
    executor = ThreadPoolExecutor(max_workers=options.workers)
    try:
        _fill_futures(
            futures,
            iterator,
            options.workers,
            executor,
            portfolio,
            database,
            api_key,
            analyzer,
            options,
            event,
            source_factory,
            repository_factory,
            sleeper,
        )
        while futures:
            done, futures = wait(futures, return_when=FIRST_COMPLETED)
            for future in done:
                outcome = future.result()
                counters["downloaded_bytes"] += outcome.downloaded_bytes
                if outcome.kind is VisualOutcomeKind.RATE_LIMITED:
                    counters["failed"] += 1
                    rate_limited = True
                    event.set()
                elif outcome.kind is VisualOutcomeKind.AUTHENTICATION:
                    counters["cancelled"] += 1
                    configuration_failed = True
                    event.set()
                else:
                    counters[outcome.kind.value] += 1
            _emit_progress(progress, len(pending), counters, started, clock)
            if not event.is_set():
                _fill_futures(
                    futures,
                    iterator,
                    options.workers,
                    executor,
                    portfolio,
                    database,
                    api_key,
                    analyzer,
                    options,
                    event,
                    source_factory,
                    repository_factory,
                    sleeper,
                )
    except KeyboardInterrupt:
        event.set()
        cancelled_by_user = True
        for future in futures:
            outcome = future.result()
            counters["downloaded_bytes"] += outcome.downloaded_bytes
            if outcome.kind in {
                VisualOutcomeKind.AUTHENTICATION,
                VisualOutcomeKind.CANCELLED,
            }:
                counters["cancelled"] += 1
            elif outcome.kind is VisualOutcomeKind.RATE_LIMITED:
                counters["failed"] += 1
                rate_limited = True
            else:
                counters[outcome.kind.value] += 1
    finally:
        executor.shutdown(wait=True, cancel_futures=False)

    elapsed = max(0.0, clock() - started)
    processed = sum(
        counters[name]
        for name in (
            "completed",
            "skipped",
            "failed",
            "cancelled",
            "running",
            "already_completed",
            "existing_failed",
            "existing_skipped",
            "ownership_lost",
        )
    )
    remaining = len(pending) - processed
    rate = counters["completed"] / elapsed if elapsed > 0 and counters["completed"] else None
    return VisualWorkflowResult(
        eligible_photographs=len(photographs),
        filter_matched_photographs=len(selected),
        selected_work_items=len(pending),
        processed_work_items=processed,
        already_completed_excluded=already_completed,
        skipped_excluded=existing_skipped,
        failed_excluded=existing_failed,
        pending_excluded=excluded_pending,
        running_excluded=running,
        completed=counters["completed"],
        skipped=counters["skipped"],
        failed=counters["failed"],
        cancelled=counters["cancelled"],
        remaining_selected_work=max(0, remaining),
        elapsed_seconds=elapsed,
        processing_rate=rate,
        downloaded_bytes=counters["downloaded_bytes"],
        ownership_lost=counters["ownership_lost"],
        rate_limited=rate_limited,
        configuration_failed=configuration_failed,
        cancelled_by_user=cancelled_by_user,
    )


def _process_asset(
    portfolio: Portfolio,
    database: Path,
    api_key: str,
    analyzer: VisualAnalyzer,
    target: _Target,
    options: VisualAnalysisOptions,
    event: Event,
    source_factory: SourceFactory,
    repository_factory: RepositoryFactory,
    sleeper: Sleeper,
) -> _Outcome:
    asset = target.asset
    with repository_factory(database) as repository:
        current = repository.visual_analysis_snapshot(
            portfolio.source_name,
            portfolio.source_id,
            asset.source_id,
            analyzer.identity,
        )
        if (
            current.state.status is not target.status
            or current.state.attempts != target.attempts
            or current.state.interruption_category != target.interruption_category
        ):
            return _outcome_for_state(current.state.status)
        claim = repository.claim_visual_analysis(
            portfolio.source_name,
            portfolio.source_id,
            asset.source_id,
            analyzer.identity,
            retry_failed=options.retry_failed or options.only_failed,
            refresh=options.refresh,
        )
        if claim is None:
            latest = repository.visual_analysis_snapshot(
                portfolio.source_name, portfolio.source_id, asset.source_id, analyzer.identity
            )
            return _outcome_for_state(latest.state.status)
        if event.is_set():
            return _persist_outcome(
                lambda: repository.cancel_visual_analysis(
                    portfolio.source_name,
                    portfolio.source_id,
                    asset.source_id,
                    analyzer.identity,
                    expected_generation=claim.attempt_generation,
                ),
                VisualOutcomeKind.CANCELLED,
            )
        source = source_factory(portfolio, api_key)
        try:
            resource = _open_preview(source, asset, analyzer, event, options, sleeper)
            with resource:
                results = tuple(analyzer.analyze(asset, resource.image, resource.metadata))
                downloaded_bytes = resource.metadata.downloaded_encoded_byte_count
                if not results and not allows_empty_results(analyzer):
                    raise _UnexpectedEmptyResults
            if event.is_set():
                return _persist_outcome(
                    lambda: repository.cancel_visual_analysis(
                        portfolio.source_name,
                        portfolio.source_id,
                        asset.source_id,
                        analyzer.identity,
                        expected_generation=claim.attempt_generation,
                    ),
                    VisualOutcomeKind.CANCELLED,
                    downloaded_bytes,
                )
            return _persist_outcome(
                lambda: repository.complete_visual_analysis(
                    portfolio.source_name,
                    portfolio.source_id,
                    asset.source_id,
                    analyzer.identity,
                    results,
                    expected_generation=claim.attempt_generation,
                ),
                VisualOutcomeKind.COMPLETED,
                downloaded_bytes,
            )
        except SourcePreviewCancelledError:
            return _persist_outcome(
                lambda: repository.cancel_visual_analysis(
                    portfolio.source_name,
                    portfolio.source_id,
                    asset.source_id,
                    analyzer.identity,
                    expected_generation=claim.attempt_generation,
                ),
                VisualOutcomeKind.CANCELLED,
            )
        except (SourceAuthenticationError, SourceAuthorizationError):
            return _persist_outcome(
                lambda: repository.cancel_visual_analysis(
                    portfolio.source_name,
                    portfolio.source_id,
                    asset.source_id,
                    analyzer.identity,
                    "source_access",
                    expected_generation=claim.attempt_generation,
                ),
                VisualOutcomeKind.AUTHENTICATION,
            )
        except SourceRateLimitError:
            return _persist_outcome(
                lambda: repository.fail_visual_analysis(
                    portfolio.source_name,
                    portfolio.source_id,
                    asset.source_id,
                    analyzer.identity,
                    "rate_limited",
                    "Preview access remained rate-limited after bounded retries.",
                    expected_generation=claim.attempt_generation,
                ),
                VisualOutcomeKind.RATE_LIMITED,
            )
        except _PERMANENT_PREVIEW_FAILURES:
            return _persist_outcome(
                lambda: repository.fail_visual_analysis(
                    portfolio.source_name,
                    portfolio.source_id,
                    asset.source_id,
                    analyzer.identity,
                    "preview_invalid",
                    "The bounded preview could not be analyzed safely.",
                    expected_generation=claim.attempt_generation,
                ),
                VisualOutcomeKind.FAILED,
            )
        except SourcePreviewUnavailableError:
            return _persist_outcome(
                lambda: repository.skip_visual_analysis(
                    portfolio.source_name,
                    portfolio.source_id,
                    asset.source_id,
                    analyzer.identity,
                    "preview unavailable",
                    expected_generation=claim.attempt_generation,
                ),
                VisualOutcomeKind.SKIPPED,
            )
        except SourceTransientError:
            return _persist_outcome(
                lambda: repository.fail_visual_analysis(
                    portfolio.source_name,
                    portfolio.source_id,
                    asset.source_id,
                    analyzer.identity,
                    "preview_transient",
                    "Preview access failed after bounded retries.",
                    expected_generation=claim.attempt_generation,
                ),
                VisualOutcomeKind.FAILED,
            )
        except _UnexpectedEmptyResults:
            return _persist_outcome(
                lambda: repository.fail_visual_analysis(
                    portfolio.source_name,
                    portfolio.source_id,
                    asset.source_id,
                    analyzer.identity,
                    "analyzer_output",
                    "The selected visual analyzer returned no results unexpectedly.",
                    expected_generation=claim.attempt_generation,
                ),
                VisualOutcomeKind.FAILED,
            )
        except Exception:
            return _persist_outcome(
                lambda: repository.fail_visual_analysis(
                    portfolio.source_name,
                    portfolio.source_id,
                    asset.source_id,
                    analyzer.identity,
                    "analyzer_error",
                    "The selected visual analyzer did not complete.",
                    expected_generation=claim.attempt_generation,
                ),
                VisualOutcomeKind.FAILED,
            )


def _persist_outcome(
    transition: Callable[[], None],
    kind: VisualOutcomeKind,
    downloaded_bytes: int = 0,
) -> _Outcome:
    try:
        transition()
    except VisualAnalysisOwnershipLostError:
        return _Outcome(VisualOutcomeKind.OWNERSHIP_LOST, downloaded_bytes)
    return _Outcome(kind, downloaded_bytes)


def _open_preview(
    source: GallerySource,
    asset: Asset,
    analyzer: VisualAnalyzer,
    event: Event,
    options: VisualAnalysisOptions,
    sleeper: Sleeper,
):
    for attempt in range(options.preview_attempts):
        try:
            return source.open_preview(
                asset,
                analyzer.preview_request,
                is_cancelled=event.is_set,
            )
        except SourceRateLimitError as error:
            if attempt + 1 == options.preview_attempts:
                raise
            delay = error.retry_after if error.retry_after is not None else 2**attempt
            _cancel_aware_sleep(event, min(delay, options.maximum_retry_delay), sleeper)
        except SourceTransientError:
            if attempt + 1 == options.preview_attempts:
                raise
            _cancel_aware_sleep(event, min(2**attempt, options.maximum_retry_delay), sleeper)
    raise AssertionError("preview retry loop exhausted")  # pragma: no cover


def _cancel_aware_sleep(event: Event, delay: float, sleeper: Sleeper) -> None:
    if event.is_set():
        raise SourcePreviewCancelledError("Temporary preview access was cancelled.")
    sleeper(delay)
    if event.is_set():
        raise SourcePreviewCancelledError("Temporary preview access was cancelled.")


def _filter_assets(
    portfolio: Portfolio,
    photographs: tuple[Asset, ...],
    options: VisualAnalysisOptions,
) -> tuple[Asset, ...]:
    selected_ids: set[str] | None = None
    if options.gallery_source_id is not None:
        gallery = next(
            (item for item in portfolio.galleries if item.source_id == options.gallery_source_id),
            None,
        )
        if gallery is None:
            raise VisualWorkflowError("the selected gallery source ID was not found")
        selected_ids = {placement.asset_source_id for placement in gallery.placements}
    selected = tuple(
        asset
        for asset in photographs
        if (selected_ids is None or asset.source_id in selected_ids)
        and (
            options.capture_year is None
            or (
                asset.metadata.captured_at is not None
                and asset.metadata.captured_at.year == options.capture_year
            )
        )
    )
    return selected[: options.limit] if options.limit is not None else selected


def _fill_futures(
    futures: set[Future[_Outcome]],
    iterator,
    workers: int,
    executor: ThreadPoolExecutor,
    portfolio: Portfolio,
    database: Path,
    api_key: str,
    analyzer: VisualAnalyzer,
    options: VisualAnalysisOptions,
    event: Event,
    source_factory: SourceFactory,
    repository_factory: RepositoryFactory,
    sleeper: Sleeper,
) -> None:
    while len(futures) < workers:
        try:
            target = next(iterator)
        except StopIteration:
            return
        futures.add(
            executor.submit(
                _process_asset,
                portfolio,
                database,
                api_key,
                analyzer,
                target,
                options,
                event,
                source_factory,
                repository_factory,
                sleeper,
            )
        )


def _emit_progress(
    callback: ProgressCallback | None,
    selected: int,
    counters: dict[str, int],
    started: float,
    clock: Clock,
) -> None:
    if callback is None:
        return
    elapsed = max(0.0, clock() - started)
    processed = sum(
        counters[name]
        for name in (
            "completed",
            "skipped",
            "failed",
            "cancelled",
            "running",
            "already_completed",
            "existing_failed",
            "existing_skipped",
            "ownership_lost",
        )
    )
    remaining = max(0, selected - processed)
    rate = counters["completed"] / elapsed if elapsed > 0 and counters["completed"] else None
    eta = remaining / rate if rate is not None and counters["completed"] >= 2 else None
    callback(
        VisualProgress(
            selected,
            processed,
            counters["completed"],
            counters["skipped"],
            counters["failed"],
            counters["cancelled"],
            counters["running"],
            remaining,
            elapsed,
            rate,
            eta,
            counters["downloaded_bytes"],
            counters["ownership_lost"],
        )
    )


def _smugmug_source(portfolio: Portfolio, api_key: str) -> GallerySource:
    return SmugMugSource(portfolio.source_url, api_key)


def _outcome_for_state(status: VisualRunStatus) -> _Outcome:
    return _Outcome(
        {
            VisualRunStatus.RUNNING: VisualOutcomeKind.RUNNING,
            VisualRunStatus.COMPLETED: VisualOutcomeKind.ALREADY_COMPLETED,
            VisualRunStatus.FAILED: VisualOutcomeKind.EXISTING_FAILED,
            VisualRunStatus.SKIPPED: VisualOutcomeKind.EXISTING_SKIPPED,
            VisualRunStatus.PENDING: VisualOutcomeKind.CANCELLED,
        }[status]
    )
