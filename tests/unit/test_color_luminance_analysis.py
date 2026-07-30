"""Production color and luminance analyzer tests."""

from __future__ import annotations

from math import isfinite

import numpy as np
import pytest
from PIL import Image

from ppa.analysis.color_luminance import (
    ANALYZER_IDENTITY,
    HIGHLIGHT_ENCODED_THRESHOLD,
    SHADOW_ENCODED_THRESHOLD,
    ColorLuminanceAnalyzer,
    PaletteColor,
    compare_palettes,
)


def _results(image: Image.Image) -> dict[str, object]:
    values = ColorLuminanceAnalyzer().analyze(None, image, None)  # type: ignore[arg-type]
    return {result.name: result.value for result in values}


def _palette_colors(value: object) -> tuple[PaletteColor, ...]:
    return tuple(
        PaletteColor(tuple(item["rgb"]), item["proportion"])  # type: ignore[arg-type,index]
        for item in value["colors"]  # type: ignore[index]
    )


def test_identity_preview_contract_and_complete_result_catalog() -> None:
    analyzer = ColorLuminanceAnalyzer()
    results = analyzer.analyze(None, Image.new("RGB", (4, 3), "gray"), None)  # type: ignore[arg-type]

    assert analyzer.identity == ANALYZER_IDENTITY
    assert analyzer.preview_request.maximum_edge == 768
    assert not analyzer.allows_empty_results
    assert {result.name for result in results} == {
        "luminance_mean",
        "luminance_median",
        "shadow_luminance_tail_proportion",
        "highlight_luminance_tail_proportion",
        "saturation_mean",
        "saturation_median",
        "colorfulness",
        "dominant_palette",
        "palette_entropy",
    }
    assert all(result.confidence is None for result in results)


def test_linear_luminance_and_exact_tail_threshold_boundaries() -> None:
    pixels = Image.new("RGB", (4, 1))
    pixels.putdata(
        [
            (5, 5, 5),
            (6, 6, 6),
            (249, 249, 249),
            (250, 250, 250),
        ]
    )
    results = _results(pixels)

    assert SHADOW_ENCODED_THRESHOLD == 5 / 255
    assert HIGHLIGHT_ENCODED_THRESHOLD == 250 / 255
    assert results["shadow_luminance_tail_proportion"] == 0.25
    assert results["highlight_luminance_tail_proportion"] == 0.25
    assert results["luminance_mean"] == pytest.approx(0.4766546717, abs=1e-12)


def test_saturation_colorfulness_and_grayscale_are_finite_nonnegative() -> None:
    colorful = Image.new("RGB", (2, 1))
    colorful.putdata([(255, 0, 0), (0, 255, 0)])
    result = _results(colorful)
    gray = _results(Image.new("L", (2, 2), 90))

    assert result["saturation_mean"] == 1.0
    assert result["colorfulness"] > 0
    assert isfinite(result["colorfulness"])
    assert gray["saturation_mean"] == 0.0
    assert gray["colorfulness"] == 0.0


def test_transparency_is_composited_against_neutral_midgray() -> None:
    hidden_red = Image.new("RGBA", (1, 1), (255, 0, 0, 0))
    visible_gray = Image.new("RGB", (1, 1), (128, 128, 128))

    assert _results(hidden_red) == _results(visible_gray)


def test_palette_cmyk_and_sixteen_bit_grayscale_normalization() -> None:
    palette_image = Image.new("P", (1, 1))
    palette_image.putpalette([255, 0, 0] + [0, 0, 0] * 255)
    palette_image.putdata([0])
    cmyk = Image.new("CMYK", (1, 1), (0, 255, 255, 0))
    sixteen = Image.fromarray(np.array([[65535]], dtype=np.uint16))

    assert _results(palette_image)["dominant_palette"] == _results(cmyk)["dominant_palette"]
    assert _results(sixteen)["luminance_mean"] == 1.0


def test_ambiguous_numeric_modes_are_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported preview numeric mode"):
        _results(Image.new("F", (2, 2), 0.5))


