"""Source-agnostic equipment and exposure metadata analysis."""

import re
from collections import Counter, defaultdict
from dataclasses import dataclass

from ppa.analysis.assets import asset_value, camera_name, text_value, unique_photographs
from ppa.analysis.baseline import Coverage
from ppa.models import Asset, Portfolio

_NUMBER = re.compile(r"[-+]?\d+(?:\.\d+)?")


@dataclass(frozen=True, slots=True)
class YearlyCamera:
    """Most frequently recorded camera for one capture year."""

    year: int
    camera: str
    count: int
    total_with_camera: int

    @property
    def percent(self) -> float:
        return self.count / self.total_with_camera * 100 if self.total_with_camera else 0.0


@dataclass(frozen=True, slots=True)
class EquipmentReport:
    """Portfolio-level equipment and exposure metadata measurements."""

    title: str
    photograph_count: int
    camera_coverage: Coverage
    lens_coverage: Coverage
    focal_length_coverage: Coverage
    aperture_coverage: Coverage
    exposure_coverage: Coverage
    iso_coverage: Coverage
    cameras: dict[str, int]
    lenses: dict[str, int]
    focal_lengths: dict[str, int]
    focal_length_ranges: dict[str, int]
    apertures: dict[str, int]
    exposures: dict[str, int]
    iso_values: dict[str, int]
    iso_ranges: dict[str, int]
    yearly_cameras: tuple[YearlyCamera, ...]


def analyze_equipment(portfolio: Portfolio) -> EquipmentReport:
    """Measure equipment and exposure patterns from normalized EXIF."""
    references = [asset for gallery in portfolio.galleries for asset in gallery.assets]
    photographs = unique_photographs(references)
    total = len(photographs)

    cameras: Counter[str] = Counter()
    lenses: Counter[str] = Counter()
    focal_lengths: Counter[str] = Counter()
    focal_ranges: Counter[str] = Counter()
    apertures: Counter[str] = Counter()
    exposures: Counter[str] = Counter()
    iso_values: Counter[str] = Counter()
    iso_ranges: Counter[str] = Counter()
    cameras_by_year: dict[int, Counter[str]] = defaultdict(Counter)

    for asset in photographs:
        camera = camera_name(asset)
        if camera:
            cameras[camera] += 1
            if asset.captured_at:
                cameras_by_year[asset.captured_at.year][camera] += 1

        lens = text_value(asset, "Lens", "LensModel", "lens", "lens_model")
        if lens:
            lenses[lens] += 1

        focal = _number(asset, "FocalLength", "focal_length")
        if focal is not None:
            focal_lengths[_measurement(focal, "mm")] += 1
            focal_ranges[_focal_range(focal)] += 1

        aperture = _number(asset, "Aperture", "FNumber", "aperture")
        if aperture is not None:
            apertures[f"f/{_compact(aperture)}"] += 1

        exposure = text_value(asset, "Exposure", "ExposureTime", "exposure")
        if exposure:
            exposures[exposure] += 1

        iso = _number(asset, "ISO", "ISOSpeedRatings", "iso")
        if iso is not None:
            iso_values[_compact(iso)] += 1
            iso_ranges[_iso_range(iso)] += 1

    yearly = tuple(
        _yearly_camera(year, counts) for year, counts in sorted(cameras_by_year.items()) if counts
    )
    return EquipmentReport(
        title=portfolio.title,
        photograph_count=total,
        camera_coverage=Coverage(sum(cameras.values()), total),
        lens_coverage=Coverage(sum(lenses.values()), total),
        focal_length_coverage=Coverage(sum(focal_lengths.values()), total),
        aperture_coverage=Coverage(sum(apertures.values()), total),
        exposure_coverage=Coverage(sum(exposures.values()), total),
        iso_coverage=Coverage(sum(iso_values.values()), total),
        cameras=dict(cameras.most_common(10)),
        lenses=dict(lenses.most_common(10)),
        focal_lengths=dict(focal_lengths.most_common(10)),
        focal_length_ranges=_ordered_ranges(focal_ranges, _focal_range_order()),
        apertures=dict(apertures.most_common(10)),
        exposures=dict(exposures.most_common(10)),
        iso_values=dict(iso_values.most_common(10)),
        iso_ranges=_ordered_ranges(iso_ranges, _iso_range_order()),
        yearly_cameras=yearly,
    )


def _number(asset: Asset, *names: str) -> float | None:
    value = asset_value(asset, *names)
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        match = _NUMBER.search(value)
        if match:
            return float(match.group())
    return None


def _measurement(value: float, unit: str) -> str:
    return f"{_compact(value)} {unit}"


def _compact(value: float) -> str:
    return f"{value:g}"


def _focal_range(value: float) -> str:
    if value < 24:
        return "<24 mm"
    if value < 35:
        return "24-34 mm"
    if value < 70:
        return "35-69 mm"
    if value < 135:
        return "70-134 mm"
    return ">=135 mm"


def _focal_range_order() -> tuple[str, ...]:
    return ("<24 mm", "24-34 mm", "35-69 mm", "70-134 mm", ">=135 mm")


def _iso_range(value: float) -> str:
    if value <= 100:
        return "<=100"
    if value <= 400:
        return "101-400"
    if value <= 800:
        return "401-800"
    if value <= 1600:
        return "801-1600"
    if value <= 3200:
        return "1601-3200"
    return ">3200"


def _iso_range_order() -> tuple[str, ...]:
    return ("<=100", "101-400", "401-800", "801-1600", "1601-3200", ">3200")


def _ordered_ranges(values: Counter[str], order: tuple[str, ...]) -> dict[str, int]:
    return {name: values[name] for name in order if values[name]}


def _yearly_camera(year: int, counts: Counter[str]) -> YearlyCamera:
    camera, count = counts.most_common(1)[0]
    return YearlyCamera(year, camera, count, sum(counts.values()))
