import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from ppa.analysis import analyze_timeline
from ppa.models import Asset, Finding, Gallery, Measurement, Observation, Portfolio
from ppa.storage import (
    SQLitePortfolioRepository,
    UnsupportedSchemaVersionError,
)
from ppa.storage.sqlite import SCHEMA_VERSION


def _portfolio() -> Portfolio:
    shared = Asset(
        source_id="asset-1",
        source_url="https://example.test/assets/1",
        preview_url="https://example.test/previews/1.jpg",
        gallery_source_id="gallery-1",
        captured_at=datetime(
            2024,
            1,
            2,
            3,
            4,
            tzinfo=timezone(timedelta(hours=-8)),
        ),
        metadata={
            "ImageKey": "shared",
            "Format": "JPG",
            "OriginalWidth": 6000,
            "OriginalHeight": 4000,
        },
        exif={"Make": "Example", "Model": "Camera A", "Lens": "Lens A"},
        measurements=(Measurement("aspect_ratio", 1.5, method="metadata"),),
    )
    second_placement = replace(shared, gallery_source_id="gallery-2")
    video = Asset(
        source_id="asset-video",
        source_url="https://example.test/assets/video",
        gallery_source_id="gallery-2",
        metadata={"ImageKey": "video", "IsVideo": True, "Format": "MP4"},
    )
    return Portfolio(
        source="test",
        source_id="portfolio-1",
        title="A body of work",
        source_url="https://example.test/",
        metadata={"owner": "Photographer"},
        galleries=(
            Gallery(
                source_id="gallery-1",
                title="People",
                source_url="https://example.test/people",
                metadata={"description": "First"},
                assets=(shared,),
            ),
            Gallery(
                source_id="gallery-2",
                title="Events",
                source_url="https://example.test/events",
                parent_source_id="gallery-1",
                assets=(second_placement, video),
            ),
            Gallery(
                source_id="gallery-empty",
                title="Empty",
                source_url="https://example.test/empty",
            ),
        ),
        observations=(Observation("Landscape orientation recurs.", ("asset-1",)),),
        findings=(Finding("Landscape orientation is common.", 0.8, ("aspect_ratio",)),),
    )


def _counts(database) -> tuple[int, int, int, int]:
    with sqlite3.connect(database) as connection:
        return tuple(
            connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("portfolios", "galleries", "assets", "gallery_placements")
        )


def _create_v2_database(database) -> None:
    schema = """
    CREATE TABLE schema_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE TABLE portfolios (
        source TEXT NOT NULL,
        source_id TEXT NOT NULL,
        title TEXT NOT NULL,
        source_url TEXT NOT NULL,
        metadata_json TEXT NOT NULL,
        observations_json TEXT NOT NULL,
        findings_json TEXT NOT NULL,
        PRIMARY KEY (source, source_id)
    );
    CREATE TABLE galleries (
        source TEXT NOT NULL,
        portfolio_source_id TEXT NOT NULL,
        source_id TEXT NOT NULL,
        title TEXT NOT NULL,
        source_url TEXT NOT NULL,
        parent_source_id TEXT,
        metadata_json TEXT NOT NULL,
        position INTEGER NOT NULL,
        PRIMARY KEY (source, portfolio_source_id, source_id)
    );
    CREATE TABLE assets (
        source TEXT NOT NULL,
        portfolio_source_id TEXT NOT NULL,
        gallery_source_id TEXT NOT NULL,
        source_id TEXT NOT NULL,
        source_url TEXT NOT NULL,
        preview_url TEXT,
        captured_at TEXT,
        metadata_json TEXT NOT NULL,
        exif_json TEXT NOT NULL,
        measurements_json TEXT NOT NULL,
        position INTEGER NOT NULL,
        PRIMARY KEY (source, portfolio_source_id, gallery_source_id, source_id)
    );
    CREATE TABLE asset_enrichments (
        source TEXT NOT NULL,
        portfolio_source_id TEXT NOT NULL,
        asset_source_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        status TEXT NOT NULL,
        attempts INTEGER NOT NULL,
        last_error TEXT,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (source, portfolio_source_id, asset_source_id, kind)
    );
    """
    with sqlite3.connect(database) as connection:
        connection.executescript(schema)
        connection.execute("INSERT INTO schema_metadata VALUES ('version', '2')")
        connection.execute(
            "INSERT INTO portfolios VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("test", "legacy", "Legacy", "https://example.test", "{}", "[]", "[]"),
        )
        for position, gallery_id in enumerate(("one", "two")):
            connection.execute(
                "INSERT INTO galleries VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "test",
                    "legacy",
                    gallery_id,
                    gallery_id.title(),
                    f"https://example.test/{gallery_id}",
                    None,
                    "{}",
                    position,
                ),
            )
            connection.execute(
                "INSERT INTO assets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "test",
                    "legacy",
                    gallery_id,
                    "shared",
                    "https://example.test/shared",
                    None,
                    "2024-01-01T00:00:00+00:00",
                    '{"ImageKey":"shared"}',
                    '{"Model":"Legacy Camera"}',
                    "[]",
                    0,
                ),
            )
        connection.execute(
            "INSERT INTO asset_enrichments VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "test",
                "legacy",
                "shared",
                "exif",
                "completed",
                1,
                None,
                "2024-01-01T00:00:00+00:00",
            ),
        )


