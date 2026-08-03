from datetime import UTC, datetime

from ppa.analysis import analyze_equipment
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
from ppa.reports import render_equipment


def _asset(
    source_id: str,
    captured_at,
    exif=None,
    focal_length_mm=None,
    aperture=None,
    exposure=None,
    iso=None,
) -> Asset:
    return Asset(
        SourceReference(source_id, f"https://example.test/{source_id}"),
        AssetMetadata(
            MediaType.PHOTOGRAPH,
            captured_at,
            {"ImageKey": source_id},
            exif or {},
            focal_length_mm=focal_length_mm,
            aperture_f_number=aperture,
            exposure_time=exposure,
            iso=iso,
        ),
    )


def test_equipment_report_measures_available_exif_without_ranking_quality() -> None:
    assets = (
        _asset(
            "one",
            datetime(2022, 1, 1, tzinfo=UTC),
            {
                "Make": "Example",
                "Model": "Camera A",
                "Lens": "24-70mm",
                "FocalLength": "35.0 mm",
                "Aperture": "2.8",
                "Exposure": "1/250",
                "ISO": 400,
            },
            35.0,
            2.8,
            RationalValue(1, 250),
            400,
        ),
        _asset(
            "two",
            datetime(2022, 2, 1, tzinfo=UTC),
            {
                "Make": "Example",
                "Model": "Camera A",
                "Lens": "70-200mm",
                "FocalLength": "135.0 mm",
                "Aperture": "4",
                "Exposure": "1/500",
                "ISO": 1600,
            },
            135.0,
            4.0,
            RationalValue(1, 500),
            1600,
        ),
        _asset(
            "three",
            datetime(2023, 1, 1, tzinfo=UTC),
            {"Make": "Other", "Model": "Other B"},
        ),
        _asset("missing", None),
    )
    portfolio = Portfolio(
        "test",
        SourceReference("portfolio", "https://example.test"),
        "Equipment Evidence",
        assets=assets,
        galleries=(
            Gallery(
                SourceReference("gallery", "https://example.test/gallery"),
                "Gallery",
                placements=tuple(GalleryPlacement(asset.source_id) for asset in assets),
            ),
        ),
    )

    report = analyze_equipment(portfolio)
    rendered = render_equipment(report)

    assert report.camera_coverage.available == 3
    assert report.camera_coverage.total == 4
    assert report.cameras["Example Camera A"] == 2
    assert report.focal_length_ranges == {"35-69 mm": 1, ">=135 mm": 1}
    assert report.iso_ranges == {"101-400": 1, "801-1600": 1}
    assert report.apertures == {"f/2.8": 1, "f/4": 1}
    assert report.exposures == {"1/500 s": 1, "1/250 s": 1}
    assert report.yearly_cameras[0].camera == "Example Camera A"
    assert "Frequency describes use within this portfolio, not equipment quality." in rendered
    assert "best" not in rendered.casefold()


def test_equipment_groups_exact_typed_exposure_and_ignores_raw_aliases() -> None:
    assets = (
        _asset(
            "one",
            None,
            {"Exposure": "malformed", "Aperture": "99", "ISO": 99999},
            aperture=2.8,
            exposure=RationalValue(1, 2),
            iso=400,
        ),
        _asset(
            "two",
            None,
            {"ExposureTime": "1/1000", "FNumber": "22", "ISOSpeedRatings": 50},
            aperture=2.8,
            exposure=RationalValue(2, 4),
            iso=400,
        ),
    )
    portfolio = Portfolio(
        "test",
        SourceReference("portfolio", "https://example.test"),
        "Typed exposure",
        assets=assets,
    )

    report = analyze_equipment(portfolio)

    assert report.apertures == {"f/2.8": 2}
    assert report.exposures == {"1/2 s": 2}
    assert report.iso_values == {"400": 2}
