from datetime import UTC, datetime

from ppa.models import Asset, Finding, Gallery, Measurement, Observation, Portfolio
from ppa.storage.sqlite import SQLitePortfolioRepository


def test_portfolio_round_trip(tmp_path) -> None:
    portfolio = Portfolio(
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
                assets=(
                    Asset(
                        source_id="asset-1",
                        source_url="https://example.test/people/1",
                        preview_url="https://example.test/preview/1.jpg",
                        gallery_source_id="gallery-1",
                        captured_at=datetime(2024, 1, 2, 3, 4, tzinfo=UTC),
                        metadata={"orientation": "landscape"},
                        exif={"camera": "Example"},
                        measurements=(Measurement("aspect_ratio", 1.5, method="metadata"),),
                    ),
                ),
            ),
        ),
        observations=(Observation("Landscape orientation recurs.", ("asset-1",)),),
        findings=(Finding("Landscape orientation is common.", 0.8, ("aspect_ratio",)),),
    )
    database = tmp_path / "portfolio.sqlite3"

    with SQLitePortfolioRepository(database) as repository:
        repository.save(portfolio)
        assert repository.get("test", "portfolio-1") == portfolio
        assert repository.get("test", "missing") is None
