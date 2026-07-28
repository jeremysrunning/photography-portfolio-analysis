"""Plain-text rendering for capture timeline measurements."""

from ppa.analysis import Coverage, TimelineReport, TimelineSegment


def render_timeline(report: TimelineReport) -> str:
    """Render a neutral report of recorded capture dates and hours."""
    lines = [
        f"Timeline report: {report.title}",
        "",
        "Evidence",
        f"  Unique photographs: {report.photograph_count:,}",
        f"  Capture timestamp: {_coverage(report.capture_coverage)}",
        f"  Camera model: {_coverage(report.camera_coverage)}",
    ]
    if report.earliest_capture and report.latest_capture:
        lines.extend(
            [
                f"  Earliest recorded capture: {report.earliest_capture.isoformat()}",
                f"  Latest recorded capture: {report.latest_capture.isoformat()}",
            ]
        )
    _add_distribution(lines, "Photographs by capture year", report.years)
    _add_distribution(lines, "Photographs by capture month", report.months)
    _add_hours(lines, report.hours_by_time_basis)
    _add_segments(lines, "Camera segments", report.camera_segments)
    _add_segments(lines, "Gallery segments", report.gallery_segments)
    lines.extend(
        [
            "",
            "Notes",
            "  Dates and hours use the calendar values and timezone offsets stored in metadata.",
            "  UTC timestamps remain UTC; no local timezone is inferred.",
            "  Naive timestamps are labeled timezone unknown and are not combined with UTC hours.",
            "  Counts describe recorded capture metadata, not productivity or intent.",
            "  Missing timestamps are reported as missing and are not inferred.",
        ]
    )
    return "\n".join(lines)


def _coverage(coverage: Coverage) -> str:
    return f"{coverage.available:,} / {coverage.total:,} ({coverage.percent:.1f}%)"


def _add_distribution(lines: list[str], title: str, values: dict[object, int]) -> None:
    if not values:
        return
    total = sum(values.values())
    lines.extend(["", title])
    for name, count in values.items():
        percent = count / total * 100 if total else 0.0
        lines.append(f"  {name}: {count:,} ({percent:.1f}%)")


def _add_hours(lines: list[str], values: dict[str, dict[int, int]]) -> None:
    for basis, hours in values.items():
        formatted = {f"{hour:02d}:00": count for hour, count in hours.items()}
        _add_distribution(
            lines,
            f"Capture hours ({basis}) — n={sum(hours.values()):,}",
            formatted,
        )


def _add_segments(
    lines: list[str],
    title: str,
    segments: tuple[TimelineSegment, ...],
) -> None:
    if not segments:
        return
    lines.extend(["", title])
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
