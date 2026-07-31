"""Neutral person and face placement measurements from bounded previews."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from itertools import pairwise
from math import isfinite
from threading import local
from typing import Any

from PIL import Image

from ppa.models import Asset
from ppa.sources import PreviewMetadata, PreviewRequest, PreviewStorageMode
from ppa.visual import AnalyzerIdentity, NormalizedBoundingBox, VisualResult, VisualResultKind
from research.people_face_calibration.detectors import (
    AdapterDetection,
    DetectionAdapter,
    NanoDetAdapter,
    YuNetAdapter,
)
from research.people_face_calibration.image_normalization import normalized_srgb_array

PERSON_RETENTION = 0.20
PERSON_ACCEPTED = 0.35
FACE_RETENTION = 0.40
FACE_ACCEPTED = 0.60
PERSON_NMS_IOU = 0.60
FACE_NMS_IOU = 0.30
MAX_DETECTIONS = 100
ROUNDING_DIGITS = 8

ANALYZER_IDENTITY = AnalyzerIdentity(
    "people-placement",
    "1.0.0",
    "preview768-nanodet416-r20-a35-n60-yunet-r40-a60-n30-max100-v1",
)
PREVIEW_REQUEST = PreviewRequest(
    maximum_edge=768,
    maximum_bytes=8_000_000,
    accepted_content_types=("image/jpeg", "image/png", "image/webp"),
    storage_mode=PreviewStorageMode.MEMORY,
)


@dataclass(frozen=True, slots=True)
class Detection:
    """One normalized retained detection."""

    detection_type: str
    box: NormalizedBoundingBox
    confidence: float
    accepted: bool
    raw_index: int

    @property
    def area(self) -> float:
        return self.box.width * self.box.height

    def as_json(self) -> dict[str, Any]:
        return {
            "type": self.detection_type,
            "box": {
                "type": "bounding_box",
                "x": _rounded(self.box.x),
                "y": _rounded(self.box.y),
                "width": _rounded(self.box.width),
                "height": _rounded(self.box.height),
            },
            "confidence": _rounded(self.confidence),
            "accepted": self.accepted,
        }


class PeoplePlacementAnalyzer:
    """Detect people and faces without identity or attribute inference."""

    identity = ANALYZER_IDENTITY
    preview_request = PREVIEW_REQUEST
    allows_empty_results = False

    def __init__(
        self,
        person_factory: Callable[[], DetectionAdapter] = NanoDetAdapter,
        face_factory: Callable[[], DetectionAdapter] = YuNetAdapter,
    ) -> None:
        self._person_factory = person_factory
        self._face_factory = face_factory
        self._thread = local()

    def analyze(
        self,
        asset: Asset,
        image: Image.Image,
        metadata: PreviewMetadata,
    ) -> tuple[VisualResult, ...]:
        del asset, metadata
        rgb = normalized_srgb_array(image)
        person_adapter, face_adapter = self._adapters()
        height, width = rgb.shape[:2]
        people = _postprocess(
            person_adapter.infer(rgb),
            "person",
            width,
            height,
            PERSON_RETENTION,
            PERSON_ACCEPTED,
            PERSON_NMS_IOU,
        )
        faces = _postprocess(
            face_adapter.infer(rgb),
            "face",
            width,
            height,
            FACE_RETENTION,
            FACE_ACCEPTED,
            FACE_NMS_IOU,
        )
        _validate_detection_set(people, "person", PERSON_RETENTION, PERSON_ACCEPTED)
        _validate_detection_set(faces, "face", FACE_RETENTION, FACE_ACCEPTED)
        return _build_results(people, faces)

    def _adapters(self) -> tuple[DetectionAdapter, DetectionAdapter]:
        adapters = getattr(self._thread, "adapters", None)
        if adapters is None:
            adapters = (self._person_factory(), self._face_factory())
            self._thread.adapters = adapters
        return adapters


def _postprocess(
    raw: tuple[AdapterDetection, ...],
    detection_type: str,
    width: int,
    height: int,
    retention: float,
    accepted: float,
    nms_iou: float,
) -> tuple[Detection, ...]:
    candidates: list[Detection] = []
    for item in raw:
        if item.confidence < retention:
            continue
        left = min(width, max(0.0, item.box[0]))
        top = min(height, max(0.0, item.box[1]))
        right = min(width, max(0.0, item.box[2]))
        bottom = min(height, max(0.0, item.box[3]))
        if right <= left or bottom <= top:
            continue
        normalized_x = left / width
        normalized_y = top / height
        normalized_width = min(1.0 - normalized_x, (right - left) / width)
        normalized_height = min(1.0 - normalized_y, (bottom - top) / height)
        candidates.append(
            Detection(
                detection_type,
                NormalizedBoundingBox(
                    normalized_x,
                    normalized_y,
                    normalized_width,
                    normalized_height,
                ),
                item.confidence,
                item.confidence >= accepted,
                item.raw_index,
            )
        )
    ordered = sorted(candidates, key=_sort_key)
    retained: list[Detection] = []
    for candidate in ordered:
        if all(_iou(candidate.box, existing.box) <= nms_iou for existing in retained):
            retained.append(candidate)
            if len(retained) == MAX_DETECTIONS:
                break
    return tuple(retained)


def _build_results(
    people: tuple[Detection, ...], faces: tuple[Detection, ...]
) -> tuple[VisualResult, ...]:
    accepted_people = tuple(item for item in people if item.accepted)
    accepted_faces = tuple(item for item in faces if item.accepted)
    person_count = len(accepted_people)
    face_count = len(accepted_faces)
    model_results = (
        VisualResult(
            "person_detections",
            VisualResultKind.CLASSIFICATION,
            [item.as_json() for item in people],
            "nanodet-postprocessing",
            "1",
            model_name="NanoDet-m-plus-1.5x-416",
            model_version="OpenCV-Zoo-2022nov",
        ),
        VisualResult(
            "face_detections",
            VisualResultKind.CLASSIFICATION,
            [item.as_json() for item in faces],
            "yunet-postprocessing",
            "1",
            model_name="YuNet",
            model_version="OpenCV-Zoo-2023mar",
        ),
    )
    measurements: list[VisualResult] = [
        _measurement("person_count", person_count, "count", "accepted-person-count"),
        _measurement("face_count", face_count, "count", "accepted-face-count"),
        _measurement(
            "people_count_category",
            "none" if person_count == 0 else "single" if person_count == 1 else "multiple",
            None,
            "accepted-person-count-category",
        ),
        _measurement(
            "largest_person_box_area",
            _rounded(max((item.area for item in accepted_people), default=0.0)),
            "frame_proportion",
            "largest-normalized-box-area",
        ),
        _measurement(
            "person_box_union_coverage",
            _rounded(_union_area(accepted_people)),
            "frame_proportion",
            "normalized-box-union",
        ),
        _measurement(
            "largest_face_box_area",
            _rounded(max((item.area for item in accepted_faces), default=0.0)),
            "frame_proportion",
            "largest-normalized-box-area",
        ),
        _measurement(
            "face_box_union_coverage",
            _rounded(_union_area(accepted_faces)),
            "frame_proportion",
            "normalized-box-union",
        ),
    ]
    for name, values in (
        ("person_box_area_weighted_centroid", accepted_people),
        ("face_box_area_weighted_centroid", accepted_faces),
    ):
        if values:
            area = sum(item.area for item in values)
            measurements.append(
                _measurement(
                    name,
                    {
                        "type": "point",
                        "x": _rounded(
                            sum((item.box.x + item.box.width / 2) * item.area for item in values)
                            / area
                        ),
                        "y": _rounded(
                            sum((item.box.y + item.box.height / 2) * item.area for item in values)
                            / area
                        ),
                    },
                    "normalized_coordinate",
                    "area-weighted-box-center",
                )
            )
    return (*model_results, *measurements)


def _measurement(name: str, value: Any, unit: str | None, method: str) -> VisualResult:
    return VisualResult(
        name,
        VisualResultKind.MEASUREMENT,
        value,
        method,
        "1",
        unit=unit,
    )


def _union_area(detections: tuple[Detection, ...]) -> float:
    if not detections:
        return 0.0
    x_values = sorted(
        {item.box.x for item in detections} | {item.box.x + item.box.width for item in detections}
    )
    total = 0.0
    for left, right in pairwise(x_values):
        intervals = sorted(
            (item.box.y, item.box.y + item.box.height)
            for item in detections
            if item.box.x < right and item.box.x + item.box.width > left
        )
        covered = 0.0
        if intervals:
            start, end = intervals[0]
            for next_start, next_end in intervals[1:]:
                if next_start > end:
                    covered += end - start
                    start, end = next_start, next_end
                else:
                    end = max(end, next_end)
            covered += end - start
        total += (right - left) * covered
    return total


def _sort_key(item: Detection) -> tuple[float, float, float, float, float, float, int]:
    return (
        -item.confidence,
        -item.area,
        item.box.x,
        item.box.y,
        item.box.width,
        item.box.height,
        item.raw_index,
    )


def _iou(first: NormalizedBoundingBox, second: NormalizedBoundingBox) -> float:
    left = max(first.x, second.x)
    top = max(first.y, second.y)
    right = min(first.x + first.width, second.x + second.width)
    bottom = min(first.y + first.height, second.y + second.height)
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    union = first.width * first.height + second.width * second.height - intersection
    return intersection / union if union else 0.0


def _validate_detection_set(
    detections: tuple[Detection, ...],
    detection_type: str,
    retention: float,
    accepted: float,
) -> None:
    if len(detections) > MAX_DETECTIONS:
        raise ValueError("detection count exceeds the configured maximum")
    if tuple(sorted(detections, key=_sort_key)) != detections:
        raise ValueError("detection order is not deterministic")
    if len({(item.box, item.confidence, item.raw_index) for item in detections}) != len(detections):
        raise ValueError("duplicate post-NMS detection")
    for item in detections:
        if item.detection_type != detection_type:
            raise ValueError("detection type does not match its result")
        if item.confidence < retention:
            raise ValueError("detection is below its retention threshold")
        if item.accepted != (item.confidence >= accepted):
            raise ValueError("detection acceptance does not match its threshold")


def _rounded(value: float) -> float:
    if not isfinite(value):
        raise ValueError("people-placement analysis produced a non-finite value")
    return round(float(value), ROUNDING_DIGITS)
