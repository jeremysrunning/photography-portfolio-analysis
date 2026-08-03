"""Source-agnostic equipment and exposure metadata analysis."""

from collections import Counter, defaultdict
from dataclasses import dataclass

from ppa.analysis.assets import camera_name, text_value, unique_photographs
from ppa.analysis.baseline import Coverage
from ppa.models import Portfolio, RationalValue


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
    photographs = unique_photographs(list(portfolio.assets))
    total = len(photographs)

    cameras: Counter[str] = Counter()
    lenses: Counter[str] = Counter()
    focal_lengths: Counter[str] = Counter()
    focal_ranges: Counter[str] = Counter()
    apertures: Counter[float] = Counter()
    exposures: Counter[RationalValue] = Counter()
    iso_values: Counter[int] = Counter()
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

        focal = asset.metadata.focal_length_mm
        if focal is not None:
            focal_lengths[_measurement(focal, "mm")] += 1
            focal_ranges[_focal_range(focal)] += 1

        aperture = asset.metadata.aperture_f_number
        if aperture is not None:
            apertures[aperture] += 1

        exposure = asset.metadata.exposure_time
        if exposure is not None:
            exposures[exposure] += 1

        iso = asset.metadata.iso
        if iso is not None:
            iso_values[iso] += 1
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
        apertures={
            f"f/{_compact(value)}": count
            for value, count in sorted(apertures.items(), key=lambda item: (-item[1], item[0]))[:10]
        },
        exposures={
            _exposure_label(value): count
            for value, count in sorted(
                exposures.items(),
                key=lambda item: (-item[1], float(item[0])),
            )[:10]
        },
        iso_values={
            str(value): count
            for value, count in sorted(iso_values.items(), key=lambda item: (-item[1], item[0]))[
                :10
            ]
        },
        iso_ranges=_ordered_ranges(iso_ranges, _iso_range_order()),
        yearly_cameras=yearly,
    )


def _measurement(value: float, unit: str) -> str:
    return f"{_compact(value)} {unit}"


def _compact(value: float) -> str:
    return f"{value:g}"


def _exposure_label(value: RationalValue) -> str:
    if value.denominator == 1:
        return f"{value.numerator} s"
    return f"{value.numerator}/{value.denominator} s"


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


def _iso_range(value: int) -> str:
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
