import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest

from ppa.models import Asset, AssetMetadata, MediaType, Portfolio, SourceReference
from ppa.storage import SQLitePortfolioRepository
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


def test_initial_claim_completion_and_round_trip_all_value_families(tmp_path) -> None:
    repository = _repository(tmp_path / "portfolio.sqlite3")
    initial = repository.visual_analysis_snapshot("test", "portfolio-1", "asset-1", IDENTITY)
    assert initial.state.status is VisualRunStatus.PENDING
    assert initial.state.attempts == 0
    assert initial.results == ()

    assert repository.claim_visual_analysis("test", "portfolio-1", "asset-1", IDENTITY, at=T0)
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
        "test", "portfolio-1", "asset-1", IDENTITY, results, at=T0 + timedelta(seconds=2)
    )

    snapshot = repository.visual_analysis_snapshot("test", "portfolio-1", "asset-1", IDENTITY)
    assert snapshot.state.status is VisualRunStatus.COMPLETED
    assert snapshot.state.has_successful_snapshot
    assert snapshot.state.attempts == 1
    assert snapshot.state.last_successful_completed_at == T0 + timedelta(seconds=2)
    assert {item.name for item in snapshot.results} == {
        "brightness",
        "contains_people",
        "palette",
        "subject_box",
    }
    assert next(item for item in snapshot.results if item.name == "contains_people").confidence == 0


def test_versions_and_configurations_coexist_without_overwrite(tmp_path) -> None:
    repository = _repository(tmp_path / "portfolio.sqlite3")
    identities = (
        IDENTITY,
        AnalyzerIdentity("visual-color", "2.0.0", "defaults-v1"),
        AnalyzerIdentity("visual-color", "1.0.0", "defaults-v2"),
    )
    for index, identity in enumerate(identities):
        assert repository.claim_visual_analysis("test", "portfolio-1", "asset-1", identity)
        repository.complete_visual_analysis(
            "test", "portfolio-1", "asset-1", identity, (_result(value=index),)
        )

    assert [
        repository.visual_analysis_snapshot("test", "portfolio-1", "asset-1", identity)
        .results[0]
        .value
        for identity in identities
    ] == [0, 1, 2]


def test_refresh_failure_and_cancellation_retain_last_successful_snapshot(tmp_path) -> None:
    repository = _repository(tmp_path / "portfolio.sqlite3")
    assert repository.claim_visual_analysis("test", "portfolio-1", "asset-1", IDENTITY, at=T0)
    repository.complete_visual_analysis(
        "test", "portfolio-1", "asset-1", IDENTITY, (_result(value=0.25),), at=T0
    )

    assert repository.claim_visual_analysis(
        "test", "portfolio-1", "asset-1", IDENTITY, refresh=True, at=T0 + timedelta(hours=1)
    )
    running = repository.visual_analysis_snapshot("test", "portfolio-1", "asset-1", IDENTITY)
    assert running.state.status is VisualRunStatus.RUNNING
    assert running.state.last_successful_completed_at == T0
    assert running.results[0].value == 0.25

    repository.cancel_visual_analysis(
        "test", "portfolio-1", "asset-1", IDENTITY, at=T0 + timedelta(hours=2)
    )
    cancelled = repository.visual_analysis_snapshot("test", "portfolio-1", "asset-1", IDENTITY)
    assert cancelled.state.status is VisualRunStatus.PENDING
    assert cancelled.state.attempts == 2
    assert cancelled.state.interruption_category == "cancelled"
    assert cancelled.state.last_successful_completed_at == T0
    assert cancelled.results[0].value == 0.25
    assert not repository.claim_visual_analysis("test", "portfolio-1", "asset-1", IDENTITY)
    assert repository.claim_visual_analysis(
        "test", "portfolio-1", "asset-1", IDENTITY, retry_failed=True
    )
    repository.fail_visual_analysis(
        "test", "portfolio-1", "asset-1", IDENTITY, "decode", "sanitized failure"
    )
    failed = repository.visual_analysis_snapshot("test", "portfolio-1", "asset-1", IDENTITY)
    assert failed.state.status is VisualRunStatus.FAILED
    assert failed.state.attempts == 3
    assert failed.results[0].value == 0.25
    assert failed.state.last_successful_completed_at == T0


def test_successful_refresh_atomically_replaces_snapshot(tmp_path) -> None:
    repository = _repository(tmp_path / "portfolio.sqlite3")
    assert repository.claim_visual_analysis("test", "portfolio-1", "asset-1", IDENTITY)
    repository.complete_visual_analysis(
        "test", "portfolio-1", "asset-1", IDENTITY, (_result("old", 1),), at=T0
    )
    assert repository.claim_visual_analysis(
        "test", "portfolio-1", "asset-1", IDENTITY, refresh=True
    )
    replacement_time = T0 + timedelta(days=1)
    repository.complete_visual_analysis(
        "test",
        "portfolio-1",
        "asset-1",
        IDENTITY,
        (_result("new", 2),),
        at=replacement_time,
    )

    snapshot = repository.visual_analysis_snapshot("test", "portfolio-1", "asset-1", IDENTITY)
    assert snapshot.state.last_successful_completed_at == replacement_time
    assert [(result.name, result.value) for result in snapshot.results] == [("new", 2)]


def test_result_replacement_rolls_back_on_failure(tmp_path) -> None:
    database = tmp_path / "portfolio.sqlite3"
    repository = _repository(database)
    assert repository.claim_visual_analysis("test", "portfolio-1", "asset-1", IDENTITY)
    repository.complete_visual_analysis(
        "test", "portfolio-1", "asset-1", IDENTITY, (_result("old", 1),), at=T0
    )
    assert repository.claim_visual_analysis(
        "test", "portfolio-1", "asset-1", IDENTITY, refresh=True
    )
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
        )
    snapshot = repository.visual_analysis_snapshot("test", "portfolio-1", "asset-1", IDENTITY)
    assert snapshot.state.status is VisualRunStatus.RUNNING
    assert snapshot.state.last_successful_completed_at == T0
    assert [(result.name, result.value) for result in snapshot.results] == [("old", 1)]


def test_exact_identity_claim_is_concurrency_safe(tmp_path) -> None:
    database = tmp_path / "portfolio.sqlite3"
    repository = _repository(database)
    repository.close()

    def claim() -> bool:
        with SQLitePortfolioRepository(database) as candidate:
            return candidate.claim_visual_analysis("test", "portfolio-1", "asset-1", IDENTITY)

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(lambda _: claim(), range(2)))

    assert sorted(outcomes) == [False, True]


def test_skip_and_foreign_key_enforcement(tmp_path) -> None:
    repository = _repository(tmp_path / "portfolio.sqlite3")
    with pytest.raises(KeyError, match="missing"):
        repository.claim_visual_analysis("test", "portfolio-1", "missing", IDENTITY)
    assert repository.claim_visual_analysis("test", "portfolio-1", "asset-1", IDENTITY)
    repository.skip_visual_analysis("test", "portfolio-1", "asset-1", IDENTITY, "not applicable")
    snapshot = repository.visual_analysis_snapshot("test", "portfolio-1", "asset-1", IDENTITY)
    assert snapshot.state.status is VisualRunStatus.SKIPPED
    assert snapshot.state.skip_reason == "not applicable"
    assert snapshot.results == ()
