"""Production deterministic preview-structure analyzer tests."""

from __future__ import annotations

from dataclasses import fields

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFilter

from ppa.analysis.preview_structure import (
    ANALYZER_IDENTITY,
    PREVIEW_REQUEST,
    PreviewStructureAnalyzer,
    _grid_contrast,
    _grid_indices,
    _percentile_span,
    measure_structure,
)
from ppa.sources import PreviewStorageMode
from ppa.visual import VisualResultKind


def _lines(size: tuple[int, int], *, vertical: bool = True) -> Image.Image:
    image = Image.new("L", size, 96)
    draw = ImageDraw.Draw(image)
    limit = size[0] if vertical else size[1]
    for position in range(0, limit, 24):
        if vertical:
            draw.rectangle((position, 0, min(position + 7, size[0] - 1), size[1]), fill=200)
        else:
            draw.rectangle((0, position, size[0], min(position + 7, size[1] - 1)), fill=200)
    return image.convert("RGB")


def _checker(size: tuple[int, int], block: int = 24) -> Image.Image:
    image = Image.new("L", size, 96)
    draw = ImageDraw.Draw(image)
    for y in range(0, size[1], block):
        for x in range(0, size[0], block):
            if (x // block + y // block) % 2:
                draw.rectangle((x, y, x + block - 1, y + block - 1), fill=200)
    return image.convert("RGB")


def _noise(size: tuple[int, int], seed: int = 41) -> Image.Image:
    rng = np.random.default_rng(seed)
    values = np.full((size[1], size[0]), 128, dtype=np.int16)
    values += rng.integers(-8, 9, values.shape)
    return Image.fromarray(values.clip(0, 255).astype(np.uint8), "L").convert("RGB")


def _at_edge(source: Image.Image, edge: int) -> Image.Image:
    ratio = edge / max(source.size)
    size = (round(source.width * ratio), round(source.height * ratio))
    return source.resize(size, Image.Resampling.LANCZOS)


def _values(image: Image.Image) -> tuple[list[str], dict[str, object]]:
    results = PreviewStructureAnalyzer().analyze(None, image, None)  # type: ignore[arg-type]
    return [result.name for result in results], {result.name: result.value for result in results}


def test_identity_preview_contract_and_exact_supported_catalog() -> None:
    analyzer = PreviewStructureAnalyzer()
    names, _ = _values(_lines((128, 96)))

    assert analyzer.identity == ANALYZER_IDENTITY
    assert analyzer.identity.name == "preview-structure"
    assert analyzer.identity.version == "1.0.0"
    assert "1024" in analyzer.identity.configuration_version
    assert "min16" in analyzer.identity.configuration_version
    assert analyzer.preview_request == PREVIEW_REQUEST
    assert PREVIEW_REQUEST.maximum_edge == 1024
    assert PREVIEW_REQUEST.storage_mode is PreviewStorageMode.MEMORY
    assert not analyzer.allows_empty_results
    assert names == [
        "structure_measurement_support",
        "global_sharpness_proxy",
        "gradient_directional_evidence",
        "gradient_directional_anisotropy",
        "edge_density",
        "local_luminance_contrast",
        "spatial_sharpness_variation",
        "noise_proxy_evidence",
        "noise_residual_mad",
        "luminance_p95_p05_span",
    ]
    results = analyzer.analyze(None, _lines((128, 96)), None)  # type: ignore[arg-type]
    assert all(result.kind is VisualResultKind.MEASUREMENT for result in results)
    assert all(result.confidence is None and result.model_name is None for result in results)


@pytest.mark.parametrize("size", [(15, 16), (16, 15), (15, 15), (100, 15), (15, 100)])
def test_small_previews_complete_with_explicit_unsupported_contract(size) -> None:
    names, values = _values(Image.new("F", size, 0.5))

    assert names == ["structure_measurement_support"]
    assert values == {"structure_measurement_support": False}


def test_sixteen_by_six_is_supported_and_uses_normal_numeric_validation() -> None:
    names, values = _values(Image.new("RGB", (16, 16), "gray"))

    assert names[0] == "structure_measurement_support"
    assert values["structure_measurement_support"] is True
    with pytest.raises(ValueError, match="unsupported preview numeric mode"):
        _values(Image.new("F", (16, 16), 0.5))


def test_uniform_results_are_finite_and_do_not_fabricate_directionality() -> None:
    measured = measure_structure(Image.new("RGB", (128, 96), (128, 128, 128)))

    assert measured.support
    assert measured.global_sharpness == 0.0
    assert measured.directional_evidence is False
    assert measured.directional_anisotropy is None
    assert measured.edge_density == 0.0
    assert measured.local_contrast == 0.0
    assert measured.spatial_sharpness_variation == 0.0
    assert measured.noise_evidence is True
    assert measured.noise_residual_mad == 0.0
    assert measured.percentile_luminance_span == 0.0


def test_sharpness_edge_density_and_spatial_variation_are_distinct() -> None:
    low = Image.new("L", (256, 256), 96)
    ImageDraw.Draw(low).rectangle((128, 0, 255, 255), fill=140)
    high = Image.new("L", (256, 256), 96)
    ImageDraw.Draw(high).rectangle((128, 0, 255, 255), fill=220)
    localized = Image.new("L", (256, 256), 96)
    ImageDraw.Draw(localized).rectangle((192, 0, 255, 63), fill=220)

    low_result = measure_structure(low.convert("RGB"))
    high_result = measure_structure(high.convert("RGB"))
    localized_result = measure_structure(localized.convert("RGB"))

    assert high_result.global_sharpness > low_result.global_sharpness  # type: ignore[operator]
    assert high_result.edge_density == low_result.edge_density
    assert localized_result.spatial_sharpness_variation > high_result.spatial_sharpness_variation  # type: ignore[operator]


def test_sharp_edge_exceeds_isotropically_blurred_edge() -> None:
    sharp = Image.new("L", (256, 192), 64)
    ImageDraw.Draw(sharp).rectangle((128, 0, 255, 191), fill=220)
    blurred = sharp.filter(ImageFilter.GaussianBlur(4))

    assert (
        measure_structure(sharp.convert("RGB")).global_sharpness
        > measure_structure(blurred.convert("RGB")).global_sharpness
    )


def test_grid_boundaries_assign_two_pixels_per_cell_at_minimum_size() -> None:
    assert _grid_indices(16, 8).tolist() == [
        0,
        0,
        1,
        1,
        2,
        2,
        3,
        3,
        4,
        4,
        5,
        5,
        6,
        6,
        7,
        7,
    ]


def test_structure_tensor_describes_direction_without_claiming_blur_cause() -> None:
    vertical = measure_structure(_lines((384, 256), vertical=True))
    horizontal = measure_structure(_lines((256, 384), vertical=False))
    isotropic = measure_structure(_checker((384, 256)))

    assert vertical.directional_evidence and horizontal.directional_evidence
    assert vertical.directional_anisotropy == pytest.approx(1.0)
    assert horizontal.directional_anisotropy == pytest.approx(1.0)
    assert isotropic.directional_anisotropy < 0.02  # type: ignore[operator]


def test_isotropic_and_directional_blur_have_expected_ordering() -> None:
    source = _checker((384, 256), block=12)
    isotropic = source.filter(ImageFilter.GaussianBlur(3))
    horizontal_array = np.asarray(source.convert("L"), dtype=np.float64)
    padded = np.pad(horizontal_array, ((0, 0), (6, 6)), mode="reflect")
    windows = np.lib.stride_tricks.sliding_window_view(padded, 13, axis=1)
    horizontal = Image.fromarray(np.mean(windows, axis=-1).astype(np.uint8), "L").convert("RGB")
    isotropic_result = measure_structure(isotropic)
    directional_result = measure_structure(horizontal)

    assert directional_result.directional_evidence
    assert isotropic_result.directional_evidence
    assert directional_result.directional_anisotropy > isotropic_result.directional_anisotropy  # type: ignore[operator]


def test_noise_proxy_is_independent_from_clean_edges_and_repeated_structure() -> None:
    clean_edge = measure_structure(_lines((512, 384)))
    repeated = measure_structure(_checker((512, 384)))
    noisy = measure_structure(_noise((512, 384)))

    assert clean_edge.noise_evidence and repeated.noise_evidence and noisy.noise_evidence
    assert clean_edge.noise_residual_mad == 0.0
    assert repeated.noise_residual_mad == 0.0
    assert noisy.noise_residual_mad > 0  # type: ignore[operator]
    assert noisy.edge_density == 0.0


def test_percentile_span_adds_distribution_evidence_beyond_issue_37_summaries() -> None:
    broad = np.tile(np.array([0.2, 0.5, 0.8]), 100)
    narrow = np.tile(np.array([0.4, 0.5, 0.6]), 100)

    assert np.mean(broad) == pytest.approx(np.mean(narrow))
    assert np.median(broad) == np.median(narrow) == 0.5
    assert np.mean(broad <= 0.02) == np.mean(narrow <= 0.02) == 0
    assert np.mean(broad >= 0.98) == np.mean(narrow >= 0.98) == 0
    assert _percentile_span(broad) > _percentile_span(narrow)


def test_percentile_span_and_global_histogram_do_not_duplicate_local_contrast() -> None:
    clustered = np.zeros((64, 64), dtype=np.float64)
    clustered[:, 32:] = 1.0
    checker = (np.indices((64, 64)).sum(axis=0) % 2).astype(np.float64)

    assert np.array_equal(np.sort(clustered.ravel()), np.sort(checker.ravel()))
    assert _percentile_span(clustered) == _percentile_span(checker) == 1.0
    assert _grid_contrast(checker, 8) > _grid_contrast(clustered, 8)


def test_color_structure_is_finite_and_not_reduced_to_palette_semantics() -> None:
    values = np.zeros((96, 128, 3), dtype=np.uint8)
    values[:, :64] = (255, 0, 0)
    values[:, 64:] = (0, 130, 0)
    measured = measure_structure(Image.fromarray(values, "RGB"))

    assert measured.support
    assert all(
        value is None or isinstance(value, bool) or np.isfinite(value)
        for value in (
            measured.global_sharpness,
            measured.directional_evidence,
            measured.directional_anisotropy,
            measured.edge_density,
            measured.local_contrast,
            measured.spatial_sharpness_variation,
            measured.noise_evidence,
            measured.noise_residual_mad,
            measured.percentile_luminance_span,
        )
    )


def test_frozen_cross_size_decision_selects_1024_and_retained_candidates_are_stable() -> None:
    source = _lines((1024, 768))
    reference = measure_structure(_at_edge(source, 1024))
    candidate_512 = measure_structure(_at_edge(source, 512))
    candidate_768 = measure_structure(_at_edge(source, 768))

    assert abs(candidate_512.edge_density - reference.edge_density) > 0.05  # type: ignore[operator]
    assert abs(candidate_768.edge_density - reference.edge_density) > 0.05  # type: ignore[operator]

    noise_source = _noise((1024, 768))
    noise_reference = measure_structure(_at_edge(noise_source, 1024))
    for edge in (512, 768):
        candidate = measure_structure(_at_edge(noise_source, edge))
        assert candidate.noise_evidence == noise_reference.noise_evidence
        assert abs(candidate.noise_residual_mad - noise_reference.noise_residual_mad) <= 0.02  # type: ignore[operator]
        assert (
            abs(candidate.percentile_luminance_span - noise_reference.percentile_luminance_span)
            <= 0.03
        )


def test_brightness_scaling_characterizes_magnitude_and_preserves_direction() -> None:
    base = _lines((384, 256)).convert("L")
    measured = {
        factor: measure_structure(
            Image.eval(base, lambda value, factor=factor: round(value * factor)).convert("RGB")
        )
        for factor in (0.5, 1.0, 1.25)
    }

    assert all(result.directional_evidence for result in measured.values())
    assert all(result.directional_anisotropy == 1.0 for result in measured.values())
    assert (
        measured[0.5].global_sharpness
        < measured[1.0].global_sharpness
        < measured[1.25].global_sharpness  # type: ignore[operator]
    )


@pytest.mark.parametrize("size", [(384, 256), (256, 384), (320, 320)])
def test_aspect_ratio_rotation_and_repeated_execution_are_deterministic(size) -> None:
    image = _lines(size)
    first = measure_structure(image)
    repeated = measure_structure(image.copy())
    rotated = measure_structure(image.transpose(Image.Transpose.ROTATE_90))

    assert first == repeated
    for field in fields(type(first)):
        left = getattr(first, field.name)
        right = getattr(rotated, field.name)
        if isinstance(left, float) and isinstance(right, float):
            assert left == pytest.approx(right, abs=1e-12)
        else:
            assert left == right
