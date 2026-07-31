"""Production people-placement analyzer tests."""

from __future__ import annotations

import json
from collections.abc import Sequence

import numpy as np
import pytest
from PIL import Image

from research.people_face_calibration.analysis import (
    ANALYZER_IDENTITY,
    MAX_DETECTIONS,
    PeoplePlacementAnalyzer,
)
from research.people_face_calibration.detectors import AdapterDetection, extract_yunet_detections


class FakeAdapter:
    def __init__(self, values: Sequence[AdapterDetection]) -> None:
        self.values = tuple(values)
        self.calls = 0

    def infer(self, rgb: np.ndarray) -> tuple[AdapterDetection, ...]:
        self.calls += 1
        return self.values


def _analyze(
    people: Sequence[AdapterDetection] = (),
    faces: Sequence[AdapterDetection] = (),
) -> dict[str, object]:
    analyzer = PeoplePlacementAnalyzer(lambda: FakeAdapter(people), lambda: FakeAdapter(faces))
    results = analyzer.analyze(None, Image.new("RGB", (100, 100)), None)  # type: ignore[arg-type]
    return {result.name: result.value for result in results}


def test_identity_preview_contract_and_no_detection_catalog() -> None:
    analyzer = PeoplePlacementAnalyzer(lambda: FakeAdapter(()), lambda: FakeAdapter(()))
    results = _analyze()

    assert analyzer.identity == ANALYZER_IDENTITY
    assert analyzer.preview_request.maximum_edge == 768
    assert analyzer.preview_request.storage_mode.value == "memory"
    assert not analyzer.allows_empty_results
    assert results["person_detections"] == ()
    assert results["face_detections"] == ()
    assert results["person_count"] == 0
    assert results["face_count"] == 0
    assert results["people_count_category"] == "none"
    assert results["largest_person_box_area"] == 0
    assert results["person_box_union_coverage"] == 0
    assert "person_box_area_weighted_centroid" not in results


def test_retained_and_accepted_boundaries_and_accepted_only_geometry() -> None:
    results = _analyze(
        people=(
            AdapterDetection((0, 0, 50, 50), 0.20, 0),
            AdapterDetection((50, 0, 100, 100), 0.35, 1),
            AdapterDetection((0, 50, 25, 100), 0.199999, 2),
        ),
        faces=(
            AdapterDetection((0, 0, 20, 20), 0.40, 0),
            AdapterDetection((80, 80, 100, 100), 0.60, 1),
            AdapterDetection((40, 40, 60, 60), 0.399999, 2),
        ),
    )

    people = results["person_detections"]
    faces = results["face_detections"]
    assert len(people) == 2  # type: ignore[arg-type]
    assert [item["accepted"] for item in people] == [True, False]  # type: ignore[index]
    assert len(faces) == 2  # type: ignore[arg-type]
    assert [item["accepted"] for item in faces] == [True, False]  # type: ignore[index]
    assert results["person_count"] == 1
    assert results["face_count"] == 1
    assert results["largest_person_box_area"] == 0.5
    assert results["person_box_union_coverage"] == 0.5
    assert results["person_box_area_weighted_centroid"] == {
        "type": "point",
        "x": 0.75,
        "y": 0.5,
    }


def test_low_confidence_evidence_is_distinct_from_no_detection() -> None:
    results = _analyze(
        people=(AdapterDetection((10, 10, 20, 20), 0.2, 0),),
        faces=(AdapterDetection((10, 10, 20, 20), 0.4, 0),),
    )

    assert len(results["person_detections"]) == 1  # type: ignore[arg-type]
    assert len(results["face_detections"]) == 1  # type: ignore[arg-type]
    assert results["person_count"] == results["face_count"] == 0
    assert results["people_count_category"] == "none"
    assert results["person_box_union_coverage"] == 0


def test_nms_clipping_order_union_and_maximum_are_deterministic() -> None:
    values = [
        AdapterDetection((-10, 0, 60, 100), 0.8, 0),
        AdapterDetection((0, 0, 60, 100), 0.8, 1),
        AdapterDetection((50, 0, 100, 100), 0.7, 2),
        *(
            AdapterDetection((index, index, index + 1, index + 1), 0.5, index + 3)
            for index in range(101)
        ),
    ]
    results = _analyze(people=values)

    assert len(results["person_detections"]) == MAX_DETECTIONS  # type: ignore[arg-type]
    assert results["person_detections"][0]["box"]["x"] == 0  # type: ignore[index]
    assert 0 <= results["person_box_union_coverage"] <= 1  # type: ignore[operator]


def test_edge_clipping_remains_normalized_for_non_power_of_two_dimensions() -> None:
    analyzer = PeoplePlacementAnalyzer(
        lambda: FakeAdapter((AdapterDetection((1, 1, 997, 613), 1.0, 0),)),
        lambda: FakeAdapter(()),
    )
    results = analyzer.analyze(  # type: ignore[arg-type]
        None,
        Image.new("RGB", (997, 613)),
        None,
    )
    detection = next(result for result in results if result.name == "person_detections")
    box = detection.value[0]["box"]  # type: ignore[index]

    assert box["x"] + box["width"] <= 1  # type: ignore[operator]
    assert box["y"] + box["height"] <= 1  # type: ignore[operator]


def test_yunet_landmarks_are_discarded_at_adapter_boundary() -> None:
    sentinels = [101.1 + index for index in range(10)]
    raw = np.array([[1, 2, 3, 4, *sentinels, 0.75]], dtype=np.float32)
    output = extract_yunet_detections(raw)
    result = _analyze(faces=output)
    serialized = json.dumps(result, default=list)

    assert output[0].box == (1, 2, 4, 6)
    assert output[0].confidence == pytest.approx(0.75)
    assert output[0].raw_index == 0
    assert all(str(value) not in serialized for value in sentinels)
    forbidden = {
        "landmarks",
        "keypoints",
        "embeddings",
        "descriptors",
        "identities",
        "tracking_ids",
        "demographics",
        "emotion",
    }
    assert forbidden.isdisjoint(result["face_detections"][0])  # type: ignore[arg-type,index]


def test_detector_instances_are_lazy_and_reused_per_thread() -> None:
    person = FakeAdapter(())
    face = FakeAdapter(())
    counts = {"person": 0, "face": 0}

    def person_factory() -> FakeAdapter:
        counts["person"] += 1
        return person

    def face_factory() -> FakeAdapter:
        counts["face"] += 1
        return face

    analyzer = PeoplePlacementAnalyzer(person_factory, face_factory)
    assert counts == {"person": 0, "face": 0}
    analyzer.analyze(None, Image.new("RGB", (2, 2)), None)  # type: ignore[arg-type]
    analyzer.analyze(None, Image.new("RGB", (2, 2)), None)  # type: ignore[arg-type]
    assert counts == {"person": 1, "face": 1}
    assert person.calls == face.calls == 2


@pytest.mark.parametrize(
    "value",
    [
        AdapterDetection((0, 0, 1, 1), 0.0, 0),
        AdapterDetection((0, 0, 1, 1), 1.0, 0),
    ],
)
def test_adapter_confidence_contract_accepts_boundaries(value: AdapterDetection) -> None:
    assert 0 <= value.confidence <= 1


@pytest.mark.parametrize("confidence", [-0.1, 1.1, float("nan")])
def test_adapter_rejects_invalid_confidence(confidence: float) -> None:
    with pytest.raises(ValueError, match="confidence"):
        AdapterDetection((0, 0, 1, 1), confidence, 0)
