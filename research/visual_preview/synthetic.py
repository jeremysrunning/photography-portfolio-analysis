"""Generate an aggregate-only synthetic benchmark artifact."""

from __future__ import annotations

import argparse
import io
import json
import time
from importlib.metadata import version
from pathlib import Path

import numpy as np
import psutil
from PIL import Image, ImageDraw, ImageFilter

from research.visual_preview.benchmark import (
    BenchmarkConfiguration,
    PeakMemorySampler,
    aggregate_results,
    decode_preview,
)
from research.visual_preview.measurements import compare_measurements, measure_image


def synthetic_aggregate() -> dict[str, object]:
    """Benchmark generated fixtures without emitting per-image records."""
    configuration = BenchmarkConfiguration(sample_size=8)
    records = []
    started = time.perf_counter()
    with PeakMemorySampler(psutil.Process()) as memory:
        for fixture in _fixtures():
            measurements = {}
            sizes = []
            decode_seconds = 0.0
            analysis_seconds = 0.0
            transferred = 0
            for edge in configuration.requested_edges:
                resized = _fit(fixture, edge)
                encoded = _encode(resized)
                transferred += len(encoded)
                decode_started = time.perf_counter()
                decoded = decode_preview(encoded, maximum_edge=configuration.maximum_edge)
                decode_seconds += time.perf_counter() - decode_started
                analysis_started = time.perf_counter()
                measurements[edge] = measure_image(decoded)
                analysis_seconds += time.perf_counter() - analysis_started
                sizes.append(
                    {
                        "requested_edge": edge,
                        "reported_width": resized.width,
                        "reported_height": resized.height,
                        "decoded_width": decoded.width,
                        "decoded_height": decoded.height,
                        "reported_edge": max(resized.size),
                        "decoded_edge": max(decoded.size),
                        "dimension_classification": "matching",
                        "content_type": "image/jpeg",
                        "redirect_count": 0,
                    }
                )
            reference = measurements[max(configuration.requested_edges)]
            records.append(
                {
                    "status": "completed",
                    "download_seconds": 0.0,
                    "decode_seconds": decode_seconds,
                    "analysis_seconds": analysis_seconds,
                    "bytes_transferred": transferred,
                    "sizes": sizes,
                    "comparisons": [
                        {
                            "requested_edge": edge,
                            **compare_measurements(measurements[edge], reference),
                        }
                        for edge in configuration.requested_edges[:-1]
                    ],
                }
            )
    aggregate = aggregate_results(
        records,
        {
            "sample_size": len(records),
            "fixture_families": [
                "solid",
                "gradient",
                "checkerboard",
                "two_color",
                "geometric",
                "low_contrast",
                "blurred",
                "seeded_noise",
            ],
        },
        elapsed_seconds=time.perf_counter() - started,
        peak_rss_bytes=memory.peak_rss,
        configuration=configuration,
    )
    aggregate["artifact_kind"] = "aggregate_non_identifying_synthetic_visual_preview_benchmark"
    aggregate["packages"] = {
        "numpy": version("numpy"),
        "Pillow": version("Pillow"),
        "psutil": version("psutil"),
    }
    aggregate["limitations"] = [
        "Generated fixtures do not represent real portfolio compression or subject matter.",
        "No network timing or redirect behavior is exercised.",
        "Results validate methodology, determinism, and bounded execution only.",
    ]
    return aggregate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/research/VISUAL_PREVIEW_SYNTHETIC_AGGREGATE.json"),
    )
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(synthetic_aggregate(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(args.output)
    return 0


def _fixtures() -> tuple[Image.Image, ...]:
    width, height = 1024, 768
    solid = Image.new("RGB", (width, height), (80, 120, 180))
    gradient_values = np.linspace(0, 255, width, dtype=np.uint8)
    gradient = Image.fromarray(
        np.repeat(gradient_values[None, :, None], height, axis=0).repeat(3, axis=2),
        "RGB",
    )
    checker = Image.fromarray(
        np.uint8(((np.indices((height, width)).sum(axis=0) // 16 % 2) * 255)[..., None]).repeat(
            3, axis=2
        ),
        "RGB",
    )
    two_color = Image.new("RGB", (width, height), (220, 60, 40))
    ImageDraw.Draw(two_color).rectangle(
        (width // 2, 0, width, height),
        fill=(30, 120, 220),
    )
    geometric = Image.new("RGB", (width, height), (230, 230, 225))
    draw = ImageDraw.Draw(geometric)
    draw.ellipse((200, 120, 620, 540), fill=(20, 70, 140))
    draw.rectangle((650, 300, 900, 650), fill=(210, 90, 20))
    low_contrast = Image.new("RGB", (width, height), (120, 122, 124))
    ImageDraw.Draw(low_contrast).rectangle((300, 200, 700, 600), fill=(130, 132, 134))
    blurred = checker.filter(ImageFilter.GaussianBlur(12))
    generator = np.random.default_rng(19)
    noise = Image.fromarray(
        generator.integers(0, 256, size=(height, width, 3), dtype=np.uint8),
        "RGB",
    )
    return (
        solid,
        gradient,
        checker,
        two_color,
        geometric,
        low_contrast,
        blurred,
        noise,
    )


def _fit(image: Image.Image, edge: int) -> Image.Image:
    copy = image.copy()
    copy.thumbnail((edge, edge), Image.Resampling.LANCZOS)
    return copy


def _encode(image: Image.Image) -> bytes:
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=85, optimize=True)
    return output.getvalue()


if __name__ == "__main__":
    raise SystemExit(main())