def test_schema_creation_version_foreign_keys_and_empty_portfolio(tmp_path) -> None:
    database = tmp_path / "portfolio.sqlite3"
    empty = Portfolio("test", "empty", "Empty", "https://example.test/empty")

    with SQLitePortfolioRepository(database) as repository:
        repository.initialize()
        repository.save(empty)
        assert repository.exists("test", "empty")
        assert not repository.exists("test", "missing")
        assert repository.get("test", "empty") == empty

    with sqlite3.connect(database) as connection:
        version = connection.execute(
            "SELECT value FROM schema_metadata WHERE key = 'version'"
        ).fetchone()[0]
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        foreign_keys = connection.execute("PRAGMA foreign_key_list(gallery_placements)").fetchall()

    assert version == str(SCHEMA_VERSION)
    assert {"portfolios", "galleries", "assets", "gallery_placements"} <= tables
    assert len(foreign_keys) == 6


def test_round_trip_shared_assets_idempotency_updates_and_retention(tmp_path) -> None:
    database = tmp_path / "portfolio.sqlite3"
    portfolio = _portfolio()

    with SQLitePortfolioRepository(database) as repository:
        repository.save(portfolio)
        loaded = repository.get("test", "portfolio-1")
        repository.save(portfolio)

    assert loaded is not None
    assert loaded.title == portfolio.title
    assert loaded.metadata == portfolio.metadata
    assert loaded.observations == portfolio.observations
    assert loaded.findings == portfolio.findings
    assert [gallery.source_id for gallery in loaded.galleries] == [
        "gallery-1",
        "gallery-2",
        "gallery-empty",
    ]
    assert loaded.galleries[2].assets == ()
    first = loaded.galleries[0].assets[0]
    placement = loaded.galleries[1].assets[0]
    assert first.source_id == placement.source_id == "asset-1"
    assert placement.gallery_source_id == "gallery-2"
    assert first.source_url == placement.source_url
    assert first.preview_url == placement.preview_url
    assert first.metadata == placement.metadata
    assert first.exif == placement.exif
    assert first.captured_at == portfolio.galleries[0].assets[0].captured_at
    assert first.captured_at is not None
    assert first.captured_at.utcoffset() == timedelta(hours=-8)
    assert loaded.galleries[1].assets[1].metadata["IsVideo"] is True
    assert _counts(database) == (1, 3, 2, 3)

    updated_asset = replace(
        portfolio.galleries[0].assets[0],
        metadata={**portfolio.galleries[0].assets[0].metadata, "Caption": "Updated"},
        exif={},
        measurements=(),
    )
    updated = replace(
        portfolio,
        title="Updated title",
        galleries=(
            replace(portfolio.galleries[0], title="Updated gallery", assets=(updated_asset,)),
        ),
    )
    with SQLitePortfolioRepository(database) as repository:
        repository.save(updated)
        reloaded = repository.get("test", "portfolio-1")

    assert reloaded is not None
    assert reloaded.title == "Updated title"
    assert reloaded.galleries[0].title == "Updated gallery"
    assert reloaded.galleries[0].assets[0].metadata["Caption"] == "Updated"
    assert reloaded.galleries[0].assets[0].exif["Model"] == "Camera A"
    assert reloaded.galleries[0].assets[0].measurements
    assert {gallery.source_id for gallery in reloaded.galleries} == {
        "gallery-1",
        "gallery-2",
        "gallery-empty",
    }
    assert _counts(database) == (1, 3, 2, 3)


