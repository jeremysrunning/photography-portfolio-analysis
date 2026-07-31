"""Aggregate-only people-placement stability validation tests."""

import pytest

from scripts.validate_people_placement import _aggregate, _match


def _row(person=(), face=()):
    return {
        "person_detections": tuple({"accepted": accepted, "box": box} for accepted, box in person),
        "face_detections": tuple({"accepted": accepted, "box": box} for accepted, box in face),
    }


def test_matching_is_iou_based_not_list_index_and_reports_unmatched() -> None:
    left = [
        {"x": 0.0, "y": 0.0, "width": 0.2, "height": 0.2},
        {"x": 0.7, "y": 0.7, "width": 0.2, "height": 0.2},
    ]
    right = list(reversed(left))

    matched, unmatched = _match(left, right)

    assert matched == pytest.approx([1.0, 1.0])
    assert unmatched == 0


def test_aggregate_excludes_low_confidence_evidence_and_applies_family_gates() -> None:
    box = {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4}
    row = _row(person=((True, box), (False, box)), face=((True, box),))
    evidence = {512: [row], 768: [row], 1024: [row]}

    output = _aggregate(evidence, {}, 123, 1)

    assert output["stability_gate_passed"]
    assert output["raw_records_retained"] is False
    assert output["comparisons"]["512_versus_1024"]["person"] == {
        "count_agreement": 1.0,
        "matched_box_median_iou": 1.0,
        "unmatched_detections": 0,
        "gate_passed": True,
    }


def test_incomplete_resolution_sets_do_not_change_comparison_alignment() -> None:
    box = {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4}
    complete = _row(person=((True, box),))
    evidence = {512: [complete], 768: [complete], 1024: [complete]}

    output = _aggregate(evidence, {"preview_or_analysis:ValueError": 1}, 10, 2)

    assert output["completed_all_three_edges"] == 1
    assert not output["stability_gate_passed"]
