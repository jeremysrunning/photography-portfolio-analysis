"""Narrow inference-adapter failure and artifact tests."""

from __future__ import annotations

import numpy as np
import pytest

from research.people_face_calibration import detectors as people_detection
from research.people_face_calibration.detectors import DetectorLoadError, extract_yunet_detections


def test_missing_or_changed_model_has_one_sanitized_failure(tmp_path, monkeypatch) -> None:
    people_detection._verified_model.cache_clear()
    monkeypatch.setattr(people_detection.resources, "files", lambda package: tmp_path)

    with pytest.raises(DetectorLoadError) as missing:
        people_detection._verified_model("missing.onnx", "0" * 64)
    assert str(missing.value) == people_detection.MODEL_LOAD_MESSAGE
    assert str(tmp_path) not in str(missing.value)

    (tmp_path / "changed.onnx").write_bytes(b"changed")
    with pytest.raises(DetectorLoadError) as changed:
        people_detection._verified_model("changed.onnx", "0" * 64)
    assert str(changed.value) == people_detection.MODEL_LOAD_MESSAGE


def test_artifact_checksum_is_cached_once(monkeypatch) -> None:
    people_detection._verified_model.cache_clear()
    reads = 0
    original = people_detection.Path.read_bytes

    def counted(path):
        nonlocal reads
        reads += 1
        return original(path)

    monkeypatch.setattr(people_detection.Path, "read_bytes", counted)
    first = people_detection._verified_model(
        people_detection.NANODET_FILE, people_detection.NANODET_SHA256
    )
    second = people_detection._verified_model(
        people_detection.NANODET_FILE, people_detection.NANODET_SHA256
    )
    assert first == second
    assert reads == 1


@pytest.mark.parametrize(
    "raw",
    [
        np.zeros((1, 14), dtype=np.float32),
        np.zeros((15,), dtype=np.float32),
        np.full((1, 15), np.nan, dtype=np.float32),
    ],
)
def test_malformed_yunet_output_is_rejected(raw: np.ndarray) -> None:
    with pytest.raises(ValueError):
        extract_yunet_detections(raw)
