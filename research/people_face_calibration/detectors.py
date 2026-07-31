"""Lazy CPU-only inference adapters for people-placement analysis."""

from __future__ import annotations

import hashlib
import importlib
from dataclasses import dataclass
from functools import cache
from importlib import resources
from math import isfinite
from pathlib import Path
from threading import Lock
from typing import Any, Protocol

import numpy as np

MODEL_PACKAGE = "research.people_face_calibration.model_data"
NANODET_FILE = "object_detection_nanodet_2022nov.onnx"
YUNET_FILE = "face_detection_yunet_2023mar.onnx"
NANODET_SHA256 = "4b82da9944b88577175ee23a459dce2e26e6e4be573def65b1055dc2d9720186"
YUNET_SHA256 = "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"
MODEL_LOAD_MESSAGE = "People-placement detection models are unavailable or invalid."

_OPENCV_LOCK = Lock()
_OPENCV_CONFIGURED = False


class DetectorLoadError(RuntimeError):
    """Raised without filesystem or runtime details when a detector cannot load."""


@dataclass(frozen=True, slots=True)
class AdapterDetection:
    """Narrow box-and-confidence output from one inference adapter."""

    box: tuple[float, float, float, float]
    confidence: float
    raw_index: int

    def __post_init__(self) -> None:
        if len(self.box) != 4 or any(not isfinite(value) for value in self.box):
            raise ValueError("detector box coordinates must be finite")
        if not isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValueError("detector confidence must be between zero and one")
        if self.raw_index < 0:
            raise ValueError("detector raw index must not be negative")


class DetectionAdapter(Protocol):
    """Infer narrow box-and-confidence evidence from an RGB preview."""

    def infer(self, rgb: np.ndarray) -> tuple[AdapterDetection, ...]: ...


