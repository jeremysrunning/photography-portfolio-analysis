import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
from PIL import Image

from ppa.analysis.color_luminance import ColorLuminanceAnalyzer
from ppa.core.visual_workflow import (
    VisualAnalysisOptions,
    VisualWorkflowError,
    run_visual_analysis,
)
from ppa.models import (
    Asset,
    AssetMetadata,
    Gallery,
    GalleryPlacement,
    MediaType,
    Portfolio,
    SourceReference,
)
from ppa.sources import (
    PreviewMetadata,
    PreviewRequest,
    PreviewResource,
    PreviewStorageMode,
    SourceAuthenticationError,
    SourcePreviewDecodeError,
    SourcePreviewUnavailableError,
    SourceRateLimitError,
    SourceTransientError,
)
from ppa.storage import SQLitePortfolioRepository
from ppa.visual import AnalyzerIdentity, VisualResult, VisualResultKind, VisualRunStatus


def _asset(
    source_id: str,
    *,
    year: int = 2024,
    media_type: MediaType = MediaType.PHOTOGRAPH,
) -> Asset:
    return Asset(
        SourceReference(source_id, f"https://example.smugmug.com/i-{source_id}"),
        AssetMetadata(media_type, datetime(year, 1, 1, tzinfo=UTC)),
    )


def _portfolio() -> Portfolio:
    assets = (
        _asset("photo-c", year=2023),
        _asset("photo-a"),
        _asset("photo-b"),
        _asset("video", media_type=MediaType.NON_PHOTO),
    )
    return Portfolio(
        "smugmug",
        SourceReference("portfolio", "https://example.smugmug.com"),
        "Portfolio",
        assets=assets,
        galleries=(
            Gallery(
                SourceReference("gallery-a", "https://example.smugmug.com/gallery-a"),
                "A",
                placements=(
                    GalleryPlacement("photo-a"),
                    GalleryPlacement("photo-c"),
                ),
            ),
            Gallery(
                SourceReference("gallery-b", "https://example.smugmug.com/gallery-b"),
                "B",
                placements=(GalleryPlacement("photo-b"),),
            ),
        ),
    )


@dataclass
class FakeAnalyzer:
    identity: AnalyzerIdentity = field(
        default_factory=lambda: AnalyzerIdentity("fake", "1", "defaults")
    )
    preview_request: PreviewRequest = field(default_factory=lambda: PreviewRequest(512))
    calls: list[str] = field(default_factory=list)
    active: int = 0
    maximum_active: int = 0
    delay: float = 0
    started: threading.Event | None = None
    release: threading.Event | None = None
    allows_empty_results: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)

    def analyze(self, asset, image, metadata):
        with self.lock:
            self.active += 1
            self.maximum_active = max(self.maximum_active, self.active)
            self.calls.append(asset.source_id)
        if self.started:
            self.started.set()
        if self.release:
            self.release.wait(timeout=5)
        if self.delay:
            time.sleep(self.delay)
        with self.lock:
            self.active -= 1
        return (
            VisualResult(
                "mean",
                VisualResultKind.MEASUREMENT,
                0.5,
                "fake",
                "1",
            ),
        )


class FakeSource:
    def __init__(self, behavior=None) -> None:
        self.behavior = behavior
        self.resources: list[PreviewResource] = []

    @property
    def source_name(self):
        return "smugmug"

    def open_preview(self, asset, request, *, is_cancelled=None):
        if self.behavior:
            self.behavior(asset)
        image = Image.new("RGB", (32, 24), "white")
        resource = PreviewResource.memory(
            PreviewMetadata(
                requested_maximum_edge=request.maximum_edge,
                width=32,
                height=24,
                content_type="image/jpeg",
                downloaded_content_type="image/jpeg",
                downloaded_encoded_byte_count=100,
                provenance="fake",
                storage_mode=PreviewStorageMode.MEMORY,
                provider_reported_width=32,
                provider_reported_height=24,
            ),
            image,
        )
        self.resources.append(resource)
        return resource


def _saved(tmp_path):
    database = tmp_path / "portfolio.sqlite3"
    portfolio = _portfolio()
    with SQLitePortfolioRepository(database) as repository:
        repository.save(portfolio)
    return portfolio, database


