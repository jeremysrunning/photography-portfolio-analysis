"""Plain-text rendering for focal-length habits measurements."""

from ppa.analysis.focal_length import (
    MIN_GALLERY_COVERAGE,
    MIN_SEGMENT_SAMPLE,
    FocalLengthBasis,
    FocalLengthReport,
    FocalLengthSegment,
    FocalLengthSummary,
)


def render_focal_lengths(
    report: FocalLengthReport,
    *,
    details: bool = False,
    camera_breakdown: bool = False,
    lens_breakdown: bool = False,
    gallery_breakdown: bool = False,
    year_breakdown: bool = False,
) -> str:
    """Render a concise report with independent optional detail sections."""
    lines = [f"Focal-length report: {report.title}", "", "Evidence"]
    lines.extend(
        [
            f"  Unique photographs: {report.photograph_count:,}",
            f"  Native focal length: {_coverage(report.native_coverage)}",
            f"  35 mm equivalent: {_coverage(report.equivalent_coverage)}",
            f"  Selected primary basis: {_basis(report.primary_basis)}",
            f"  Primary sample size: {report.primary_coverage.available:,}",
            f"  Excluded from primary distribution: {report.primary_excluded:,}",
            "",
            "Focal-Length Summary",
        ]
    )
    _add_summary(lines, report.primary_summary, indent="  ")

    lines.extend(["", "Key Measurements"])
    _add_key_measurements(lines, report.primary_summary)

    lines.extend(["", "Range Distribution"])
    _add_ranges(lines, report.primary_summary, indent="  ")

    lines.extend(["", f"Recorded Use by Camera ({_basis(report.primary_basis)})"])
    _add_default_segments(lines, report.camera_segments, 5)
    lines.extend(["", "Recorded Use by Lens (native focal length)"])
    _add_default_segments(lines, report.lens_segments, 5)
    lines.extend(["", f"Top Galleries ({_basis(report.primary_basis)})"])
    _add_default_segments(lines, report.gallery_segments, 10)
    lines.extend(["", f"Recorded Use by Year ({_basis(report.primary_basis)})"])
    _add_year_summary(lines, report)

    if details:
        lines.extend(["", "Detailed Primary Distribution"])
        _add_grouped_values(lines, report.primary_summary)
        _add_ranges(lines, report.primary_summary, indent="  ")
    if camera_breakdown:
        lines.extend(["", "Camera Breakdown"])
        _add_segments(lines, report.camera_segments)
    if lens_breakdown:
        lines.extend(["", "Lens Breakdown (native focal length)"])
        _add_segments(lines, report.lens_segments)
    if gallery_breakdown:
        lines.extend(["", "Gallery Breakdown"])
        _add_segments(lines, report.gallery_segments)
    if year_breakdown:
        lines.extend(["", "Year Breakdown"])
        _add_segments(lines, report.year_segments)

    lines.extend(
        [
            "",
            "Notes",
            "  Every distribution uses one explicitly labeled focal-length basis.",
            (
                "  The primary basis is the field with greater usable coverage; "
                "coverage ties prefer 35 mm equivalent."
            ),
            (
                "  Medians, limits, and ranges use unrounded typed measurements; "
                "repeated values are grouped to the nearest whole millimeter, half up."
            ),
            ("  Named photographic ranges are used only for 35 mm-equivalent measurements."),
            (
                f"  Default segment summaries require at least {MIN_SEGMENT_SAMPLE} "
                "measured photographs."
            ),
            (
                f"  Default galleries also require at least "
                f"{MIN_GALLERY_COVERAGE * 100:.0f}% focal-length coverage."
            ),
            "  Missing focal lengths are reported as missing and are not inferred.",
            "  Counts describe recorded metadata, not intent, quality, or equipment value.",
        ]
    )
    return "\n".join(lines)


def _coverage(coverage) -> str:
    return f"{coverage.available:,} / {coverage.total:,} ({coverage.percent:.1f}%)"


def _basis(basis: FocalLengthBasis | None) -> str:
    return basis.value if basis is not None else "not available"


def _measurement(value: float | None) -> str:
    return f"{value:g} mm" if value is not None else "not available"


def _modes(values: tuple[int, ...]) -> str:
    return ", ".join(f"{value} mm" for value in values) if values else "not available"


