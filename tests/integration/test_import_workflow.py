import sqlite3
from collections.abc import Iterator
from importlib import import_module

import pytest

from ppa.cli import main
from ppa.core.workflows import PersistenceError, persist_portfolio
from ppa.models import (
    Asset,
    AssetMetadata,
    Gallery,
    GalleryPlacement,
    MediaType,
    Portfolio,
    SourceReference,
)
from ppa.sources import SourceRateLimitError
from ppa.storage import SQLitePortfolioRepository


def _asset(source_id: str, media_type: MediaType = MediaType.PHOTOGRAPH) -> Asset:
    return Asset(
        SourceReference(source_id, f"https://example.smugmug.com/i-{source_id}"),
        AssetMetadata(media_type),
    )


def _portfolio(*assets: Asset, title: str = "Example Portfolio") -> Portfolio:
    return Portfolio(
        "smugmug",
        SourceReference("example", "https://example.smugmug.com"),
        title,
        assets=assets,
        galleries=(
            Gallery(
                SourceReference("gallery", "https://example.smugmug.com/gallery"),
                "Gallery",
                placements=tuple(GalleryPlacement(asset.source_id) for asset in assets),
            ),
        ),
    )


def _install_source(monkeypatch, portfolio: Portfolio) -> None:
    class FakeSource:
        def __init__(self, url: str, api_key: str) -> None:
            assert url == portfolio.source_url
            assert api_key == "secret"

        def discover_portfolio(self) -> Portfolio:
            return Portfolio(portfolio.source_name, portfolio.source, portfolio.title)

        def iter_galleries(self, discovered: Portfolio) -> Iterator[Gallery]:
            yield from portfolio.galleries

        def iter_assets(self, gallery: Gallery) -> Iterator[Asset]:
            yield from portfolio.gallery_assets(gallery)

    workflows = import_module("ppa.core.workflows")
    monkeypatch.setattr(workflows, "SmugMugSource", FakeSource)


def test_import_runs_all_stages_and_rerun_skips_completed_assets(
    monkeypatch, tmp_path, capsys
) -> None:
    portfolio = _portfolio(_asset("photo"), _asset("video", MediaType.NON_PHOTO))
    _install_source(monkeypatch, portfolio)

    class FakeClient:
        calls = 0

        def __init__(self, site_url: str, api_key: str) -> None:
            assert api_key == "secret"

        def get_response(self, uri: str):
            FakeClient.calls += 1
            return {
                "ImageMetadata": {
                    "Uri": "/api/v2/image/photo!metadata",
                    "Model": "Camera",
                }
            }

    workflows = import_module("ppa.core.workflows")
    monkeypatch.setattr(workflows, "SmugMugApiClient", FakeClient)
    database = tmp_path / "portfolio.sqlite3"
    command = [
        "import",
        portfolio.source_url,
        "--database",
        str(database),
        "--api-key",
        "secret",
    ]

    assert main(command) == 0
    output = capsys.readouterr().out
    assert output.index("Stage 1/3") < output.index("Stage 2/3") < output.index("Stage 3/3")
    assert "Photographs newly enriched during this run: 1" in output
    assert "Non-photo assets marked complete because EXIF is not applicable: 1" in output
    assert FakeClient.calls == 1

    assert main(command) == 0
    rerun_output = capsys.readouterr().out
    assert "Photographs newly enriched during this run: 0" in rerun_output
    assert "Photographs already enriched before this run: 1" in rerun_output
    assert FakeClient.calls == 1


def test_partial_import_preserves_success_and_gives_retry_guidance(
    monkeypatch, tmp_path, capsys
) -> None:
    portfolio = _portfolio(_asset("photo-1"), _asset("photo-2"))
    _install_source(monkeypatch, portfolio)

    class PartialClient:
        def __init__(self, site_url: str, api_key: str) -> None:
            pass

        def get_response(self, uri: str):
            return {
                "ImageMetadata": {
                    "Uri": "/api/v2/image/photo-1!metadata",
                    "Model": "Camera",
                }
            }

    workflows = import_module("ppa.core.workflows")
    monkeypatch.setattr(workflows, "SmugMugApiClient", PartialClient)
    database = tmp_path / "portfolio.sqlite3"

    assert (
        main(
            [
                "import",
                portfolio.source_url,
                "--database",
                str(database),
                "--api-key",
                "secret",
            ]
        )
        == 1
    )
    output = capsys.readouterr().out
    assert "Failed assets: 1" in output
    assert "database remains usable" in output
    assert "successful enrichment was preserved" in output
    assert "--retry-failed" in output
    with SQLitePortfolioRepository(database) as repository:
        stored = repository.get("smugmug", "example")
    assert stored is not None
    assert stored.asset("photo-1").exif["Model"] == "Camera"


