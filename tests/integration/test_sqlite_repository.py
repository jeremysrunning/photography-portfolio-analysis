import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from ppa.analysis import analyze_timeline
from ppa.models import (
    Asset,
    AssetMetadata,
    Finding,
    Gallery,
    GalleryPlacement,
    Measurement,
    MediaType,
    Observation,
    Portfolio,
    SourceReference,
)
from ppa.storage import SQLitePortfolioRepository, UnsupportedSchemaVersionError
from ppa.storage.sqlite import SCHEMA_VERSION


def _reference(source_id: str, prefix: str = "https://example.test") -> SourceReference:
    return SourceReference(source_id, f"{prefix}/{source_id}")


def _portfolio() -> Portfolio:
    shared = Asset(
        _reference("asset-1"),
        AssetMetadata(
            MediaType.PHOTOGRAPH,
            datetime(
                2024,
                1,
                2,
                3,
                4,
                tzinfo=timezone(timedelta(hours=-8)),
            ),
            {
                "ImageKey": "shared",
                "Format": "JPG",
                "OriginalWidth": 6000,
                "OriginalHeight": 4000,
                "Caption": None,
            },
            {"Make": "Example", "Model": "Camera A", "Lens": "Lens A"},
        ),
        preview_url="https://example.test/previews/1.jpg",
        measurements=(Measurement("aspect_ratio", 1.5, method="metadata"),),
    )
    video = Asset(
        _reference("asset-video"),
        AssetMetadata(
            MediaType.NON_PHOTO,
            values={"ImageKey": "video", "IsVideo": True, "Format": "MP4"},
        ),
    )
    return Portfolio(
        "test",
        _reference("portfolio-1"),
        "A body of work",
        metadata={"description": None},
        assets=(shared, video),
        galleries=(
            Gallery(
                _reference("gallery-1"),
                "People",
                metadata={"description": "First"},
                placements=(GalleryPlacement("asset-1"),),
            ),
            Gallery(
                _reference("gallery-2"),
                "Events",
                parent_source_id="gallery-1",
                placements=(
                    GalleryPlacement("asset-1"),
                    GalleryPlacement("asset-video"),
                ),
            ),
            Gallery(_reference("gallery-empty"), "Empty"),
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
        source TEXT NOT NULL, source_id TEXT NOT NULL, title TEXT NOT NULL,
        source_url TEXT NOT NULL, metadata_json TEXT NOT NULL,
        observations_json TEXT NOT NULL, findings_json TEXT NOT NULL,
        PRIMARY KEY (source, source_id)
    );
    CREATE TABLE galleries (
        source TEXT NOT NULL, portfolio_source_id TEXT NOT NULL,
        source_id TEXT NOT NULL, title TEXT NOT NULL, source_url TEXT NOT NULL,
        parent_source_id TEXT, metadata_json TEXT NOT NULL, position INTEGER NOT NULL,
        PRIMARY KEY (source, portfolio_source_id, source_id)
    );
    CREATE TABLE assets (
        source TEXT NOT NULL, portfolio_source_id TEXT NOT NULL,
        gallery_source_id TEXT NOT NULL, source_id TEXT NOT NULL,
        source_url TEXT NOT NULL, preview_url TEXT, captured_at TEXT,
        metadata_json TEXT NOT NULL, exif_json TEXT NOT NULL,
        measurements_json TEXT NOT NULL, position INTEGER NOT NULL,
        PRIMARY KEY (source, portfolio_source_id, gallery_source_id, source_id)
    );
    CREATE TABLE asset_enrichments (
        source TEXT NOT NULL, portfolio_source_id TEXT NOT NULL,
        asset_source_id TEXT NOT NULL, kind TEXT NOT NULL, status TEXT NOT NULL,
        attempts INTEGER NOT NULL, last_error TEXT, updated_at TEXT NOT NULL,
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
                    '{"Format":"JPG","IsVideo":false}',
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
    empty = Portfolio("test", _reference("empty"), "Empty")

    with SQLitePortfolioRepository(database) as repository:
        repository.initialize()
        repository.save(empty)
        assert repository.exists("test", "empty")
        assert repository.get("test", "empty") == empty

    with sqlite3.connect(database) as connection:
        version = connection.execute(
            "SELECT value FROM schema_metadata WHERE key = 'version'"
        ).fetchone()[0]
        asset_columns = {row[1]: row for row in connection.execute("PRAGMA table_info(assets)")}
        foreign_keys = connection.execute("PRAGMA foreign_key_list(gallery_placements)").fetchall()

    assert version == str(SCHEMA_VERSION)
    assert asset_columns["captured_at"][3] == 0
    assert asset_columns["media_type"][3] == 1
    assert len(foreign_keys) == 6


def test_round_trip_preserves_semantic_graph_missing_values_and_updates(tmp_path) -> None:
    database = tmp_path / "portfolio.sqlite3"
    portfolio = _portfolio()

    with SQLitePortfolioRepository(database) as repository:
        repository.save(portfolio)
        loaded = repository.get("test", "portfolio-1")
        repository.save(portfolio)

    assert loaded == portfolio
    assert loaded is not portfolio
    assert loaded is not None
    assert loaded.assets[0].metadata.values["Caption"] is None
    assert loaded.metadata["description"] is None
    assert loaded.assets[0].captured_at is not None
    assert loaded.assets[0].captured_at.utcoffset() == timedelta(hours=-8)
    assert loaded.assets[1].media_type is MediaType.NON_PHOTO
    assert loaded.gallery_assets(loaded.galleries[0])[0] == loaded.assets[0]
    assert loaded.gallery_assets(loaded.galleries[1])[0] == loaded.assets[0]
    assert _counts(database) == (1, 3, 2, 3)

    updated_asset = replace(
        portfolio.assets[0],
        metadata=replace(
            portfolio.assets[0].metadata,
            values={**portfolio.assets[0].values, "Caption": "Updated"},
            exif={},
        ),
        measurements=(),
    )
    updated = replace(
        portfolio,
        title="Updated title",
        assets=(updated_asset, portfolio.assets[1]),
        galleries=(replace(portfolio.galleries[0], title="Updated gallery"),),
    )
    with SQLitePortfolioRepository(database) as repository:
        repository.save(updated)
        reloaded = repository.get("test", "portfolio-1")

    assert reloaded is not None
    assert reloaded.title == "Updated title"
    assert reloaded.galleries[0].title == "Updated gallery"
    assert reloaded.assets[0].values["Caption"] == "Updated"
    assert reloaded.assets[0].exif["Model"] == "Camera A"
    assert reloaded.assets[0].measurements
    assert {gallery.source_id for gallery in reloaded.galleries} == {
        "gallery-1",
        "gallery-2",
        "gallery-empty",
    }


def test_transaction_rolls_back_and_foreign_keys_are_enforced(tmp_path) -> None:
    database = tmp_path / "portfolio.sqlite3"
    portfolio = _portfolio()

    with SQLitePortfolioRepository(database) as repository:
        repository.save(portfolio)
        original = repository.get("test", "portfolio-1")
        invalid = replace(portfolio, title="Must roll back")
        connection = repository._connect()
        connection.execute(
            """
            CREATE TRIGGER fail_gallery_update BEFORE UPDATE ON galleries
            BEGIN SELECT RAISE(ABORT, 'forced rollback'); END
            """
        )
        with pytest.raises(sqlite3.IntegrityError, match="forced rollback"):
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


def test_version_two_database_migrates_to_explicit_media_and_placements(tmp_path) -> None:
    database = tmp_path / "legacy.sqlite3"
    _create_v2_database(database)

    with SQLitePortfolioRepository(database) as repository:
        repository.initialize()
        migrated = repository.get("test", "legacy")
        status = repository.enrichment_status("test", "legacy", "exif")

    assert migrated is not None
    assert len(migrated.assets) == 1
    assert migrated.assets[0].media_type is MediaType.PHOTOGRAPH
    assert migrated.assets[0].exif["Model"] == "Legacy Camera"
    assert len(migrated.galleries) == 2
    assert migrated.galleries[0].placements == (GalleryPlacement("shared"),)
    assert migrated.galleries[1].placements == (GalleryPlacement("shared"),)
    assert status.completed == 1
    assert _counts(database) == (1, 2, 1, 2)


def test_version_three_database_migrates_without_losing_data(tmp_path) -> None:
    database = tmp_path / "version-three.sqlite3"
    portfolio = _portfolio()
    with SQLitePortfolioRepository(database) as repository:
        repository.save(portfolio)

    with sqlite3.connect(database) as connection:
        connection.execute("ALTER TABLE assets DROP COLUMN media_type")
        connection.execute("UPDATE schema_metadata SET value = '3' WHERE key = 'version'")

    with SQLitePortfolioRepository(database) as repository:
        migrated = repository.get("test", "portfolio-1")

    assert migrated is not None
    assert len(migrated.assets) == 2
    assert migrated.assets[0].media_type is MediaType.PHOTOGRAPH
    assert migrated.assets[1].media_type is MediaType.NON_PHOTO
    assert migrated.galleries[1].placements == (
        GalleryPlacement("asset-1"),
        GalleryPlacement("asset-video"),
    )


def test_connection_closes_and_reports_operate_after_load(tmp_path) -> None:
    database = tmp_path / "portfolio.sqlite3"
    with SQLitePortfolioRepository(database) as repository:
        repository.save(_portfolio())
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
