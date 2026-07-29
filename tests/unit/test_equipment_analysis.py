from datetime import UTC, datetime

from ppa.analysis import analyze_equipment
from ppa.models import (
    Asset,
    AssetMetadata,
    Gallery,
    GalleryPlacement,
    MediaType,
    Portfolio,
    SourceReference,
)
from ppa.reports import render_equipment


def _asset(source_id: str, captured_at, exif=None) -> Asset:
    return Asset(
        SourceReference(source_id, f"https://example.test/{source_id}"),
        AssetMetadata(
            MediaType.PHOTOGRAPH,
            captured_at,
            {"ImageKey": source_id},
            exif or {},
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
    assert report.yearly_cameras[0].camera == "Example Camera A"
    assert "Frequency describes use within this portfolio, not equipment quality." in rendered
    assert "best" not in rendered.casefold()
