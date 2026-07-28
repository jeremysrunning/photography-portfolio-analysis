"""Source-agnostic capture timeline analysis."""

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta

from ppa.analysis.assets import camera_name, unique_photographs
from ppa.analysis.baseline import Coverage
from ppa.models import Asset, Portfolio


@dataclass(frozen=True, slots=True)
class TimelineSegment:
    """Capture-time measurements for one camera or gallery segment."""

    key: str
    label: str
    photograph_count: int
    capture_coverage: Coverage
    earliest_capture: datetime | None
    latest_capture: datetime | None
    years: dict[int, int]
    months: dict[str, int]
    hours_by_time_basis: dict[str, dict[int, int]]


@dataclass(frozen=True, slots=True)
class TimelineReport:
    """Neutral timeline measurements derived from normalized timestamps."""

    title: str
    photograph_count: int
    capture_coverage: Coverage
    camera_coverage: Coverage
    earliest_capture: datetime | None
    latest_capture: datetime | None
    years: dict[int, int]
    months: dict[str, int]
    hours_by_time_basis: dict[str, dict[int, int]]
    camera_segments: tuple[TimelineSegment, ...]
    gallery_segments: tuple[TimelineSegment, ...]


def analyze_timeline(portfolio: Portfolio) -> TimelineReport:
    """Measure recorded capture dates and hours without inferring timezones."""
    references = [asset for gallery in portfolio.galleries for asset in gallery.assets]
    photographs = unique_photographs(references)
    cameras = [asset for asset in photographs if camera_name(asset) is not None]

    camera_groups: dict[str, list[Asset]] = {}
    for asset in cameras:
        camera = camera_name(asset)
        if camera is not None:
            camera_groups.setdefault(camera, []).append(asset)

    camera_segments = tuple(
        _segment(camera, camera, assets)
        for camera, assets in sorted(camera_groups.items(), key=lambda item: item[0].casefold())
    )
    gallery_segments = tuple(
        _segment(
            gallery.source_id,
            gallery.title,
            unique_photographs(list(gallery.assets)),
        )
        for gallery in portfolio.galleries
    )
    overall = _segment("portfolio", portfolio.title, photographs)
    return TimelineReport(
        title=portfolio.title,
        photograph_count=len(photographs),
        capture_coverage=overall.capture_coverage,
        camera_coverage=Coverage(len(cameras), len(photographs)),
        earliest_capture=overall.earliest_capture,
        latest_capture=overall.latest_capture,
        years=overall.years,
        months=overall.months,
        hours_by_time_basis=overall.hours_by_time_basis,
        camera_segments=camera_segments,
        gallery_segments=gallery_segments,
    )


def _segment(key: str, label: str, photographs: list[Asset]) -> TimelineSegment:
    timestamps = [asset.captured_at for asset in photographs if asset.captured_at is not None]
    earliest, latest = _capture_range(timestamps)
    years = Counter(timestamp.year for timestamp in timestamps)
    months = Counter(timestamp.strftime("%Y-%m") for timestamp in timestamps)
    hours: dict[str, Counter[int]] = {}
    for timestamp in timestamps:
        hours.setdefault(_time_basis(timestamp), Counter())[timestamp.hour] += 1
    return TimelineSegment(
        key=key,
        label=label,
        photograph_count=len(photographs),
        capture_coverage=Coverage(len(timestamps), len(photographs)),
        earliest_capture=earliest,
        latest_capture=latest,
        years=dict(sorted(years.items())),
        months=dict(sorted(months.items())),
        hours_by_time_basis={
            basis: dict(sorted(counts.items()))
            for basis, counts in sorted(hours.items(), key=lambda item: _basis_order(item[0]))
        },
    )


def _capture_range(values: list[datetime]) -> tuple[datetime | None, datetime | None]:
    if not values:
        return (None, None)
    awareness = {value.tzinfo is not None and value.utcoffset() is not None for value in values}
    if len(awareness) > 1:
        return (None, None)
    return (min(values), max(values))


def _time_basis(value: datetime) -> str:
    offset = value.utcoffset() if value.tzinfo is not None else None
    if offset is None:
        return "timezone unknown"
    if offset == timedelta(0):
        return "UTC"
    total_minutes = int(offset.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "-"
    hours, minutes = divmod(abs(total_minutes), 60)
    return f"UTC{sign}{hours:02d}:{minutes:02d}"


def _basis_order(value: str) -> tuple[int, str]:
    if value == "UTC":
        return (0, value)
    if value.startswith("UTC"):
        return (1, value)
    return (2, value)
