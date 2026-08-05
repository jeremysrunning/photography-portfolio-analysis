import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest

from ppa.models import Asset, AssetMetadata, MediaType, Portfolio, SourceReference
from ppa.storage import (
    SQLitePortfolioRepository,
    VisualAnalysisClaim,
    VisualAnalysisOwnershipLostError,
)
from ppa.storage.sqlite import SCHEMA_VERSION
from ppa.visual import (
    AnalyzerIdentity,
    NormalizedBoundingBox,
    VisualResult,
    VisualResultKind,
    VisualRunStatus,
)

IDENTITY = AnalyzerIdentity("visual-color", "1.0.0", "defaults-v1")
T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _portfolio() -> Portfolio:
    asset = Asset(
        SourceReference("asset-1", "https://example.test/asset-1"),
        AssetMetadata(MediaType.PHOTOGRAPH),
    )
    return Portfolio(
        "test",
        SourceReference("portfolio-1", "https://example.test/portfolio-1"),
        "Portfolio",
        assets=(asset,),
    )


def _result(name: str = "brightness", value: object = 0.4) -> VisualResult:
    return VisualResult(
        name,
        VisualResultKind.MEASUREMENT,
        value,  # type: ignore[arg-type]
        "pixel-statistics",
        "1.0",
        unit="normalized",
    )


def _repository(database) -> SQLitePortfolioRepository:
    repository = SQLitePortfolioRepository(database)
    repository.save(_portfolio())
    return repository


def test_schema_v6_creation_and_v5_additive_migration(tmp_path) -> None:
    database = tmp_path / "portfolio.sqlite3"
    repository = _repository(database)
    repository.close()
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TABLE visual_analysis_results")
        connection.execute("DROP TABLE visual_analysis_runs")
        connection.execute("UPDATE schema_metadata SET value = '5' WHERE key = 'version'")

    with SQLitePortfolioRepository(database) as migrated:
        migrated.initialize()
        assert migrated.get("test", "portfolio-1") == _portfolio()

    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT value FROM schema_metadata WHERE key = 'version'"
        ).fetchone() == (str(SCHEMA_VERSION),)
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert {"visual_analysis_runs", "visual_analysis_results"} <= tables
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM visual_analysis_runs").fetchone() == (0,)
        assert connection.execute("SELECT COUNT(*) FROM visual_analysis_results").fetchone() == (0,)


def test_initial_claim_completion_and_round_trip_all_value_families(tmp_path) -> None:
    repository = _repository(tmp_path / "portfolio.sqlite3")
    initial = repository.visual_analysis_snapshot("test", "portfolio-1", "asset-1", IDENTITY)
    assert initial.state.status is VisualRunStatus.PENDING
    assert initial.state.attempts == 0
    assert initial.results == ()

    claim = repository.claim_visual_analysis("test", "portfolio-1", "asset-1", IDENTITY, at=T0)
    assert claim == VisualAnalysisClaim(1)
    results = (
        _result(),
        VisualResult(
            "contains_people",
            VisualResultKind.CLASSIFICATION,
            False,
            "person-detector",
            "1",
            confidence=0.0,
            model_name="detector",
            model_version="2026-01",
        ),
        _result(
            "subject_box",
            NormalizedBoundingBox(0.1, 0.2, 0.3, 0.4),
        ),
        _result("palette", {"colors": ["#112233", "#445566"]}),
    )
    repository.complete_visual_analysis(
        "test",
        "portfolio-1",
        "asset-1",
        IDENTITY,
        results,
        expected_generation=claim.attempt_generation,
        at=T0 + timedelta(seconds=2),
    )

    snapshot = repository.visual_analysis_snapshot("test", "portfolio-1", "asset-1", IDENTITY)
    assert snapshot.state.status is VisualRunStatus.COMPLETED
    assert snapshot.state.has_successful_snapshot
    assert snapshot.state.attempts == 1
    assert snapshot.state.last_successful_completed_at == T0 + timedelta(seconds=2)
    assert {item.completed_at for item in snapshot.results} == {
        snapshot.state.last_successful_completed_at
    }
    assert all(item.completed_at is not None for item in snapshot.results)
    assert all(item.completed_at.utcoffset() is not None for item in snapshot.results)
    assert {item.name for item in snapshot.results} == {
        "brightness",
        "contains_people",
        "palette",
        "subject_box",
    }
    assert next(item for item in snapshot.results if item.name == "contains_people").confidence == 0


