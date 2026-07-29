"""Source-agnostic focal-length habits analysis."""

from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from math import floor
from statistics import median

from ppa.analysis.assets import camera_name, text_value, unique_photographs
from ppa.analysis.baseline import Coverage
from ppa.models import Asset, Portfolio

MIN_SEGMENT_SAMPLE = 20
MIN_GALLERY_COVERAGE = 0.5


class FocalLengthBasis(StrEnum):
    """The normalized focal-length measurement used by a distribution."""

    NATIVE = "native"
    EQUIVALENT_35MM = "35 mm equivalent"


@dataclass(frozen=True, slots=True)
class FocalLengthSummary:
    """Measurements for one explicitly identified focal-length basis."""

    basis: FocalLengthBasis
    sample_size: int
    median_mm: float | None
    minimum_mm: float | None
    maximum_mm: float | None
    modes_mm: tuple[int, ...]
    distinct_grouped_values: int
    grouped_values: dict[int, int]
    ranges: dict[str, int]
    most_common_ranges: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FocalLengthSegment:
    """Focal-length measurements for one camera, lens, gallery, or year."""

    key: str
    label: str
    photograph_count: int
    coverage: Coverage
    summary: FocalLengthSummary
    qualifies_for_default: bool


@dataclass(frozen=True, slots=True)
class FocalLengthYearChange:
    """Difference between consecutive adequately sampled yearly medians."""

    from_year: int
    to_year: int
    from_median_mm: float
    to_median_mm: float
    change_mm: float


@dataclass(frozen=True, slots=True)
class FocalLengthReport:
    """Portfolio focal-length evidence and source-agnostic measurements."""

    title: str
    photograph_count: int
    native_coverage: Coverage
    equivalent_coverage: Coverage
    primary_basis: FocalLengthBasis | None
    primary_coverage: Coverage
    primary_excluded: int
    primary_summary: FocalLengthSummary | None
    native_summary: FocalLengthSummary | None
    equivalent_summary: FocalLengthSummary | None
    camera_segments: tuple[FocalLengthSegment, ...]
    lens_segments: tuple[FocalLengthSegment, ...]
    gallery_segments: tuple[FocalLengthSegment, ...]
    year_segments: tuple[FocalLengthSegment, ...]
    largest_yearly_median_change: FocalLengthYearChange | None


def analyze_focal_lengths(portfolio: Portfolio) -> FocalLengthReport:
    """Describe recorded focal-length use without mixing measurement bases."""
    photographs = unique_photographs(list(portfolio.assets))
    native_count = sum(asset.metadata.focal_length_mm is not None for asset in photographs)
    equivalent_count = sum(asset.metadata.focal_length_35mm is not None for asset in photographs)
    basis = _select_primary_basis(native_count, equivalent_count)
    total = len(photographs)

    native_summary = _summary(photographs, FocalLengthBasis.NATIVE) if native_count else None
    equivalent_summary = (
        _summary(photographs, FocalLengthBasis.EQUIVALENT_35MM) if equivalent_count else None
    )
    primary_summary = (
        equivalent_summary
        if basis is FocalLengthBasis.EQUIVALENT_35MM
        else native_summary
        if basis is FocalLengthBasis.NATIVE
        else None
    )
    primary_count = primary_summary.sample_size if primary_summary is not None else 0

    camera_groups: dict[str, list[Asset]] = {}
    lens_groups: dict[str, list[Asset]] = {}
    year_groups: dict[int, list[Asset]] = {}
    for asset in photographs:
        camera = camera_name(asset)
        if camera:
            camera_groups.setdefault(camera, []).append(asset)
        lens = text_value(asset, "Lens", "LensModel", "lens", "lens_model")
        if lens:
            lens_groups.setdefault(lens, []).append(asset)
        if asset.captured_at is not None:
            year_groups.setdefault(asset.captured_at.year, []).append(asset)

    camera_segments = _segments(camera_groups, basis)
    lens_segments = _segments(lens_groups, FocalLengthBasis.NATIVE)
    gallery_segments = tuple(
        _segment(
            gallery.source_id,
            gallery.title,
            unique_photographs(list(portfolio.gallery_assets(gallery))),
            basis,
            require_gallery_coverage=True,
        )
        for gallery in portfolio.galleries
        if basis is not None
    )
    year_segments = tuple(
        _segment(str(year), str(year), assets, basis)
        for year, assets in sorted(year_groups.items())
        if basis is not None
    )

    return FocalLengthReport(
        title=portfolio.title,
        photograph_count=total,
        native_coverage=Coverage(native_count, total),
        equivalent_coverage=Coverage(equivalent_count, total),
        primary_basis=basis,
        primary_coverage=Coverage(primary_count, total),
        primary_excluded=total - primary_count,
        primary_summary=primary_summary,
        native_summary=native_summary,
        equivalent_summary=equivalent_summary,
        camera_segments=camera_segments,
        lens_segments=lens_segments,
        gallery_segments=gallery_segments,
        year_segments=year_segments,
        largest_yearly_median_change=_largest_year_change(year_segments),
    )


