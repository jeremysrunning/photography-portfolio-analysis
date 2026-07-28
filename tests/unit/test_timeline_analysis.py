from datetime import UTC, datetime, timedelta, timezone

from ppa.analysis import analyze_timeline
from ppa.models import Asset, Gallery, Portfolio
from ppa.reports import render_timeline


def _asset(
    source_id: str,
    captured_at: datetime | None,
    *,
    gallery_id: str = "gallery",
    camera: str | None = None,
) -> Asset:
    exif = {"Model": camera} if camera else {}
    return Asset(
        source_id=source_id,
        source_url=f"https://example.test/{source_id}",
        gallery_source_id=gallery_id,
        captured_at=captured_at,
        metadata={"ImageKey": source_id},
        exif=exif,
    )


def _portfolio(assets: tuple[Asset, ...], title: str = "Timeline Evidence") -> Portfolio:
    return Portfolio(
        source="test",
        source_id="portfolio",
        title=title,
        source_url="https://example.test",
        galleries=(
            Gallery(
                source_id="gallery",
                title="Gallery",
                source_url="https://example.test/gallery",
                assets=assets,
            ),
        ),
    )


def test_default_report_is_concise_neutral_and_measurement_driven() -> None:
    assets = (
        _asset("2020-a", datetime(2020, 1, 1, 5, tzinfo=UTC), camera="Camera A"),
        _asset("2020-b", datetime(2020, 1, 2, 5, tzinfo=UTC), camera="Camera A"),
        _asset("2021-a", datetime(2021, 2, 1, 5, tzinfo=UTC), camera="Camera A"),
        _asset("2021-b", datetime(2021, 2, 2, 6, tzinfo=UTC), camera="Camera A"),
        _asset("2021-c", datetime(2021, 2, 3, 6, tzinfo=UTC), camera="Camera A"),
        _asset("2021-d", datetime(2021, 2, 4, 6, tzinfo=UTC), camera="Camera A"),
        _asset("2022-a", datetime(2022, 3, 1, 6, tzinfo=UTC), camera="Camera B"),
        _asset("2023-a", datetime(2023, 4, 1, 6, tzinfo=UTC), camera="Camera B"),
        _asset("2023-b", datetime(2023, 4, 2, 6, tzinfo=UTC), camera="Camera B"),
        _asset("2023-c", datetime(2023, 4, 3, 6, tzinfo=UTC), camera="Camera B"),
        _asset("missing", None),
    )

    report = analyze_timeline(_portfolio(assets))
    rendered = render_timeline(report)

    assert report.peak_year is not None
    assert (report.peak_year.period, report.peak_year.count) == ("2021", 4)
    assert report.peak_month is not None
    assert (report.peak_month.period, report.peak_month.count) == ("2021-02", 4)
    assert report.least_active_complete_year is not None
    assert (report.least_active_complete_year.period, report.least_active_complete_year.count) == (
        "2022",
        1,
    )
    assert report.largest_yearly_increase is not None
    assert (
        report.largest_yearly_increase.from_year,
        report.largest_yearly_increase.to_year,
        report.largest_yearly_increase.change,
    ) == (2020, 2021, 2)
    assert report.largest_yearly_decrease is not None
    assert (
        report.largest_yearly_decrease.from_year,
        report.largest_yearly_decrease.to_year,
        report.largest_yearly_decrease.change,
    ) == (2021, 2022, -3)
    assert report.most_common_utc_hour is not None
    assert (report.most_common_utc_hour.period, report.most_common_utc_hour.count) == ("6", 7)
    assert [era.camera for era in report.camera_eras] == ["Camera A", "Camera B"]
    assert (report.camera_eras[0].first_year, report.camera_eras[0].last_year) == (2020, 2021)

    headings = [
        "Evidence",
        "Timeline Summary",
        "Key Measurements",
        "Camera Eras",
        "Top Galleries",
        "Notes",
    ]
    assert [rendered.index(heading) for heading in headings] == sorted(
        rendered.index(heading) for heading in headings
    )
    assert "Detailed Timeline Distributions" not in rendered
    assert "Camera Breakdown" not in rendered
    assert "Gallery Breakdown" not in rendered
    assert "Most active capture year: 2021: 4" in rendered
    assert "Largest recorded year-over-year decrease: 2021 to 2022: -3" in rendered
    assert "Camera dates describe recorded use in this portfolio, not ownership." in rendered
    lowered = rendered.casefold()
    for unsupported in ("career peak", "strong recovery", "pandemic", "photography slowed down"):
        assert unsupported not in lowered


