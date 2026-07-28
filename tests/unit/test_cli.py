from collections.abc import Iterator
from importlib import import_module

from ppa.cli import main
from ppa.models import Asset, Gallery, Portfolio
from ppa.storage import SQLitePortfolioRepository


def test_init_db_command_creates_database(tmp_path) -> None:
    database = tmp_path / "portfolio.sqlite3"
    assert main(["init-db", str(database)]) == 0
    assert database.exists()


def test_inspect_prints_summary_and_saves_dataset(monkeypatch, tmp_path, capsys) -> None:
    portfolio = Portfolio(
        source="smugmug",
        source_id="example",
        title="Example Photographer",
        source_url="https://example.smugmug.com",
        galleries=(
            Gallery(
                source_id="gallery-1",
                title="People",
                source_url="https://example.smugmug.com/People",
                assets=(
                    Asset(
                        source_id="image-1",
                        source_url="https://example.smugmug.com/People/i-image-1",
                        gallery_source_id="gallery-1",
                    ),
                ),
            ),
        ),
    )

    class FakeSource:
        def __init__(self, url, api_key) -> None:
            assert url == "https://example.smugmug.com"
            assert api_key == "secret"

        def discover_portfolio(self) -> Portfolio:
            return Portfolio(
                source=portfolio.source,
                source_id=portfolio.source_id,
                title=portfolio.title,
                source_url=portfolio.source_url,
            )

        def iter_galleries(self, discovered: Portfolio) -> Iterator[Gallery]:
            assert discovered.source_id == portfolio.source_id
            yield from portfolio.galleries

        def iter_assets(self, gallery: Gallery) -> Iterator[Asset]:
            yield from gallery.assets

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
    portfolio = Portfolio(
        source="test",
        source_id="example",
        title="Example Portfolio",
        source_url="https://example.test",
        galleries=(
            Gallery(
                source_id="gallery",
                title="Gallery",
                source_url="https://example.test/gallery",
                assets=(
                    Asset(
                        source_id="image",
                        source_url="https://example.test/image",
                        gallery_source_id="gallery",
                        metadata={"OriginalWidth": 3, "OriginalHeight": 2, "Format": "JPG"},
                    ),
                ),
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


def test_enrich_exif_updates_saved_asset(monkeypatch, tmp_path, capsys) -> None:
    database = tmp_path / "portfolio.sqlite3"
    portfolio = Portfolio(
        source="smugmug",
        source_id="example",
        title="Example Portfolio",
        source_url="https://example.smugmug.com",
        galleries=(
            Gallery(
                source_id="gallery",
                title="Gallery",
                source_url="https://example.smugmug.com/gallery",
                assets=(
                    Asset(
                        source_id="image-1",
                        source_url="https://example.smugmug.com/image",
                        gallery_source_id="gallery",
                    ),
                ),
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
    assert enriched.galleries[0].assets[0].exif["Model"] == "Camera A"
