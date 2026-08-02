"""Production deterministic composition-saliency analyzer tests."""

from __future__ import annotations

from math import hypot, sqrt

import numpy as np
import pytest
from PIL import Image, ImageDraw

from ppa.analysis.composition_saliency import (
    ANALYZER_IDENTITY,
    EVIDENCE_RELATIVE_DISPERSION,
    GRID_REGION_ORDER,
    PREVIEW_REQUEST,
    WORKING_SIZE,
    CompositionSaliencyAnalyzer,
    grid_l1_difference,
    grid_region_index,
    measure_saliency,
    measure_saliency_map,
    normalized_centroid_distance,
    normalized_centroid_distances,
)
from ppa.sources import PreviewStorageMode
from ppa.visual import VisualResultKind


def _values(image: Image.Image) -> dict[str, object]:
    results = CompositionSaliencyAnalyzer().analyze(None, image, None)  # type: ignore[arg-type]
    return {result.name: result.value for result in results}


def _fixture(size: tuple[int, int], kind: str) -> Image.Image:
    width, height = size
    image = Image.new("RGB", size, (80, 80, 80))
    draw = ImageDraw.Draw(image)
    if kind == "center":
        draw.ellipse(
            (
                round(width * 0.35),
                round(height * 0.35),
                round(width * 0.65),
                round(height * 0.65),
            ),
            fill=(220, 220, 220),
        )
    elif kind == "two_regions":
        draw.ellipse(
            (
                round(width * 0.15),
                round(height * 0.20),
                round(width * 0.35),
                round(height * 0.45),
            ),
            fill=(220, 220, 220),
        )
        draw.rectangle(
            (
                round(width * 0.65),
                round(height * 0.55),
                round(width * 0.85),
                round(height * 0.80),
            ),
            fill=(20, 20, 20),
        )
    elif kind == "border":
        draw.rectangle(
            (0, 0, width - 1, height - 1),
            outline=(240, 240, 240),
            width=max(2, round(min(size) * 0.01)),
        )
    elif kind == "texture":
        for x in range(0, width, 20):
            draw.line((x, 0, x, height), fill=(160, 160, 160), width=4)
    else:  # pragma: no cover - test helper guard
        raise ValueError(kind)
    return image


def _stable(candidate, reference) -> bool:
    if candidate.evidence != reference.evidence:
        return False
    centroid = normalized_centroid_distance(candidate, reference)
    if centroid is not None and centroid > 0.05:
        return False
    if (
        candidate.spread is not None
        and reference.spread is not None
        and abs(candidate.spread - reference.spread) > 0.05
    ):
        return False
    grid = grid_l1_difference(candidate, reference)
    if grid is None and candidate.grid_masses != reference.grid_masses:
        return False
    if grid is not None and grid > 0.15:
        return False
    for name in (
        "center_distance",
        "thirds_line_distance",
        "thirds_intersection_distance",
    ):
        left = getattr(candidate, name)
        right = getattr(reference, name)
        if left is not None and right is not None and abs(left - right) > 0.05:
            return False
    return True


def test_identity_preview_contract_and_deterministic_result_catalog() -> None:
    analyzer = CompositionSaliencyAnalyzer()
    results = analyzer.analyze(None, _fixture((320, 240), "center"), None)  # type: ignore[arg-type]

    assert analyzer.identity == ANALYZER_IDENTITY
    assert analyzer.preview_request == PREVIEW_REQUEST
    assert PREVIEW_REQUEST.maximum_edge == 512
    assert PREVIEW_REQUEST.maximum_bytes == 8_000_000
    assert PREVIEW_REQUEST.storage_mode is PreviewStorageMode.MEMORY
    assert WORKING_SIZE == 128
    assert not analyzer.allows_empty_results
    assert [result.name for result in results] == [
        "saliency_evidence",
        "saliency_centroid",
        "saliency_spread",
        "saliency_grid_3x3",
        "saliency_center_distance",
        "saliency_thirds_line_distance",
        "saliency_thirds_intersection_distance",
    ]
    assert all(result.kind is VisualResultKind.MEASUREMENT for result in results)
    assert all(result.confidence is None and result.model_name is None for result in results)


