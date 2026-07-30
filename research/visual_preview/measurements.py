"""Deterministic preview measurements and cross-size comparisons."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import hypot
from typing import Any

import numpy as np
from PIL import Image

# Predeclared before real-portfolio results are examined. These are family-specific
# research thresholds, not a universal stability score.
STABILITY_THRESHOLDS = {
    "luminance_mean": 0.02,
    "luminance_median": 0.03,
    "luminance_spread": 0.03,
    "global_contrast": 0.03,
    "saturation_mean": 0.03,
    "saturation_median": 0.03,
    "colorfulness": 0.05,
    "warmth_proxy": 0.03,
    "highlight_clipping": 0.02,
    "shadow_clipping": 0.02,
    "palette_diversity": 0.08,
    "palette_distance": 0.08,
    "palette_proportion_l1": 0.15,
    "edge_density": 0.05,
    "saliency_centroid_distance": 0.05,
    "saliency_spread": 0.05,
}


@dataclass(frozen=True, slots=True)
class PaletteEntry:
    """One deterministic quantized RGB palette entry."""

    red: float
    green: float
    blue: float
    proportion: float


@dataclass(frozen=True, slots=True)
class MeasurementResult:
    """Compact deterministic measurements for one decoded preview."""

    width: int
    height: int
    luminance_mean: float
    luminance_median: float
    luminance_spread: float
    global_contrast: float
    saturation_mean: float
    saturation_median: float
    colorfulness: float
    warmth_proxy: float
    highlight_clipping: float
    shadow_clipping: float
    palette_diversity: float
    palette: tuple[PaletteEntry, ...]
    edge_density: float
    sharpness_proxy: float
    saliency_centroid_x: float
    saliency_centroid_y: float
    saliency_spread: float

    def serializable(self) -> dict[str, Any]:
        """Return a deterministic JSON-compatible representation."""
        return asdict(self)


def measure_image(image: Image.Image) -> MeasurementResult:
    """Measure one decoded image after deterministic RGB normalization."""
    rgb = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0
    luminance = rgb[..., 0] * 0.2126 + rgb[..., 1] * 0.7152 + rgb[..., 2] * 0.0722
    maximum = rgb.max(axis=2)
    minimum = rgb.min(axis=2)
    saturation = np.divide(
        maximum - minimum,
        maximum,
        out=np.zeros_like(maximum),
        where=maximum > 0,
    )
    red_green = rgb[..., 0] - rgb[..., 1]
    yellow_blue = (rgb[..., 0] + rgb[..., 1]) / 2 - rgb[..., 2]
    colorfulness = hypot(
        float(np.std(red_green)),
        float(np.std(yellow_blue)),
    ) + 0.3 * hypot(
        float(np.mean(red_green)),
        float(np.mean(yellow_blue)),
    )
    low, high = np.percentile(luminance, (5, 95))
    gradients_x, gradients_y = np.gradient(luminance)
    gradient_magnitude = np.hypot(gradients_x, gradients_y)
    laplacian = (
        -4 * luminance
        + np.roll(luminance, 1, axis=0)
        + np.roll(luminance, -1, axis=0)
        + np.roll(luminance, 1, axis=1)
        + np.roll(luminance, -1, axis=1)
    )
    saliency = _spectral_residual_saliency(luminance)
    centroid_x, centroid_y, spread = _saliency_geometry(saliency)
    return MeasurementResult(
        width=image.width,
        height=image.height,
        luminance_mean=float(np.mean(luminance)),
        luminance_median=float(np.median(luminance)),
        luminance_spread=float(np.std(luminance)),
        global_contrast=float(high - low),
        saturation_mean=float(np.mean(saturation)),
        saturation_median=float(np.median(saturation)),
        colorfulness=float(colorfulness),
        warmth_proxy=float(np.mean(rgb[..., 0] - rgb[..., 2])),
        highlight_clipping=float(np.mean(luminance >= 250 / 255)),
        shadow_clipping=float(np.mean(luminance <= 5 / 255)),
        palette_diversity=_palette_diversity(rgb),
        palette=_palette(rgb),
        edge_density=float(np.mean(gradient_magnitude >= 0.08)),
        sharpness_proxy=float(np.var(laplacian)),
        saliency_centroid_x=centroid_x,
        saliency_centroid_y=centroid_y,
        saliency_spread=spread,
    )


def compare_measurements(
    candidate: MeasurementResult,
    reference: MeasurementResult,
) -> dict[str, float | bool]:
    """Compare a smaller preview with the largest tested preview."""
    scalar_names = tuple(
        name
        for name in STABILITY_THRESHOLDS
        if name
        not in {
            "palette_distance",
            "palette_proportion_l1",
            "saliency_centroid_distance",
        }
    )
    comparisons: dict[str, float | bool] = {}
    for name in scalar_names:
        difference = abs(float(getattr(candidate, name)) - float(getattr(reference, name)))
        comparisons[f"{name}_difference"] = difference
        comparisons[f"{name}_stable"] = difference <= STABILITY_THRESHOLDS[name]
    palette_distance, proportion_l1 = _palette_comparison(
        candidate.palette,
        reference.palette,
    )
    comparisons["palette_distance"] = palette_distance
    comparisons["palette_distance_stable"] = (
        palette_distance <= STABILITY_THRESHOLDS["palette_distance"]
    )
    comparisons["palette_proportion_l1"] = proportion_l1
    comparisons["palette_proportion_l1_stable"] = (
        proportion_l1 <= STABILITY_THRESHOLDS["palette_proportion_l1"]
    )
    centroid_distance = (
        hypot(
            candidate.saliency_centroid_x - reference.saliency_centroid_x,
            candidate.saliency_centroid_y - reference.saliency_centroid_y,
        )
        / 2**0.5
    )
    comparisons["saliency_centroid_distance"] = centroid_distance
    comparisons["saliency_centroid_distance_stable"] = (
        centroid_distance <= STABILITY_THRESHOLDS["saliency_centroid_distance"]
    )
    return comparisons


def bounding_box_iou(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> float:
    """Return IoU for normalized ``x, y, width, height`` boxes."""
    _validate_box(first)
    _validate_box(second)
    first_right, first_bottom = first[0] + first[2], first[1] + first[3]
    second_right, second_bottom = second[0] + second[2], second[1] + second[3]
    intersection_width = max(0.0, min(first_right, second_right) - max(first[0], second[0]))
    intersection_height = max(
        0.0,
        min(first_bottom, second_bottom) - max(first[1], second[1]),
    )
    intersection = intersection_width * intersection_height
    union = first[2] * first[3] + second[2] * second[3] - intersection
    return intersection / union if union else 0.0


def normalized_centroid_distance(
    first: tuple[float, float],
    second: tuple[float, float],
) -> float:
    """Return centroid distance as a fraction of the frame diagonal."""
    for point in (first, second):
        if any(value < 0 or value > 1 for value in point):
            raise ValueError("normalized centroids must be within the frame")
    return hypot(first[0] - second[0], first[1] - second[1]) / 2**0.5


def _palette(rgb: np.ndarray, count: int = 5) -> tuple[PaletteEntry, ...]:
    quantized = np.minimum((rgb * 16).astype(np.uint8), 15)
    codes = (
        quantized[..., 0].astype(np.uint16) * 256
        + quantized[..., 1].astype(np.uint16) * 16
        + quantized[..., 2].astype(np.uint16)
    )
    values, counts = np.unique(codes, return_counts=True)
    ordered = sorted(
        zip(values.tolist(), counts.tolist(), strict=True),
        key=lambda item: (-item[1], item[0]),
    )[:count]
    total = codes.size
    return tuple(
        PaletteEntry(
            red=((code // 256) + 0.5) / 16,
            green=(((code // 16) % 16) + 0.5) / 16,
            blue=((code % 16) + 0.5) / 16,
            proportion=frequency / total,
        )
        for code, frequency in ordered
    )


def _palette_diversity(rgb: np.ndarray) -> float:
    quantized = np.minimum((rgb * 8).astype(np.uint8), 7)
    codes = (
        quantized[..., 0].astype(np.uint16) * 64
        + quantized[..., 1].astype(np.uint16) * 8
        + quantized[..., 2].astype(np.uint16)
    )
    _, counts = np.unique(codes, return_counts=True)
    probabilities = counts / counts.sum()
    entropy = -np.sum(probabilities * np.log2(probabilities))
    return float(entropy / 9.0)


def _spectral_residual_saliency(luminance: np.ndarray) -> np.ndarray:
    target = Image.fromarray(np.uint8(np.clip(luminance * 255, 0, 255))).resize(
        (64, 64),
        Image.Resampling.BILINEAR,
    )
    normalized = np.asarray(target, dtype=np.float32) / 255.0
    spectrum = np.fft.fft2(normalized)
    log_amplitude = np.log(np.abs(spectrum) + 1e-9)
    residual = log_amplitude - _box_blur(log_amplitude, 3)
    reconstructed = np.fft.ifft2(np.exp(residual + 1j * np.angle(spectrum)))
    saliency = _box_blur(np.abs(reconstructed) ** 2, 5)
    maximum = float(np.max(saliency))
    return saliency / maximum if maximum > 0 else np.zeros_like(saliency)


def _box_blur(values: np.ndarray, size: int) -> np.ndarray:
    pad = size // 2
    padded = np.pad(values, pad, mode="reflect")
    windows = np.lib.stride_tricks.sliding_window_view(padded, (size, size))
    return np.mean(windows, axis=(-2, -1))


def _saliency_geometry(saliency: np.ndarray) -> tuple[float, float, float]:
    total = float(np.sum(saliency))
    if total <= 0:
        return (0.5, 0.5, 0.0)
    height, width = saliency.shape
    x_values = np.linspace(0, 1, width)
    y_values = np.linspace(0, 1, height)
    centroid_x = float(np.sum(saliency * x_values[None, :]) / total)
    centroid_y = float(np.sum(saliency * y_values[:, None]) / total)
    distances = (x_values[None, :] - centroid_x) ** 2 + (y_values[:, None] - centroid_y) ** 2
    spread = float(np.sqrt(np.sum(saliency * distances) / total) / 2**0.5)
    return (centroid_x, centroid_y, spread)


def _palette_comparison(
    candidate: tuple[PaletteEntry, ...],
    reference: tuple[PaletteEntry, ...],
) -> tuple[float, float]:
    if not candidate or not reference:
        return (1.0, 1.0)
    distance = 0.0
    proportion_l1 = 0.0
    for entry in candidate:
        matched = min(
            reference,
            key=lambda item: (
                (entry.red - item.red) ** 2
                + (entry.green - item.green) ** 2
                + (entry.blue - item.blue) ** 2
            ),
        )
        color_distance = (
            (entry.red - matched.red) ** 2
            + (entry.green - matched.green) ** 2
            + (entry.blue - matched.blue) ** 2
        ) ** 0.5 / 3**0.5
        distance += entry.proportion * color_distance
        proportion_l1 += abs(entry.proportion - matched.proportion)
    return (distance, min(1.0, proportion_l1))


def _validate_box(box: tuple[float, float, float, float]) -> None:
    x, y, width, height = box
    if x < 0 or y < 0 or width < 0 or height < 0 or x + width > 1 or y + height > 1:
        raise ValueError("normalized bounding box must be within the frame")
