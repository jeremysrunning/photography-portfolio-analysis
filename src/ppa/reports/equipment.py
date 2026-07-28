"""Plain-text rendering for equipment metadata measurements."""

from ppa.analysis import Coverage, EquipmentReport


def render_equipment(report: EquipmentReport) -> str:
    """Render a neutral equipment and exposure report."""
    lines = [
        f"Equipment report: {report.title}",
        "",
        "Evidence",
        f"  Unique photographs: {report.photograph_count:,}",
        f"  Camera model: {_coverage(report.camera_coverage)}",
        f"  Lens model: {_coverage(report.lens_coverage)}",
        f"  Focal length: {_coverage(report.focal_length_coverage)}",
        f"  Aperture: {_coverage(report.aperture_coverage)}",
        f"  Exposure time: {_coverage(report.exposure_coverage)}",
        f"  ISO: {_coverage(report.iso_coverage)}",
    ]
    _add_distribution(lines, "Camera models (top 10)", report.cameras, report.camera_coverage)
    _add_distribution(lines, "Lens models (top 10)", report.lenses, report.lens_coverage)
    _add_distribution(
        lines,
        "Focal-length ranges",
        report.focal_length_ranges,
        report.focal_length_coverage,
    )
    _add_distribution(
        lines,
        "Exact focal lengths (top 10)",
        report.focal_lengths,
        report.focal_length_coverage,
    )
    _add_distribution(lines, "Apertures (top 10)", report.apertures, report.aperture_coverage)
    _add_distribution(
        lines,
        "Exposure times (top 10)",
        report.exposures,
        report.exposure_coverage,
    )
    _add_distribution(lines, "ISO ranges", report.iso_ranges, report.iso_coverage)
    _add_distribution(lines, "Exact ISO values (top 10)", report.iso_values, report.iso_coverage)

    if report.yearly_cameras:
        lines.extend(["", "Most frequently recorded camera by capture year"])
        for item in report.yearly_cameras:
            lines.append(
                f"  {item.year}: {item.camera} — {item.count:,} / "
                f"{item.total_with_camera:,} ({item.percent:.1f}%)"
            )
    lines.extend(
        [
            "",
            "Notes",
            "  Counts describe photographs with available EXIF metadata.",
            "  Missing EXIF is reported as missing and is not inferred.",
            "  Frequency describes use within this portfolio, not equipment quality.",
        ]
    )
    return "\n".join(lines)


def _coverage(coverage: Coverage) -> str:
    return f"{coverage.available:,} / {coverage.total:,} ({coverage.percent:.1f}%)"


def _add_distribution(
    lines: list[str],
    title: str,
    values: dict[str, int],
    coverage: Coverage,
) -> None:
    if not values:
        return
    lines.extend(["", title])
    for name, count in values.items():
        percent = count / coverage.available * 100 if coverage.available else 0.0
        lines.append(f"  {name}: {count:,} ({percent:.1f}%)")
