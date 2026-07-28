"""Plain-text rendering for capture timeline measurements."""

from datetime import datetime, timedelta

from ppa.analysis import Coverage, PeriodCount, TimelineReport, TimelineSegment, YearChange


def render_timeline(
    report: TimelineReport,
    *,
    details: bool = False,
    camera_breakdown: bool = False,
    gallery_breakdown: bool = False,
) -> str:
    """Render a concise, neutral report with optional exhaustive sections."""
    lines = [f"Timeline report: {report.title}", "", "Evidence"]
    lines.extend(
        [
            f"  Unique photographs: {report.photograph_count:,}",
            f"  Capture timestamp: {_coverage(report.capture_coverage)}",
            f"  Camera model: {_coverage(report.camera_coverage)}",
            f"  Earliest recorded capture: {_timestamp(report.earliest_capture)}",
            f"  Latest recorded capture: {_timestamp(report.latest_capture)}",
            "",
            "Timeline Summary",
            f"  Recorded capture timespan: {_duration(report.timespan)}",
            f"  Most active capture year: {_period(report.peak_year)}",
            f"  Most active capture month: {_period(report.peak_month)}",
            (f"  Least active complete year: {_period(report.least_active_complete_year)}"),
            (
                "  Average photographs per represented year: "
                f"{report.average_per_represented_year:,.1f}"
            ),
            f"  Represented capture years: {report.represented_year_count:,}",
            "",
            "Key Measurements",
            (
                "  Largest recorded year-over-year increase: "
                f"{_year_change(report.largest_yearly_increase)}"
            ),
            (
                "  Largest recorded year-over-year decrease: "
                f"{_year_change(report.largest_yearly_decrease)}"
            ),
            f"  Longest gap between recorded captures: {_gap(report)}",
            (f"  Most frequently recorded UTC capture hour: {_utc_hour(report)}"),
            "",
            "Camera Eras",
        ]
    )
    _add_camera_eras(lines, report)
    lines.extend(["", "Top Galleries"])
    _add_top_galleries(lines, report)

    if details:
        lines.extend(["", "Detailed Timeline Distributions"])
        _add_distribution(lines, "Photographs by capture year", report.years)
        _add_distribution(lines, "Photographs by capture month", report.months)
        _add_hours(lines, report.hours_by_time_basis)
    if camera_breakdown:
        lines.extend(["", "Camera Breakdown"])
        _add_segments(lines, report.camera_segments)
    if gallery_breakdown:
        lines.extend(["", "Gallery Breakdown"])
        _add_segments(lines, report.gallery_segments)

    lines.extend(
        [
            "",
            "Notes",
            "  Dates and hours use the calendar values and timezone offsets stored in metadata.",
            "  UTC timestamps remain UTC; no local timezone is inferred.",
            "  Naive timestamps are labeled timezone unknown and are not combined with UTC hours.",
            (
                "  Comparable capture ranges and gaps are unavailable when timestamp "
                "timezone bases are mixed."
            ),
            "  Camera Eras lists the five most represented recorded camera models.",
            "  Camera dates describe recorded use in this portfolio, not ownership.",
            "  Counts describe recorded capture metadata, not productivity or intent.",
            (
                "  Missing timestamps and camera metadata are reported as missing "
                "and are not inferred."
            ),
        ]
    )
    return "\n".join(lines)


def _coverage(coverage: Coverage) -> str:
    return f"{coverage.available:,} / {coverage.total:,} ({coverage.percent:.1f}%)"


def _timestamp(value: datetime | None) -> str:
    return value.isoformat() if value is not None else "not available"


def _duration(value: timedelta | None) -> str:
    if value is None:
        return "not available"
    return f"{value.days:,} days"


def _period(value: PeriodCount | None) -> str:
    return f"{value.period}: {value.count:,}" if value is not None else "not available"


def _year_change(value: YearChange | None) -> str:
    if value is None:
        return "not available"
    return f"{value.from_year} to {value.to_year}: {value.change:+,}"


def _gap(report: TimelineReport) -> str:
    value = report.longest_capture_gap
    if value is None:
        return "not available"
    return f"{_duration(value.duration)}; {value.start.isoformat()} to {value.end.isoformat()}"


def _utc_hour(report: TimelineReport) -> str:
    value = report.most_common_utc_hour
    if value is None:
        return "not available"
    return f"{int(value.period):02d}:00; {value.count:,} photographs"


def _add_camera_eras(lines: list[str], report: TimelineReport) -> None:
    if not report.camera_eras:
        lines.append("  No camera metadata available.")
        return
    for era in report.camera_eras:
        year_range = _year_range(era.first_year, era.last_year)
        lines.append(
            f"  {era.camera}: {year_range}; {era.photograph_count:,} "
            f"({era.percent:.1f}% of photographs with camera metadata)"
        )


def _add_top_galleries(lines: list[str], report: TimelineReport) -> None:
    if not report.top_galleries:
        lines.append("  No galleries available.")
        return
    for segment in report.top_galleries:
        year_range = _year_range(
            min(segment.years, default=None),
            max(segment.years, default=None),
        )
        lines.append(
            f"  {segment.label} [{segment.key}]: {segment.photograph_count:,} photographs; "
            f"{year_range}; {_coverage(segment.capture_coverage)} timestamps"
        )
    if report.omitted_gallery_count:
        lines.append(f"  Additional galleries omitted: {report.omitted_gallery_count:,}")


def _year_range(first: int | None, last: int | None) -> str:
    if first is None or last is None:
        return "capture years not available"
    if first == last:
        return f"capture year {first}"
    return f"capture years {first}-{last}"


def _add_distribution(lines: list[str], title: str, values: dict[object, int]) -> None:
    if not values:
        lines.append(f"  {title}: not available")
        return
    total = sum(values.values())
    lines.append(f"  {title}")
    for name, count in values.items():
        percent = count / total * 100 if total else 0.0
        lines.append(f"    {name}: {count:,} ({percent:.1f}%)")


def _add_hours(lines: list[str], values: dict[str, dict[int, int]]) -> None:
    if not values:
        lines.append("  Capture hours: not available")
        return
    for basis, hours in values.items():
        formatted = {f"{hour:02d}:00": count for hour, count in hours.items()}
        _add_distribution(
            lines,
            f"Capture hours ({basis}; n={sum(hours.values()):,})",
            formatted,
        )


def _add_segments(lines: list[str], segments: tuple[TimelineSegment, ...]) -> None:
    if not segments:
        lines.append("  No segments available.")
        return
    for segment in segments:
        lines.append(
            f"  {segment.label} [{segment.key}]: {_coverage(segment.capture_coverage)} timestamps"
        )
        if segment.years:
            lines.append(f"    Years: {_counts(segment.years)}")
        if segment.months:
            lines.append(f"    Months: {_counts(segment.months)}")
        for basis, hours in segment.hours_by_time_basis.items():
            formatted = {f"{hour:02d}:00": count for hour, count in hours.items()}
            lines.append(f"    Hours ({basis}): {_counts(formatted)}")


def _counts(values: dict[object, int]) -> str:
    return ", ".join(f"{name}: {count:,}" for name, count in values.items())
