"""Local calibration matrix and aggregate privacy tests."""

from datetime import UTC, datetime

from ppa.models import (
    Asset,
    AssetMetadata,
    Gallery,
    GalleryPlacement,
    MediaType,
    Portfolio,
    SourceReference,
)
from scripts.calibrate_people_face_detectors import (
    _candidate,
    _manual_review,
    _stratified_sample,
)


def _detection(confidence: float, raw_index: int = 0):
    return {
        "box": [0.1, 0.1, 0.4, 0.6],
        "confidence": confidence,
        "raw_index": raw_index,
    }


def _record(token: str, people, faces):
    return {
        "sample_token": token,
        "edges": {
            str(edge): {
                "people": people[edge],
                "faces": faces[edge],
            }
            for edge in (512, 768, 1024)
        },
    }


def test_candidate_reports_manual_accuracy_separately_from_resolution_consistency() -> None:
    records = [
        _record(
            "sample-001",
            {
                512: [_detection(0.34)],
                768: [_detection(0.35)],
                1024: [_detection(0.36)],
            },
            {512: [], 768: [], 1024: []},
        )
    ]
    annotations = {"sample-001": {"visible_person_count": "1", "confidence": "high"}}

    candidate = _candidate(records, annotations, "person", 0.20, 0.35, 0.60)

    assert candidate["edges"]["512"]["visible_count_agreement"] == 0
    assert candidate["edges"]["512"]["accepted_count_agreement_with_1024"] == 0
    assert candidate["edges"]["768"]["visible_count_agreement"] == 1
    assert candidate["edges"]["768"]["accepted_count_agreement_with_1024"] == 1
    assert candidate["edges"]["1024"]["precision_like_rate"] == 1
    assert candidate["edges"]["1024"]["recall_like_rate"] == 1


def test_nms_boundary_and_unequal_detection_counts_are_deterministic() -> None:
    duplicate = _detection(0.9)
    second = _detection(0.8, 1)
    records = [
        _record(
            "sample-001",
            {
                512: [duplicate, second],
                768: [duplicate, second],
                1024: [duplicate],
            },
            {512: [], 768: [], 1024: []},
        )
    ]
    annotations = {"sample-001": {"visible_person_count": "1", "confidence": "medium"}}

    first = _candidate(records, annotations, "person", 0.20, 0.35, 0.60)
    repeated = _candidate(records, annotations, "person", 0.20, 0.35, 0.60)

    assert first == repeated
    assert first["edges"]["512"]["accepted_total"] == 1
    assert first["edges"]["1024"]["accepted_total"] == 1


def test_strata_summary_describes_selected_sample_not_full_population() -> None:
    assets = tuple(
        Asset(
            SourceReference(f"asset-{index}", f"https://example.test/{index}"),
            AssetMetadata(
                MediaType.PHOTOGRAPH,
                captured_at=datetime(2000 + index, 1, 1, tzinfo=UTC),
                exif={"Model": f"camera-{index}"},
            ),
        )
        for index in range(6)
    )
    galleries = tuple(
        Gallery(
            SourceReference(f"gallery-{index}", f"https://example.test/g/{index}"),
            f"Gallery {index}",
            placements=(GalleryPlacement(asset.source_id),),
        )
        for index, asset in enumerate(assets)
    )
    portfolio = Portfolio(
        "test",
        SourceReference("portfolio", "https://example.test/portfolio"),
        "Portfolio",
        galleries=galleries,
        assets=assets,
    )

    selected, strata = _stratified_sample(portfolio, 2)

    assert len(selected) == 2
    assert strata["camera_hash_groups"] == 2
    assert strata["gallery_hash_groups"] == 2


def test_manual_review_preserves_confidence_and_condition_denominators() -> None:
    base = {
        "visible_person_count": "1",
        "visible_face_count": "1",
        "obvious_person_false_positives": "2",
        "obvious_person_false_negatives": "0",
        "obvious_face_false_positives": "0",
        "obvious_face_false_negatives": "1",
        "small_subject": "yes",
        "occlusion": "no",
        "edge_crop": "yes",
    }
    annotations = {
        "sample-001": {**base, "confidence": "high"},
        "sample-002": {**base, "confidence": "low"},
    }

    result = _manual_review(annotations)

    assert result["annotation_confidence_counts"] == {"high": 1, "low": 1}
    assert result["confidence_sensitivity"]["high_only"]["person"]["images"] == 1
    assert result["conditions"]["small_subject"]["true"]["images"] == 2
    assert result["conditions"]["occlusion"]["false"]["images"] == 2
