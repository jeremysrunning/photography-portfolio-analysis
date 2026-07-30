"""Bounded real-portfolio benchmark orchestration."""

from __future__ import annotations

import io
import json
import threading
import time
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import median
from typing import Any

import psutil
from PIL import Image, ImageOps, UnidentifiedImageError

from ppa.models import Portfolio
from ppa.sources import SourceError, SourcePreviewUnavailableError
from research.visual_preview.measurements import (
    STABILITY_THRESHOLDS,
    compare_measurements,
    measure_image,
)
from research.visual_preview.sampling import sample_summary, select_sample
from research.visual_preview.smugmug_sizes import ExperimentalSmugMugSizeResolver

TARGET_EDGES = (256, 512, 768, 1024)


@dataclass(frozen=True, slots=True)
class BenchmarkConfiguration:
    """Versioned bounded experiment settings."""

    sample_size: int = 48
    seed: str = "issue-19-v1"
    requested_edges: tuple[int, ...] = TARGET_EDGES
    maximum_edge: int = 1280
    maximum_bytes: int = 8_000_000
    algorithm_version: str = "issue-19-research-v1"


def run_benchmark(
    portfolio: Portfolio,
    site_url: str,
    api_key: str,
    output: Path,
    *,
    configuration: BenchmarkConfiguration | None = None,
) -> dict[str, Any]:
    """Run the local-only raw benchmark and return non-identifying aggregates."""
    configuration = configuration or BenchmarkConfiguration()
    sample = select_sample(
        portfolio,
        configuration.sample_size,
        seed=configuration.seed,
    )
    process = psutil.Process()
    started = time.perf_counter()
    raw_records: list[dict[str, Any]] = []
    with PeakMemorySampler(process) as memory:
        for index, record in enumerate(sample):
            raw_records.append(
                _benchmark_asset(
                    index,
                    record.asset.source_id,
                    site_url,
                    api_key,
                    configuration,
                )
            )
    elapsed = time.perf_counter() - started
    raw_document = {
        "warning": "LOCAL RAW RESEARCH DATA - DO NOT COMMIT",
        "configuration": asdict(configuration),
        "sample_summary": sample_summary(sample),
        "manual_rubric": _manual_rubric_template(len(sample)),
        "records": raw_records,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(raw_document, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return aggregate_results(
        raw_records,
        sample_summary(sample),
        elapsed_seconds=elapsed,
        peak_rss_bytes=memory.peak_rss,
        configuration=configuration,
    )


def aggregate_results(
    records: list[dict[str, Any]],
    selected_sample: dict[str, object],
    *,
    elapsed_seconds: float,
    peak_rss_bytes: int,
    configuration: BenchmarkConfiguration,
) -> dict[str, Any]:
    """Aggregate local records without retaining linkable per-image values."""
    successful = [record for record in records if record["status"] == "completed"]
    stage_names = ("download_seconds", "decode_seconds", "analysis_seconds")
    timing = {
        stage: _distribution([float(record[stage]) for record in successful])
        for stage in stage_names
    }
    transferred = [int(record["bytes_transferred"]) for record in successful]
    requested_edges: dict[str, dict[str, Any]] = {}
    for edge in configuration.requested_edges[:-1]:
        comparison_rows = [
            comparison
            for record in successful
            for comparison in record["comparisons"]
            if comparison["requested_edge"] == edge
        ]
        stable_fields = sorted(
            {
                key.removesuffix("_stable")
                for row in comparison_rows
                for key in row
                if key.endswith("_stable")
            }
        )
        requested_edges[str(edge)] = {
            "comparison_count": len(comparison_rows),
            "stable_rates": {
                field: (
                    sum(bool(row[f"{field}_stable"]) for row in comparison_rows)
                    / len(comparison_rows)
                    if comparison_rows
                    else None
                )
                for field in stable_fields
            },
        }
    total_analysis_seconds = sum(
        float(record["decode_seconds"]) + float(record["analysis_seconds"]) for record in successful
    )
    total_download_seconds = sum(float(record["download_seconds"]) for record in successful)
    return {
        "artifact_kind": "aggregate_non_identifying_visual_preview_benchmark",
        "algorithm_version": configuration.algorithm_version,
        "configuration": {
            "sample_size": configuration.sample_size,
            "seed": configuration.seed,
            "requested_edges": list(configuration.requested_edges),
            "maximum_edge": configuration.maximum_edge,
            "maximum_bytes": configuration.maximum_bytes,
        },
        "predeclared_stability_thresholds": STABILITY_THRESHOLDS,
        "selected_sample": selected_sample,
        "outcomes": {
            "completed": len(successful),
            "unavailable_or_invalid": len(records) - len(successful),
        },
        "actual_preview_edges": _counts(
            int(size["actual_edge"]) for record in successful for size in record["sizes"]
        ),
        "bytes_transferred": _distribution(transferred),
        "timing_seconds": timing,
        "total_elapsed_seconds": elapsed_seconds,
        "peak_rss_bytes": peak_rss_bytes,
        "cleanup": {
            "temporary_files_created": 0,
            "temporary_files_remaining": 0,
            "all_preview_bytes_released_after_each_asset": True,
        },
        "full_portfolio_estimate_30000": {
            "network_seconds_one_worker": (
                total_download_seconds / len(successful) * 30_000 if successful else None
            ),
            "cpu_seconds_one_worker": (
                total_analysis_seconds / len(successful) * 30_000 if successful else None
            ),
            "warning": "Bounded sample extrapolation; not a production-runtime guarantee.",
        },
        "stability_by_requested_edge": requested_edges,
    }


def decode_preview(
    content: bytes,
    *,
    maximum_edge: int,
) -> Image.Image:
    """Decode one bounded preview and detach it from its byte stream."""
    try:
        with Image.open(io.BytesIO(content)) as opened:
            if opened.width < 1 or opened.height < 1:
                raise SourcePreviewUnavailableError("Preview dimensions were invalid.")
            if max(opened.size) > maximum_edge:
                raise SourcePreviewUnavailableError(
                    "Decoded preview exceeded the experimental dimension limit."
                )
            return ImageOps.exif_transpose(opened).convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise SourcePreviewUnavailableError(
            "Preview could not be decoded as a supported image."
        ) from error


class PeakMemorySampler(AbstractContextManager["PeakMemorySampler"]):
    """Poll process RSS while a bounded benchmark runs."""

    def __init__(self, process: psutil.Process, interval: float = 0.005) -> None:
        self.process = process
        self.interval = interval
        self.peak_rss = process.memory_info().rss
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> PeakMemorySampler:
        self._thread = threading.Thread(target=self._sample, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)
        self.peak_rss = max(self.peak_rss, self.process.memory_info().rss)

    def _sample(self) -> None:
        while not self._stop.wait(self.interval):
            self.peak_rss = max(self.peak_rss, self.process.memory_info().rss)


def _benchmark_asset(
    index: int,
    asset_source_id: str,
    site_url: str,
    api_key: str,
    configuration: BenchmarkConfiguration,
) -> dict[str, Any]:
    resolver = ExperimentalSmugMugSizeResolver(
        site_url,
        api_key,
        maximum_edge=configuration.maximum_edge,
        maximum_bytes=configuration.maximum_bytes,
    )
    measurements: dict[int, Any] = {}
    sizes: list[dict[str, Any]] = []
    download_seconds = 0.0
    decode_seconds = 0.0
    analysis_seconds = 0.0
    bytes_transferred = 0
    try:
        candidates = {
            edge: resolver.resolve(asset_source_id, edge) for edge in configuration.requested_edges
        }
        payloads = {}
        for edge, candidate in candidates.items():
            key = (candidate.width, candidate.height, candidate.content_url)
            if key not in payloads:
                started = time.perf_counter()
                payloads[key] = resolver.fetch(candidate)
                download_seconds += time.perf_counter() - started
                bytes_transferred += payloads[key].bytes_transferred
            payload = payloads[key]
            started = time.perf_counter()
            image = decode_preview(payload.content, maximum_edge=configuration.maximum_edge)
            decode_seconds += time.perf_counter() - started
            actual_edge = max(image.size)
            if actual_edge > configuration.maximum_edge:
                raise SourcePreviewUnavailableError(
                    "Decoded preview exceeded the experimental maximum."
                )
            started = time.perf_counter()
            measurements[edge] = measure_image(image)
            analysis_seconds += time.perf_counter() - started
            sizes.append(
                {
                    "requested_edge": edge,
                    "reported_edge": candidate.longest_edge,
                    "actual_edge": actual_edge,
                    "content_type": payload.content_type,
                    "redirect_count": payload.redirect_count,
                }
            )
        reference_edge = max(configuration.requested_edges)
        reference = measurements[reference_edge]
        comparisons = [
            {
                "requested_edge": edge,
                **compare_measurements(measurements[edge], reference),
            }
            for edge in configuration.requested_edges
            if edge != reference_edge
        ]
        return {
            "sample_index": index,
            "status": "completed",
            "download_seconds": download_seconds,
            "decode_seconds": decode_seconds,
            "analysis_seconds": analysis_seconds,
            "bytes_transferred": bytes_transferred,
            "sizes": sizes,
            "measurements": {
                str(edge): result.serializable() for edge, result in measurements.items()
            },
            "comparisons": comparisons,
        }
    except (SourcePreviewUnavailableError, SourceError) as error:
        return {
            "sample_index": index,
            "status": "unavailable_or_invalid",
            "error_category": type(error).__name__,
            "download_seconds": download_seconds,
            "decode_seconds": decode_seconds,
            "analysis_seconds": analysis_seconds,
            "bytes_transferred": bytes_transferred,
            "sizes": sizes,
            "measurements": {},
            "comparisons": [],
        }


def _manual_rubric_template(sample_size: int) -> dict[str, Any]:
    return {
        "instruction": (
            "Complete locally after decoding. Do not commit per-image annotations. "
            "Aggregate category counts before publication."
        ),
        "maximum_edge_case_additions": 12,
        "categories": [
            "people_none_one_multiple",
            "small_or_occluded_subject",
            "indoor_outdoor",
            "daylight_low_light",
            "stage_or_performance",
            "studio_like",
            "natural_urban_architectural",
            "bright_dark",
            "high_low_contrast",
            "saturated_muted",
            "simple_complex_background",
        ],
        "rows": [{"sample_index": index, "annotations": {}} for index in range(sample_size)],
    }


def _distribution(values: list[int | float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "minimum": None, "median": None, "maximum": None}
    return {
        "count": len(values),
        "minimum": min(values),
        "median": median(values),
        "maximum": max(values),
    }


def _counts(values) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value)
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: int(item[0])))