def test_transaction_rolls_back_and_foreign_keys_are_enforced(tmp_path) -> None:
    database = tmp_path / "portfolio.sqlite3"
    portfolio = _portfolio()

    with SQLitePortfolioRepository(database) as repository:
        repository.save(portfolio)
        original = repository.get("test", "portfolio-1")
        invalid_asset = replace(
            portfolio.galleries[0].assets[0],
            gallery_source_id="wrong-gallery",
        )
        invalid = replace(
            portfolio,
            title="Must roll back",
            galleries=(replace(portfolio.galleries[0], assets=(invalid_asset,)),),
        )
        with pytest.raises(ValueError, match="does not match"):
            repository.save(invalid)
        assert repository.get("test", "portfolio-1") == original

    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO gallery_placements VALUES (
                    'test', 'portfolio-1', 'missing-gallery', 'asset-1', 0
                )
                """
            )


def test_unsupported_newer_schema_fails_clearly(tmp_path) -> None:
    database = tmp_path / "newer.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE schema_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO schema_metadata VALUES ('version', ?)",
            (str(SCHEMA_VERSION + 1),),
        )

    with (
        SQLitePortfolioRepository(database) as repository,
        pytest.raises(UnsupportedSchemaVersionError, match="Unsupported SQLite schema"),
    ):
        repository.initialize()


def test_version_two_database_migrates_without_losing_placements(tmp_path) -> None:
    database = tmp_path / "legacy.sqlite3"
    _create_v2_database(database)

    with SQLitePortfolioRepository(database) as repository:
        repository.initialize()
        migrated = repository.get("test", "legacy")
        status = repository.enrichment_status("test", "legacy", "exif")

    assert migrated is not None
    assert len(migrated.galleries) == 2
    assert migrated.galleries[0].assets[0].source_id == "shared"
    assert migrated.galleries[1].assets[0].source_id == "shared"
    assert migrated.galleries[0].assets[0].exif["Model"] == "Legacy Camera"
    assert status.completed == 1
    assert _counts(database) == (1, 2, 1, 2)
    with sqlite3.connect(database) as connection:
        version = connection.execute(
            "SELECT value FROM schema_metadata WHERE key = 'version'"
        ).fetchone()[0]
    assert version == str(SCHEMA_VERSION)


def test_file_connection_closes_and_timeline_reads_persisted_data(tmp_path) -> None:
    database = tmp_path / "portfolio.sqlite3"
    portfolio = _portfolio()

    with SQLitePortfolioRepository(database) as repository:
        repository.save(portfolio)
        persisted = repository.get("test", "portfolio-1")

    assert persisted is not None
    timeline = analyze_timeline(persisted)
    assert timeline.photograph_count == 1
    assert timeline.capture_coverage.available == 1
    moved = database.with_name("moved.sqlite3")
    database.rename(moved)
    assert moved.is_file()


def test_schema_contains_no_blob_columns_or_image_bytes(tmp_path) -> None:
    database = tmp_path / "portfolio.sqlite3"
    marker = b"binary-image-content-must-not-be-stored"

    with SQLitePortfolioRepository(database) as repository:
        repository.save(_portfolio())

    with sqlite3.connect(database) as connection:
        definitions = " ".join(
            row[0] or ""
            for row in connection.execute("SELECT sql FROM sqlite_master WHERE type = 'table'")
        )
    assert " BLOB" not in definitions.upper()
    assert marker not in database.read_bytes()