class NanoDetAdapter:
    """Decode the OpenCV Zoo NanoDet person class using one owned DNN network."""

    _strides = (8, 16, 32)
    _mean = np.array([103.53, 116.28, 123.675], dtype=np.float32)
    _std = np.array([57.375, 57.12, 58.395], dtype=np.float32)

    def __init__(self) -> None:
        try:
            cv2 = _opencv()
            model = _verified_model(NANODET_FILE, NANODET_SHA256)
            self._net = cv2.dnn.readNet(str(model))
            self._net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
            self._net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
            self._output_names = self._net.getUnconnectedOutLayersNames()
            self._anchors = tuple(_anchors(416 // stride, stride) for stride in self._strides)
        except Exception as error:
            raise DetectorLoadError(MODEL_LOAD_MESSAGE) from error

    def infer(self, rgb: np.ndarray) -> tuple[AdapterDetection, ...]:
        try:
            blob, transform = _nanodet_blob(rgb)
            self._net.setInput(blob)
            outputs = self._net.forward(self._output_names)
            return _decode_nanodet(outputs, self._anchors, transform)
        except Exception as error:
            raise RuntimeError("Person detection inference did not complete.") from error


class YuNetAdapter:
    """Discard YuNet landmarks at the detector boundary and return boxes and scores."""

    def __init__(self, retention_threshold: float = 0.40) -> None:
        try:
            cv2 = _opencv()
            model = _verified_model(YUNET_FILE, YUNET_SHA256)
            self._detector = cv2.FaceDetectorYN.create(
                str(model),
                "",
                (320, 320),
                retention_threshold,
                1.0,
                5000,
                cv2.dnn.DNN_BACKEND_OPENCV,
                cv2.dnn.DNN_TARGET_CPU,
            )
        except Exception as error:
            raise DetectorLoadError(MODEL_LOAD_MESSAGE) from error

    def infer(self, rgb: np.ndarray) -> tuple[AdapterDetection, ...]:
        try:
            bgr = np.ascontiguousarray(rgb[..., ::-1])
            self._detector.setInputSize((rgb.shape[1], rgb.shape[0]))
            _, raw = self._detector.detect(bgr)
            return extract_yunet_detections(raw)
        except Exception as error:
            raise RuntimeError("Face detection inference did not complete.") from error


def extract_yunet_detections(raw: np.ndarray | None) -> tuple[AdapterDetection, ...]:
    """Narrow YuNet rows to boxes and scores; landmark columns never escape."""
    if raw is None:
        return ()
    matrix = np.asarray(raw)
    if matrix.ndim != 2 or matrix.shape[1] != 15:
        raise ValueError("face detector returned malformed output")
    narrowed = np.column_stack((matrix[:, 0:4], matrix[:, 14])).astype(np.float64, copy=True)
    del matrix
    detections: list[AdapterDetection] = []
    for index, row in enumerate(narrowed):
        x, y, width, height, confidence = (float(value) for value in row)
        detections.append(AdapterDetection((x, y, x + width, y + height), confidence, index))
    del narrowed
    return tuple(detections)


@cache
def _verified_model(filename: str, expected_sha256: str) -> Path:
    try:
        item = resources.files(MODEL_PACKAGE).joinpath(filename)
        path = Path(str(item))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != expected_sha256:
            raise DetectorLoadError(MODEL_LOAD_MESSAGE)
        return path
    except DetectorLoadError:
        raise
    except Exception as error:
        raise DetectorLoadError(MODEL_LOAD_MESSAGE) from error


def _opencv() -> Any:
    global _OPENCV_CONFIGURED
    try:
        cv2 = importlib.import_module("cv2")
        with _OPENCV_LOCK:
            if not _OPENCV_CONFIGURED:
                cv2.setNumThreads(1)
                _OPENCV_CONFIGURED = True
        return cv2
    except Exception as error:
        raise DetectorLoadError(MODEL_LOAD_MESSAGE) from error


def _anchors(size: int, stride: int) -> np.ndarray:
    x, y = np.meshgrid(np.arange(size), np.arange(size))
    return np.column_stack(
        (
            x.reshape(-1) * stride + 0.5 * (stride - 1),
            y.reshape(-1) * stride + 0.5 * (stride - 1),
        )
    )


@dataclass(frozen=True, slots=True)
class _LetterboxTransform:
    scale: float
    left: int
    top: int
    preview_width: int
    preview_height: int


def _nanodet_blob(rgb: np.ndarray) -> tuple[np.ndarray, _LetterboxTransform]:
    cv2 = _opencv()
    height, width = rgb.shape[:2]
    scale = min(416 / width, 416 / height)
    resized_width = min(416, max(1, int(width * scale + 0.5)))
    resized_height = min(416, max(1, int(height * scale + 0.5)))
    resized = cv2.resize(
        np.ascontiguousarray(rgb[..., ::-1]),
        (resized_width, resized_height),
        interpolation=cv2.INTER_LINEAR,
    ).astype(np.float32)
    normalized = (resized - NanoDetAdapter._mean) / NanoDetAdapter._std
    left = (416 - resized_width) // 2
    top = (416 - resized_height) // 2
    canvas = np.zeros((416, 416, 3), dtype=np.float32)
    canvas[top : top + resized_height, left : left + resized_width] = normalized
    blob = np.transpose(canvas, (2, 0, 1))[None, ...]
    return blob, _LetterboxTransform(scale, left, top, width, height)


def _decode_nanodet(
    outputs: list[np.ndarray] | tuple[np.ndarray, ...],
    anchors_by_level: tuple[np.ndarray, ...],
    transform: _LetterboxTransform,
) -> tuple[AdapterDetection, ...]:
    if len(outputs) != 6:
        raise ValueError("person detector returned malformed output")
    detections: list[AdapterDetection] = []
    raw_index = 0
    project = np.arange(8)
    for stride, class_scores, box_values, anchors in zip(
        NanoDetAdapter._strides,
        outputs[::2],
        outputs[1::2],
        anchors_by_level,
        strict=True,
    ):
        scores = np.squeeze(class_scores, axis=0) if class_scores.ndim == 3 else class_scores
        boxes = np.squeeze(box_values, axis=0) if box_values.ndim == 3 else box_values
        if scores.ndim != 2 or scores.shape[1] < 1 or boxes.shape != (scores.shape[0], 32):
            raise ValueError("person detector returned malformed output")
        logits = boxes.reshape(-1, 8).astype(np.float64)
        logits -= logits.max(axis=1, keepdims=True)
        probabilities = np.exp(logits)
        probabilities /= probabilities.sum(axis=1, keepdims=True)
        distances = (probabilities @ project).reshape(-1, 4) * stride
        for index, confidence_value in enumerate(scores[:, 0]):
            confidence = float(confidence_value)
            x1 = (float(anchors[index, 0] - distances[index, 0]) - transform.left) / (
                transform.scale
            )
            y1 = (float(anchors[index, 1] - distances[index, 1]) - transform.top) / (
                transform.scale
            )
            x2 = (float(anchors[index, 0] + distances[index, 2]) - transform.left) / (
                transform.scale
            )
            y2 = (float(anchors[index, 1] + distances[index, 3]) - transform.top) / (
                transform.scale
            )
            detections.append(AdapterDetection((x1, y1, x2, y2), confidence, raw_index))
            raw_index += 1
    return tuple(detections)
