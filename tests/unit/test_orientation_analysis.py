from datetime import UTC, datetime

from ppa.analysis import AspectRatio, analyze_orientation
from ppa.models import (
    Asset,
    AssetMetadata,
    Gallery,
    GalleryPlacement,
    MediaType,
    Portfolio,
    SourceReference,
)
from ppa.reports import render_orientation


def _asset(index: int, width: int | None, height: int | None, *, year: int = 2020) -> Asset:
    return Asset(
        SourceReference(f"a-{index}", f"https://example.test/a-{index}"),
        AssetMetadata(
            media_type=MediaType.PHOTOGRAPH,
            captured_at=datetime(year, 1, 1, tzinfo=UTC),
            values={"Model": "Camera A"},
            width_px=width,
            height_px=height,
        ),
    )


def test_aspect_ratio_reduces_exactly_and_remains_directional() -> None:
    assert AspectRatio(6000, 4000) == AspectRatio(3, 2)
    assert AspectRatio(3, 2) != AspectRatio(2, 3)
    assert str(AspectRatio(2048, 1366)) == "1024:683"
    assert AspectRatio(2, 3).exact_value < AspectRatio(3, 2).exact_value


def test_orientation_analysis_preserves_partial_pairs_and_exact_grouping() -> None:
    assets = (
        _asset(1, 6000, 4000),
        _asset(2, 3, 2),
        _asset(3, 4000, 6000),
        _asset(4, 4000, 4000),
        _asset(5, 3001, 2000),
        _asset(6, 3000, None),
        _asset(7, None, 2000),
        _asset(8, None, None),
    )
    report = analyze_orientation(
        Portfolio(
            "test",
            SourceReference("p", "https://example.test/p"),
            "Portfolio",
            assets=assets,
        )
    )
    assert report.width_coverage.available == 6
    assert report.height_coverage.available == 6
    assert report.pair_coverage.available == 5
    assert (report.width_only, report.height_only, report.dimensions_missing) == (1, 1, 1)
    assert (report.landscape, report.portrait, report.square) == (3, 1, 1)
    assert report.aspect_ratios[0].ratio == AspectRatio(3, 2)
    assert report.aspect_ratios[0].count == 2
    assert AspectRatio(3001, 2000) in {item.ratio for item in report.aspect_ratios}


def test_segments_apply_sample_and_gallery_coverage_thresholds() -> None:
    assets = tuple(_asset(index, 3, 2) for index in range(20)) + tuple(
        _asset(index + 20, None, None) for index in range(20)
    )
    portfolio = Portfolio(
        "test",
        SourceReference("p", "https://example.test/p"),
        "Portfolio",
        assets=assets,
        galleries=(
            Gallery(
                SourceReference("g", "https://example.test/g"),
                "Gallery",
                placements=tuple(GalleryPlacement(asset.source_id) for asset in assets),
            ),
        ),
    )
    report = analyze_orientation(portfolio)
    assert report.year_segments[0].qualifies_for_default
    assert report.gallery_segments[0].qualifies_for_default
    assert report.camera_segments[0].qualifies_for_default


def test_renderer_is_bounded_and_zero_denominators_are_unavailable() -> None:
    empty = analyze_orientation(
        Portfolio("test", SourceReference("p", "https://example.test/p"), "Empty")
    )
    rendered = render_orientation(empty, details=True)
    assert "unavailable (no photographs)" in rendered
    assert "0 / 0 (0.0%)" not in rendered

    assets = tuple(_asset(index, index + 2, index + 1) for index in range(60))
    report = analyze_orientation(
        Portfolio(
            "test",
            SourceReference("p", "https://example.test/p"),
            "Many ratios",
            assets=assets,
        )
    )
    assert (
        len(
            [
                line
                for line in render_orientation(report).splitlines()
                if line.startswith("  ") and ":" in line
            ]
        )
        < 25
    )
    detailed = render_orientation(report, details=True)
    assert "additional ratios not shown" in detailed
    assert "quality" in detailed


def test_combined_breakdowns_do_not_duplicate_headings() -> None:
    assets = tuple(_asset(index, 3, 2) for index in range(20))
    portfolio = Portfolio(
        "test",
        SourceReference("p", "https://example.test/p"),
        "Portfolio",
        assets=assets,
        galleries=(
            Gallery(
                SourceReference("g", "https://example.test/g"),
                "Gallery",
                placements=tuple(GalleryPlacement(asset.source_id) for asset in assets),
            ),
        ),
    )
    rendered = render_orientation(
        analyze_orientation(portfolio),
        year_breakdown=True,
        gallery_breakdown=True,
        camera_breakdown=True,
    )
    for heading in ("Capture-year breakdown", "Gallery breakdown", "Camera breakdown"):
        assert rendered.count(heading) == 1
