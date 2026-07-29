from datetime import UTC, datetime

import pytest

from ppa.analysis import FocalLengthBasis, analyze_focal_lengths
from ppa.models import (
    Asset,
    AssetMetadata,
    Gallery,
    GalleryPlacement,
    MediaType,
    Portfolio,
    SourceReference,
)
from ppa.reports import render_focal_lengths


def _reference(source_id: str) -> SourceReference:
    return SourceReference(source_id, f"https://example.test/{source_id}")


def _asset(
    source_id: str,
    *,
    native: float | None = None,
    equivalent: float | None = None,
    camera: str | None = None,
    lens: str | None = None,
    year: int | None = None,
) -> Asset:
    exif = {}
    if camera:
        exif["Model"] = camera
    if lens:
        exif["Lens"] = lens
    return Asset(
        _reference(source_id),
        AssetMetadata(
            MediaType.PHOTOGRAPH,
            datetime(year, 1, 1, tzinfo=UTC) if year else None,
            exif=exif,
            focal_length_mm=native,
            focal_length_35mm=equivalent,
        ),
    )


def _portfolio(
    assets: tuple[Asset, ...],
    galleries: tuple[Gallery, ...] = (),
) -> Portfolio:
    return Portfolio(
        "test",
        _reference("portfolio"),
        "Focal Evidence",
        assets=assets,
        galleries=galleries,
    )


@pytest.mark.parametrize(
    ("assets", "basis", "sample_size", "excluded"),
    [
        (
            (
                _asset("one", native=24, equivalent=35),
                _asset("two", equivalent=50),
            ),
            FocalLengthBasis.EQUIVALENT_35MM,
            2,
            0,
        ),
        (
            (
                _asset("one", native=24, equivalent=35),
                _asset("two", native=50),
            ),
            FocalLengthBasis.NATIVE,
            2,
            0,
        ),
        (
            (
                _asset("one", native=24, equivalent=35),
                _asset("two"),
            ),
            FocalLengthBasis.EQUIVALENT_35MM,
            1,
            1,
        ),
        (
            (
                _asset("one", native=24, equivalent=35),
                _asset("two", native=50),
                _asset("three", native=85),
            ),
            FocalLengthBasis.NATIVE,
            3,
            0,
        ),
        ((_asset("missing"),), None, 0, 1),
        ((), None, 0, 0),
    ],
)
def test_primary_basis_uses_coverage_without_mixing(
    assets: tuple[Asset, ...],
    basis: FocalLengthBasis | None,
    sample_size: int,
    excluded: int,
) -> None:
    report = analyze_focal_lengths(_portfolio(assets))

    assert report.primary_basis is basis
    assert report.primary_coverage.available == sample_size
    assert report.primary_excluded == excluded
    if report.primary_summary is not None:
        expected = [
            (
                asset.metadata.focal_length_35mm
                if basis is FocalLengthBasis.EQUIVALENT_35MM
                else asset.metadata.focal_length_mm
            )
            for asset in assets
        ]
        assert report.primary_summary.sample_size == sum(value is not None for value in expected)


def test_summary_calculates_median_modes_grouping_and_limits_deterministically() -> None:
    report = analyze_focal_lengths(
        _portfolio(
            (
                _asset("one", equivalent=23.49),
                _asset("two", equivalent=23.5),
                _asset("three", equivalent=24.49),
                _asset("four", equivalent=24.5),
                _asset("five", equivalent=69.9),
                _asset("six", equivalent=70.0),
            )
        )
    )
    summary = report.primary_summary

    assert summary is not None
    assert summary.median_mm == pytest.approx(24.495)
    assert summary.minimum_mm == 23.49
    assert summary.maximum_mm == 70.0
    assert summary.grouped_values == {23: 1, 24: 2, 25: 1, 70: 2}
    assert summary.modes_mm == (24, 70)
    assert summary.distinct_grouped_values == 4