def test_completed_result_round_trip_preserves_timestamp_exactly(tmp_path) -> None:
    repository = _repository(tmp_path / "portfolio.sqlite3")
    completed = VisualResult(
        "brightness",
        VisualResultKind.MEASUREMENT,
        0.4,
        "pixel-statistics",
        "1.0",
        unit="normalized",
        completed_at=T0,
    )
    claim = repository.claim_visual_analysis("test", "portfolio-1", "asset-1", IDENTITY)
    assert claim is not None
    repository.complete_visual_analysis(
        "test",
        "portfolio-1",
        "asset-1",
        IDENTITY,
        (completed,),
        expected_generation=claim.attempt_generation,
        at=T0,
    )

    loaded = repository.visual_analysis_snapshot("test", "portfolio-1", "asset-1", IDENTITY)
    assert loaded.results == (completed,)
    assert loaded.state.last_successful_completed_at == completed.completed_at


def test_versions_and_configurations_coexist_without_overwrite(tmp_path) -> None:
    repository = _repository(tmp_path / "portfolio.sqlite3")
    identities = (
        IDENTITY,
        AnalyzerIdentity("visual-color", "2.0.0", "defaults-v1"),
        AnalyzerIdentity("visual-color", "1.0.0", "defaults-v2"),
    )
    for index, identity in enumerate(identities):
        claim = repository.claim_visual_analysis("test", "portfolio-1", "asset-1", identity)
        assert claim is not None
        repository.complete_visual_analysis(
            "test",
            "portfolio-1",
            "asset-1",
            identity,
            (_result(value=index),),
            expected_generation=claim.attempt_generation,
        )

    assert [
        repository.visual_analysis_snapshot("test", "portfolio-1", "asset-1", identity)
        .results[0]
        .value
        for identity in identities
    ] == [0, 1, 2]


def test_bulk_visual_reads_use_normalized_assets_and_include_implicit_pending(tmp_path) -> None:
    second = Asset(
        SourceReference("asset-2", "https://example.test/asset-2"),
        AssetMetadata(MediaType.PHOTOGRAPH),
    )
    portfolio = Portfolio(
        "test",
        SourceReference("portfolio-1", "https://example.test/portfolio-1"),
        "Portfolio",
        assets=(*_portfolio().assets, second),
    )
    repository = SQLitePortfolioRepository(tmp_path / "portfolio.sqlite3")
    repository.save(portfolio)
    historical = AnalyzerIdentity("visual-color", "0.9.0", "defaults-v0")
    for identity in (IDENTITY, historical):
        claim = repository.claim_visual_analysis("test", "portfolio-1", "asset-1", identity, at=T0)
        assert claim is not None
        repository.complete_visual_analysis(
            "test",
            "portfolio-1",
            "asset-1",
            identity,
            (_result(),),
            expected_generation=claim.attempt_generation,
            at=T0,
        )

    assert repository.list_visual_analysis_identities(portfolio) == (historical, IDENTITY)
    records = repository.list_visual_analysis_records(portfolio, IDENTITY)
    assert tuple(record.asset for record in records) == portfolio.assets
    assert records[0].snapshot.state.status is VisualRunStatus.COMPLETED
    assert records[0].snapshot.results[0].value == 0.4
    assert records[1].snapshot.state.status is VisualRunStatus.PENDING
    assert records[1].snapshot.state.attempts == 0
    assert records[1].snapshot.results == ()