def test_retry_failed_import_processes_prior_failure(monkeypatch, tmp_path, capsys) -> None:
    portfolio = _portfolio(_asset("photo"))
    _install_source(monkeypatch, portfolio)
    database = tmp_path / "portfolio.sqlite3"
    persist_portfolio(portfolio, database)
    with SQLitePortfolioRepository(database) as repository:
        repository.fail_asset_enrichment(
            "smugmug",
            "example",
            "photo",
            "exif",
            "temporary failure",
        )

    class SuccessfulClient:
        def __init__(self, site_url: str, api_key: str) -> None:
            pass

        def get_response(self, uri: str):
            return {
                "ImageMetadata": {
                    "Uri": "/api/v2/image/photo!metadata",
                    "Model": "Recovered Camera",
                }
            }

    workflows = import_module("ppa.core.workflows")
    monkeypatch.setattr(workflows, "SmugMugApiClient", SuccessfulClient)

    assert (
        main(
            [
                "import",
                portfolio.source_url,
                "--database",
                str(database),
                "--api-key",
                "secret",
                "--retry-failed",
            ]
        )
        == 0
    )
    assert "Photographs newly enriched during this run: 1" in capsys.readouterr().out


def test_inspection_failure_stops_before_persistence_and_enrichment(
    monkeypatch, tmp_path, capsys
) -> None:
    cli_module = import_module("ppa.cli.main")

    def fail_inspection(url: str, api_key: str):
        raise ValueError("portfolio unavailable")

    monkeypatch.setattr(cli_module, "inspect_public_portfolio", fail_inspection)
    database = tmp_path / "portfolio.sqlite3"

    assert (
        main(
            [
                "import",
                "https://example.smugmug.com",
                "--database",
                str(database),
                "--api-key",
                "secret",
            ]
        )
        == 1
    )
    output = capsys.readouterr().out
    assert "Inspection failed: portfolio unavailable" in output
    assert "Stage 2/3" not in output
    assert not database.exists()


def test_persistence_failure_is_identified_and_stops_enrichment(
    monkeypatch, tmp_path, capsys
) -> None:
    portfolio = _portfolio(_asset("photo"))
    _install_source(monkeypatch, portfolio)
    cli_module = import_module("ppa.cli.main")

    def fail_persistence(portfolio: Portfolio, database) -> None:
        raise PersistenceError("disk unavailable")

    monkeypatch.setattr(cli_module, "persist_portfolio", fail_persistence)

    assert (
        main(
            [
                "import",
                portfolio.source_url,
                "--database",
                str(tmp_path / "portfolio.sqlite3"),
                "--api-key",
                "secret",
            ]
        )
        == 1
    )
    output = capsys.readouterr().out
    assert "Stage 2/3: Persisting normalized metadata" in output
    assert "Persistence failed: disk unavailable" in output
    assert "EXIF enrichment was not started." in output
    assert "Stage 3/3" not in output


def test_rate_limited_import_preserves_completed_batches(monkeypatch, tmp_path, capsys) -> None:
    portfolio = _portfolio(*(_asset(f"photo-{index:02}") for index in range(26)))
    _install_source(monkeypatch, portfolio)

    class RateLimitedClient:
        calls = 0

        def __init__(self, site_url: str, api_key: str) -> None:
            pass

        def get_response(self, uri: str):
            RateLimitedClient.calls += 1
            if RateLimitedClient.calls == 2:
                raise SourceRateLimitError(30)
            identifiers = uri.split("/image/", 1)[1].split("!", 1)[0].split(",")
            return {
                "ImageMetadata": [
                    {
                        "Uri": f"/api/v2/image/{source_id}!metadata",
                        "Model": "Camera",
                    }
                    for source_id in identifiers
                ]
            }

    workflows = import_module("ppa.core.workflows")
    monkeypatch.setattr(workflows, "SmugMugApiClient", RateLimitedClient)
    database = tmp_path / "portfolio.sqlite3"

    assert (
        main(
            [
                "import",
                portfolio.source_url,
                "--database",
                str(database),
                "--api-key",
                "secret",
            ]
        )
        == 2
    )
    output = capsys.readouterr().out
    assert "Photographs newly enriched during this run: 25" in output
    assert "Pending or remaining assets: 1" in output
    assert "database remains usable" in output
    assert "resumed safely" in output


def test_persistence_failure_rolls_back_file_backed_database(tmp_path) -> None:
    database = tmp_path / "portfolio.sqlite3"
    original = _portfolio(_asset("photo"), title="Original")
    persist_portfolio(original, database)
    connection = sqlite3.connect(database)
    connection.execute(
        """
        CREATE TRIGGER reject_portfolio_update
        BEFORE UPDATE ON portfolios
        BEGIN SELECT RAISE(ABORT, 'forced persistence failure'); END
        """
    )
    connection.commit()
    connection.close()

    with pytest.raises(PersistenceError, match="forced persistence failure"):
        persist_portfolio(_portfolio(_asset("photo"), title="Changed"), database)

    with SQLitePortfolioRepository(database) as repository:
        stored = repository.get("smugmug", "example")
    assert stored is not None
    assert stored.title == "Original"