def test_primary_distribution_contains_only_the_selected_basis() -> None:
    equivalent_report = analyze_focal_lengths(
        _portfolio(
            (
                _asset("one", native=10, equivalent=100),
                _asset("two", native=20, equivalent=200),
            )
        )
    )
    native_report = analyze_focal_lengths(
        _portfolio(
            (
                _asset("one", native=10, equivalent=100),
                _asset("two", native=20),
            )
        )
    )

    assert equivalent_report.primary_summary is not None
    assert equivalent_report.primary_summary.grouped_values == {100: 1, 200: 1}
    assert native_report.primary_summary is not None
    assert native_report.primary_summary.grouped_values == {10: 1, 20: 1}


@pytest.mark.parametrize(
    ("value", "expected_label"),
    [
        (23.999, "Ultra-wide (<24 mm)"),
        (24.0, "Wide (24 to <35 mm)"),
        (34.999, "Wide (24 to <35 mm)"),
        (35.0, "Normal (35 to <50 mm)"),
        (49.999, "Normal (35 to <50 mm)"),
        (50.0, "Short telephoto (50 to <85 mm)"),
        (84.999, "Short telephoto (50 to <85 mm)"),
        (85.0, "Medium telephoto (85 to <200 mm)"),
        (199.999, "Medium telephoto (85 to <200 mm)"),
        (200.0, "Super telephoto (>=200 mm)"),
    ],
)
def test_equivalent_range_boundaries(value: float, expected_label: str) -> None:
    summary = analyze_focal_lengths(
        _portfolio((_asset("image", equivalent=value),))
    ).primary_summary
    assert summary is not None
    assert summary.ranges == {expected_label: 1}


def test_native_ranges_are_neutral_and_tied_ranges_follow_boundary_order() -> None:
    report = analyze_focal_lengths(
        _portfolio(
            (
                _asset("wide", native=24),
                _asset("normal", native=35),
            )
        )
    )
    summary = report.primary_summary

    assert report.primary_basis is FocalLengthBasis.NATIVE
    assert summary is not None
    assert summary.most_common_ranges == (
        "24 to <35 mm (native)",
        "35 to <50 mm (native)",
    )
    assert all("Ultra-wide" not in label for label in summary.ranges)


def test_camera_lens_gallery_and_year_segments_disclose_basis_coverage_and_thresholds() -> None:
    assets = tuple(
        _asset(
            f"image-{index}",
            native=50 + index % 2,
            equivalent=75 + index % 2,
            camera="Camera A" if index < 20 else None,
            lens="Lens A" if index < 20 else None,
            year=2020 if index < 20 else 2021,
        )
        for index in range(21)
    )
    gallery = Gallery(
        _reference("gallery"),
        "Gallery",
        placements=tuple(GalleryPlacement(asset.source_id) for asset in assets),
    )

    report = analyze_focal_lengths(_portfolio(assets, (gallery,)))

    camera = report.camera_segments[0]
    lens = report.lens_segments[0]
    gallery_segment = report.gallery_segments[0]
    assert camera.summary.basis is FocalLengthBasis.EQUIVALENT_35MM
    assert camera.coverage == camera.coverage.__class__(20, 20)
    assert camera.qualifies_for_default
    assert lens.summary.basis is FocalLengthBasis.NATIVE
    assert lens.qualifies_for_default
    assert gallery_segment.coverage.available == 21
    assert gallery_segment.qualifies_for_default
    assert report.year_segments[0].qualifies_for_default
    assert not report.year_segments[1].qualifies_for_default


def test_gallery_default_requires_minimum_sample_and_half_coverage() -> None:
    measured = tuple(_asset(f"measured-{index}", equivalent=35) for index in range(20))
    missing = tuple(_asset(f"missing-{index}") for index in range(21))
    assets = measured + missing
    gallery = Gallery(
        _reference("gallery"),
        "Sparse Gallery",
        placements=tuple(GalleryPlacement(asset.source_id) for asset in assets),
    )

    segment = analyze_focal_lengths(_portfolio(assets, (gallery,))).gallery_segments[0]

    assert segment.coverage.available == 20
    assert segment.coverage.total == 41
    assert not segment.qualifies_for_default


