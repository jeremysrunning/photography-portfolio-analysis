from datetime import UTC, datetime

from ppa.analysis import analyze_equipment
from ppa.models import Asset, Gallery, Portfolio
from ppa.reports import render_equipment


def test_equipment_report_measures_available_exif_without_ranking_quality() -> None:
    assets = (
        Asset(
            source_id="one",
            source_url="https://example.test/one",
            gallery_source_id="gallery",
            captured_at=datetime(2022, 1, 1, tzinfo=UTC),
            metadata={"ImageKey": "one"},
            exif={
                "Make": "Example",
                "Model": "Camera A",
                "Lens": "24-70mm",
                "FocalLength": "35.0 mm",
                "Aperture": "2.8",
                "Exposure": "1/250",
                "ISO": 400,
            },
        ),
        Asset(
            source_id="two",
            source_url="https://example.test/two",
            gallery_source_id="gallery",
            captured_at=datetime(2022, 2, 1, tzinfo=UTC),
            metadata={"ImageKey": "two"},
            exif={
                "Make": "Example",
                "Model": "Camera A",
                "Lens": "70-200mm",
                "FocalLength": "135.0 mm",
                "Aperture": "4",
                "Exposure": "1/500",
                "ISO": 1600,
            },
        ),
        Asset(
            source_id="three",
            source_url="https://example.test/three",
            gallery_source_id="gallery",
            captured_at=datetime(2023, 1, 1, tzinfo=UTC),
            metadata={"ImageKey": "three"},
            exif={"Make": "Other", "Model": "Other B"},
        ),
        Asset(
            source_id="missing",
            source_url="https://example.test/missing",
            gallery_source_id="gallery",
            metadata={"ImageKey": "missing"},
        ),
    )
    portfolio = Portfolio(
        source="test",
        source_id="portfolio",
        title="Equipment Evidence",
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