def test_uniform_and_zero_mass_low_information_complete_without_centroid() -> None:
    uniform = measure_saliency(Image.new("RGB", (320, 240), (128, 128, 128)))
    zero = measure_saliency_map(np.zeros((128, 128), dtype=np.float64))

    assert not uniform.evidence
    assert uniform.centroid is None
    assert uniform.spread is None
    assert uniform.center_distance is None
    assert uniform.grid_masses is not None
    assert sum(uniform.grid_masses) == 1.0
    assert zero == type(zero)(False, None, None, None, None, None, None)
    assert list(_values(Image.new("RGB", (8, 8), "black"))) == ["saliency_evidence"]


def test_near_uniform_generated_images_bracket_evidence_threshold() -> None:
    below = np.full((128, 128, 3), 128, dtype=np.uint8)
    below[6:121, 4:123] = 129
    above = np.full((128, 128, 3), 128, dtype=np.uint8)
    above[0:127, 14:113] = 129

    below_result = measure_saliency(Image.fromarray(below, "RGB"))
    above_result = measure_saliency(Image.fromarray(above, "RGB"))

    assert EVIDENCE_RELATIVE_DISPERSION == 0.05
    assert not below_result.evidence
    assert above_result.evidence
    assert below_result == measure_saliency(Image.fromarray(below, "RGB"))
    assert above_result == measure_saliency(Image.fromarray(above, "RGB"))


def test_exact_evidence_threshold_boundary() -> None:
    below = np.array([[1.0 - 0.05, 1.0 + 0.05 - 1e-12]])
    exact = np.array([[1.0 - 0.05, 1.0 + 0.05]])

    assert not measure_saliency_map(below).evidence
    assert measure_saliency_map(exact).evidence


