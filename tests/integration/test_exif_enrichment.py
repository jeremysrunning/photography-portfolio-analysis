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


def _portfolio(*assets: Asset) -> Portfolio:
    return Portfolio(
        "smugmug",
        SourceReference("example", "https://example.smugmug.com"),
        "Example",
        assets=assets,
        galleries=(
            Gallery(
                SourceReference("gallery", "https://example.smugmug.com/gallery"),
                "Gallery",
                placements=tuple(GalleryPlacement(asset.source_id) for asset in assets),
            ),
        ),
    )


def _asset(source_id: str, media_type: MediaType = MediaType.PHOTOGRAPH) -> Asset:
    return Asset(
        SourceReference(source_id, f"https://example.smugmug.com/i-{source_id}"),
        AssetMetadata(media_type, values={"ImageKey": source_id}),
    )


def test_exif_enrichment_is_incremental_and_skips_stored_video(tmp_path) -> None:
    database = tmp_path / "portfolio.sqlite3"
    portfolio = _portfolio(
        _asset("photo-1"),
        _asset("video-1", MediaType.NON_PHOTO),
        _asset("photo-2"),
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
    assert enriched.assets[0].exif["Model"] == "Camera A"
    assert enriched.assets[1].exif["Model"] == "Camera B"
    assert enriched.assets[2].exif == {}


def test_failed_enrichment_is_only_selected_when_retrying(tmp_path) -> None:
    database = tmp_path / "portfolio.sqlite3"
    portfolio = _portfolio(_asset("photo-1"))

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
    portfolio = _portfolio(_asset("photo-1"))

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