def test_top_galleries_are_limited_and_deterministically_ordered() -> None:
    galleries = tuple(
        Gallery(
            source_id=f"g{index:02d}",
            title=f"Gallery {index:02d}",
            source_url=f"https://example.test/g{index:02d}",
            assets=tuple(
                _asset(
                    f"g{index:02d}-{asset_index:02d}",
                    datetime(2024, 1, index, tzinfo=UTC),
                    gallery_id=f"g{index:02d}",
                    camera="Camera",
                )
                for asset_index in range(index)
            ),
        )
        for index in range(1, 13)
    )
    portfolio = Portfolio(
        "test",
        "portfolio",
        "Gallery Ranking",
        "https://example.test",
        galleries=galleries,
    )

    report = analyze_timeline(portfolio)
    rendered = render_timeline(report)

    assert [segment.key for segment in report.top_galleries] == [
        "g12",
        "g11",
        "g10",
        "g09",
        "g08",
        "g07",
        "g06",
        "g05",
        "g04",
        "g03",
    ]
    assert report.omitted_gallery_count == 2
    assert "[g01]" not in rendered
    assert "[g02]" not in rendered
    assert "Additional galleries omitted: 2" in rendered


def test_ties_use_earliest_period_and_stable_names() -> None:
    assets = (
        _asset("a-2020", datetime(2020, 1, 1, 4, tzinfo=UTC), camera="Zulu"),
        _asset("b-2021", datetime(2021, 1, 1, 5, tzinfo=UTC), camera="Alpha"),
    )

    report = analyze_timeline(_portfolio(assets))

    assert report.peak_year is not None
    assert report.peak_year.period == "2020"
    assert report.peak_month is not None
    assert report.peak_month.period == "2020-01"
    assert report.most_common_utc_hour is not None
    assert report.most_common_utc_hour.period == "4"
    assert [era.camera for era in report.camera_eras] == ["Alpha", "Zulu"]

    tied_galleries = (
        Gallery(
            "zulu",
            "Zulu",
            "https://example.test/zulu",
            assets=(_asset("zulu", assets[0].captured_at, gallery_id="zulu"),),
        ),
        Gallery(
            "alpha",
            "Alpha",
            "https://example.test/alpha",
            assets=(_asset("alpha", assets[1].captured_at, gallery_id="alpha"),),
        ),
    )
    gallery_report = analyze_timeline(
        Portfolio("test", "ties", "Ties", "https://example.test", galleries=tied_galleries)
    )
    assert [segment.key for segment in gallery_report.top_galleries] == ["alpha", "zulu"]


def test_boundary_dates_and_timezone_bases_remain_separate() -> None:
    portfolio = _portfolio(
        (
            _asset("utc", datetime(2022, 12, 31, 23, 59, tzinfo=UTC), camera="Camera"),
            _asset(
                "offset",
                datetime(2023, 1, 1, 0, 0, tzinfo=timezone(timedelta(hours=14))),
                camera="Camera",
            ),
            _asset("naive", datetime(2023, 1, 31, 23, 59), camera="Camera"),
        )
    )

    report = analyze_timeline(portfolio)

    assert report.years == {2022: 1, 2023: 2}
    assert report.months == {"2022-12": 1, "2023-01": 2}
    assert report.hours_by_time_basis == {
        "UTC": {23: 1},
        "UTC+14:00": {0: 1},
        "timezone unknown": {23: 1},
    }
    assert report.longest_capture_gap is None


def test_optional_detail_modes_are_independent_and_do_not_duplicate_sections() -> None:
    portfolio = _portfolio(
        (
            _asset("one", datetime(2022, 1, 1, 1, tzinfo=UTC), camera="Camera A"),
            _asset("two", datetime(2023, 2, 1, 2, tzinfo=UTC), camera="Camera B"),
        )
    )
    report = analyze_timeline(portfolio)

    details = render_timeline(report, details=True)
    cameras = render_timeline(report, camera_breakdown=True)
    galleries = render_timeline(report, gallery_breakdown=True)
    combined = render_timeline(
        report,
        details=True,
        camera_breakdown=True,
        gallery_breakdown=True,
    )

    assert "Photographs by capture month" in details
    assert "Camera Breakdown" not in details
    assert "Camera Breakdown" in cameras
    assert "Gallery Breakdown" not in cameras
    assert "Gallery Breakdown" in galleries
    assert combined.count("Detailed Timeline Distributions") == 1
    assert combined.count("Camera Breakdown") == 1
    assert combined.count("Gallery Breakdown") == 1
    assert "Months: 2022-01: 1" in cameras
    assert "Hours (UTC): 01:00: 1" in galleries


def test_missing_metadata_and_empty_portfolios_remain_explicit() -> None:
    missing_report = analyze_timeline(_portfolio((_asset("missing", None),), "Missing Timeline"))
    missing_rendered = render_timeline(missing_report)
    empty_report = analyze_timeline(
        Portfolio("test", "empty", "Empty Timeline", "https://example.test")
    )
    empty_rendered = render_timeline(empty_report)

    assert missing_report.capture_coverage.available == 0
    assert missing_report.camera_coverage.available == 0
    assert "Capture timestamp: 0 / 1 (0.0%)" in missing_rendered
    assert "Camera model: 0 / 1 (0.0%)" in missing_rendered
    assert "Most active capture year: not available" in missing_rendered
    assert "Unique photographs: 0" in empty_rendered
    assert "No camera metadata available." in empty_rendered
    assert "No galleries available." in empty_rendered
    assert "Missing timestamps and camera metadata are reported as missing" in empty_rendered