def test_success_resume_refresh_and_preview_cleanup(tmp_path) -> None:
    portfolio, database = _saved(tmp_path)
    analyzer = FakeAnalyzer()
    sources: list[FakeSource] = []

    def source_factory(portfolio, api_key):
        source = FakeSource()
        sources.append(source)
        return source

    first = run_visual_analysis(
        portfolio,
        database,
        "secret",
        analyzer,
        source_factory=source_factory,
    )
    assert first.completed == 3
    assert first.downloaded_bytes == 300
    assert analyzer.calls == ["photo-a", "photo-b", "photo-c"]
    assert all(resource.closed for source in sources for resource in source.resources)

    resumed = run_visual_analysis(
        portfolio,
        database,
        "secret",
        analyzer,
        source_factory=source_factory,
    )
    assert resumed.completed == 0
    assert resumed.already_completed == 3

    refreshed = run_visual_analysis(
        portfolio,
        database,
        "secret",
        analyzer,
        options=VisualAnalysisOptions(refresh=True, limit=1),
        source_factory=source_factory,
    )
    assert refreshed.completed == 1
    assert analyzer.calls[-1] == "photo-a"


def test_production_color_luminance_analyzer_persists_and_resumes(tmp_path) -> None:
    portfolio, database = _saved(tmp_path)
    analyzer = ColorLuminanceAnalyzer()
    sources: list[FakeSource] = []

    def source_factory(*_):
        source = FakeSource()
        sources.append(source)
        return source

    first = run_visual_analysis(
        portfolio,
        database,
        "secret",
        analyzer,
        options=VisualAnalysisOptions(limit=1),
        source_factory=source_factory,
    )
    resumed = run_visual_analysis(
        portfolio,
        database,
        "secret",
        analyzer,
        options=VisualAnalysisOptions(limit=1),
        source_factory=source_factory,
    )

    assert first.completed == 1
    assert resumed.already_completed == 1
    assert all(resource.closed for source in sources for resource in source.resources)
    with SQLitePortfolioRepository(database) as repository:
        snapshot = repository.visual_analysis_snapshot(
            "smugmug", "portfolio", "photo-a", analyzer.identity
        )
    assert snapshot.state.status is VisualRunStatus.COMPLETED
    assert len(snapshot.results) == 9
    assert {result.name for result in snapshot.results} >= {
        "luminance_mean",
        "dominant_palette",
        "palette_entropy",
    }


def test_filters_and_limit_follow_deterministic_asset_order(tmp_path) -> None:
    portfolio, database = _saved(tmp_path)
    analyzer = FakeAnalyzer()

    result = run_visual_analysis(
        portfolio,
        database,
        "secret",
        analyzer,
        options=VisualAnalysisOptions(
            gallery_source_id="gallery-a",
            capture_year=2024,
            limit=1,
        ),
        source_factory=lambda *_: FakeSource(),
    )

    assert result.eligible_photographs == 3
    assert result.selected_photographs == 1
    assert analyzer.calls == ["photo-a"]


def test_failed_retry_and_only_failed_are_independent(tmp_path) -> None:
    portfolio, database = _saved(tmp_path)
    analyzer = FakeAnalyzer()
    failures = {"photo-a"}

    def behavior(asset):
        if asset.source_id in failures:
            raise SourceTransientError("temporary")

    first = run_visual_analysis(
        portfolio,
        database,
        "secret",
        analyzer,
        options=VisualAnalysisOptions(preview_attempts=1),
        source_factory=lambda *_: FakeSource(behavior),
    )
    assert first.failed == 1
    failures.clear()

    normal = run_visual_analysis(
        portfolio,
        database,
        "secret",
        analyzer,
        source_factory=lambda *_: FakeSource(),
    )
    assert normal.existing_failed == 1
    retry = run_visual_analysis(
        portfolio,
        database,
        "secret",
        analyzer,
        options=VisualAnalysisOptions(only_failed=True),
        source_factory=lambda *_: FakeSource(),
    )
    assert retry.completed == 1


def test_unavailable_preview_is_skipped_neutrally(tmp_path) -> None:
    portfolio, database = _saved(tmp_path)

    result = run_visual_analysis(
        portfolio,
        database,
        "secret",
        FakeAnalyzer(),
        options=VisualAnalysisOptions(limit=1),
        source_factory=lambda *_: FakeSource(
            lambda asset: (_ for _ in ()).throw(SourcePreviewUnavailableError("missing"))
        ),
    )

    assert result.skipped == 1
    with SQLitePortfolioRepository(database) as repository:
        snapshot = repository.visual_analysis_snapshot(
            "smugmug", "portfolio", "photo-a", AnalyzerIdentity("fake", "1", "defaults")
        )
    assert snapshot.state.status is VisualRunStatus.SKIPPED
    assert snapshot.state.skip_reason == "preview unavailable"


