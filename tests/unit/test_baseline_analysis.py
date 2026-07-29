from datetime import UTC, datetime

import pytest

from ppa.analysis import analyze_baseline
from ppa.models import (
    Asset,
    AssetMetadata,
    Gallery,
    GalleryPlacement,
    MediaType,
    Portfolio,
    SourceReference,
)
from ppa.reports import render_baseline


def _reference(source_id: str) -> SourceReference:
    return SourceReference(source_id, f"https://example.test/{source_id}")


def test_baseline_distinguishes_references_and_unique_photographs() -> None:
    first = Asset(
        _reference("image-1"),
        AssetMetadata(
            MediaType.PHOTOGRAPH,
            datetime(2020, 1, 1, tzinfo=UTC),
            {
                "ImageKey": "shared-image",
                "OriginalWidth": 6000,
                "OriginalHeight": 4000,
                "Format": "JPG",
                "Latitude": 45.0,
                "Longitude": -122.0,
                "Model": "Camera A",
                "Lens": "Lens A",
            },
        ),
    )
    portrait = Asset(
        _reference("image-2"),
        AssetMetadata(
            MediaType.PHOTOGRAPH,
            values={
                "ImageKey": "image-2",
                "OriginalWidth": 3000,
                "OriginalHeight": 4000,
                "Format": "JPG",
            },
        ),
    )
    video = Asset(
        _reference("video-1"),
        AssetMetadata(
            MediaType.NON_PHOTO,
            values={"ImageKey": "video-1", "Format": "MP4", "IsVideo": True},
        ),
    )
    portfolio = Portfolio(
        "test",
        _reference("portfolio"),
        "Portfolio",
        assets=(first, portrait, video),
        galleries=(
            Gallery(
                _reference("gallery-1"),
                "One",
                placements=(GalleryPlacement("image-1"),),
            ),
            Gallery(
                _reference("gallery-2"),
                "Two",
                placements=tuple(
                    GalleryPlacement(item) for item in ("image-1", "image-2", "video-1")
                ),
            ),
        ),
    )

    report = analyze_baseline(portfolio)

    assert report.media_references == 4
    assert report.unique_media == 3
    assert report.unique_photographs == 2
    assert report.excluded_non_photographs == 1
    assert report.duplicate_references == 1
    assert report.gallery_size_median == 2.0
    assert report.orientations == {"landscape": 1, "portrait": 1}
    assert report.capture_date_coverage.available == 1
    assert report.geolocation_coverage.available == 1
    assert "Missing metadata is reported as missing" in render_baseline(report)


@pytest.mark.parametrize(
    ("gallery_assets", "expected"),
    [
        ((), 0),
        (("placed",), 0),
        (("placed", "placed"), 1),
        (("placed", "second", "placed"), 1),
    ],
)
def test_additional_placements_ignore_unplaced_assets(
    gallery_assets: tuple[str, ...],
    expected: int,
) -> None:
    assets = tuple(
        Asset(
            _reference(source_id),
            AssetMetadata(MediaType.PHOTOGRAPH),
        )
        for source_id in ("placed", "second", "unplaced")
    )
    galleries = tuple(
        Gallery(
            _reference(f"gallery-{index}"),
            f"Gallery {index}",
            placements=(GalleryPlacement(source_id),),
        )
        for index, source_id in enumerate(gallery_assets)
    )
    portfolio = Portfolio(
        "test",
        _reference("portfolio"),
        "Portfolio",
        assets=assets,
        galleries=galleries,
    )

    assert analyze_baseline(portfolio).duplicate_references == expected
