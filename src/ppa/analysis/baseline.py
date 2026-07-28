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

    for asset in photographs:
        width = _positive_number(asset, "OriginalWidth", "width", "Width")
        height = _positive_number(asset, "OriginalHeight", "height", "Height")
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


def _positive_number(asset: Asset, *names: str) -> float | None:
    value = _number(asset, *names)
    return value if value is not None and value > 0 else None
