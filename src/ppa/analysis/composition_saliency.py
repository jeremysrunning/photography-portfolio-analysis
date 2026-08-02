"""Deterministic spectral-residual saliency geometry measurements."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from math import floor, hypot, isfinite, sqrt

import numpy as np
from PIL import Image

from ppa.analysis.image_normalization import normalized_srgb
from ppa.models import Asset, JsonValue
from ppa.sources import PreviewMetadata, PreviewRequest, PreviewStorageMode
from ppa.visual import AnalyzerIdentity, NormalizedPoint, VisualResult, VisualResultKind

ANALYZER_IDENTITY = AnalyzerIdentity(
    "composition-saliency",
    "1.0.0",
    (
        "rendered-srgb-512-stretch128-bilinear-sr-box3-smooth5-"
        "logeps1e-9-masseps1e-12-rd005-grid3-round8-v1"
    ),
)
PREVIEW_REQUEST = PreviewRequest(
    maximum_edge=512,
    maximum_bytes=8_000_000,
    accepted_content_types=frozenset({"image/jpeg", "image/png", "image/webp"}),
    storage_mode=PreviewStorageMode.MEMORY,
)
WORKING_SIZE = 128
LOG_EPSILON = 1e-9
MASS_EPSILON = 1e-12
EVIDENCE_RELATIVE_DISPERSION = 0.05
SPECTRAL_AVERAGE_SIZE = 3
SMOOTHING_SIZE = 5
SCALAR_ROUNDING_DIGITS = 12
GRID_ROUNDING_DIGITS = 8
GRID_REGION_ORDER = (
    "top_left",
    "top_center",
    "top_right",
    "middle_left",
    "center",
    "middle_right",
    "bottom_left",
    "bottom_center",
    "bottom_right",
)


@dataclass(frozen=True, slots=True)
class SaliencyMeasurements:
    """Complete transient measurement set for one normalized saliency map."""

    evidence: bool
    centroid: tuple[float, float] | None
    spread: float | None
    grid_masses: tuple[float, ...] | None
    center_distance: float | None
    thirds_line_distance: float | None
    thirds_intersection_distance: float | None


class CompositionSaliencyAnalyzer:
    """Measure neutral saliency geometry from one bounded rendered preview."""

    identity = ANALYZER_IDENTITY
    preview_request = PREVIEW_REQUEST
    allows_empty_results = False

    def analyze(
        self,
        asset: Asset,
        image: Image.Image,
        metadata: PreviewMetadata,
    ) -> tuple[VisualResult, ...]:
        """Return the evidence-aware deterministic result catalog."""
        del asset, metadata
        measured = measure_saliency(image, working_size=WORKING_SIZE)
        results = [
            _result(
                "saliency_evidence",
                measured.evidence,
                "boolean",
                "spectral-residual-evidence",
            )
        ]
        if measured.centroid is not None:
            results.append(
                VisualResult(
                    name="saliency_centroid",
                    kind=VisualResultKind.MEASUREMENT,
                    value=NormalizedPoint(*measured.centroid),
                    method_name="spectral-residual-centroid",
                    method_version="1",
                    unit="normalized_frame_coordinate",
                )
            )
        if measured.spread is not None:
            results.append(
                _result(
                    "saliency_spread",
                    measured.spread,
                    "frame_diagonal_fraction",
                    "spectral-residual-spread",
                )
            )
        if measured.grid_masses is not None:
            results.append(
                _result(
                    "saliency_grid_3x3",
                    {
                        "order": list(GRID_REGION_ORDER),
                        "masses": list(measured.grid_masses),
                    },
                    "proportion",
                    "spectral-residual-grid-mass",
                )
            )
        if measured.center_distance is not None:
            results.append(
                _result(
                    "saliency_center_distance",
                    measured.center_distance,
                    "normalized_distance",
                    "saliency-centroid-frame-center-distance",
                )
            )
        if measured.thirds_line_distance is not None:
            results.append(
                _result(
                    "saliency_thirds_line_distance",
                    measured.thirds_line_distance,
                    "normalized_distance",
                    "saliency-centroid-thirds-line-distance",
                )
            )
        if measured.thirds_intersection_distance is not None:
            results.append(
                _result(
                    "saliency_thirds_intersection_distance",
                    measured.thirds_intersection_distance,
                    "normalized_distance",
                    "saliency-centroid-thirds-intersection-distance",
                )
            )
        return tuple(results)


def measure_saliency(
    image: Image.Image,
    *,
    working_size: int = WORKING_SIZE,
) -> SaliencyMeasurements:
    """Measure one image using the versioned spectral-residual method."""
    if working_size < 3:
        raise ValueError("saliency working size must be at least three pixels")
    luminance = _working_luminance(image, working_size)
    saliency = _spectral_residual_map(luminance)
    return measure_saliency_map(saliency)


def measure_saliency_map(saliency: np.ndarray) -> SaliencyMeasurements:
    """Derive evidence, mass, and geometry from one finite saliency map."""
    values = np.asarray(saliency, dtype=np.float64)
    if values.ndim != 2 or values.size == 0:
        raise ValueError("saliency map must be a nonempty two-dimensional array")
    if not np.all(np.isfinite(values)) or np.any(values < 0):
        raise ValueError("saliency map must contain finite nonnegative values")
    mean = float(np.mean(values))
    relative_dispersion = float(np.std(values) / mean) if mean > MASS_EPSILON else 0.0
    evidence = mean > MASS_EPSILON and relative_dispersion >= EVIDENCE_RELATIVE_DISPERSION
    total = float(np.sum(values))
    grid = _grid_masses(values, total) if total > MASS_EPSILON else None
    if not evidence:
        return SaliencyMeasurements(False, None, None, grid, None, None, None)

    height, width = values.shape
    x_coordinates = (np.arange(width, dtype=np.float64) + 0.5) / width
    y_coordinates = (np.arange(height, dtype=np.float64) + 0.5) / height
    centroid_x = float(np.sum(values * x_coordinates[None, :]) / total)
    centroid_y = float(np.sum(values * y_coordinates[:, None]) / total)
    squared_distances = (x_coordinates[None, :] - centroid_x) ** 2 + (
        y_coordinates[:, None] - centroid_y
    ) ** 2
    spread = sqrt(float(np.sum(values * squared_distances) / total)) / sqrt(2)
    center_distance, thirds_line_distance, thirds_intersection_distance = (
        normalized_centroid_distances(centroid_x, centroid_y)
    )
    rounded = tuple(
        _rounded(value)
        for value in (
            centroid_x,
            centroid_y,
            spread,
            center_distance,
            thirds_line_distance,
            thirds_intersection_distance,
        )
    )
    return SaliencyMeasurements(
        True,
        (rounded[0], rounded[1]),
        rounded[2],
        grid,
        rounded[3],
        rounded[4],
        rounded[5],
    )


def normalized_centroid_distance(
    first: SaliencyMeasurements,
    second: SaliencyMeasurements,
) -> float | None:
    """Compare two available centroids as a fraction of the frame diagonal."""
    if first.centroid is None or second.centroid is None:
        return None
    return hypot(
        first.centroid[0] - second.centroid[0],
        first.centroid[1] - second.centroid[1],
    ) / sqrt(2)


def grid_l1_difference(first: SaliencyMeasurements, second: SaliencyMeasurements) -> float | None:
    """Return the L1 difference between two available regional distributions."""
    if first.grid_masses is None or second.grid_masses is None:
        return None
    return sum(
        abs(left - right) for left, right in zip(first.grid_masses, second.grid_masses, strict=True)
    )


def normalized_centroid_distances(x: float, y: float) -> tuple[float, float, float]:
    """Return normalized center, thirds-line, and thirds-intersection distances."""
    if not 0 <= x <= 1 or not 0 <= y <= 1:
        raise ValueError("normalized centroid coordinates must be within the frame")
    center = hypot(x - 0.5, y - 0.5) / (sqrt(2) / 2)
    line = min(
        abs(x - 1 / 3),
        abs(x - 2 / 3),
        abs(y - 1 / 3),
        abs(y - 2 / 3),
    ) / (1 / 3)
    intersection = min(
        hypot(x - thirds_x, y - thirds_y)
        for thirds_x in (1 / 3, 2 / 3)
        for thirds_y in (1 / 3, 2 / 3)
    ) / (sqrt(2) / 3)
    return center, line, intersection


def _working_luminance(image: Image.Image, working_size: int) -> np.ndarray:
    rgb = normalized_srgb(image)
    encoded = rgb.astype(np.float64) / 255.0
    luminance = encoded[..., 0] * 0.2126 + encoded[..., 1] * 0.7152 + encoded[..., 2] * 0.0722
    quantized = np.rint(np.clip(luminance, 0.0, 1.0) * 255).astype(np.uint8)
    working = Image.fromarray(quantized, "L").resize(
        (working_size, working_size),
        Image.Resampling.BILINEAR,
    )
    return np.asarray(working, dtype=np.float64) / 255.0


def _spectral_residual_map(luminance: np.ndarray) -> np.ndarray:
    spectrum = np.fft.fft2(luminance)
    amplitude = np.abs(spectrum)
    log_amplitude = np.log(amplitude + LOG_EPSILON)
    residual = log_amplitude - _box_mean(log_amplitude, SPECTRAL_AVERAGE_SIZE)
    reconstructed_spectrum = np.exp(residual + 1j * np.angle(spectrum))
    reconstructed_spectrum = np.where(amplitude > MASS_EPSILON, reconstructed_spectrum, 0.0)
    reconstructed = np.fft.ifft2(reconstructed_spectrum)
    smoothed = _box_mean(np.abs(reconstructed) ** 2, SMOOTHING_SIZE)
    if not np.all(np.isfinite(smoothed)) or np.any(smoothed < 0):
        raise ValueError("spectral-residual calculation produced invalid values")
    maximum = float(np.max(smoothed))
    if maximum <= MASS_EPSILON:
        return np.zeros_like(smoothed, dtype=np.float64)
    return np.asarray(smoothed / maximum, dtype=np.float64)


def _box_mean(values: np.ndarray, size: int) -> np.ndarray:
    padding = size // 2
    padded = np.pad(values, padding, mode="reflect")
    windows = np.lib.stride_tricks.sliding_window_view(padded, (size, size))
    return np.mean(windows, axis=(-2, -1))


def _grid_masses(values: np.ndarray, total: float) -> tuple[float, ...]:
    height, width = values.shape
    masses = [0.0] * 9
    for row in range(height):
        y = (row + 0.5) / height
        region_row = grid_region_index(y)
        for column in range(width):
            x = (column + 0.5) / width
            region_column = grid_region_index(x)
            masses[region_row * 3 + region_column] += float(values[row, column])
    quantum = Decimal(1).scaleb(-GRID_ROUNDING_DIGITS)
    rounded = [
        Decimal(str(value / total)).quantize(quantum, rounding=ROUND_HALF_EVEN)
        for value in masses[:8]
    ]
    remainder = Decimal("1.00000000") - sum(rounded, Decimal(0))
    if remainder < 0:
        raise ValueError("rounded saliency grid produced a negative remainder")
    rounded.append(remainder)
    return tuple(float(value) for value in rounded)


def grid_region_index(coordinate: float) -> int:
    """Assign one normalized cell center to the fixed three-region axis."""
    if not 0 <= coordinate <= 1:
        raise ValueError("normalized grid coordinate must be within the frame")
    return min(2, floor(3 * coordinate))


def _result(name: str, value: JsonValue, unit: str, method: str) -> VisualResult:
    return VisualResult(
        name=name,
        kind=VisualResultKind.MEASUREMENT,
        value=value,
        method_name=method,
        method_version="1",
        unit=unit,
    )


def _rounded(value: float) -> float:
    numeric = float(value)
    if not isfinite(numeric):
        raise ValueError("saliency geometry produced a non-finite result")
    return round(numeric, SCALAR_ROUNDING_DIGITS)