def _select_primary_basis(
    native_count: int,
    equivalent_count: int,
) -> FocalLengthBasis | None:
    if native_count == 0 and equivalent_count == 0:
        return None
    if native_count > equivalent_count:
        return FocalLengthBasis.NATIVE
    return FocalLengthBasis.EQUIVALENT_35MM


def _value(asset: Asset, basis: FocalLengthBasis) -> float | None:
    if basis is FocalLengthBasis.EQUIVALENT_35MM:
        return asset.metadata.focal_length_35mm
    return asset.metadata.focal_length_mm


def _group(value: float) -> int:
    """Group positive measurements to the nearest whole millimeter, half up."""
    return floor(value + 0.5)


def _summary(
    photographs: list[Asset],
    basis: FocalLengthBasis,
) -> FocalLengthSummary:
    values = [_value(asset, basis) for asset in photographs]
    measured = [value for value in values if value is not None]
    grouped = Counter(_group(value) for value in measured)
    mode_count = max(grouped.values(), default=0)
    modes = tuple(sorted(value for value, count in grouped.items() if count == mode_count))
    ranges = Counter(_range_label(value, basis) for value in measured)
    ordered_ranges = {label: ranges[label] for label in _range_labels(basis) if ranges[label]}
    range_count = max(ranges.values(), default=0)
    common_ranges = tuple(
        label for label in _range_labels(basis) if ranges[label] == range_count and range_count
    )
    return FocalLengthSummary(
        basis=basis,
        sample_size=len(measured),
        median_mm=float(median(measured)) if measured else None,
        minimum_mm=min(measured, default=None),
        maximum_mm=max(measured, default=None),
        modes_mm=modes,
        distinct_grouped_values=len(grouped),
        grouped_values=dict(sorted(grouped.items())),
        ranges=ordered_ranges,
        most_common_ranges=common_ranges,
    )


def _range_label(value: float, basis: FocalLengthBasis) -> str:
    labels = _range_labels(basis)
    if value < 24:
        return labels[0]
    if value < 35:
        return labels[1]
    if value < 50:
        return labels[2]
    if value < 85:
        return labels[3]
    if value < 200:
        return labels[4]
    return labels[5]


def _range_labels(basis: FocalLengthBasis) -> tuple[str, ...]:
    if basis is FocalLengthBasis.EQUIVALENT_35MM:
        return (
            "Ultra-wide (<24 mm)",
            "Wide (24 to <35 mm)",
            "Normal (35 to <50 mm)",
            "Short telephoto (50 to <85 mm)",
            "Medium telephoto (85 to <200 mm)",
            "Super telephoto (>=200 mm)",
        )
    return (
        "<24 mm (native)",
        "24 to <35 mm (native)",
        "35 to <50 mm (native)",
        "50 to <85 mm (native)",
        "85 to <200 mm (native)",
        ">=200 mm (native)",
    )


def _segments(
    groups: dict[str, list[Asset]],
    basis: FocalLengthBasis | None,
) -> tuple[FocalLengthSegment, ...]:
    if basis is None:
        return ()
    return tuple(
        _segment(key, key, assets, basis)
        for key, assets in sorted(groups.items(), key=lambda item: item[0].casefold())
    )


def _segment(
    key: str,
    label: str,
    photographs: list[Asset],
    basis: FocalLengthBasis,
    *,
    require_gallery_coverage: bool = False,
) -> FocalLengthSegment:
    summary = _summary(photographs, basis)
    coverage = Coverage(summary.sample_size, len(photographs))
    qualifies = summary.sample_size >= MIN_SEGMENT_SAMPLE
    if require_gallery_coverage:
        qualifies = qualifies and coverage.percent >= MIN_GALLERY_COVERAGE * 100
    return FocalLengthSegment(
        key=key,
        label=label,
        photograph_count=len(photographs),
        coverage=coverage,
        summary=summary,
        qualifies_for_default=qualifies,
    )


def _largest_year_change(
    segments: tuple[FocalLengthSegment, ...],
) -> FocalLengthYearChange | None:
    eligible = {
        int(segment.key): segment
        for segment in segments
        if segment.summary.sample_size >= MIN_SEGMENT_SAMPLE
        and segment.summary.median_mm is not None
    }
    changes = []
    for year in sorted(eligible):
        previous = eligible.get(year - 1)
        current = eligible[year]
        if previous is None:
            continue
        previous_median = previous.summary.median_mm
        current_median = current.summary.median_mm
        if previous_median is None or current_median is None:
            continue
        changes.append(
            FocalLengthYearChange(
                year - 1,
                year,
                previous_median,
                current_median,
                current_median - previous_median,
            )
        )
    return max(
        changes,
        key=lambda item: (abs(item.change_mm), -item.from_year),
        default=None,
    )