def test_corrupt_preview_and_analyzer_failure_are_failed_without_leaking_resources(
    tmp_path,
) -> None:
    portfolio, database = _saved(tmp_path)
    corrupt = run_visual_analysis(
        portfolio,
        database,
        "secret",
        FakeAnalyzer(),
        options=VisualAnalysisOptions(limit=1),
        source_factory=lambda *_: FakeSource(
            lambda asset: (_ for _ in ()).throw(SourcePreviewDecodeError("corrupt"))
        ),
    )
    assert corrupt.failed == 1

    class FailingAnalyzer(FakeAnalyzer):
        def analyze(self, asset, image, metadata):
            raise RuntimeError("private analyzer detail")

    sources = []

    def source_factory(*_):
        source = FakeSource()
        sources.append(source)
        return source

    failed = run_visual_analysis(
        portfolio,
        database,
        "secret",
        FailingAnalyzer(identity=AnalyzerIdentity("failing", "1", "defaults")),
        options=VisualAnalysisOptions(limit=1),
        source_factory=source_factory,
    )
    assert failed.failed == 1
    assert sources[0].resources[0].closed
    with SQLitePortfolioRepository(database) as repository:
        snapshot = repository.visual_analysis_snapshot(
            "smugmug",
            "portfolio",
            "photo-a",
            AnalyzerIdentity("failing", "1", "defaults"),
        )
    assert snapshot.state.error_message == "The selected visual analyzer did not complete."


def test_unexpected_empty_output_fails_after_cleanup_without_completed_snapshot(
    tmp_path,
) -> None:
    portfolio, database = _saved(tmp_path)

    class EmptyAnalyzer(FakeAnalyzer):
        def analyze(self, asset, image, metadata):
            return ()

    sources = []

    def source_factory(*_):
        source = FakeSource()
        sources.append(source)
        return source

    result = run_visual_analysis(
        portfolio,
        database,
        "secret",
        EmptyAnalyzer(),
        options=VisualAnalysisOptions(limit=1),
        source_factory=source_factory,
    )

    assert result.failed == 1
    assert result.completed == 0
    assert sources[0].resources[0].closed
    with SQLitePortfolioRepository(database) as repository:
        snapshot = repository.visual_analysis_snapshot(
            "smugmug",
            "portfolio",
            "photo-a",
            AnalyzerIdentity("fake", "1", "defaults"),
        )
    assert snapshot.state.status is VisualRunStatus.FAILED
    assert snapshot.state.error_category == "analyzer_output"
    assert snapshot.state.error_message == (
        "The selected visual analyzer returned no results unexpectedly."
    )
    assert not snapshot.state.has_successful_snapshot
    assert snapshot.results == ()


def test_empty_output_failed_refresh_preserves_previous_successful_snapshot(
    tmp_path,
) -> None:
    portfolio, database = _saved(tmp_path)
    analyzer = FakeAnalyzer()
    run_visual_analysis(
        portfolio,
        database,
        "secret",
        analyzer,
        options=VisualAnalysisOptions(limit=1),
        source_factory=lambda *_: FakeSource(),
    )
    with SQLitePortfolioRepository(database) as repository:
        before = repository.visual_analysis_snapshot(
            "smugmug", "portfolio", "photo-a", analyzer.identity
        )

    class EmptyAnalyzer(FakeAnalyzer):
        def analyze(self, asset, image, metadata):
            return ()

    result = run_visual_analysis(
        portfolio,
        database,
        "secret",
        EmptyAnalyzer(),
        options=VisualAnalysisOptions(limit=1, refresh=True),
        source_factory=lambda *_: FakeSource(),
    )

    assert result.failed == 1
    with SQLitePortfolioRepository(database) as repository:
        after = repository.visual_analysis_snapshot(
            "smugmug", "portfolio", "photo-a", analyzer.identity
        )
    assert after.state.status is VisualRunStatus.FAILED
    assert after.state.last_successful_completed_at == (before.state.last_successful_completed_at)
    assert after.results == before.results


def test_explicitly_allowed_empty_output_completes_and_resumes_as_complete(
    tmp_path,
) -> None:
    portfolio, database = _saved(tmp_path)

    class IntentionallyEmptyAnalyzer(FakeAnalyzer):
        allows_empty_results = True

        def analyze(self, asset, image, metadata):
            return ()

    analyzer = IntentionallyEmptyAnalyzer(allows_empty_results=True)
    first = run_visual_analysis(
        portfolio,
        database,
        "secret",
        analyzer,
        options=VisualAnalysisOptions(limit=1),
        source_factory=lambda *_: FakeSource(),
    )
    assert first.completed == 1
    with SQLitePortfolioRepository(database) as repository:
        snapshot = repository.visual_analysis_snapshot(
            "smugmug", "portfolio", "photo-a", analyzer.identity
        )
    assert snapshot.state.status is VisualRunStatus.COMPLETED
    assert snapshot.state.has_successful_snapshot
    assert snapshot.results == ()

    resumed = run_visual_analysis(
        portfolio,
        database,
        "secret",
        analyzer,
        options=VisualAnalysisOptions(limit=1),
        source_factory=lambda *_: FakeSource(),
    )
    assert resumed.completed == 0
    assert resumed.already_completed == 1


