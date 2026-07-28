from ppa.models import Asset, Gallery, Portfolio
from ppa.sources import SourceRateLimitError
from ppa.sources.smugmug import SmugMugExifEnricher
from ppa.storage import SQLitePortfolioRepository


class FakeClient:
    def __init__(self) -> None:
        self.uris = []

    def get_response(self, uri):
        self.uris.append(uri)
        return {
            "ImageMetadata": [
                {
                    "Uri": "/api/v2/image/photo-1!metadata",
                    "Make": "Example",
                    "Model": "Camera A",
                    "Lens": "Lens A",
                    "ISO": 400,
                    "FocalLength": "35 mm",
                },
                {
                    "Uri": "/api/v2/image/photo-2!metadata",
                    "Make": "Example",
                    "Model": "Camera B",
                },
            ]
        }


def test_exif_enrichment_is_incremental_and_skips_stored_video(tmp_path) -> None:
    database = tmp_path / "portfolio.sqlite3"
    portfolio = Portfolio(
        source="smugmug",
        source_id="example",
        title="Example",
        source_url="https://example.smugmug.com",
        galleries=(
            Gallery(
                source_id="gallery",
                title="Gallery",
                source_url="https://example.smugmug.com/gallery",
                assets=(
                    Asset(
                        source_id="photo-1",
                        source_url="https://example.smugmug.com/i-photo-1",
                        gallery_source_id="gallery",
                        metadata={"ImageKey": "photo"},
                    ),
                    Asset(
                        source_id="video-1",
                        source_url="https://example.smugmug.com/i-video-1",
                        gallery_source_id="gallery",
                        metadata={"ImageKey": "video", "IsVideo": True, "Format": "MP4"},
                    ),
                    Asset(
                        source_id="photo-2",
                        source_url="https://example.smugmug.com/i-photo-2",
                        gallery_source_id="gallery",
                        metadata={"ImageKey": "photo-two"},
                    ),
                ),
            ),
        ),
    )
    client = FakeClient()

    with SQLitePortfolioRepository(database) as repository:
        repository.save(portfolio)
        targets = repository.list_enrichment_targets("smugmug", "example", "exif")
        result = SmugMugExifEnricher(client, repository).enrich(
            "smugmug",
            "example",
            targets,
        )

        assert result.completed == 3
        assert result.skipped_non_photos == 1
        assert client.uris == ["/api/v2/image/photo-1,photo-2!metadata"]
        assert repository.list_enrichment_targets("smugmug", "example", "exif") == ()
        assert repository.enrichment_status("smugmug", "example", "exif").completed == 3
        enriched = repository.get("smugmug", "example")

    assert enriched is not None
    assert enriched.galleries[0].assets[0].exif["Model"] == "Camera A"
    assert enriched.galleries[0].assets[1].exif == {}
    assert enriched.galleries[0].assets[2].exif["Model"] == "Camera B"


def test_failed_enrichment_is_only_selected_when_retrying(tmp_path) -> None:
    database = tmp_path / "portfolio.sqlite3"
    portfolio = Portfolio(
        source="smugmug",
        source_id="example",
        title="Example",
        source_url="https://example.smugmug.com",
        galleries=(
            Gallery(
                source_id="gallery",
                title="Gallery",
                source_url="https://example.smugmug.com/gallery",
                assets=(
                    Asset(
                        source_id="photo-1",
                        source_url="https://example.smugmug.com/i-photo-1",
                        gallery_source_id="gallery",
                    ),
                ),
            ),
        ),
    )

    with SQLitePortfolioRepository(database) as repository:
        repository.save(portfolio)
        repository.fail_asset_enrichment(
            "smugmug",
            "example",
            "photo-1",
            "exif",
            "temporary failure",
        )

        assert repository.list_enrichment_targets("smugmug", "example", "exif") == ()
        retry = repository.list_enrichment_targets(
            "smugmug",
            "example",
            "exif",
            retry_failed=True,
        )

    assert [target.source_id for target in retry] == ["photo-1"]


def test_rate_limit_leaves_targets_pending(tmp_path) -> None:
    class RateLimitedClient:
        def get_response(self, uri):
            raise SourceRateLimitError(30)

    database = tmp_path / "portfolio.sqlite3"
    portfolio = Portfolio(
        source="smugmug",
        source_id="example",
        title="Example",
        source_url="https://example.smugmug.com",
        galleries=(
            Gallery(
                source_id="gallery",
                title="Gallery",
                source_url="https://example.smugmug.com/gallery",
                assets=(
                    Asset(
                        source_id="photo-1",
                        source_url="https://example.smugmug.com/i-photo-1",
                        gallery_source_id="gallery",
                    ),
                ),
            ),
        ),
    )

    with SQLitePortfolioRepository(database) as repository:
        repository.save(portfolio)
        targets = repository.list_enrichment_targets("smugmug", "example", "exif")
        enricher = SmugMugExifEnricher(RateLimitedClient(), repository)

        try:
            enricher.enrich("smugmug", "example", targets)
        except SourceRateLimitError:
            pass
        else:
            raise AssertionError("Expected SourceRateLimitError")

        status = repository.enrichment_status("smugmug", "example", "exif")

    assert status.pending == 1
    assert status.failed == 0
