"""Source-agnostic baseline metadata analysis."""

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from statistics import median
from typing import Any

from ppa.analysis.assets import is_photograph, text_value
from ppa.models import Asset, Portfolio


@dataclass(frozen=True, slots=True)
class Coverage:
    """Availability of a measurement across unique photographs."""

    available: int
    total: int

    @property
    def percent(self) -> float:
        return self.available / self.total * 100 if self.total else 0.0


@dataclass(frozen=True, slots=True)
class BaselineReport:
    """Neutral portfolio-level measurements derived from stored metadata."""

    title: str
    gallery_count: int
    media_references: int
    unique_media: int
    unique_photographs: int
    excluded_non_photographs: int
    duplicate_references: int
    gallery_size_min: int
    gallery_size_median: float
    gallery_size_max: int
    capture_date_coverage: Coverage
    earliest_capture: datetime | None
    latest_capture: datetime | None
    dimension_coverage: Coverage
    orientations: dict[str, int]
    format_coverage: Coverage
    formats: dict[str, int]
    geolocation_coverage: Coverage
    camera_coverage: Coverage
    cameras: dict[str, int]
    lens_coverage: Coverage
    lenses: dict[str, int]
    focal_length_coverage: Coverage
    focal_length_35mm_coverage: Coverage
    aperture_coverage: Coverage
    exposure_time_coverage: Coverage
    iso_coverage: Coverage
    exposure_compensation_coverage: Coverage
    flash_evidence_coverage: Coverage
    flash_fired: int
    flash_not_fired: int
    flash_missing_or_ambiguous: int


def analyze_baseline(portfolio: Portfolio) -> BaselineReport:
    """Measure metadata coverage and broad portfolio distributions."""
    photographs = [asset for asset in portfolio.assets if is_photograph(asset)]
    total = len(photographs)
    reference_count = sum(len(gallery.placements) for gallery in portfolio.galleries)
    placed_asset_ids = {
        placement.asset_source_id
        for gallery in portfolio.galleries
        for placement in gallery.placements
    }
    gallery_sizes = [len(gallery.placements) for gallery in portfolio.galleries]

    captured = [asset.captured_at for asset in photographs if asset.captured_at is not None]
    orientations: Counter[str] = Counter()
    formats: Counter[str] = Counter()
    cameras: Counter[str] = Counter()
    lenses: Counter[str] = Counter()
    dimension_count = 0
    format_count = 0
    geolocation_count = 0
    camera_count = 0
    lens_count = 0
    focal_length_count = 0
    focal_length_35mm_count = 0
    aperture_count = 0
    exposure_time_count = 0
    iso_count = 0
    exposure_compensation_count = 0
    flash_evidence_count = 0
    flash_fired_count = 0

    for asset in photographs:
        width = asset.metadata.width_px
        height = asset.metadata.height_px
        if width is not None and height is not None:
            dimension_count += 1
            if width > height:
                orientations["landscape"] += 1
            elif height > width:
                orientations["portrait"] += 1
            else:
                orientations["square"] += 1

        image_format = _text(asset, "Format", "format")
        if image_format:
            format_count += 1
            formats[image_format.upper()] += 1

        latitude = _number(asset, "Latitude", "latitude")
        longitude = _number(asset, "Longitude", "longitude")
        if latitude is not None and longitude is not None and (latitude != 0 or longitude != 0):
            geolocation_count += 1

        camera = _text(asset, "CameraModel", "Model", "camera", "camera_model")
        if camera:
            camera_count += 1
            cameras[camera] += 1

        lens = _text(asset, "LensModel", "Lens", "lens", "lens_model")
        if lens:
            lens_count += 1
            lenses[lens] += 1
        if asset.metadata.focal_length_mm is not None:
            focal_length_count += 1
        if asset.metadata.focal_length_35mm is not None:
            focal_length_35mm_count += 1
        if asset.metadata.aperture_f_number is not None:
            aperture_count += 1
        if asset.metadata.exposure_time is not None:
            exposure_time_count += 1
        if asset.metadata.iso is not None:
            iso_count += 1
        if asset.metadata.exposure_compensation_ev is not None:
            exposure_compensation_count += 1
        if asset.metadata.flash_fired is not None:
            flash_evidence_count += 1
            if asset.metadata.flash_fired:
                flash_fired_count += 1

    return BaselineReport(
        title=portfolio.title,
        gallery_count=len(portfolio.galleries),
        media_references=reference_count,
        unique_media=len(portfolio.assets),
        unique_photographs=total,
        excluded_non_photographs=len(portfolio.assets) - total,
        duplicate_references=reference_count - len(placed_asset_ids),
        gallery_size_min=min(gallery_sizes, default=0),
        gallery_size_median=float(median(gallery_sizes)) if gallery_sizes else 0.0,
        gallery_size_max=max(gallery_sizes, default=0),
        capture_date_coverage=Coverage(len(captured), total),
        earliest_capture=min(captured, default=None),
        latest_capture=max(captured, default=None),
        dimension_coverage=Coverage(dimension_count, total),
        orientations=dict(orientations),
        format_coverage=Coverage(format_count, total),
        formats=dict(formats.most_common()),
        geolocation_coverage=Coverage(geolocation_count, total),
        camera_coverage=Coverage(camera_count, total),
        cameras=dict(cameras.most_common()),
        lens_coverage=Coverage(lens_count, total),
        lenses=dict(lenses.most_common()),
        focal_length_coverage=Coverage(focal_length_count, total),
        focal_length_35mm_coverage=Coverage(focal_length_35mm_count, total),
        aperture_coverage=Coverage(aperture_count, total),
        exposure_time_coverage=Coverage(exposure_time_count, total),
        iso_coverage=Coverage(iso_count, total),
        exposure_compensation_coverage=Coverage(exposure_compensation_count, total),
        flash_evidence_coverage=Coverage(flash_evidence_count, total),
        flash_fired=flash_fired_count,
        flash_not_fired=flash_evidence_count - flash_fired_count,
        flash_missing_or_ambiguous=total - flash_evidence_count,
    )


def _value(asset: Asset, *names: str) -> Any:
    for mapping in (asset.exif, asset.values):
        for name in names:
            value = mapping.get(name)
            if value is not None:
                return value
    return None


def _text(asset: Asset, *names: str) -> str | None:
    return text_value(asset, *names)


def _number(asset: Asset, *names: str) -> float | None:
    value = _value(asset, *names)
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None
