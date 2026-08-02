"""Plain-text rendering for deterministic portfolio visual habits."""

from ppa.analysis.visual_habits import (
    AnalyzerHabits,
    BooleanSummary,
    ScalarSummary,
    SegmentSection,
    VisualHabitsReport,
)


def render_visual_habits(
    report: VisualHabitsReport,
    *,
    details: bool = False,
    gallery_breakdown: bool = False,
    year_breakdown: bool = False,
    camera_breakdown: bool = False,
    lens_breakdown: bool = False,
    orientation_breakdown: bool = False,
) -> str:
    """Render concise core evidence plus independent optional sections."""
    lines = [f"Visual-habits report: {report.title}", "", "Evidence and Coverage"]
    lines.append(f"  Eligible photographs: {report.eligible_photographs:,}")
    for analyzer in report.analyzers:
        _add_evidence(lines, analyzer)

    _add_composition(lines, report.analyzers[1])
    _add_color(lines, report.analyzers[0], details=details)
    _add_structure(lines, report.analyzers[2])
    _add_year_changes(lines, report)

    if details:
        _add_details(lines, report)
    if gallery_breakdown:
        _add_segments(lines, "Gallery Comparison", report.gallery_segments)
    if year_breakdown:
        _add_segments(lines, "Capture-Year Breakdown", report.year_segments)
    if camera_breakdown:
        _add_segments(lines, "Camera Comparison", report.camera_segments)
    if lens_breakdown:
        _add_segments(lines, "Lens Comparison", report.lens_segments)
    if orientation_breakdown:
        _add_segments(lines, "Orientation Comparison", report.orientation_segments)

    lines.extend(["", "Methods and Limitations"])
    lines.extend(
        [
            "  Distributions use only the exact registered identities shown above.",
            "  Historical analyzer or configuration identities are never combined.",
            "  Current attempt states are separate from retained last-successful snapshots.",
            "  Supersession is not represented by SQLite schema version 6.",
            "  Measurements describe bounded provider-rendered previews, not original files.",
            (
                "  Saliency values describe the configured spectral-residual representation; "
                "they do not identify semantic content or intent."
            ),
            (
                "  Camera and lens differences may reflect subject matter, galleries, capture "
                "conditions, provider rendering, editing, usage patterns, and unequal samples."
            ),
        ]
    )
    for family in report.unavailable_families:
        lines.append(f"  {family.family}: unavailable ({family.reason} Issue #{family.issue}.)")
    lines.append("  Report generation reads persisted data only and performs no image access.")
    return "\n".join(lines)


def _add_evidence(lines: list[str], analyzer: AnalyzerHabits) -> None:
    evidence = analyzer.evidence
    identity = evidence.identity
    successful = evidence.successful_snapshots
    incomplete_coverage = _coverage(evidence.incomplete_expected_snapshots, successful)
    lines.extend(
        [
            f"  {identity.name}",
            f"    Analyzer version: {identity.version}",
            f"    Configuration version: {identity.configuration_version}",
            (
                "    Current states: "
                f"{evidence.completed:,} completed, {evidence.failed:,} failed, "
                f"{evidence.skipped:,} skipped, {evidence.pending:,} pending, "
                f"{evidence.running:,} running"
            ),
            f"    Cancellation-interrupted pending: {evidence.cancellation_interrupted_pending:,}",
            (
                "    Last-successful snapshots: "
                f"{_coverage(evidence.successful_snapshots, evidence.eligible_photographs)}"
            ),
            (
                "    Retained under a non-completed current state: "
                f"{evidence.retained_under_noncompleted_state:,}"
            ),
            (
                "    Complete expected snapshots: "
                f"{_coverage(evidence.complete_expected_snapshots, evidence.successful_snapshots)}"
            ),
            (f"    Incomplete expected snapshots: {incomplete_coverage}"),
            (
                "    Malformed or condition-inconsistent snapshots: "
                f"{_coverage(evidence.malformed_snapshots, evidence.successful_snapshots)}"
            ),
            f"    Historical identities excluded: {len(evidence.historical_identities):,}",
        ]
    )


def _add_composition(lines: list[str], analyzer: AnalyzerHabits) -> None:
    lines.extend(["", "Composition and Saliency"])
    evidence = _boolean(analyzer, "saliency_evidence")
    lines.append(f"  Saliency evidence: {_coverage(evidence.true_count, evidence.count)}")
    if analyzer.point is not None:
        point = analyzer.point
        lines.append(
            f"  Saliency centroid: n={point.count:,}/{point.denominator:,}; "
            f"median x {_number(point.median_x)}, median y {_number(point.median_y)}"
        )
    _add_scalar_lines(lines, analyzer)
    if analyzer.regional_mass is not None:
        grid = analyzer.regional_mass
        lines.append(
            f"  Aggregate 3-by-3 saliency mass (row-major; n={grid.count:,}): "
            + ", ".join(
                f"{name}={value:.8f}" for name, value in zip(grid.order, grid.masses, strict=True)
            )
        )
    if not analyzer.scalars and analyzer.point is None and analyzer.regional_mass is None:
        lines.append("  No complete selected-identity measurement snapshots are available.")