def test_palette_order_ties_proportions_coverage_and_entropy() -> None:
    image = Image.new("RGB", (6, 1))
    image.putdata(
        [
            (0, 0, 0),
            (0, 0, 0),
            (255, 255, 255),
            (255, 255, 255),
            (255, 0, 0),
            (0, 255, 0),
        ]
    )
    results = _results(image)
    palette = results["dominant_palette"]
    colors = palette["colors"]  # type: ignore[index]

    assert colors[0]["rgb"] == (8, 8, 8)  # type: ignore[index]
    assert colors[1]["rgb"] == (248, 248, 248)  # type: ignore[index]
    assert sum(item["proportion"] for item in colors) == 1.0  # type: ignore[index]
    assert palette["covered_pixel_proportion"] == 1.0  # type: ignore[index]
    assert 0 < results["palette_entropy"] <= 1


def test_repeated_analysis_is_exactly_deterministic() -> None:
    rng = np.random.default_rng(20260730)
    pixels = rng.integers(0, 256, (64, 48, 3), dtype=np.uint8)
    image = Image.fromarray(pixels, "RGB")

    assert _results(image) == _results(image.copy())


def test_predeclared_smooth_fixture_stability_at_768_against_1024() -> None:
    axis = np.linspace(0, 255, 1024, dtype=np.uint8)
    red = np.broadcast_to(axis, (1024, 1024))
    green = red.T
    blue = ((red.astype(np.uint16) + green.astype(np.uint16)) // 2).astype(np.uint8)
    reference_image = Image.fromarray(np.stack((red, green, blue), axis=2), "RGB")
    candidate_image = reference_image.resize((768, 768), Image.Resampling.LANCZOS)
    reference = _results(reference_image)
    candidate = _results(candidate_image)

    thresholds = {
        "luminance_mean": 0.02,
        "luminance_median": 0.03,
        "saturation_mean": 0.03,
        "saturation_median": 0.03,
        "colorfulness": 0.05,
        "shadow_luminance_tail_proportion": 0.02,
        "highlight_luminance_tail_proportion": 0.02,
        "palette_entropy": 0.08,
    }
    for name, tolerance in thresholds.items():
        assert abs(candidate[name] - reference[name]) <= tolerance  # type: ignore[operator]
    comparison = compare_palettes(
        _palette_colors(candidate["dominant_palette"]),
        _palette_colors(reference["dominant_palette"]),
    )
    assert comparison.color_distance <= 0.08
    assert comparison.proportion_l1 <= 0.15


def test_palette_matching_is_order_independent_and_detects_shift() -> None:
    first = (
        PaletteColor((8, 8, 8), 0.7),
        PaletteColor((248, 248, 248), 0.3),
    )
    reversed_palette = tuple(reversed(first))
    shifted = (
        PaletteColor((24, 8, 8), 0.7),
        PaletteColor((248, 248, 248), 0.3),
    )

    identical = compare_palettes(first, reversed_palette)
    changed = compare_palettes(first, shifted)
    assert identical.color_distance == 0
    assert identical.proportion_l1 == 0
    assert changed.color_distance > 0


def test_palette_matching_ties_and_unequal_lengths_are_deterministic() -> None:
    first = (PaletteColor((128, 128, 128), 1.0),)
    tied = (
        PaletteColor((112, 128, 128), 0.9),
        PaletteColor((144, 128, 128), 0.1),
    )
    repeated = [compare_palettes(first, tied) for _ in range(5)]

    assert repeated.count(repeated[0]) == 5
    assert repeated[0].assignments[0] == (0, 0)
    assert repeated[0].color_distance > 0
    assert repeated[0].proportion_l1 > 0


def test_palette_matching_missing_low_proportion_color_has_bounded_penalty() -> None:
    full = (
        PaletteColor((8, 8, 8), 0.95),
        PaletteColor((248, 248, 248), 0.05),
    )
    reduced = (PaletteColor((8, 8, 8), 1.0),)
    comparison = compare_palettes(full, reduced)

    assert comparison.assignments == ((0, 0), (1, None))
    assert comparison.color_distance == 0.025
    assert comparison.proportion_l1 == 0.05