def test_transient_preview_retries_are_bounded_and_progress_includes_eta(tmp_path) -> None:
    portfolio, database = _saved(tmp_path)
    attempts = 0
    progress = []

    def behavior(asset):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise SourceTransientError("temporary")

    result = run_visual_analysis(
        portfolio,
        database,
        "secret",
        FakeAnalyzer(delay=0.01),
        options=VisualAnalysisOptions(limit=3, preview_attempts=3),
        progress=progress.append,
        source_factory=lambda *_: FakeSource(behavior),
        sleeper=lambda _: None,
    )

    assert result.completed == 3
    assert attempts == 5
    assert progress[-1].processed == 3
    assert progress[-1].remaining == 0
    assert any(item.estimated_seconds_remaining is not None for item in progress)


def test_exhausted_rate_limit_stops_scheduling_and_preserves_progress(tmp_path) -> None:
    portfolio, database = _saved(tmp_path)
    attempts = 0

    def behavior(asset):
        nonlocal attempts
        attempts += 1
        raise SourceRateLimitError(0)

    result = run_visual_analysis(
        portfolio,
        database,
        "secret",
        FakeAnalyzer(),
        options=VisualAnalysisOptions(preview_attempts=2),
        source_factory=lambda *_: FakeSource(behavior),
        sleeper=lambda _: None,
    )

    assert result.rate_limited
    assert result.failed == 1
    assert result.remaining == 3
    assert attempts == 2


def test_credentials_and_authentication_fail_without_losing_claim_state(tmp_path) -> None:
    portfolio, database = _saved(tmp_path)
    analyzer = FakeAnalyzer()
    with pytest.raises(VisualWorkflowError, match="credentials"):
        run_visual_analysis(
            portfolio,
            database,
            "",
            analyzer,
            source_factory=lambda *_: FakeSource(),
        )

    result = run_visual_analysis(
        portfolio,
        database,
        "secret",
        analyzer,
        source_factory=lambda *_: FakeSource(
            lambda asset: (_ for _ in ()).throw(SourceAuthenticationError("denied"))
        ),
    )
    assert result.configuration_failed
    assert result.cancelled == 1
    assert analyzer.calls == []
    with SQLitePortfolioRepository(database) as repository:
        snapshot = repository.visual_analysis_snapshot(
            "smugmug", "portfolio", "photo-a", analyzer.identity
        )
    assert snapshot.state.status is VisualRunStatus.PENDING
    assert snapshot.state.interruption_category == "source_access"


def test_cancellation_preserves_prior_snapshot_and_requires_retry(tmp_path) -> None:
    portfolio, database = _saved(tmp_path)
    analyzer = FakeAnalyzer()
    run_visual_analysis(
        portfolio,
        database,
        "secret",
        analyzer,
        options=VisualAnalysisOptions(limit=1),
        source_factory=lambda *_: FakeSource(),
    )
    cancellation = threading.Event()

    class CancellingAnalyzer(FakeAnalyzer):
        def analyze(self, asset, image, metadata):
            cancellation.set()
            return super().analyze(asset, image, metadata)

    cancelled = run_visual_analysis(
        portfolio,
        database,
        "secret",
        CancellingAnalyzer(),
        options=VisualAnalysisOptions(limit=1, refresh=True),
        cancellation=cancellation,
        source_factory=lambda *_: FakeSource(),
    )
    assert cancelled.cancelled == 1
    with SQLitePortfolioRepository(database) as repository:
        snapshot = repository.visual_analysis_snapshot(
            "smugmug", "portfolio", "photo-a", analyzer.identity
        )
    assert snapshot.state.status is VisualRunStatus.PENDING
    assert snapshot.state.attempts == 2
    assert snapshot.state.has_successful_snapshot
    assert snapshot.results