def _add_color(lines: list[str], analyzer: AnalyzerHabits, *, details: bool) -> None:
    lines.extend(["", "Color and Luminance"])
    _add_scalar_lines(lines, analyzer)
    palettes = analyzer.palette_bins if details else analyzer.palette_bins[:5]
    if palettes:
        lines.append("  Quantized dominant-palette recurrence")
        for item in palettes:
            lines.append(
                f"    RGB {item.rgb}: {_coverage(item.photograph_count, item.denominator)}"
            )
    if not analyzer.scalars and not analyzer.palette_bins:
        lines.append("  No complete selected-identity measurement snapshots are available.")


def _add_structure(lines: list[str], analyzer: AnalyzerHabits) -> None:
    lines.extend(["", "Preview Structure"])
    support = _boolean(analyzer, "structure_measurement_support")
    lines.append(f"  Structure measurement support: {_coverage(support.true_count, support.count)}")
    directional = _boolean(analyzer, "gradient_directional_evidence")
    lines.append(f"  Directional evidence: {_coverage(directional.true_count, directional.count)}")
    noise = _boolean(analyzer, "noise_proxy_evidence")
    lines.append(f"  Noise-proxy evidence: {_coverage(noise.true_count, noise.count)}")
    _add_scalar_lines(lines, analyzer)
    if not analyzer.scalars and support.count == 0:
        lines.append("  No complete selected-identity measurement snapshots are available.")


def _add_year_changes(lines: list[str], report: VisualHabitsReport) -> None:
    lines.extend(["", "Changes Over Time"])
    if not report.yearly_differences:
        lines.append("  No adjacent capture-year pairs meet the minimum sample requirement.")
        return
    for item in report.yearly_differences:
        lines.append(
            f"  {item.name}: largest recorded consecutive-year median difference "
            f"{item.from_year} (n={item.from_count:,}) to {item.to_year} "
            f"(n={item.to_count:,}); {_number(item.from_median)} to "
            f"{_number(item.to_median)}; signed difference {_signed(item.difference)} "
            f"{item.unit}"
        )


def _add_details(lines: list[str], report: VisualHabitsReport) -> None:
    lines.extend(["", "Detailed Measurement Evidence"])
    for analyzer in report.analyzers:
        evidence = analyzer.evidence
        lines.append(f"  {evidence.identity.name}")
        for item in evidence.result_availability:
            lines.append(
                f"    {item.name}: {_coverage(item.available, item.denominator)}; "
                f"denominator: {item.denominator_description}; unit: {item.unit}; "
                f"method: {item.method_name}/{item.method_version}"
            )
        lines.append(
            f"    Ignored unexpected catalog entries: {evidence.unexpected_entry_count:,} "
            f"across {evidence.snapshots_with_unexpected_entries:,} snapshots"
        )
        lines.append(
            f"    Persisted expected results used: {evidence.measurement_results:,} "
            f"measurements, {evidence.classification_results:,} classifications"
        )
        for historical in evidence.historical_identities:
            lines.append(
                f"    Excluded identity: {historical.name} / {historical.version} / "
                f"{historical.configuration_version}"
            )


def _add_segments(lines: list[str], title: str, section: SegmentSection) -> None:
    lines.extend(["", title])
    if not section.segments:
        lines.append("  No segments meet the minimum measurement requirements.")
    for segment in section.segments:
        lines.append(f"  {segment.label}: {segment.eligible_photographs:,} eligible photographs")
        for measurement in segment.measurements:
            summary = measurement.summary
            lines.append(
                f"    {measurement.analyzer_name} / {summary.name}: snapshots "
                f"{_coverage(measurement.successful_snapshots, segment.eligible_photographs)}; "
                f"{_summary(summary)}"
            )
    lines.append(f"  Segments omitted for insufficient evidence: {section.omitted_segments:,}")


def _add_scalar_lines(lines: list[str], analyzer: AnalyzerHabits) -> None:
    for summary in analyzer.scalars:
        lines.append(f"  {summary.name}: {_summary(summary)}")


def _summary(summary: ScalarSummary) -> str:
    return (
        f"n={summary.count:,}/{summary.denominator:,} ({summary.percent:.1f}%); "
        f"min {_number(summary.minimum)}, median {_number(summary.median)}, "
        f"max {_number(summary.maximum)} {summary.unit}"
    )


def _availability(analyzer: AnalyzerHabits, name: str):
    return next(item for item in analyzer.evidence.result_availability if item.name == name)


def _boolean(analyzer: AnalyzerHabits, name: str):
    return next(
        (item for item in analyzer.booleans if item.name == name),
        BooleanSummary(name, 0, 0),
    )


def _coverage(available: int, total: int) -> str:
    return f"{available:,} / {total:,} ({_percent(available, total)})"


def _percent(available: int, total: int) -> str:
    return f"{available / total * 100 if total else 0.0:.1f}%"


def _number(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".") or "0"


def _signed(value: float) -> str:
    return ("+" if value >= 0 else "") + _number(value)