def test_refresh_failure_and_cancellation_retain_last_successful_snapshot(tmp_path) -> None:
    repository = _repository(tmp_path / "portfolio.sqlite3")
    first_claim = repository.claim_visual_analysis(
        "test", "portfolio-1", "asset-1", IDENTITY, at=T0
    )
    assert first_claim == VisualAnalysisClaim(1)
    repository.complete_visual_analysis(
        "test",
        "portfolio-1",
        "asset-1",
        IDENTITY,
        (_result(value=0.25),),
        expected_generation=first_claim.attempt_generation,
        at=T0,
    )

    refresh_claim = repository.claim_visual_analysis(
        "test", "portfolio-1", "asset-1", IDENTITY, refresh=True, at=T0 + timedelta(hours=1)
    )
    assert refresh_claim == VisualAnalysisClaim(2)
    running = repository.visual_analysis_snapshot("test", "portfolio-1", "asset-1", IDENTITY)
    assert running.state.status is VisualRunStatus.RUNNING
    assert running.state.last_successful_completed_at == T0
    assert running.results[0].value == 0.25
    assert running.results[0].completed_at == T0

    repository.cancel_visual_analysis(
        "test",
        "portfolio-1",
        "asset-1",
        IDENTITY,
        expected_generation=refresh_claim.attempt_generation,
        at=T0 + timedelta(hours=2),
    )
    cancelled = repository.visual_analysis_snapshot("test", "portfolio-1", "asset-1", IDENTITY)
    assert cancelled.state.status is VisualRunStatus.PENDING
    assert cancelled.state.attempts == 2
    assert cancelled.state.interruption_category == "cancelled"
    assert cancelled.state.last_successful_completed_at == T0
    assert cancelled.results[0].value == 0.25
    assert cancelled.results[0].completed_at == T0
    assert not repository.claim_visual_analysis("test", "portfolio-1", "asset-1", IDENTITY)
    retry_claim = repository.claim_visual_analysis(
        "test", "portfolio-1", "asset-1", IDENTITY, retry_failed=True
    )
    assert retry_claim == VisualAnalysisClaim(3)
    repository.fail_visual_analysis(
        "test",
        "portfolio-1",
        "asset-1",
        IDENTITY,
        "decode",
        "sanitized failure",
        expected_generation=retry_claim.attempt_generation,
    )
    failed = repository.visual_analysis_snapshot("test", "portfolio-1", "asset-1", IDENTITY)
    assert failed.state.status is VisualRunStatus.FAILED
    assert failed.state.attempts == 3
    assert failed.results[0].value == 0.25
    assert failed.state.last_successful_completed_at == T0
    assert failed.results[0].completed_at == T0


def test_successful_refresh_atomically_replaces_snapshot(tmp_path) -> None:
    repository = _repository(tmp_path / "portfolio.sqlite3")
    first_claim = repository.claim_visual_analysis("test", "portfolio-1", "asset-1", IDENTITY)
    assert first_claim is not None
    repository.complete_visual_analysis(
        "test",
        "portfolio-1",
        "asset-1",
        IDENTITY,
        (_result("old", 1),),
        expected_generation=first_claim.attempt_generation,
        at=T0,
    )
    refresh_claim = repository.claim_visual_analysis(
        "test", "portfolio-1", "asset-1", IDENTITY, refresh=True
    )
    assert refresh_claim is not None
    replacement_time = T0 + timedelta(days=1)
    repository.complete_visual_analysis(
        "test",
        "portfolio-1",
        "asset-1",
        IDENTITY,
        (_result("new", 2),),
        expected_generation=refresh_claim.attempt_generation,
        at=replacement_time,
    )

    snapshot = repository.visual_analysis_snapshot("test", "portfolio-1", "asset-1", IDENTITY)
    assert snapshot.state.last_successful_completed_at == replacement_time
    assert [(result.name, result.value) for result in snapshot.results] == [("new", 2)]
    assert snapshot.results[0].completed_at == replacement_time


