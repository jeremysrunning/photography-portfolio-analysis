"""Plain-text rendering for recorded orientation and aspect ratios."""

from ppa.analysis.orientation import OrientationReport, OrientationSegment


def render_orientation(
    report: OrientationReport,
    *,
    details: bool = False,
    all_aspect_ratios: bool = False,
    year_breakdown: bool = False,
    gallery_breakdown: bool = False,
    camera_breakdown: bool = False,
) -> str:
    """Render one bounded, neutral recorded-dimensions report."""
    lines = [
        f"Orientation and aspect-ratio report: {report.title}",
        "",
        "Recorded dimension evidence",
        f"  Unique photographs: {report.photograph_count:,}",
        f"  Width: {_coverage(report.width_coverage)}",
        f"  Height: {_coverage(report.height_coverage)}",
        f"  Complete pairs: {_coverage(report.pair_coverage)}",
    ]
    if details:
        lines.extend(
            [
                f"  Width only: {report.width_only:,}",
                f"  Height only: {report.height_only:,}",
                f"  Neither dimension: {report.dimensions_missing:,}",
            ]
        )
    lines.extend(["", "Recorded orientation"])
    if report.pair_coverage.total == 0 or report.pair_coverage.available == 0:
        lines.append("  unavailable (no photographs with complete recorded dimensions)")
    else:
        for label, count in (
            ("Landscape", report.landscape),
            ("Portrait", report.portrait),
            ("Square", report.square),
        ):
            lines.append(
                f"  {label}: {count:,} ({count / report.pair_coverage.available * 100:.1f}%)"
            )
    lines.extend(["", f"Exact aspect ratios ({len(report.aspect_ratios):,} distinct)"])
    limit = len(report.aspect_ratios) if all_aspect_ratios else 50 if details else 10
    if not report.aspect_ratios:
        lines.append("  unavailable (no photographs with complete recorded dimensions)")
    else:
        for item in report.aspect_ratios[:limit]:
            lines.append(
                f"  {item.ratio}: {item.count:,} "
                f"({item.count / report.pair_coverage.available * 100:.1f}%)"
            )
        if len(report.aspect_ratios) > limit:
            lines.append(f"  {len(report.aspect_ratios) - limit:,} additional ratios not shown")

    for enabled, heading, segments, default_limit in (
        (year_breakdown, "Capture-year breakdown", report.year_segments, None),
        (gallery_breakdown, "Gallery breakdown", report.gallery_segments, 10),
        (camera_breakdown, "Camera breakdown", report.camera_segments, 5),
    ):
        if enabled:
            qualifying = [segment for segment in segments if segment.qualifies_for_default]
            if default_limit is not None:
                qualifying.sort(
                    key=lambda segment: (
                        -segment.coverage.available,
                        segment.label.casefold(),
                        segment.key,
                    )
                )
            lines.extend(["", heading])
            if not qualifying:
                lines.append("  unavailable (no segments meet the evidence threshold)")
            for segment in qualifying:
                lines.extend(_segment(segment))

    lines.extend(
        [
            "",
            "Methods and limitations",
            "  Orientation is derived from source-reported original pixel dimensions.",
            "  Exact reduced ratios remain directional; nearby crop ratios are not combined.",
            "  Provider handling of EXIF rotation is not independently verified.",
            "  These measurements do not describe quality, intent, or recommended cropping.",
        ]
    )
    return "\n".join(lines)


def _coverage(coverage) -> str:
    if coverage.total == 0:
        return "unavailable (no photographs)"
    return f"{coverage.available:,} / {coverage.total:,} ({coverage.percent:.1f}%)"


def _segment(segment: OrientationSegment) -> list[str]:
    ratios = ", ".join(f"{item.ratio} ({item.count:,})" for item in segment.aspect_ratios[:3])
    return [
        f"  {segment.label}: {segment.coverage.available:,} / "
        f"{segment.photograph_count:,} ({segment.coverage.percent:.1f}% coverage)",
        f"    Landscape / portrait / square: {segment.landscape:,} / "
        f"{segment.portrait:,} / {segment.square:,}",
        f"    Most frequent ratios: {ratios or 'unavailable'}",
    ]
