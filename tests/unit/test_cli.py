from collections.abc import Iterator
from importlib import import_module

from ppa.cli import main
from ppa.models import (
    Asset,
    AssetMetadata,
    Gallery,
    GalleryPlacement,
    MediaType,
    Portfolio,
    SourceReference,
)
from ppa.storage import SQLitePortfolioRepository


def test_init_db_command_creates_database(tmp_path) -> None:
    database = tmp_path / "portfolio.sqlite3"
    assert main(["init-db", str(database)]) == 0
    assert database.exists()


def test_inspect_prints_summary_and_saves_dataset(monkeypatch, tmp_path, capsys) -> None:
    asset = Asset(
        SourceReference(
            "image-1",
            "https://example.smugmug.com/People/i-image-1",
        ),
        AssetMetadata(MediaType.PHOTOGRAPH),
    )
    portfolio = Portfolio(
        "smugmug",
        SourceReference("example", "https://example.smugmug.com"),
        "Example Photographer",
        assets=(asset,),
        galleries=(
            Gallery(
                SourceReference("gallery-1", "https://example.smugmug.com/People"),
                "People",
                placements=(GalleryPlacement("image-1"),),
            ),
        ),
    )

    class FakeSource:
        def __init__(self, url, api_key) -> None:
            assert url == "https://example.smugmug.com"
            assert api_key == "secret"

        def discover_portfolio(self) -> Portfolio:
            return Portfolio(
                portfolio.source_name,
                portfolio.source,
                portfolio.title,
            )

        def iter_galleries(self, discovered: Portfolio) -> Iterator[Gallery]:
            assert discovered.source_id == portfolio.source_id
            yield from portfolio.galleries

        def iter_assets(self, gallery: Gallery) -> Iterator[Asset]:
            yield from portfolio.gallery_assets(gallery)

    cli_module = import_module("ppa.cli.main")
    monkeypatch.setattr(cli_module, "SmugMugSource", FakeSource)
    database = tmp_path / "portfolio.sqlite3"

    result = main(
        [
            "inspect",
            "https://example.smugmug.com",
            "--api-key",
            "secret",
            "--database",
            str(database),
        ]
    )

    assert result == 0
    assert database.exists()
    assert "Galleries: 1" in capsys.readouterr().out


def test_show_and_baseline_report_read_saved_portfolio(tmp_path, capsys) -> None:
    database = tmp_path / "portfolio.sqlite3"
    asset = Asset(
        SourceReference("image", "https://example.test/image"),
        AssetMetadata(
            MediaType.PHOTOGRAPH,
            values={"OriginalWidth": 3, "OriginalHeight": 2, "Format": "JPG"},
        ),
    )
    portfolio = Portfolio(
        "test",
        SourceReference("example", "https://example.test"),
        "Example Portfolio",
        assets=(asset,),
        galleries=(
            Gallery(
                SourceReference("gallery", "https://example.test/gallery"),
                "Gallery",
                placements=(GalleryPlacement("image"),),
            ),
        ),
    )
    with SQLitePortfolioRepository(database) as repository:
        repository.save(portfolio)

    assert main(["show", str(database)]) == 0
    show_output = capsys.readouterr().out
    assert "Unique photographs: 1" in show_output

    assert main(["report", "baseline", str(database)]) == 0
    report_output = capsys.readouterr().out
    assert "Baseline report: Example Portfolio" in report_output
    assert "landscape: 1 (100.0%)" in report_output

    assert main(["report", "equipment", str(database)]) == 0
    equipment_output = capsys.readouterr().out
    assert "Equipment report: Example Portfolio" in equipment_output

    assert main(["report", "timeline", str(database)]) == 0
    timeline_output = capsys.readouterr().out
    assert "Timeline report: Example Portfolio" in timeline_output
    assert "Detailed Timeline Distributions" not in timeline_output

    assert (
        main(
            [
                "report",
                "timeline",
                str(database),
                "--details",
                "--camera-breakdown",
                "--gallery-breakdown",
            ]
        )
        == 0
    )
    detailed_timeline_output = capsys.readouterr().out
    assert "Detailed Timeline Distributions" in detailed_timeline_output
    assert "Camera Breakdown" in detailed_timeline_output
    assert "Gallery Breakdown" in detailed_timeline_output


def test_enrich_exif_updates_saved_asset(monkeypatch, tmp_path, capsys) -> None:
    database = tmp_path / "portfolio.sqlite3"
    asset = Asset(
        SourceReference("image-1", "https://example.smugmug.com/image"),
        AssetMetadata(MediaType.PHOTOGRAPH),
    )
    portfolio = Portfolio(
        "smugmug",
        SourceReference("example", "https://example.smugmug.com"),
        "Example Portfolio",
        assets=(asset,),
        galleries=(
            Gallery(
                SourceReference("gallery", "https://example.smugmug.com/gallery"),
                "Gallery",
                placements=(GalleryPlacement("image-1"),),
            ),
        ),
    )
    with SQLitePortfolioRepository(database) as repository:
        repository.save(portfolio)

    class FakeClient:
        def __init__(self, site_url, api_key) -> None:
            assert site_url == portfolio.source_url
            assert api_key == "secret"

        def get_response(self, uri):
            assert uri == "/api/v2/image/image-1!metadata"
            return {
                "ImageMetadata": {
                    "Uri": "/api/v2/image/image-1!metadata",
                    "Model": "Camera A",
                }
            }

    cli_module = import_module("ppa.cli.main")
    monkeypatch.setattr(cli_module, "SmugMugApiClient", FakeClient)

    assert (
        main(
            [
                "enrich",
                "exif",
                str(database),
                "--api-key",
                "secret",
            ]
        )
        == 0
    )
    assert "Overall status: 1 completed, 0 pending, 0 failed" in capsys.readouterr().out
    with SQLitePortfolioRepository(database) as repository:
        enriched = repository.get("smugmug", "example")
    assert enriched is not None
    assert enriched.assets[0].exif["Model"] == "Camera A"
