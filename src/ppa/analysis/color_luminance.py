"""Deterministic rendered-preview color and luminance measurements."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import permutations
from math import hypot, isfinite, sqrt
from typing import Any

import numpy as np
from PIL import Image

from ppa.models import Asset
from ppa.sources import PreviewMetadata, PreviewRequest, PreviewStorageMode
from ppa.visual import AnalyzerIdentity, VisualResult, VisualResultKind

ANALYZER_IDENTITY = AnalyzerIdentity(
    "color-luminance",
    "1.0.0",
    "rendered-srgb-768-v1",
)
PREVIEW_REQUEST = PreviewRequest(
    maximum_edge=768,
    storage_mode=PreviewStorageMode.MEMORY,
)
SHADOW_ENCODED_THRESHOLD = 5 / 255
HIGHLIGHT_ENCODED_THRESHOLD = 250 / 255
ROUNDING_DIGITS = 12
PALETTE_SIZE = 5


@dataclass(frozen=True, slots=True)
class PaletteColor:
    """One color in the deterministic quantized palette."""

    rgb: tuple[int, int, int]
    proportion: float


@dataclass(frozen=True, slots=True)
class PaletteComparison:
    """Aggregate palette stability measurements used by tests and research."""

    color_distance: float
    proportion_l1: float
    assignments: tuple[tuple[int | None, int | None], ...]


class ColorLuminanceAnalyzer:
    """Measure rendered-preview color and linear-sRGB relative luminance."""

    identity = ANALYZER_IDENTITY
    preview_request = PREVIEW_REQUEST
    allows_empty_results = False

    def analyze(
        self,
        asset: Asset,
        image: Image.Image,
        metadata: PreviewMetadata,
    ) -> tuple[VisualResult, ...]:
        """Return the complete deterministic result catalog for one preview."""
        del asset, metadata
        rgb = _normalized_srgb(image)
        encoded = rgb.astype(np.float64) / 255.0
        linear = np.where(
            encoded <= 0.04045,
            encoded / 12.92,
            ((encoded + 0.055) / 1.055) ** 2.4,
        )
        luminance = linear[..., 0] * 0.2126 + linear[..., 1] * 0.7152 + linear[..., 2] * 0.0722
        maximum = encoded.max(axis=2)
        minimum = encoded.min(axis=2)
        saturation = np.divide(
            maximum - minimum,
            maximum,
            out=np.zeros_like(maximum),
            where=maximum > 0,
        )
        red_green = encoded[..., 0] - encoded[..., 1]
        yellow_blue = (encoded[..., 0] + encoded[..., 1]) / 2 - encoded[..., 2]
        colorfulness = hypot(
            float(np.std(red_green)),
            float(np.std(yellow_blue)),
        ) + 0.3 * hypot(
            float(np.mean(red_green)),
            float(np.mean(yellow_blue)),
        )
        shadow_threshold = _linearize(SHADOW_ENCODED_THRESHOLD)
        highlight_threshold = _linearize(HIGHLIGHT_ENCODED_THRESHOLD)
        palette, coverage = _palette(encoded)
        values: tuple[tuple[str, Any, str, str], ...] = (
            (
                "luminance_mean",
                _rounded(np.mean(luminance)),
                "relative_linear_luminance",
                "srgb-relative-luminance",
            ),
            (
                "luminance_median",
                _rounded(np.median(luminance)),
                "relative_linear_luminance",
                "srgb-relative-luminance",
            ),
            (
                "shadow_luminance_tail_proportion",
                _rounded(np.mean(luminance <= shadow_threshold)),
                "proportion",
                "relative-luminance-tail",
            ),
            (
                "highlight_luminance_tail_proportion",
                _rounded(np.mean(luminance >= highlight_threshold)),
                "proportion",
                "relative-luminance-tail",
            ),
            (
                "saturation_mean",
                _rounded(np.mean(saturation)),
                "proportion",
                "srgb-hsv-saturation",
            ),
            (
                "saturation_median",
                _rounded(np.median(saturation)),
                "proportion",
                "srgb-hsv-saturation",
            ),
            (
                "colorfulness",
                _rounded(colorfulness),
                "normalized_srgb_formula_output",
                "hasler-susstrunk-colorfulness",
            ),
            (
                "dominant_palette",
                {
                    "color_space": "srgb",
                    "quantization": "4bit_per_channel",
                    "colors": [
                        {"rgb": list(entry.rgb), "proportion": entry.proportion}
                        for entry in palette
                    ],
                    "covered_pixel_proportion": coverage,
                },
                "encoded_srgb",
                "srgb-histogram-palette",
            ),
            (
                "palette_entropy",
                _rounded(_palette_entropy(encoded)),
                "normalized_entropy",
                "srgb-histogram-entropy",
            ),
        )
        if any(
            isinstance(value, float) and (not isfinite(value) or value < 0)
            for _, value, _, _ in values
        ):
            raise ValueError("color-luminance analysis produced an invalid numeric result")
        return tuple(
            VisualResult(
                name=name,
                kind=VisualResultKind.MEASUREMENT,
                value=value,
                method_name=method,
                method_version="1",
                unit=unit,
            )
            for name, value, unit, method in values
        )


def compare_palettes(
    first: tuple[PaletteColor, ...],
    second: tuple[PaletteColor, ...],
) -> PaletteComparison:
    """Compare palettes through deterministic exhaustive minimum-cost assignment.

    Assignment cost uses normalized Euclidean encoded-sRGB distance only. Proportions
    do not affect assignment. Missing colors have distance one. Equal-cost assignments
    use lexicographic index order. The reported color distance is weighted by the mean
    assigned mass; proportion L1 is halved to remain in the unit interval.
    """
    if not first and not second:
        return PaletteComparison(0.0, 0.0, ())
    size = max(len(first), len(second))
    left = (*range(len(first)), *((None,) * (size - len(first))))
    right_values = (*range(len(second)), *((None,) * (size - len(second))))
    best: tuple[float, tuple[int, ...], tuple[int | None, ...]] | None = None
    for order in permutations(range(size)):
        right = tuple(right_values[index] for index in order)
        cost = sum(
            _assignment_distance(first, second, a, b) for a, b in zip(left, right, strict=True)
        )
        candidate = (cost, order, right)
        if best is None or candidate[:2] < best[:2]:
            best = candidate
    assert best is not None
    assignments = tuple(zip(left, best[2], strict=True))
    weighted_distance = 0.0
    proportion_difference = 0.0
    mass = 0.0
    for left_index, right_index in assignments:
        left_share = first[left_index].proportion if left_index is not None else 0.0
        right_share = second[right_index].proportion if right_index is not None else 0.0
        weight = (left_share + right_share) / 2
        weighted_distance += _assignment_distance(first, second, left_index, right_index) * weight
        mass += weight
        proportion_difference += abs(left_share - right_share)
    return PaletteComparison(
        color_distance=_rounded(weighted_distance / mass if mass else 0.0),
        proportion_l1=_rounded(proportion_difference / 2),
        assignments=assignments,
    )


def _normalized_srgb(image: Image.Image) -> np.ndarray:
    if image.width < 1 or image.height < 1:
        raise ValueError("preview dimensions must be positive")
    if image.mode in {"I;16", "I;16L", "I;16B", "I;16N"}:
        values = np.asarray(image, dtype=np.float64)
        gray = np.rint(np.clip(values, 0, 65535) * (255 / 65535)).astype(np.uint8)
        return np.repeat(gray[..., None], 3, axis=2)
    if image.mode in {"I", "F"}:
        raise ValueError(f"unsupported preview numeric mode: {image.mode}")
    if image.mode in {"RGBA", "LA"} or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (128, 128, 128, 255))
        normalized = Image.alpha_composite(background, rgba).convert("RGB")
    else:
        normalized = image.convert("RGB")
    return np.asarray(normalized, dtype=np.uint8).copy()


def _palette(encoded: np.ndarray) -> tuple[tuple[PaletteColor, ...], float]:
    quantized = np.minimum((encoded * 16).astype(np.uint8), 15)
    codes = (
        quantized[..., 0].astype(np.uint16) * 256
        + quantized[..., 1].astype(np.uint16) * 16
        + quantized[..., 2].astype(np.uint16)
    )
    values, counts = np.unique(codes, return_counts=True)
    ordered = sorted(
        zip(values.tolist(), counts.tolist(), strict=True),
        key=lambda item: (-item[1], item[0]),
    )[:PALETTE_SIZE]
    selected_total = sum(count for _, count in ordered)
    proportions = [_rounded(count / selected_total) for _, count in ordered]
    if proportions:
        proportions[-1] = _rounded(1.0 - sum(proportions[:-1]))
    entries = tuple(
        PaletteColor(
            rgb=(
                (code // 256) * 16 + 8,
                ((code // 16) % 16) * 16 + 8,
                (code % 16) * 16 + 8,
            ),
            proportion=proportion,
        )
        for (code, _), proportion in zip(ordered, proportions, strict=True)
    )
    return entries, _rounded(selected_total / codes.size)


def _palette_entropy(encoded: np.ndarray) -> float:
    quantized = np.minimum((encoded * 8).astype(np.uint8), 7)
    codes = (
        quantized[..., 0].astype(np.uint16) * 64
        + quantized[..., 1].astype(np.uint16) * 8
        + quantized[..., 2].astype(np.uint16)
    )
    _, counts = np.unique(codes, return_counts=True)
    probabilities = counts / counts.sum()
    return float(-np.sum(probabilities * np.log2(probabilities)) / 9)


def _assignment_distance(
    first: tuple[PaletteColor, ...],
    second: tuple[PaletteColor, ...],
    left: int | None,
    right: int | None,
) -> float:
    if left is None and right is None:
        return 0.0
    if left is None or right is None:
        return 1.0
    return sqrt(
        sum(((first[left].rgb[index] - second[right].rgb[index]) / 255) ** 2 for index in range(3))
        / 3
    )


def _linearize(value: float) -> float:
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def _rounded(value: Any) -> float:
    return round(float(value), ROUNDING_DIGITS)