def test_centroid_spread_grid_and_distance_formulas() -> None:
    saliency = np.zeros((3, 3), dtype=np.float64)
    saliency[0, 0] = 1.0
    measured = measure_saliency_map(saliency)
    coordinate = 1 / 6

    assert measured.centroid == (round(coordinate, 12), round(coordinate, 12))
    assert measured.spread == 0.0
    assert measured.grid_masses == (1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    expected = normalized_centroid_distances(coordinate, coordinate)
    assert measured.center_distance == round(expected[0], 12)
    assert measured.thirds_line_distance == round(expected[1], 12)
    assert measured.thirds_intersection_distance == round(expected[2], 12)

    center, line, intersection = normalized_centroid_distances(1 / 3, 1 / 3)
    assert center == pytest.approx(1 / 3)
    assert line == 0.0
    assert intersection == 0.0


def test_equal_symmetric_regions_have_centered_centroid() -> None:
    saliency = np.zeros((9, 9), dtype=np.float64)
    saliency[2, 2] = saliency[6, 6] = 1.0
    measured = measure_saliency_map(saliency)

    assert measured.centroid == (0.5, 0.5)
    assert measured.center_distance == 0.0
    assert measured.spread == pytest.approx(hypot(2 / 9, 2 / 9) / sqrt(2))


def test_grid_boundaries_assignment_order_and_rounding() -> None:
    assert grid_region_index(0.0) == 0
    assert grid_region_index(1 / 3) == 1
    assert grid_region_index(2 / 3) == 2
    assert grid_region_index(1.0) == 2
    assert len(GRID_REGION_ORDER) == 9

    measured = measure_saliency_map(np.arange(1, 82, dtype=np.float64).reshape(9, 9))
    assert measured.grid_masses is not None
    assert len(measured.grid_masses) == 9
    assert sum(measured.grid_masses) == 1.0
    assert all(0 <= value <= 1 for value in measured.grid_masses)
    assert all(round(value, 8) == value for value in measured.grid_masses)


@pytest.mark.parametrize(
    ("x", "y"),
    [
        (0.5, 0.5),
        (0.05, 0.5),
        (0.95, 0.5),
        (0.5, 0.05),
        (0.5, 0.95),
        (1 / 3, 0.5),
        (2 / 3, 0.5),
        (0.5, 1 / 3),
        (0.5, 2 / 3),
        (1 / 3, 1 / 3),
        (2 / 3, 1 / 3),
        (1 / 3, 2 / 3),
        (2 / 3, 2 / 3),
    ],
)
def test_generated_salient_regions_remain_within_normalized_geometry(x: float, y: float) -> None:
    image = Image.new("RGB", (600, 400), (80, 80, 80))
    draw = ImageDraw.Draw(image)
    radius = 24
    center_x, center_y = round(x * image.width), round(y * image.height)
    draw.ellipse(
        (center_x - radius, center_y - radius, center_x + radius, center_y + radius),
        fill=(230, 230, 230),
    )
    measured = measure_saliency(image)

    assert measured.evidence
    assert measured.centroid is not None
    assert all(0 <= value <= 1 for value in measured.centroid)
    assert measured.spread is not None and 0 <= measured.spread <= 1
    assert measured.center_distance is not None and 0 <= measured.center_distance <= 1
    assert measured.thirds_line_distance is not None and 0 <= measured.thirds_line_distance <= 1
    assert (
        measured.thirds_intersection_distance is not None
        and 0 <= measured.thirds_intersection_distance <= 1
    )


def test_smallest_working_resolution_passing_predeclared_gates_is_128() -> None:
    candidates = (64, 96, 128)
    passing = {candidate: True for candidate in candidates}
    for size in ((640, 480), (480, 640), (512, 512)):
        for kind in ("center", "two_regions", "border", "texture"):
            image = _fixture(size, kind)
            reference = measure_saliency(image, working_size=128)
            for candidate in candidates:
                passing[candidate] &= _stable(
                    measure_saliency(image, working_size=candidate),
                    reference,
                )

    assert passing == {64: False, 96: False, 128: True}


def test_square_stretch_is_stable_across_controlled_aspect_ratios() -> None:
    for kind in ("center", "two_regions", "border"):
        reference = measure_saliency(_fixture((512, 512), kind))
        for size in ((640, 480), (480, 640)):
            assert _stable(measure_saliency(_fixture(size, kind)), reference)


def test_nonclipping_uniform_brightness_scaling_is_materially_stable() -> None:
    base = Image.new("L", (640, 480), 80)
    draw = ImageDraw.Draw(base)
    draw.ellipse((160, 100, 360, 300), fill=160)
    draw.rectangle((430, 280, 560, 400), fill=120)
    measurements = {
        factor: measure_saliency(
            Image.eval(base, lambda pixel, factor=factor: int(pixel * factor)).convert("RGB")
        )
        for factor in (0.5, 1.0, 1.5)
    }
    reference = measurements[1.0]

    for measured in measurements.values():
        assert measured.evidence == reference.evidence
        assert normalized_centroid_distance(measured, reference) <= 0.01  # type: ignore[operator]
        assert abs(measured.spread - reference.spread) <= 0.01  # type: ignore[operator]
        assert grid_l1_difference(measured, reference) <= 0.02  # type: ignore[operator]


def test_repeated_texture_border_multiple_regions_and_determinism() -> None:
    images = (
        _fixture((640, 480), "texture"),
        _fixture((640, 480), "border"),
        _fixture((640, 480), "two_regions"),
    )
    for image in images:
        first = measure_saliency(image)
        assert first == measure_saliency(image.copy())
        assert first.grid_masses is None or sum(first.grid_masses) == 1.0


def test_image_modes_follow_rendered_srgb_normalization_contract() -> None:
    palette = Image.new("P", (16, 16))
    palette.putpalette([255, 0, 0] + [0, 0, 0] * 255)
    palette.putdata([0] * 256)
    transparent = Image.new("RGBA", (16, 16), (255, 0, 0, 0))
    gray = Image.new("RGB", (16, 16), (128, 128, 128))
    sixteen = Image.fromarray(np.full((16, 16), 65535, dtype=np.uint16))

    assert not measure_saliency(palette).evidence
    assert measure_saliency(transparent) == measure_saliency(gray)
    assert not measure_saliency(sixteen).evidence
    with pytest.raises(ValueError, match="unsupported preview numeric mode"):
        measure_saliency(Image.new("F", (16, 16), 0.5))


def test_invalid_maps_and_coordinates_are_rejected() -> None:
    with pytest.raises(ValueError, match="two-dimensional"):
        measure_saliency_map(np.zeros((2, 2, 2)))
    with pytest.raises(ValueError, match="finite nonnegative"):
        measure_saliency_map(np.array([[np.nan]]))
    with pytest.raises(ValueError, match="within the frame"):
        normalized_centroid_distances(-0.1, 0.5)
    with pytest.raises(ValueError, match="within the frame"):
        grid_region_index(1.1)
