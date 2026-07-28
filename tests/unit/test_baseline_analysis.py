from datetime import UTC, datetime

from ppa.analysis import analyze_baseline
from ppa.models import Asset, Gallery, Portfolio
from ppa.reports import render_baseline


def test_baseline_distinguishes_references_and_unique_photographs() -> None:
    first = Asset(
        source_id="image-1",
        source_url="https://example.test/i/image-1",
        gallery_source_id="gallery-1",
        captured_at=datetime(2020, 1, 1, tzinfo=UTC),
        metadata={
            "ImageKey": "shared-image",
            "OriginalWidth": 6000,
            "OriginalHeight": 4000,
            "Format": "JPG",
            "Latitude": 45.0,
            "Longitude": -122.0,
            "Model": "Camera A",
            "Lens": "Lens A",
        },
    )
    placement = Asset(
        source_id="image-1",
        source_url="https://example.test/i/image-1",
        gallery_source_id="gallery-2",
        metadata={"ImageKey": "shared-image"},
    )
    portrait = Asset(
        source_id="image-2",
        source_url="https://example.test/i/image-2",
        gallery_source_id="gallery-2",
        metadata={
            "ImageKey": "image-2",
            "OriginalWidth": 3000,
            "OriginalHeight": 4000,
            "Format": "JPG",
        },
    )
    video = Asset(
        source_id="video-1",
        source_url="https://example.test/i/video-1",
        gallery_source_id="gallery-2",
        metadata={"ImageKey": "video-1", "Format": "MP4", "IsVideo": True},
    )
    portfolio = Portfolio(
        source="test",
        source_id="portfolio",
        title="Portfolio",
        source_url="https://example.test",
        galleries=(
            Gallery("gallery-1", "One", "https://example.test/one", assets=(first,)),
            Gallery(
                "gallery-2",
                "Two",
                "https://example.test/two",
                assets=(placement, portrait, video),
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
