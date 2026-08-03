"""Plain-text rendering for baseline portfolio measurements."""

from ppa.analysis import BaselineReport, Coverage


def render_baseline(report: BaselineReport) -> str:
    """Render a neutral, human-readable baseline report."""
    lines = [
        f"Baseline report: {report.title}",
        "",
        "Dataset",
        f"  Galleries: {report.gallery_count:,}",
        f"  Media references: {report.media_references:,}",
        f"  Unique media: {report.unique_media:,}",
        f"  Unique photographs: {report.unique_photographs:,}",
        f"  Non-photo media excluded: {report.excluded_non_photographs:,}",
        f"  Additional gallery placements: {report.duplicate_references:,}",
        (
            "  Gallery size (min / median / max): "
            f"{report.gallery_size_min:,} / {report.gallery_size_median:,.1f} / "
            f"{report.gallery_size_max:,}"
        ),
        "",
        "Metadata coverage",
        f"  Capture date: {_coverage(report.capture_date_coverage)}",
        f"  Dimensions: {_coverage(report.dimension_coverage)}",
        f"  File format: {_coverage(report.format_coverage)}",
        f"  Geolocation: {_coverage(report.geolocation_coverage)}",
        f"  Camera model: {_coverage(report.camera_coverage)}",
        f"  Lens model: {_coverage(report.lens_coverage)}",
        f"  Focal length: {_coverage(report.focal_length_coverage)}",
        f"  35 mm equivalent: {_coverage(report.focal_length_35mm_coverage)}",
        f"  Aperture: {_coverage(report.aperture_coverage)}",
        f"  Exposure time: {_coverage(report.exposure_time_coverage)}",
        f"  ISO: {_coverage(report.iso_coverage)}",
        (f"  Exposure compensation: {_coverage(report.exposure_compensation_coverage)}"),
        f"  Flash evidence: {_coverage(report.flash_evidence_coverage)}",
        f"    Fired: {report.flash_fired:,}",
        f"    Did not fire: {report.flash_not_fired:,}",
        f"    Missing or ambiguous: {report.flash_missing_or_ambiguous:,}",
    ]
    if report.earliest_capture and report.latest_capture:
        lines.extend(
            [
                "",
                "Capture range",
                f"  Earliest: {report.earliest_capture.isoformat()}",
                f"  Latest: {report.latest_capture.isoformat()}",
            ]
        )
    if report.orientations:
        lines.extend(["", "Orientation (among photographs with dimensions)"])
        lines.extend(_distribution(report.orientations, report.dimension_coverage.available))
    if report.formats:
        lines.extend(["", "File formats (among photographs with format metadata)"])
        lines.extend(_distribution(report.formats, report.format_coverage.available))
    if report.cameras:
        lines.extend(["", "Camera models (top 10)"])
        lines.extend(
            _distribution(dict(list(report.cameras.items())[:10]), report.camera_coverage.available)
        )
    if report.lenses:
        lines.extend(["", "Lens models (top 10)"])
        lines.extend(
            _distribution(dict(list(report.lenses.items())[:10]), report.lens_coverage.available)
        )
    lines.extend(
        [
            "",
            "Notes",
            "  Percentages describe available metadata, not photographic quality.",
            "  Missing metadata is reported as missing and is not interpreted as behavior.",
        ]
    )
    return "\n".join(lines)


def _coverage(coverage: Coverage) -> str:
    return f"{coverage.available:,} / {coverage.total:,} ({coverage.percent:.1f}%)"


def _distribution(values: dict[str, int], total: int) -> list[str]:
    return [
        f"  {name}: {count:,} ({count / total * 100 if total else 0:.1f}%)"
        for name, count in values.items()
    ]