def test_keyboard_interrupt_preserves_completed_assets_and_stops_new_claims(tmp_path) -> None:
    portfolio, database = _saved(tmp_path)

    def interrupt_after_progress(progress):
        raise KeyboardInterrupt

    result = run_visual_analysis(
        portfolio,
        database,
        "secret",
        FakeAnalyzer(),
        progress=interrupt_after_progress,
        source_factory=lambda *_: FakeSource(),
    )

    assert result.cancelled_by_user
    assert result.completed == 1
    assert result.remaining == 2
    with SQLitePortfolioRepository(database) as repository:
        first = repository.visual_analysis_snapshot(
            "smugmug",
            "portfolio",
            "photo-a",
            AnalyzerIdentity("fake", "1", "defaults"),
        )
        second = repository.visual_analysis_snapshot(
            "smugmug",
            "portfolio",
            "photo-b",
            AnalyzerIdentity("fake", "1", "defaults"),
        )
    assert first.state.status is VisualRunStatus.COMPLETED
    assert second.state.status is VisualRunStatus.PENDING


def test_running_is_never_reclaimed_by_any_retry_mode(tmp_path) -> None:
    portfolio, database = _saved(tmp_path)
    identity = AnalyzerIdentity("fake", "1", "defaults")
    with SQLitePortfolioRepository(database) as repository:
        assert repository.claim_visual_analysis("smugmug", "portfolio", "photo-a", identity)

    for options in (
        VisualAnalysisOptions(limit=1),
        VisualAnalysisOptions(limit=1, retry_failed=True),
        VisualAnalysisOptions(limit=1, only_failed=True),
    ):
        analyzer = FakeAnalyzer()
        result = run_visual_analysis(
            portfolio,
            database,
            "secret",
            analyzer,
            options=options,
            source_factory=lambda *_: FakeSource(),
        )
        assert result.running_elsewhere == 1
        assert analyzer.calls == []
        with SQLitePortfolioRepository(database) as repository:
            snapshot = repository.visual_analysis_snapshot(
                "smugmug", "portfolio", "photo-a", identity
            )
        assert snapshot.state.status is VisualRunStatus.RUNNING
        assert snapshot.state.attempts == 1


def test_default_one_worker_and_explicit_multi_worker_are_bounded(tmp_path) -> None:
    portfolio, database = _saved(tmp_path)
    single = FakeAnalyzer(delay=0.01)
    run_visual_analysis(
        portfolio,
        database,
        "secret",
        single,
        source_factory=lambda *_: FakeSource(),
    )
    assert single.maximum_active == 1

    second_identity = AnalyzerIdentity("fake", "2", "defaults")
    multiple = FakeAnalyzer(identity=second_identity, delay=0.05)
    run_visual_analysis(
        portfolio,
        database,
        "secret",
        multiple,
        options=VisualAnalysisOptions(workers=2),
        source_factory=lambda *_: FakeSource(),
    )
    assert multiple.maximum_active == 2


@pytest.mark.parametrize("workers", [0, 5])
def test_invalid_worker_count_is_rejected_before_execution(workers) -> None:
    with pytest.raises(ValueError, match="between 1 and 4"):
        VisualAnalysisOptions(workers=workers)


def test_new_analyzer_version_is_independently_pending(tmp_path) -> None:
    portfolio, database = _saved(tmp_path)
    first = FakeAnalyzer()
    run_visual_analysis(
        portfolio,
        database,
        "secret",
        first,
        options=VisualAnalysisOptions(limit=1),
        source_factory=lambda *_: FakeSource(),
    )
    second = FakeAnalyzer(identity=AnalyzerIdentity("fake", "2", "defaults"))
    result = run_visual_analysis(
        portfolio,
        database,
        "secret",
        second,
        options=VisualAnalysisOptions(limit=1),
        source_factory=lambda *_: FakeSource(),
    )
    assert result.completed == 1
    assert second.calls == ["photo-a"]


def test_two_commands_cannot_process_same_exact_identity(tmp_path) -> None:
    portfolio, database = _saved(tmp_path)
    started = threading.Event()
    release = threading.Event()
    analyzer = FakeAnalyzer(started=started, release=release)
    results = []

    def run():
        results.append(
            run_visual_analysis(
                portfolio,
                database,
                "secret",
                analyzer,
                options=VisualAnalysisOptions(limit=1),
                source_factory=lambda *_: FakeSource(),
            )
        )

    first = threading.Thread(target=run)
    first.start()
    assert started.wait(timeout=5)
    second = run_visual_analysis(
        portfolio,
        database,
        "secret",
        analyzer,
        options=VisualAnalysisOptions(limit=1, retry_failed=True),
        source_factory=lambda *_: FakeSource(),
    )
    release.set()
    first.join(timeout=5)

    assert second.running_elsewhere == 1
    assert sum(result.completed for result in results) == 1
    assert analyzer.calls == ["photo-a"]
