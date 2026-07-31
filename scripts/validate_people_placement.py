"""Run aggregate-only cross-resolution validation of people-placement detection."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from pathlib import Path
from statistics import median

from ppa.models import MediaType, Portfolio
from ppa.sources import PreviewRequest
from ppa.sources.smugmug import SmugMugSource
from ppa.storage import SQLitePortfolioRepository
from research.people_face_calibration.analysis import PeoplePlacementAnalyzer
from research.people_face_calibration.detectors import NanoDetAdapter, YuNetAdapter

EDGES = (512, 768, 1024)
SAMPLE_SEED = "issue-38-people-placement-v1"
# Declared before real output is examined. Stability is consistency, not accuracy.
COUNT_AGREEMENT_MINIMUM = {
    512: {"person": 0.80, "face": 0.70},
    768: {"person": 0.90, "face": 0.85},
}
MEDIAN_MATCHED_IOU_MINIMUM = {
    512: {"person": 0.75, "face": 0.65},
    768: {"person": 0.85, "face": 0.75},
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("--sample-size", type=int, default=20)
    args = parser.parse_args()
    if not 1 <= args.sample_size <= 32:
        parser.error("--sample-size must be between 1 and 32")
    api_key = os.environ.get("PPA_SMUGMUG_API_KEY", "")
    if not api_key.strip():
        parser.error("PPA_SMUGMUG_API_KEY is required")
    portfolio = _load_portfolio(args.database)
    sample = _sample(portfolio, args.sample_size)
    source = SmugMugSource(portfolio.source_url, api_key)
    analyzer = PeoplePlacementAnalyzer(lambda: NanoDetAdapter(), lambda: YuNetAdapter())
    evidence: dict[int, list[dict[str, object]]] = {edge: [] for edge in EDGES}
    failures: Counter[str] = Counter()
    downloaded = 0
    for asset in sample:
        asset_evidence: dict[int, dict[str, object]] = {}
        for edge in EDGES:
            try:
                with source.open_preview(asset, PreviewRequest(edge)) as preview:
                    results = analyzer.analyze(asset, preview.image, preview.metadata)
                    asset_evidence[edge] = {result.name: result.value for result in results}
                    downloaded += preview.metadata.downloaded_encoded_byte_count
            except Exception as error:
                failures[f"preview_or_analysis:{type(error).__name__}"] += 1
                break
        if len(asset_evidence) == len(EDGES):
            for edge in EDGES:
                evidence[edge].append(asset_evidence[edge])
    output = _aggregate(evidence, failures, downloaded, len(sample))
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if output["stability_gate_passed"] and not failures else 1


def _load_portfolio(database: Path) -> Portfolio:
    with SQLitePortfolioRepository(database) as repository:
        keys = repository.list_keys()
        if len(keys) != 1:
            raise ValueError("validation requires exactly one portfolio")
        portfolio = repository.get(*keys[0])
    if portfolio is None or portfolio.source_name != "smugmug":
        raise ValueError("validation requires one persisted SmugMug portfolio")
    return portfolio


def _sample(portfolio: Portfolio, size: int):
    photographs = [
        asset for asset in portfolio.assets if asset.metadata.media_type is MediaType.PHOTOGRAPH
    ]
    return tuple(
        sorted(
            photographs,
            key=lambda asset: hashlib.sha256(f"{SAMPLE_SEED}:{asset.source_id}".encode()).digest(),
        )[:size]
    )


def _aggregate(evidence, failures, downloaded: int, selected: int) -> dict[str, object]:
    reference = evidence[1024]
    comparisons: dict[str, object] = {}
    gate = len(reference) == selected
    for edge in (512, 768):
        rows = evidence[edge]
        family_output = {}
        for family in ("person", "face"):
            counts_equal: list[bool] = []
            matched_ious: list[float] = []
            unmatched = 0
            for candidate, baseline in zip(rows, reference, strict=False):
                candidate_boxes = _accepted_boxes(candidate[f"{family}_detections"])
                baseline_boxes = _accepted_boxes(baseline[f"{family}_detections"])
                counts_equal.append(len(candidate_boxes) == len(baseline_boxes))
                ious, missing = _match(candidate_boxes, baseline_boxes)
                matched_ious.extend(ious)
                unmatched += missing
            agreement = sum(counts_equal) / len(counts_equal) if counts_equal else 0.0
            matched_median = median(matched_ious) if matched_ious else 1.0
            family_gate = (
                agreement >= COUNT_AGREEMENT_MINIMUM[edge][family]
                and matched_median >= MEDIAN_MATCHED_IOU_MINIMUM[edge][family]
            )
            gate &= family_gate
            family_output[family] = {
                "count_agreement": round(agreement, 4),
                "matched_box_median_iou": round(matched_median, 4),
                "unmatched_detections": unmatched,
                "gate_passed": family_gate,
            }
        comparisons[f"{edge}_versus_1024"] = family_output
    return {
        "artifact_kind": "aggregate_non_identifying_people_placement_validation",
        "selected": selected,
        "completed_all_three_edges": len(reference),
        "requested_edges": list(EDGES),
        "downloaded_preview_bytes": downloaded,
        "failure_categories": dict(sorted(failures.items())),
        "comparisons": comparisons,
        "stability_gate_passed": gate,
        "raw_records_retained": False,
    }


def _accepted_boxes(value) -> list[dict[str, float]]:
    return [dict(item["box"]) for item in value if item["accepted"]]


def _match(first, second) -> tuple[list[float], int]:
    candidates = sorted(
        (
            (-_iou(left, right), left_index, right_index)
            for left_index, left in enumerate(first)
            for right_index, right in enumerate(second)
        )
    )
    used_left: set[int] = set()
    used_right: set[int] = set()
    matched: list[float] = []
    for negative_iou, left_index, right_index in candidates:
        iou = -negative_iou
        if iou < 0.5 or left_index in used_left or right_index in used_right:
            continue
        used_left.add(left_index)
        used_right.add(right_index)
        matched.append(iou)
    return matched, len(first) + len(second) - 2 * len(matched)


def _iou(first, second) -> float:
    left = max(first["x"], second["x"])
    top = max(first["y"], second["y"])
    right = min(first["x"] + first["width"], second["x"] + second["width"])
    bottom = min(first["y"] + first["height"], second["y"] + second["height"])
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    union = first["width"] * first["height"] + second["width"] * second["height"] - intersection
    return intersection / union if union else 0.0


if __name__ == "__main__":
    raise SystemExit(main())
