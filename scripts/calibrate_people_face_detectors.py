"""Collect local detector evidence and evaluate aggregate calibration candidates."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import time
from collections import Counter, defaultdict
from math import hypot
from pathlib import Path
from statistics import median

from PIL import ImageDraw

from ppa.models import MediaType, Portfolio
from ppa.sources import PreviewRequest
from ppa.sources.smugmug import SmugMugSource
from ppa.storage import SQLitePortfolioRepository
from research.people_face_calibration.analysis import _postprocess, _union_area
from research.people_face_calibration.detectors import (
    AdapterDetection,
    NanoDetAdapter,
    YuNetAdapter,
)
from research.people_face_calibration.image_normalization import normalized_srgb_array

EDGES = (512, 768, 1024)
PERSON_RETENTIONS = (0.15, 0.20, 0.25)
PERSON_ACCEPTED = (0.30, 0.35, 0.40, 0.45)
PERSON_NMS = (0.50, 0.60, 0.70)
FACE_RETENTIONS = (0.30, 0.40, 0.50)
FACE_ACCEPTED = (0.50, 0.60, 0.70)
FACE_NMS = (0.20, 0.30, 0.40)
SEED = "issue-49-detector-calibration-v1"
ANNOTATION_FIELDS = (
    "sample_token",
    "visible_person_count",
    "visible_face_count",
    "obvious_person_false_positives",
    "obvious_person_false_negatives",
    "obvious_face_false_positives",
    "obvious_face_false_negatives",
    "small_subject",
    "occlusion",
    "edge_crop",
    "confidence",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    collect = subparsers.add_parser("collect")
    collect.add_argument("database", type=Path)
    collect.add_argument("local_directory", type=Path)
    collect.add_argument("--sample-size", type=int, default=48)
    evaluate = subparsers.add_parser("evaluate")
    evaluate.add_argument("local_directory", type=Path)
    evaluate.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.command == "collect":
        if not 40 <= args.sample_size <= 60:
            parser.error("--sample-size must be between 40 and 60")
        return _collect(args.database, args.local_directory, args.sample_size)
    return _evaluate(args.local_directory, args.output)


def _collect(database: Path, directory: Path, sample_size: int) -> int:
    api_key = os.environ.get("PPA_SMUGMUG_API_KEY", "")
    if not api_key.strip():
        raise ValueError("PPA_SMUGMUG_API_KEY is required")
    directory = directory.resolve()
    if directory.exists() and any(directory.iterdir()):
        raise ValueError("local calibration directory must be absent or empty")
    directory.mkdir(parents=True, exist_ok=True)
    previews = directory / "previews"
    overlays = directory / "overlays"
    previews.mkdir()
    overlays.mkdir()
    portfolio = _load_portfolio(database)
    sample, strata = _stratified_sample(portfolio, sample_size)
    source = SmugMugSource(portfolio.source_url, api_key)
    person = NanoDetAdapter()
    face = YuNetAdapter(0.30)
    records: list[dict[str, object]] = []
    failures: Counter[str] = Counter()
    runtime: defaultdict[str, list[float]] = defaultdict(list)
    downloaded = 0
    for index, asset in enumerate(sample, 1):
        token = f"sample-{index:03d}"
        edge_records: dict[str, object] = {}
        for edge in EDGES:
            try:
                started = time.perf_counter()
                with source.open_preview(asset, PreviewRequest(edge)) as preview:
                    acquisition_done = time.perf_counter()
                    image = preview.image.copy()
                    rgb = normalized_srgb_array(image)
                    normalized_done = time.perf_counter()
                    raw_people = person.infer(rgb)
                    people_done = time.perf_counter()
                    raw_faces = face.infer(rgb)
                    faces_done = time.perf_counter()
                    downloaded += preview.metadata.downloaded_encoded_byte_count
                    edge_records[str(edge)] = {
                        "width": image.width,
                        "height": image.height,
                        "people": _compact(raw_people, image.width, image.height, 0.15),
                        "faces": _compact(raw_faces, image.width, image.height, 0.30),
                    }
                    runtime["preview_acquisition"].append(acquisition_done - started)
                    runtime["normalization"].append(normalized_done - acquisition_done)
                    runtime["person_inference"].append(people_done - normalized_done)
                    runtime["face_inference"].append(faces_done - people_done)
                    if edge == 1024:
                        image.save(previews / f"{token}.png", format="PNG")
                        _overlay(image, edge_records[str(edge)]).save(
                            overlays / f"{token}.png", format="PNG"
                        )
                    image.close()
            except Exception as error:
                failures[type(error).__name__] += 1
                break
        if len(edge_records) == len(EDGES):
            records.append({"sample_token": token, "edges": edge_records})
    (directory / "raw-local.json").write_text(
        json.dumps({"records": records}, separators=(",", ":")), encoding="utf-8"
    )
    with (directory / "annotations.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, ANNOTATION_FIELDS)
        writer.writeheader()
        for record in records:
            writer.writerow({"sample_token": record["sample_token"]})
    summary = {
        "artifact_kind": "local_detector_calibration_collection_summary",
        "requested": sample_size,
        "complete_triplets": len(records),
        "failure_categories": dict(sorted(failures.items())),
        "requested_edges": list(EDGES),
        "downloaded_preview_bytes": downloaded,
        "metadata_strata": strata,
        "mean_seconds": {
            name: round(sum(values) / len(values), 4) for name, values in sorted(runtime.items())
        },
        "raw_records_are_local": True,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if len(records) == sample_size else 1


def _evaluate(directory: Path, output: Path | None) -> int:
    payload = json.loads((directory / "raw-local.json").read_text(encoding="utf-8"))
    annotations = _annotations(directory / "annotations.csv")
    if set(annotations) != {record["sample_token"] for record in payload["records"]}:
        raise ValueError("every collected sample requires one annotation row")
    candidates = []
    for family, retentions, accepted_values, nms_values in (
        ("person", PERSON_RETENTIONS, PERSON_ACCEPTED, PERSON_NMS),
        ("face", FACE_RETENTIONS, FACE_ACCEPTED, FACE_NMS),
    ):
        for retention in retentions:
            for accepted in accepted_values:
                if accepted < retention:
                    continue
                for nms in nms_values:
                    candidates.append(
                        _candidate(
                            payload["records"], annotations, family, retention, accepted, nms
                        )
                    )
    aggregate = {
        "artifact_kind": "aggregate_non_identifying_detector_calibration",
        "sample_size": len(payload["records"]),
        "candidates": candidates,
        "baseline_manual_review": _manual_review(annotations),
        "contains_identifiers_or_per_image_rows": False,
    }
    encoded = json.dumps(aggregate, indent=2, sort_keys=True)
    if output:
        output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0


def _candidate(records, annotations, family, retention, accepted, nms):
    edge_counts: dict[int, list[int]] = defaultdict(list)
    edge_retained: dict[int, list[int]] = defaultdict(list)
    edge_detections: dict[int, list[tuple]] = defaultdict(list)
    truth_total = 0
    predicted_total: dict[int, int] = defaultdict(int)
    exact: dict[int, int] = defaultdict(int)
    evidence_key = "people" if family == "person" else "faces"
    for record in records:
        truth = int(annotations[record["sample_token"]][f"visible_{family}_count"])
        truth_total += truth
        for edge in EDGES:
            raw = tuple(
                AdapterDetection(tuple(item["box"]), item["confidence"], item["raw_index"])
                for item in record["edges"][str(edge)][evidence_key]
            )
            detections = _postprocess(
                raw,
                family,
                1,
                1,
                retention,
                accepted,
                nms,
            )
            count = sum(item.accepted for item in detections)
            edge_detections[edge].append(detections)
            edge_retained[edge].append(len(detections))
            edge_counts[edge].append(count)
            predicted_total[edge] += count
            exact[edge] += count == truth
    output = {
        "family": family,
        "retention": retention,
        "accepted": accepted,
        "nms": nms,
        "edges": {},
    }
    for edge in EDGES:
        true_positive_like = sum(
            min(predicted, int(annotations[record["sample_token"]][f"visible_{family}_count"]))
            for predicted, record in zip(edge_counts[edge], records, strict=True)
        )
        output["edges"][str(edge)] = {
            "visible_count_agreement": round(exact[edge] / len(records), 4),
            "precision_like_rate": round(
                true_positive_like / predicted_total[edge] if predicted_total[edge] else 1.0, 4
            ),
            "recall_like_rate": round(true_positive_like / truth_total if truth_total else 1.0, 4),
            "accepted_total": predicted_total[edge],
            "annotation_confidence_sensitivity": _candidate_sensitivity(
                records, annotations, family, edge_counts[edge], edge_counts[1024]
            ),
        }
    for edge in (512, 768):
        output["edges"][str(edge)]["accepted_count_agreement_with_1024"] = round(
            sum(
                left == right
                for left, right in zip(edge_counts[edge], edge_counts[1024], strict=True)
            )
            / len(records),
            4,
        )
        output["edges"][str(edge)]["retained_count_agreement_with_1024"] = round(
            sum(
                left == right
                for left, right in zip(edge_retained[edge], edge_retained[1024], strict=True)
            )
            / len(records),
            4,
        )
        output["edges"][str(edge)]["geometry_vs_1024"] = _geometry_comparison(
            edge_detections[edge], edge_detections[1024], edge
        )
    for edge in EDGES:
        output["edges"][str(edge)]["accepted_box_area_buckets"] = _area_buckets(
            edge_detections[edge]
        )
        if family == "face":
            dimensions = [
                (
                    item.box.width * edge,
                    item.box.height * edge,
                )
                for detections in edge_detections[edge]
                for item in detections
                if item.accepted
            ]
            output["edges"][str(edge)]["accepted_face_pixel_box_median"] = (
                {
                    "width": round(median(item[0] for item in dimensions), 2),
                    "height": round(median(item[1] for item in dimensions), 2),
                }
                if dimensions
                else None
            )
    return output


def _candidate_sensitivity(records, annotations, family, counts, reference_counts):
    output = {}
    for name, allowed in (
        ("all", {"high", "medium", "low"}),
        ("high_only", {"high"}),
        ("high_and_medium", {"high", "medium"}),
    ):
        indexes = [
            index
            for index, record in enumerate(records)
            if annotations[record["sample_token"]]["confidence"].strip().lower() in allowed
        ]
        truth = [
            int(annotations[records[index]["sample_token"]][f"visible_{family}_count"])
            for index in indexes
        ]
        predicted = [counts[index] for index in indexes]
        reference = [reference_counts[index] for index in indexes]
        true_positive_like = sum(
            min(left, right) for left, right in zip(predicted, truth, strict=True)
        )
        if not indexes:
            output[name] = {
                "images": 0,
                "visible_count": 0,
                "accepted_count": 0,
                "visible_count_agreement": None,
                "accepted_count_agreement_with_1024": None,
                "count_derived_precision_like_rate": None,
                "count_derived_recall_like_rate": None,
            }
            continue
        output[name] = {
            "images": len(indexes),
            "visible_count": sum(truth),
            "accepted_count": sum(predicted),
            "visible_count_agreement": round(
                sum(left == right for left, right in zip(predicted, truth, strict=True))
                / len(indexes),
                4,
            ),
            "accepted_count_agreement_with_1024": round(
                sum(left == right for left, right in zip(predicted, reference, strict=True))
                / len(indexes),
                4,
            ),
            "count_derived_precision_like_rate": round(
                true_positive_like / sum(predicted) if sum(predicted) else 1.0, 4
            ),
            "count_derived_recall_like_rate": round(
                true_positive_like / sum(truth) if sum(truth) else 1.0, 4
            ),
        }
    return output


def _manual_review(annotations):
    subsets = {
        "all": tuple(annotations.values()),
        "high_only": tuple(row for row in annotations.values() if row["confidence"] == "high"),
        "high_and_medium": tuple(
            row for row in annotations.values() if row["confidence"] in {"high", "medium"}
        ),
    }
    return {
        "annotation_confidence_counts": dict(
            sorted(Counter(row["confidence"] for row in annotations.values()).items())
        ),
        "confidence_sensitivity": {
            name: {family: _manual_family(rows, family) for family in ("person", "face")}
            for name, rows in subsets.items()
        },
        "conditions": {
            condition: {
                state: {
                    "images": len(rows),
                    "people": _manual_family(rows, "person"),
                    "faces": _manual_family(rows, "face"),
                }
                for state, rows in (
                    (
                        "true",
                        tuple(row for row in annotations.values() if _boolean(row[condition])),
                    ),
                    (
                        "false",
                        tuple(row for row in annotations.values() if not _boolean(row[condition])),
                    ),
                )
            }
            for condition in ("small_subject", "occlusion", "edge_crop")
        },
    }


def _manual_family(rows, family):
    visible = sum(int(row[f"visible_{family}_count"]) for row in rows)
    false_positives = sum(int(row[f"obvious_{family}_false_positives"]) for row in rows)
    false_negatives = sum(int(row[f"obvious_{family}_false_negatives"]) for row in rows)
    matched = max(0, visible - false_negatives)
    return {
        "images": len(rows),
        "visible_count": visible,
        "obvious_false_positives": false_positives,
        "obvious_false_negatives": false_negatives,
        "false_positives_per_image": round(false_positives / len(rows), 4) if rows else None,
        "false_negatives_per_image": round(false_negatives / len(rows), 4) if rows else None,
        "bounded_manual_precision_like_rate": round(
            matched / (matched + false_positives) if matched + false_positives else 1.0, 4
        ),
        "bounded_manual_recall_like_rate": round(matched / visible if visible else 1.0, 4),
    }


def _geometry_comparison(candidate_sets, reference_sets, edge: int):
    ious: list[float] = []
    confidence_differences: list[float] = []
    centroid_distances: list[float] = []
    largest_area_differences: list[float] = []
    union_differences: list[float] = []
    unmatched = 0
    for candidate, reference in zip(candidate_sets, reference_sets, strict=True):
        candidate = tuple(item for item in candidate if item.accepted)
        reference = tuple(item for item in reference if item.accepted)
        pairs, missing = _matched_pairs(candidate, reference)
        unmatched += missing
        ious.extend(pair[0] for pair in pairs)
        confidence_differences.extend(
            abs(pair[1].confidence - pair[2].confidence) for pair in pairs
        )
        if candidate and reference:
            first = _centroid(candidate)
            second = _centroid(reference)
            centroid_distances.append(hypot(first[0] - second[0], first[1] - second[1]))
        largest_area_differences.append(
            abs(
                max((item.area for item in candidate), default=0.0)
                - max((item.area for item in reference), default=0.0)
            )
        )
        union_differences.append(abs(_union_area(candidate) - _union_area(reference)))
    return {
        "comparison_edge": edge,
        "matched_box_iou": _distribution(ious),
        "matched_confidence_absolute_difference": _distribution(confidence_differences),
        "area_weighted_centroid_distance": _distribution(centroid_distances),
        "largest_box_area_absolute_difference": _distribution(largest_area_differences),
        "union_coverage_absolute_difference": _distribution(union_differences),
        "unmatched_detections": unmatched,
    }


def _matched_pairs(first, second):
    possible = sorted(
        (
            (-_iou(left, right), left.raw_index, right.raw_index, left, right)
            for left in first
            for right in second
        ),
        key=lambda item: item[:3],
    )
    used_left: set[int] = set()
    used_right: set[int] = set()
    pairs = []
    for negative_iou, left_index, right_index, left, right in possible:
        iou = -negative_iou
        if iou < 0.5 or left_index in used_left or right_index in used_right:
            continue
        used_left.add(left_index)
        used_right.add(right_index)
        pairs.append((iou, left, right))
    return pairs, len(first) + len(second) - 2 * len(pairs)


def _iou(first, second):
    left = max(first.box.x, second.box.x)
    top = max(first.box.y, second.box.y)
    right = min(first.box.x + first.box.width, second.box.x + second.box.width)
    bottom = min(first.box.y + first.box.height, second.box.y + second.box.height)
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    union = first.area + second.area - intersection
    return intersection / union if union else 0.0


def _centroid(detections):
    area = sum(item.area for item in detections)
    return (
        sum((item.box.x + item.box.width / 2) * item.area for item in detections) / area,
        sum((item.box.y + item.box.height / 2) * item.area for item in detections) / area,
    )


def _distribution(values):
    ordered = sorted(values)
    if not ordered:
        return {"count": 0, "minimum": None, "median": None, "maximum": None}
    return {
        "count": len(ordered),
        "minimum": round(ordered[0], 4),
        "median": round(median(ordered), 4),
        "maximum": round(ordered[-1], 4),
    }


def _area_buckets(detection_sets):
    counts = Counter()
    for detections in detection_sets:
        for item in detections:
            if not item.accepted:
                continue
            area = item.area
            bucket = (
                "below_0.1_percent"
                if area < 0.001
                else "0.1_to_0.5_percent"
                if area < 0.005
                else "0.5_to_2_percent"
                if area < 0.02
                else "2_to_10_percent"
                if area < 0.10
                else "above_10_percent"
            )
            counts[bucket] += 1
    return dict(sorted(counts.items()))


def _compact(raw, width: int, height: int, minimum: float):
    values = []
    for item in raw:
        if item.confidence < minimum:
            continue
        left = max(0.0, min(width, item.box[0])) / width
        top = max(0.0, min(height, item.box[1])) / height
        right = max(0.0, min(width, item.box[2])) / width
        bottom = max(0.0, min(height, item.box[3])) / height
        if right > left and bottom > top:
            values.append(
                {
                    "box": [left, top, right, bottom],
                    "confidence": item.confidence,
                    "raw_index": item.raw_index,
                }
            )
    return values


def _overlay(image, record):
    draw = ImageDraw.Draw(image)
    for family, color, retention, accepted, nms in (
        ("person", "red", 0.20, 0.35, 0.60),
        ("face", "blue", 0.40, 0.60, 0.30),
    ):
        evidence_key = "people" if family == "person" else "faces"
        raw = tuple(
            AdapterDetection(tuple(item["box"]), item["confidence"], item["raw_index"])
            for item in record[evidence_key]
        )
        for item in _postprocess(raw, family, 1, 1, retention, accepted, nms):
            box = item.box
            coordinates = (
                box.x * image.width,
                box.y * image.height,
                (box.x + box.width) * image.width,
                (box.y + box.height) * image.height,
            )
            draw.rectangle(coordinates, outline=color, width=2)
            draw.text(
                coordinates[:2],
                f"{family[0].upper()} {item.confidence:.2f}{'*' if item.accepted else ''}",
                fill=color,
            )
    return image


def _load_portfolio(database: Path) -> Portfolio:
    with SQLitePortfolioRepository(database) as repository:
        keys = repository.list_keys()
        if len(keys) != 1:
            raise ValueError("calibration requires exactly one portfolio")
        portfolio = repository.get(*keys[0])
    if portfolio is None or portfolio.source_name != "smugmug":
        raise ValueError("calibration requires one persisted SmugMug portfolio")
    return portfolio


def _stratified_sample(portfolio: Portfolio, size: int):
    galleries: defaultdict[str, list[str]] = defaultdict(list)
    for gallery in portfolio.galleries:
        for placement in gallery.placements:
            galleries[placement.asset_source_id].append(gallery.source_id)
    groups: defaultdict[tuple[str, str, str], list] = defaultdict(list)
    asset_groups: dict[str, tuple[str, str, str]] = {}
    for asset in portfolio.assets:
        if asset.metadata.media_type is not MediaType.PHOTOGRAPH:
            continue
        year = str(asset.captured_at.year // 5 * 5) if asset.captured_at else "missing"
        camera = str(asset.exif.get("Model") or asset.exif.get("Camera") or "missing")
        gallery = min(galleries[asset.source_id], default="unplaced")
        group = (
            year,
            hashlib.sha256(camera.encode()).hexdigest()[:8],
            hashlib.sha256(gallery.encode()).hexdigest()[:8],
        )
        asset_groups[asset.source_id] = group
        groups[group].append(asset)
    for assets in groups.values():
        assets.sort(key=lambda asset: hashlib.sha256(f"{SEED}:{asset.source_id}".encode()).digest())
    ordered_groups = sorted(groups, key=lambda group: hashlib.sha256(repr(group).encode()).digest())
    selected = []
    while len(selected) < size and ordered_groups:
        remaining = []
        for group in ordered_groups:
            if groups[group] and len(selected) < size:
                selected.append(groups[group].pop(0))
            if groups[group]:
                remaining.append(group)
        ordered_groups = remaining
    selected_groups = [asset_groups[asset.source_id] for asset in selected]
    return tuple(selected), {
        "five_year_bands": len({group[0] for group in selected_groups}),
        "camera_hash_groups": len({group[1] for group in selected_groups}),
        "gallery_hash_groups": len({group[2] for group in selected_groups}),
    }


def _annotations(path: Path):
    with path.open(newline="", encoding="utf-8") as handle:
        rows = {row["sample_token"]: row for row in csv.DictReader(handle)}
    for token, row in rows.items():
        for field in ANNOTATION_FIELDS[1:7]:
            if not row[field].strip().isdigit():
                raise ValueError(f"{token}: {field} requires a nonnegative integer")
        for field in ANNOTATION_FIELDS[7:10]:
            _boolean(row[field])
        confidence = row["confidence"].strip().lower()
        if confidence not in {"high", "medium", "low"}:
            raise ValueError(f"{token}: confidence must be high, medium, or low")
        row["confidence"] = confidence
    return rows


def _boolean(value: str) -> int:
    normalized = value.strip().lower()
    if normalized not in {"0", "1", "false", "true", "no", "yes"}:
        raise ValueError("condition flags must use yes/no, true/false, or 1/0")
    return int(normalized in {"1", "true", "yes"})


if __name__ == "__main__":
    raise SystemExit(main())
