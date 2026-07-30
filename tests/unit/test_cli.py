from collections.abc import Iterator
from importlib import import_module

from ppa.analysis.visual import register_visual_analyzer
from ppa.cli import main
from ppa.core.visual_workflow import VisualWorkflowResult
from ppa.models import (
    Asset,
    AssetMetadata,
    Gallery,
    GalleryPlacement,
    MediaType,
    Portfolio,
    SourceReference,
)
from ppa.sources import PreviewRequest
from ppa.storage import SQLitePortfolioRepository
from ppa.visual import AnalyzerIdentity


def test_init_db_command_creates_database(tmp_path) -> None:
    database = tmp_path / "portfolio.sqlite3"
    assert main(["init-db", str(database)]) == 0
    assert database.exists()


def test_visual_command_reports_no_registered_production_analyzers(capsys) -> None:
    assert main(["analyze", "visual", "missing.sqlite3"]) == 1
    assert "No production visual analyzers are registered." in capsys.readouterr().out

    assert main(["analyze", "visual", "missing.sqlite3", "--list-analyzers"]) == 0
    assert "No production visual analyzers are registered." in capsys.readouterr().out


def test_visual_analyzer_listing_and_unknown_name_are_deterministic(monkeypatch, capsys) -> None:
    class Analyzer:
        identity = AnalyzerIdentity("zeta", "1", "defaults")
        preview_request = PreviewRequest(512)

        def analyze(self, asset, image, metadata):
            return ()

    visual_module = import_module("ppa.analysis.visual")
    monkeypatch.setattr(visual_module, "_ANALYZERS", {})
    register_visual_analyzer(Analyzer())

    assert main(["analyze", "visual", "missing.sqlite3", "--list-analyzers"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "Registered visual analyzers:",
        "  zeta",
    ]
    assert (
        main(
            [
                "analyze",
                "visual",
                "missing.sqlite3",
                "--analyzer",
                "unknown",
            ]
        )
        == 1
    )
    assert capsys.readouterr().out.splitlines() == [
        "Unknown visual analyzer: unknown",
        "Registered visual analyzers: zeta",
    ]


def test_visual_command_renders_aggregate_summary_without_asset_identifiers(
    monkeypatch, tmp_path, capsys
) -> None:
    class Analyzer:
        identity = AnalyzerIdentity("summary", "1", "defaults")
        preview_request = PreviewRequest(512)

        def analyze(self, asset, image, metadata):
            return ()

    visual_module = import_module("ppa.analysis.visual")
    monkeypatch.setattr(visual_module, "_ANALYZERS", {})
    register_visual_analyzer(Analyzer())
    database = tmp_path / "portfolio.sqlite3"
    portfolio = Portfolio(
        "smugmug",
        SourceReference("private-source-id", "https://example.smugmug.com"),
        "Portfolio",
        assets=(
            Asset(
                SourceReference(
                    "private-asset-id",
                    "https://example.smugmug.com/private-asset-id",
                ),
                AssetMetadata(MediaType.PHOTOGRAPH),
            ),
        ),
    )
    with SQLitePortfolioRepository(database) as repository:
        repository.save(portfolio)
    cli_module = import_module("ppa.cli.main")
    monkeypatch.setattr(
        cli_module,
        "run_visual_analysis",
        lambda *args, **kwargs: VisualWorkflowResult(
            eligible_photographs=3,
            selected_photographs=3,
            already_completed=1,
            existing_skipped=0,
            existing_failed=0,
            running_elsewhere=1,
            completed=1,
            skipped=0,
            failed=0,
            cancelled=0,
            remaining=1,
            elapsed_seconds=2,
            processing_rate=0.5,
            downloaded_bytes=100,
        ),
    )

    assert (
        main(
            [
                "analyze",
                "visual",
                str(database),
                "--analyzer",
                "summary",
                "--api-key",
                "secret",
            ]
        )
        == 1
    )
    output = capsys.readouterr().out
    assert "Running elsewhere or left running: 1" in output
    assert "Remaining: 1" in output
    assert "Recovery requires a separately scoped stale-run policy." in output
    assert "private-source-id" not in output
    assert "private-asset-id" not in output


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

    workflows_module = import_module("ppa.core.workflows")
    monkeypatch.setattr(workflows_module, "SmugMugSource", FakeSource)
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
            focal_length_mm=35,
            focal_length_35mm=52.5,
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

    assert main(["report", "focal-length", str(database)]) == 0
    focal_output = capsys.readouterr().out
    assert "Focal-length report: Example Portfolio" in focal_output
    assert "Selected primary basis: 35 mm equivalent" in focal_output

    assert (
        main(
            [
                "report",
                "focal-length",
                str(database),
                "--details",
                "--camera-breakdown",
                "--lens-breakdown",
                "--gallery-breakdown",
                "--year-breakdown",
            ]
        )
        == 0
    )
    detailed_focal_output = capsys.readouterr().out
    assert "Detailed Primary Distribution" in detailed_focal_output
    assert "Camera Breakdown" in detailed_focal_output
    assert "Lens Breakdown" in detailed_focal_output
    assert "Gallery Breakdown" in detailed_focal_output
    assert "Year Breakdown" in detailed_focal_output


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

    workflows_module = import_module("ppa.core.workflows")
    monkeypatch.setattr(workflows_module, "SmugMugApiClient", FakeClient)

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