def test_year_change_requires_consecutive_adequately_sampled_years() -> None:
    assets = tuple(
        _asset(f"2020-{index}", equivalent=35, year=2020) for index in range(20)
    ) + tuple(_asset(f"2021-{index}", equivalent=50, year=2021) for index in range(20))

    change = analyze_focal_lengths(_portfolio(assets)).largest_yearly_median_change

    assert change is not None
    assert (change.from_year, change.to_year, change.change_mm) == (2020, 2021, 15.0)


def test_report_is_concise_neutral_and_renders_basis_exclusions_and_modes() -> None:
    assets = (
        _asset("one", native=24, equivalent=35),
        _asset("two", native=50),
        _asset("three"),
    )
    rendered = render_focal_lengths(analyze_focal_lengths(_portfolio(assets)))

    assert "Selected primary basis: native" in rendered
    assert "Primary sample size: 2" in rendered
    assert "Excluded from primary distribution: 1" in rendered
    assert "35 mm equivalent: 1 / 3 (33.3%)" in rendered
    assert "Detailed Primary Distribution" not in rendered
    lowered = rendered.casefold()
    for prohibited in ("favorite", "prefers", "should", "better composition"):
        assert prohibited not in lowered


def test_optional_modes_are_independent_and_do_not_duplicate_sections() -> None:
    assets = tuple(
        _asset(
            f"image-{index}",
            native=35,
            equivalent=50,
            camera="Camera",
            lens="Lens",
            year=2024,
        )
        for index in range(20)
    )
    gallery = Gallery(
        _reference("gallery"),
        "Gallery",
        placements=tuple(GalleryPlacement(asset.source_id) for asset in assets),
    )
    report = analyze_focal_lengths(_portfolio(assets, (gallery,)))

    details = render_focal_lengths(report, details=True)
    cameras = render_focal_lengths(report, camera_breakdown=True)
    combined = render_focal_lengths(
        report,
        details=True,
        camera_breakdown=True,
        lens_breakdown=True,
        gallery_breakdown=True,
        year_breakdown=True,
    )

    assert "Detailed Primary Distribution" in details
    assert "Camera Breakdown" not in details
    assert "Camera Breakdown" in cameras
    for heading in (
        "Detailed Primary Distribution",
        "Camera Breakdown",
        "Lens Breakdown",
        "Gallery Breakdown",
        "Year Breakdown",
    ):
        assert combined.count(heading) == 1


@pytest.mark.parametrize(
    ("option", "heading"),
    [
        ("camera_breakdown", "Camera Breakdown"),
        ("lens_breakdown", "Lens Breakdown"),
        ("gallery_breakdown", "Gallery Breakdown"),
        ("year_breakdown", "Year Breakdown"),
    ],
)
def test_each_segment_breakdown_can_be_requested_independently(
    option: str,
    heading: str,
) -> None:
    assets = tuple(
        _asset(
            f"image-{index}",
            native=35,
            equivalent=50,
            camera="Camera",
            lens="Lens",
            year=2024,
        )
        for index in range(20)
    )
    gallery = Gallery(
        _reference("gallery"),
        "Gallery",
        placements=tuple(GalleryPlacement(asset.source_id) for asset in assets),
    )
    report = analyze_focal_lengths(_portfolio(assets, (gallery,)))

    rendered = render_focal_lengths(report, **{option: True})

    assert heading in rendered
    other_headings = {
        "Camera Breakdown",
        "Lens Breakdown",
        "Gallery Breakdown",
        "Year Breakdown",
    } - {heading}
    assert all(other not in rendered for other in other_headings)


def test_missing_camera_lens_gallery_and_dates_remain_explicit() -> None:
    report = analyze_focal_lengths(_portfolio((_asset("image", native=35),)))
    rendered = render_focal_lengths(report)

    assert report.camera_segments == ()
    assert report.lens_segments == ()
    assert report.gallery_segments == ()
    assert report.year_segments == ()
    assert "No segments meet the default sample threshold." in rendered
    assert "No capture years with focal-length metadata." in rendered
