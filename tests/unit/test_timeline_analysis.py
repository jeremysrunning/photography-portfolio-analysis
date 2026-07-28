from datetime import UTC, datetime, timedelta, timezone

from ppa.analysis import analyze_timeline
from ppa.models import Asset, Gallery, Portfolio
from ppa.reports import render_timeline


def test_timeline_report_measures_boundaries_timezones_and_segments() -> None:
    utc_boundary = Asset(
        source_id="utc-boundary",
        source_url="https://example.test/utc-boundary",
        gallery_source_id="first",
        captured_at=datetime(2022, 12, 31, 23, 59, tzinfo=UTC),
        metadata={"ImageKey": "utc-boundary"},
        exif={"Make": "Example", "Model": "Camera A"},
    )
    offset_capture = Asset(
        source_id="offset",
        source_url="https://example.test/offset",
        gallery_source_id="first",
        captured_at=datetime(2023, 1, 1, 0, 0, tzinfo=timezone(timedelta(hours=14))),
        metadata={"ImageKey": "offset"},
        exif={"Make": "Example", "Model": "Camera A"},
    )
    naive_capture = Asset(
        source_id="naive",
        source_url="https://example.test/naive",
        gallery_source_id="second",
        captured_at=datetime(2023, 1, 31, 23, 59),
        metadata={"ImageKey": "naive"},
        exif={"Model": "Camera B"},
    )
    missing_capture = Asset(
        source_id="missing",
        source_url="https://example.test/missing",
        gallery_source_id="first",
        metadata={"ImageKey": "missing"},
    )
    duplicate_boundary = Asset(
        source_id="utc-boundary-copy",
        source_url="https://example.test/utc-boundary",
        gallery_source_id="second",
        captured_at=utc_boundary.captured_at,
        metadata={"ImageKey": "utc-boundary"},
        exif=utc_boundary.exif,
    )
    portfolio = Portfolio(
        source="test",
        source_id="portfolio",
        title="Timeline Evidence",
        source_url="https://example.test",
        galleries=(
            Gallery(
                source_id="first",
                title="First Gallery",
                source_url="https://example.test/first",
                assets=(utc_boundary, offset_capture, missing_capture),
            ),
            Gallery(
                source_id="second",
                title="Second Gallery",
                source_url="https://example.test/second",
                assets=(duplicate_boundary, naive_capture),
            ),
        ),
    )

    report = analyze_timeline(portfolio)
    rendered = render_timeline(report)

    assert report.photograph_count == 4
    assert report.capture_coverage.available == 3
    assert report.capture_coverage.total == 4
    assert report.years == {2022: 1, 2023: 2}
    assert report.months == {"2022-12": 1, "2023-01": 2}
    assert report.hours_by_time_basis == {
        "UTC": {23: 1},
        "UTC+14:00": {0: 1},
        "timezone unknown": {23: 1},
    }
    assert report.camera_coverage.available == 3
    assert report.camera_segments[0].label == "Camera B"
    assert report.camera_segments[1].label == "Example Camera A"
    assert report.camera_segments[1].years == {2022: 1, 2023: 1}
    assert report.camera_segments[1].months == {"2022-12": 1, "2023-01": 1}
    assert report.gallery_segments[0].capture_coverage.available == 2
    assert report.gallery_segments[0].capture_coverage.total == 3
    assert report.gallery_segments[1].years == {2022: 1, 2023: 1}
    assert report.gallery_segments[1].hours_by_time_basis == {
        "UTC": {23: 1},
        "timezone unknown": {23: 1},
    }
    assert "Capture hours (UTC)" in rendered
    assert "Capture hours (UTC+14:00)" in rendered
    assert "Capture hours (timezone unknown)" in rendered
    assert "Months: 2022-12: 1, 2023-01: 1" in rendered
    assert "Hours (UTC+14:00): 00:00: 1" in rendered
    assert "UTC timestamps remain UTC; no local timezone is inferred." in rendered
    assert "productivity or intent" in rendered


def test_timeline_report_handles_missing_timestamps() -> None:
    portfolio = Portfolio(
        source="test",
        source_id="missing",
        title="Missing Timeline",
        source_url="https://example.test",
        galleries=(
            Gallery(
                source_id="gallery",
                title="Gallery",
                source_url="https://example.test/gallery",
                assets=(
                    Asset(
                        source_id="asset",
                        source_url="https://example.test/asset",
                        gallery_source_id="gallery",
                    ),
                ),
            ),
        ),
    )

    report = analyze_timeline(portfolio)
    rendered = render_timeline(report)

    assert report.capture_coverage.available == 0
    assert report.capture_coverage.total == 1
    assert report.years == {}
    assert report.months == {}
    assert report.hours_by_time_basis == {}
    assert "Capture timestamp: 0 / 1 (0.0%)" in rendered
    assert "Missing timestamps are reported as missing" in rendered
