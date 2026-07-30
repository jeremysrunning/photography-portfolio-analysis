from dataclasses import FrozenInstanceError

import pytest

from ppa.visual import (
    AnalyzerIdentity,
    NormalizedBoundingBox,
    NormalizedPoint,
    VisualResult,
    VisualResultKind,
)


def test_identity_and_non_null_json_values_are_validated() -> None:
    with pytest.raises(ValueError, match="configuration_version"):
        AnalyzerIdentity("color", "1.0", "")
    with pytest.raises(ValueError, match="must not be missing"):
        VisualResult("brightness", VisualResultKind.MEASUREMENT, None, "mean", "1")
    with pytest.raises(ValueError, match="JSON-compatible"):
        VisualResult("bytes", VisualResultKind.MEASUREMENT, b"image", "raw", "1")


def test_visual_values_are_deeply_immutable_and_preserve_boolean_and_structured_json() -> None:
    original = {"palette": [{"hex": "#ffffff", "share": 0.5}], "neutral": True}
    result = VisualResult(
        "palette",
        VisualResultKind.MEASUREMENT,
        original,
        "deterministic-palette",
        "1",
    )
    original["palette"][0]["hex"] = "#000000"

    assert result.value["palette"][0]["hex"] == "#ffffff"  # type: ignore[index]
    with pytest.raises(TypeError):
        result.value["neutral"] = False  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        result.name = "changed"  # type: ignore[misc]


def test_confidence_distinguishes_zero_none_and_deterministic_measurements() -> None:
    zero = VisualResult(
        "scene",
        VisualResultKind.CLASSIFICATION,
        "indoor",
        "classifier",
        "1",
        confidence=0.0,
        model_name="small-model",
        model_version="1",
    )
    missing = VisualResult(
        "scene",
        VisualResultKind.CLASSIFICATION,
        "indoor",
        "classifier",
        "1",
    )

    assert zero.confidence == 0.0
    assert missing.confidence is None
    with pytest.raises(ValueError, match="must not carry confidence"):
        VisualResult(
            "brightness",
            VisualResultKind.MEASUREMENT,
            0.4,
            "mean",
            "1",
            confidence=0.5,
        )


def test_normalized_geometry_is_validated_and_serialized() -> None:
    point = NormalizedPoint(0.25, 1.0)
    box = NormalizedBoundingBox(0.1, 0.2, 0.3, 0.4)

    assert point.as_json()["type"] == "point"
    assert box.as_json()["width"] == 0.3
    with pytest.raises(ValueError, match="within"):
        NormalizedBoundingBox(0.8, 0.2, 0.3, 0.4)
    with pytest.raises(ValueError, match="positive"):
        NormalizedBoundingBox(0.1, 0.2, 0.0, 0.4)