def _add_summary(
    lines: list[str],
    summary: FocalLengthSummary | None,
    *,
    indent: str,
) -> None:
    if summary is None:
        lines.append(f"{indent}No usable focal-length metadata.")
        return
    lines.extend(
        [
            f"{indent}Basis: {summary.basis.value}",
            f"{indent}Measured photographs: {summary.sample_size:,}",
            f"{indent}Median recorded focal length: {_measurement(summary.median_mm)}",
            f"{indent}Most frequently recorded focal length: {_modes(summary.modes_mm)}",
        ]
    )


def _add_key_measurements(
    lines: list[str],
    summary: FocalLengthSummary | None,
) -> None:
    if summary is None:
        lines.append("  No measurements available.")
        return
    lines.extend(
        [
            f"  Minimum recorded focal length: {_measurement(summary.minimum_mm)}",
            f"  Maximum recorded focal length: {_measurement(summary.maximum_mm)}",
            (
                "  Most common recorded focal-length range: "
                + (", ".join(summary.most_common_ranges) or "not available")
            ),
            f"  Represented measurements: {summary.sample_size:,}",
            f"  Distinct whole-millimeter groups: {summary.distinct_grouped_values:,}",
        ]
    )


def _add_ranges(
    lines: list[str],
    summary: FocalLengthSummary | None,
    *,
    indent: str,
) -> None:
    if summary is None or not summary.ranges:
        lines.append(f"{indent}No range measurements available.")
        return
    for label, count in summary.ranges.items():
        percent = count / summary.sample_size * 100 if summary.sample_size else 0.0
        lines.append(f"{indent}{label}: {count:,} ({percent:.1f}%)")


def _ordered_default_segments(
    segments: tuple[FocalLengthSegment, ...],
) -> list[FocalLengthSegment]:
    return sorted(
        (segment for segment in segments if segment.qualifies_for_default),
        key=lambda segment: (
            -segment.summary.sample_size,
            segment.label.casefold(),
            segment.key,
        ),
    )


def _add_default_segments(
    lines: list[str],
    segments: tuple[FocalLengthSegment, ...],
    limit: int,
) -> None:
    selected = _ordered_default_segments(segments)[:limit]
    if not selected:
        lines.append("  No segments meet the default sample threshold.")
        return
    for segment in selected:
        _add_segment(lines, segment)
    omitted = max(0, len(segments) - len(selected))
    if omitted:
        lines.append(f"  Additional segments omitted: {omitted:,}")


def _add_segment(lines: list[str], segment: FocalLengthSegment) -> None:
    common_range = (
        ", ".join(_short_range(label) for label in segment.summary.most_common_ranges)
        or "not available"
    )
    identity = segment.label if segment.key == segment.label else f"{segment.label} [{segment.key}]"
    lines.append(
        f"  {identity}: n={segment.coverage.available:,}/{segment.coverage.total:,} "
        f"({segment.coverage.percent:.1f}%); median {_measurement(segment.summary.median_mm)}; "
        f"mode {_modes(segment.summary.modes_mm)}; {common_range}"
    )


def _short_range(label: str) -> str:
    return label.split(" (", 1)[0] if " (" in label else label.replace(" (native)", "")


def _add_segments(
    lines: list[str],
    segments: tuple[FocalLengthSegment, ...],
) -> None:
    if not segments:
        lines.append("  No segments available.")
        return
    for segment in segments:
        _add_segment(lines, segment)


def _add_year_summary(lines: list[str], report: FocalLengthReport) -> None:
    represented = [segment for segment in report.year_segments if segment.summary.sample_size > 0]
    if not represented:
        lines.append("  No capture years with focal-length metadata.")
        return
    first = represented[0]
    last = represented[-1]
    _add_segment(lines, first)
    if last.key != first.key:
        _add_segment(lines, last)
    change = report.largest_yearly_median_change
    if change is None:
        lines.append(
            f"  Largest consecutive-year median change: not available "
            f"(requires {MIN_SEGMENT_SAMPLE} measurements in both years)"
        )
    else:
        lines.append(
            "  Largest consecutive-year median change: "
            f"{change.from_year} to {change.to_year}; "
            f"{_measurement(change.from_median_mm)} to "
            f"{_measurement(change.to_median_mm)} "
            f"({change.change_mm:+g} mm)"
        )


def _add_grouped_values(
    lines: list[str],
    summary: FocalLengthSummary | None,
) -> None:
    if summary is None or not summary.grouped_values:
        lines.append("  No grouped focal-length values available.")
        return
    for value, count in summary.grouped_values.items():
        percent = count / summary.sample_size * 100 if summary.sample_size else 0.0
        lines.append(f"  {value} mm: {count:,} ({percent:.1f}%)")
