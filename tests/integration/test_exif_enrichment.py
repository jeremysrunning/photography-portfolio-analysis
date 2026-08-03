import sqlite3

import pytest

from ppa.models import (
    Asset,
    AssetMetadata,
    Gallery,
    GalleryPlacement,
    MediaType,
    Portfolio,
    RationalValue,
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
                    "FocalLength35mm": "52.5 mm",
                    "Aperture": "2.8",
                    "Exposure": "1/250",
                    "ExposureCompensation": "+2/3",
                    "Flash": "Off, Did not fire",
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
    assert enriched.assets[0].metadata.focal_length_mm == 35.0
    assert enriched.assets[0].metadata.focal_length_35mm == 52.5
    assert enriched.assets[0].metadata.aperture_f_number == 2.8
    assert enriched.assets[0].metadata.exposure_time == RationalValue(1, 250)
    assert enriched.assets[0].metadata.iso == 400
    assert enriched.assets[0].metadata.exposure_compensation_ev == RationalValue(2, 3)
    assert enriched.assets[0].metadata.flash_fired is False
    assert enriched.assets[1].metadata.focal_length_mm is None
    assert enriched.assets[1].metadata.focal_length_35mm is None
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


def test_partial_retry_merges_raw_exif_and_preserves_unrelated_typed_fields(tmp_path) -> None:
    class PartialClient:
        def get_response(self, uri):
            return {
                "ImageMetadata": {
                    "Uri": "/api/v2/image/photo-1!metadata",
                    "Model": "Updated Camera",
                    "Exposure": "malformed",
                }
            }

    database = tmp_path / "portfolio.sqlite3"
    asset = Asset(
        SourceReference("photo-1", "https://example.smugmug.com/i-photo-1"),
        AssetMetadata(
            MediaType.PHOTOGRAPH,
            exif={
                "Aperture": "2.8",
                "Exposure": "1/250",
                "ISO": 400,
                "ExposureCompensation": "-1/3",
                "Flash": "On, Fired",
            },
            aperture_f_number=2.8,
            exposure_time=RationalValue(1, 250),
            iso=400,
            exposure_compensation_ev=RationalValue(-1, 3),
            flash_fired=True,
        ),
    )
    with SQLitePortfolioRepository(database) as repository:
        repository.save(_portfolio(asset))
        repository.fail_asset_enrichment("smugmug", "example", "photo-1", "exif", "temporary")
        targets = repository.list_enrichment_targets(
            "smugmug", "example", "exif", retry_failed=True
        )
        SmugMugExifEnricher(PartialClient(), repository).enrich("smugmug", "example", targets)
        stored = repository.get("smugmug", "example")

    assert stored is not None
    metadata = stored.asset("photo-1").metadata
    assert stored.asset("photo-1").exif["Exposure"] == "malformed"
    assert stored.asset("photo-1").exif["Model"] == "Updated Camera"
    assert metadata.exposure_time is None
    assert metadata.aperture_f_number == 2.8
    assert metadata.iso == 400
    assert metadata.exposure_compensation_ev == RationalValue(-1, 3)
    assert metadata.flash_fired is True


def test_exposure_enrichment_and_completion_roll_back_atomically(tmp_path) -> None:
    database = tmp_path / "portfolio.sqlite3"
    portfolio = _portfolio(_asset("photo-1"))

    with SQLitePortfolioRepository(database) as repository:
        repository.save(portfolio)
        connection = repository._connect()
        connection.execute(
            """
            CREATE TRIGGER reject_exposure_update
            BEFORE UPDATE OF aperture_f_number ON assets
            BEGIN SELECT RAISE(ABORT, 'forced exposure rollback'); END
            """
        )
        with pytest.raises(sqlite3.IntegrityError, match="forced exposure rollback"):
            repository.save_asset_enrichment(
                "smugmug",
                "example",
                "photo-1",
                "exif",
                {"Aperture": "2.8"},
                aperture_f_number=2.8,
            )
        stored = repository.get("smugmug", "example")
        status = repository.enrichment_status("smugmug", "example", "exif")

    assert stored is not None
    assert stored.asset("photo-1").exif == {}
    assert stored.asset("photo-1").metadata.aperture_f_number is None
    assert status.pending == 1
    assert status.completed == 0
