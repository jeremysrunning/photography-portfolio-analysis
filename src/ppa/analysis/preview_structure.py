"""Deterministic technical structure measurements from rendered previews."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, sqrt

import numpy as np
from PIL import Image

from ppa.analysis.image_normalization import relative_linear_luminance
from ppa.models import Asset, JsonValue
from ppa.sources import PreviewMetadata, PreviewRequest, PreviewStorageMode
from ppa.visual import AnalyzerIdentity, VisualResult, VisualResultKind

MINIMUM_DIMENSION = 16
DIRECTIONAL_GRADIENT_THRESHOLD = 0.05
DIRECTIONAL_MINIMUM_PIXELS = 64
DIRECTIONAL_MINIMUM_COVERAGE = 0.01
EDGE_DENSITY_THRESHOLD = 0.10
LOCAL_CONTRAST_GRID = 8
SHARPNESS_GRID = 4
NOISE_GRADIENT_THRESHOLD = 0.05
NOISE_LOCAL_RANGE_THRESHOLD = 0.10
NOISE_MINIMUM_BLOCKS = 64
NOISE_MINIMUM_COVERAGE = 0.01
MAD_NORMALIZATION = 0.6744897501960817
ROUNDING_DIGITS = 12

# Provisional until generated 512/768/1024 validation freezes the smallest passing edge.
PREVIEW_EDGE = 1024
PREVIEW_REQUEST = PreviewRequest(
    maximum_edge=PREVIEW_EDGE,
    maximum_bytes=8_000_000,
    accepted_content_types=frozenset({"image/jpeg", "image/png", "image/webp"}),
    storage_mode=PreviewStorageMode.MEMORY,
)
ANALYZER_IDENTITY = AnalyzerIdentity(
    "preview-structure",
    "1.0.0",
    (
        "rendered-srgb-1024-min16-linear-luma-fullres-reflect-lap4var16-"
        "sobel4-dirg005-min64-cov001-edge010-jtensor-grid8lc-grid4sv-"
        "haarmad-grad005-range010-min64-cov001-p05p95-linear-round12-v1"
    ),
)


@dataclass(frozen=True, slots=True)
class StructureMeasurements:
    """Transient complete candidate catalog for one decoded preview."""

    support: bool
    global_sharpness: float | None = None
    directional_evidence: bool | None = None
    directional_anisotropy: float | None = None
    edge_density: float | None = None
    local_contrast: float | None = None
    spatial_sharpness_variation: float | None = None
    noise_evidence: bool | None = None
    noise_residual_mad: float | None = None
    percentile_luminance_span: float | None = None


class PreviewStructureAnalyzer:
    """Measure source-agnostic technical structure in one rendered preview."""

    identity = ANALYZER_IDENTITY
    preview_request = PREVIEW_REQUEST
    allows_empty_results = False

    def analyze(
        self,
        asset: Asset,
        image: Image.Image,
        metadata: PreviewMetadata,
    ) -> tuple[VisualResult, ...]:
        """Return the deterministic evidence-aware structure catalog."""
        del asset, metadata
        measured = measure_structure(image)
        results = [_result("structure_measurement_support", measured.support, "boolean")]
        if not measured.support:
            return tuple(results)
        candidates: tuple[tuple[str, JsonValue | None, str], ...] = (
            (
                "global_sharpness_proxy",
                measured.global_sharpness,
                "normalized_laplacian_variance",
            ),
            ("gradient_directional_evidence", measured.directional_evidence, "boolean"),
            (
                "gradient_directional_anisotropy",
                measured.directional_anisotropy,
                "proportion",
            ),
            ("edge_density", measured.edge_density, "proportion"),
            (
                "local_luminance_contrast",
                measured.local_contrast,
                "normalized_local_rms_contrast",
            ),
            (
                "spatial_sharpness_variation",
                measured.spatial_sharpness_variation,
                "normalized_spatial_variation",
            ),
            ("noise_proxy_evidence", measured.noise_evidence, "boolean"),
            (
                "noise_residual_mad",
                measured.noise_residual_mad,
                "relative_linear_luminance",
            ),
            (
                "luminance_p95_p05_span",
                measured.percentile_luminance_span,
                "relative_linear_luminance_span",
            ),
        )
        results.extend(
            _result(name, value, unit) for name, value, unit in candidates if value is not None
        )
        return tuple(results)


def measure_structure(image: Image.Image) -> StructureMeasurements:
    """Measure the complete provisional catalog without retaining intermediate arrays."""
    if image.width < MINIMUM_DIMENSION or image.height < MINIMUM_DIMENSION:
        return StructureMeasurements(False)
    luminance = relative_linear_luminance(image)
    laplacian = _convolve3(luminance, np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]]))
    sobel_x = (
        _convolve3(
            luminance,
            np.array([[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]], dtype=np.float64),
        )
        / 4
    )
    sobel_y = (
        _convolve3(
            luminance,
            np.array([[-1, -2, -1], [0, 0, 0], [1, 2, 1]], dtype=np.float64),
        )
        / 4
    )
    gradient = np.hypot(sobel_x, sobel_y) / sqrt(2)
    directional_mask = gradient >= DIRECTIONAL_GRADIENT_THRESHOLD
    directional_count = int(np.count_nonzero(directional_mask))
    directional_evidence = (
        directional_count >= DIRECTIONAL_MINIMUM_PIXELS
        and directional_count / gradient.size >= DIRECTIONAL_MINIMUM_COVERAGE
    )
    anisotropy = (
        _directional_anisotropy(sobel_x[directional_mask], sobel_y[directional_mask])
        if directional_evidence
        else None
    )
    noise_evidence, noise = _noise_proxy(luminance, gradient)
    measured = StructureMeasurements(
        support=True,
        global_sharpness=_rounded(np.var(laplacian) / 16),
        directional_evidence=directional_evidence,
        directional_anisotropy=_rounded(anisotropy) if anisotropy is not None else None,
        edge_density=_rounded(np.mean(gradient >= EDGE_DENSITY_THRESHOLD)),
        local_contrast=_rounded(_grid_contrast(luminance, LOCAL_CONTRAST_GRID)),
        spatial_sharpness_variation=_rounded(_grid_sharpness_variation(laplacian, SHARPNESS_GRID)),
        noise_evidence=noise_evidence,
        noise_residual_mad=_rounded(noise) if noise is not None else None,
        percentile_luminance_span=_rounded(_percentile_span(luminance)),
    )
    _validate(measured)
    return measured


def _convolve3(values: np.ndarray, kernel: np.ndarray) -> np.ndarray:
    padded = np.pad(values, 1, mode="reflect")
    windows = np.lib.stride_tricks.sliding_window_view(padded, (3, 3))
    return np.sum(windows * kernel, axis=(-2, -1), dtype=np.float64)


def _directional_anisotropy(gx: np.ndarray, gy: np.ndarray) -> float:
    jxx = float(np.mean(gx * gx))
    jyy = float(np.mean(gy * gy))
    jxy = float(np.mean(gx * gy))
    center = (jxx + jyy) / 2
    radius = sqrt(max(0.0, ((jxx - jyy) / 2) ** 2 + jxy**2))
    maximum = center + radius
    minimum = max(0.0, center - radius)
    total = maximum + minimum
    return (maximum - minimum) / total if total > 0 else 0.0


def _grid_indices(length: int, count: int) -> np.ndarray:
    return np.minimum(count - 1, ((np.arange(length) + 0.5) * count / length).astype(int))


def _grid_contrast(values: np.ndarray, count: int) -> float:
    rows = _grid_indices(values.shape[0], count)
    columns = _grid_indices(values.shape[1], count)
    deviations = [
        float(np.std(values[np.ix_(rows == row, columns == column)]))
        for row in range(count)
        for column in range(count)
    ]
    return 2 * float(np.mean(deviations))


def _grid_sharpness_variation(laplacian: np.ndarray, count: int) -> float:
    rows = _grid_indices(laplacian.shape[0], count)
    columns = _grid_indices(laplacian.shape[1], count)
    sharpness = [
        float(np.var(laplacian[np.ix_(rows == row, columns == column)]) / 16)
        for row in range(count)
        for column in range(count)
    ]
    return 2 * float(np.std(sharpness))


def _noise_proxy(values: np.ndarray, gradient: np.ndarray) -> tuple[bool, float | None]:
    height = values.shape[0] - values.shape[0] % 2
    width = values.shape[1] - values.shape[1] % 2
    blocks = values[:height, :width].reshape(height // 2, 2, width // 2, 2)
    block_range = np.max(blocks, axis=(1, 3)) - np.min(blocks, axis=(1, 3))
    gradient_blocks = gradient[:height, :width].reshape(height // 2, 2, width // 2, 2)
    mean_gradient = np.mean(gradient_blocks, axis=(1, 3))
    usable = (block_range <= NOISE_LOCAL_RANGE_THRESHOLD) & (
        mean_gradient <= NOISE_GRADIENT_THRESHOLD
    )
    usable_count = int(np.count_nonzero(usable))
    evidence = (
        usable_count >= NOISE_MINIMUM_BLOCKS
        and usable_count / usable.size >= NOISE_MINIMUM_COVERAGE
    )
    if not evidence:
        return False, None
    coefficients = (
        blocks[:, 0, :, 0] - blocks[:, 0, :, 1] - blocks[:, 1, :, 0] + blocks[:, 1, :, 1]
    ) / 2
    selected = coefficients[usable]
    median = float(np.median(selected))
    return True, float(np.median(np.abs(selected - median)) / MAD_NORMALIZATION)


def _percentile_span(values: np.ndarray) -> float:
    return float(
        np.percentile(values, 95, method="linear") - np.percentile(values, 5, method="linear")
    )


def _result(name: str, value: JsonValue, unit: str) -> VisualResult:
    return VisualResult(
        name=name,
        kind=VisualResultKind.MEASUREMENT,
        value=value,
        method_name=name.replace("_", "-"),
        method_version="1",
        unit=unit,
    )


def _rounded(value: float | np.floating) -> float:
    numeric = float(value)
    if not isfinite(numeric):
        raise ValueError("preview-structure analysis produced a non-finite result")
    return round(numeric, ROUNDING_DIGITS)


def _validate(measured: StructureMeasurements) -> None:
    normalized = (
        measured.global_sharpness,
        measured.directional_anisotropy,
        measured.edge_density,
        measured.local_contrast,
        measured.spatial_sharpness_variation,
        measured.percentile_luminance_span,
    )
    if any(value is not None and not 0 <= value <= 1 for value in normalized):
        raise ValueError("preview-structure analysis produced an out-of-range result")
    if measured.noise_residual_mad is not None and not 0 <= measured.noise_residual_mad <= 2.9653:
        raise ValueError("preview-structure noise proxy is out of range")