def test_result_replacement_rolls_back_on_failure(tmp_path) -> None:
    database = tmp_path / "portfolio.sqlite3"
    repository = _repository(database)
    first_claim = repository.claim_visual_analysis("test", "portfolio-1", "asset-1", IDENTITY)
    assert first_claim is not None
    repository.complete_visual_analysis(
        "test",
        "portfolio-1",
        "asset-1",
        IDENTITY,
        (_result("old", 1),),
        expected_generation=first_claim.attempt_generation,
        at=T0,
    )
    refresh_claim = repository.claim_visual_analysis(
        "test", "portfolio-1", "asset-1", IDENTITY, refresh=True
    )
    assert refresh_claim is not None
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_visual_result
            BEFORE INSERT ON visual_analysis_results
            WHEN NEW.result_name = 'reject'
            BEGIN SELECT RAISE(ABORT, 'rejected'); END
            """
        )

    with pytest.raises(sqlite3.IntegrityError):
        repository.complete_visual_analysis(
            "test",
            "portfolio-1",
            "asset-1",
            IDENTITY,
            (_result("replacement", 2), _result("reject", 3)),
            expected_generation=refresh_claim.attempt_generation,
        )
    snapshot = repository.visual_analysis_snapshot("test", "portfolio-1", "asset-1", IDENTITY)
    assert snapshot.state.status is VisualRunStatus.RUNNING
    assert snapshot.state.last_successful_completed_at == T0
    assert [(result.name, result.value) for result in snapshot.results] == [("old", 1)]
    assert snapshot.results[0].completed_at == T0


def test_claim_generation_increments_once_per_successful_claim(tmp_path) -> None:
    repository = _repository(tmp_path / "portfolio.sqlite3")
    first = repository.claim_visual_analysis("test", "portfolio-1", "asset-1", IDENTITY)
    assert first == VisualAnalysisClaim(1)
    assert repository.claim_visual_analysis("test", "portfolio-1", "asset-1", IDENTITY) is None

    repository.cancel_visual_analysis(
        "test",
        "portfolio-1",
        "asset-1",
        IDENTITY,
        expected_generation=first.attempt_generation,
    )
    second = repository.claim_visual_analysis(
        "test", "portfolio-1", "asset-1", IDENTITY, retry_failed=True
    )
    assert second == VisualAnalysisClaim(2)


@pytest.mark.parametrize("transition", ["complete", "fail", "cancel", "skip"])
def test_older_generation_terminal_transition_preserves_newer_attempt_and_snapshot(
    tmp_path, transition
) -> None:
    repository = _repository(tmp_path / f"{transition}.sqlite3")
    first = repository.claim_visual_analysis("test", "portfolio-1", "asset-1", IDENTITY, at=T0)
    assert first == VisualAnalysisClaim(1)
    repository.complete_visual_analysis(
        "test",
        "portfolio-1",
        "asset-1",
        IDENTITY,
        (_result("retained", 1),),
        expected_generation=first.attempt_generation,
        at=T0,
    )
    second = repository.claim_visual_analysis(
        "test",
        "portfolio-1",
        "asset-1",
        IDENTITY,
        refresh=True,
        at=T0 + timedelta(hours=1),
    )
    assert second == VisualAnalysisClaim(2)
    before = repository.visual_analysis_snapshot("test", "portfolio-1", "asset-1", IDENTITY)

    with pytest.raises(
        VisualAnalysisOwnershipLostError,
        match="attempt ownership was lost",
    ):
        if transition == "complete":
            repository.complete_visual_analysis(
                "test",
                "portfolio-1",
                "asset-1",
                IDENTITY,
                (_result("replacement", 2),),
                expected_generation=first.attempt_generation,
            )
        elif transition == "fail":
            repository.fail_visual_analysis(
                "test",
                "portfolio-1",
                "asset-1",
                IDENTITY,
                "late",
                "sanitized",
                expected_generation=first.attempt_generation,
            )
        elif transition == "cancel":
            repository.cancel_visual_analysis(
                "test",
                "portfolio-1",
                "asset-1",
                IDENTITY,
                expected_generation=first.attempt_generation,
            )
        else:
            repository.skip_visual_analysis(
                "test",
                "portfolio-1",
                "asset-1",
                IDENTITY,
                "late skip",
                expected_generation=first.attempt_generation,
            )

    after = repository.visual_analysis_snapshot("test", "portfolio-1", "asset-1", IDENTITY)
    assert after == before
    assert after.state.status is VisualRunStatus.RUNNING
    assert after.state.attempts == second.attempt_generation
    assert after.state.last_successful_completed_at == T0
    assert [(result.name, result.value) for result in after.results] == [("retained", 1)]


def test_exact_identity_claim_is_concurrency_safe(tmp_path) -> None:
    database = tmp_path / "portfolio.sqlite3"
    repository = _repository(database)
    repository.close()

    def claim() -> VisualAnalysisClaim | None:
        with SQLitePortfolioRepository(database) as candidate:
            return candidate.claim_visual_analysis("test", "portfolio-1", "asset-1", IDENTITY)

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(lambda _: claim(), range(2)))

    assert sum(outcome is not None for outcome in outcomes) == 1
    assert {outcome.attempt_generation for outcome in outcomes if outcome is not None} == {1}


def test_skip_and_foreign_key_enforcement(tmp_path) -> None:
    repository = _repository(tmp_path / "portfolio.sqlite3")
    with pytest.raises(KeyError, match="missing"):
        repository.claim_visual_analysis("test", "portfolio-1", "missing", IDENTITY)
    claim = repository.claim_visual_analysis("test", "portfolio-1", "asset-1", IDENTITY)
    assert claim is not None
    repository.skip_visual_analysis(
        "test",
        "portfolio-1",
        "asset-1",
        IDENTITY,
        "not applicable",
        expected_generation=claim.attempt_generation,
    )
    snapshot = repository.visual_analysis_snapshot("test", "portfolio-1", "asset-1", IDENTITY)
    assert snapshot.state.status is VisualRunStatus.SKIPPED
    assert snapshot.state.skip_reason == "not applicable"
    assert snapshot.results == ()
