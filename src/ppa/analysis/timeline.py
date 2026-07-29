"""Source-agnostic capture timeline analysis."""

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import pairwise

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
class PeriodCount:
    """A deterministic count for one calendar period."""

    period: str
    count: int


@dataclass(frozen=True, slots=True)
class YearChange:
    """The recorded-count difference between consecutive calendar years."""

    from_year: int
    to_year: int
    change: int


@dataclass(frozen=True, slots=True)
class CaptureGap:
    """A comparable pair of capture timestamps and the interval between them."""

    start: datetime
    end: datetime
    duration: timedelta


@dataclass(frozen=True, slots=True)
class CameraEra:
    """Recorded use bounds for one frequently represented camera model."""

    camera: str
    first_year: int | None
    last_year: int | None
    photograph_count: int
    total_with_camera: int

    @property
    def percent(self) -> float:
        return self.photograph_count / self.total_with_camera * 100 if self.total_with_camera else 0


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
    represented_year_count: int
    average_per_represented_year: float
    timespan: timedelta | None
    peak_year: PeriodCount | None
    peak_month: PeriodCount | None
    least_active_complete_year: PeriodCount | None
    largest_yearly_increase: YearChange | None
    largest_yearly_decrease: YearChange | None
    longest_capture_gap: CaptureGap | None
    most_common_utc_hour: PeriodCount | None
    camera_eras: tuple[CameraEra, ...]
    top_galleries: tuple[TimelineSegment, ...]
    omitted_gallery_count: int


def analyze_timeline(portfolio: Portfolio) -> TimelineReport:
    """Measure recorded capture dates and hours without inferring timezones."""
    photographs = unique_photographs(list(portfolio.assets))
    captured = [asset for asset in photographs if asset.captured_at is not None]
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
            unique_photographs(list(portfolio.gallery_assets(gallery))),
        )
        for gallery in portfolio.galleries
    )
    overall = _segment("portfolio", portfolio.title, photographs)
    camera_eras = tuple(
        _camera_era(segment, len(cameras))
        for segment in sorted(
            camera_segments,
            key=lambda segment: (-segment.photograph_count, segment.label.casefold(), segment.key),
        )[:5]
    )
    top_galleries = tuple(
        sorted(
            gallery_segments,
            key=lambda segment: (-segment.photograph_count, segment.label.casefold(), segment.key),
        )[:10]
    )
    increase, decrease = _year_changes(overall.years)
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
        represented_year_count=len(overall.years),
        average_per_represented_year=(len(captured) / len(overall.years) if overall.years else 0.0),
        timespan=_timespan(overall.earliest_capture, overall.latest_capture),
        peak_year=_period_count(overall.years, largest=True),
        peak_month=_period_count(overall.months, largest=True),
        least_active_complete_year=_least_active_complete_year(
            overall.years,
            overall.earliest_capture,
            overall.latest_capture,
        ),
        largest_yearly_increase=increase,
        largest_yearly_decrease=decrease,
        longest_capture_gap=_longest_gap(
            [asset.captured_at for asset in photographs if asset.captured_at is not None]
        ),
        most_common_utc_hour=_period_count(
            overall.hours_by_time_basis.get("UTC", {}),
            largest=True,
        ),
        camera_eras=camera_eras,
        top_galleries=top_galleries,
        omitted_gallery_count=max(0, len(gallery_segments) - len(top_galleries)),
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


def _timespan(start: datetime | None, end: datetime | None) -> timedelta | None:
    return end - start if start is not None and end is not None else None


def _period_count(values: dict[object, int], *, largest: bool) -> PeriodCount | None:
    if not values:
        return None
    ordered = sorted(values.items(), key=lambda item: _period_order(item[0]))
    period, count = (max if largest else min)(ordered, key=lambda item: item[1])
    return PeriodCount(str(period), count)


def _period_order(value: object) -> tuple[int, int | str]:
    if isinstance(value, int):
        return (0, value)
    return (1, str(value))


def _least_active_complete_year(
    years: dict[int, int],
    earliest: datetime | None,
    latest: datetime | None,
) -> PeriodCount | None:
    if earliest is None or latest is None or latest.year - earliest.year < 2:
        return None
    complete = {year: years.get(year, 0) for year in range(earliest.year + 1, latest.year)}
    return _period_count(complete, largest=False)


def _year_changes(years: dict[int, int]) -> tuple[YearChange | None, YearChange | None]:
    if len(years) < 2:
        return (None, None)
    first_year = min(years)
    last_year = max(years)
    changes = [
        YearChange(year - 1, year, years.get(year, 0) - years.get(year - 1, 0))
        for year in range(first_year + 1, last_year + 1)
    ]
    return (
        max(changes, key=lambda item: item.change),
        min(changes, key=lambda item: item.change),
    )


def _longest_gap(values: list[datetime]) -> CaptureGap | None:
    if len(values) < 2:
        return None
    awareness = {value.tzinfo is not None and value.utcoffset() is not None for value in values}
    if len(awareness) > 1:
        return None
    ordered = sorted(values)
    gaps = [CaptureGap(start, end, end - start) for start, end in pairwise(ordered)]
    return max(gaps, key=lambda item: item.duration)


def _camera_era(segment: TimelineSegment, total_with_camera: int) -> CameraEra:
    return CameraEra(
        camera=segment.label,
        first_year=min(segment.years, default=None),
        last_year=max(segment.years, default=None),
        photograph_count=segment.photograph_count,
        total_with_camera=total_with_camera,
    )


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
