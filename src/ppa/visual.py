"""Source-agnostic contracts for durable visual-analysis results."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from math import isfinite
from types import MappingProxyType

from ppa.models import JsonValue


class VisualResultKind(StrEnum):
    """The evidence-producing family of a visual result."""

    MEASUREMENT = "measurement"
    CLASSIFICATION = "classification"


class VisualRunStatus(StrEnum):
    """The current attempt state for one immutable analyzer identity."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class AnalyzerIdentity:
    """Immutable analyzer and configuration identity."""

    name: str
    version: str
    configuration_version: str

    def __post_init__(self) -> None:
        for field_name in ("name", "version", "configuration_version"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"analyzer {field_name} must not be empty")


@dataclass(frozen=True, slots=True)
class NormalizedPoint:
    """A point in image coordinates normalized to the inclusive unit interval."""

    x: float
    y: float

    def __post_init__(self) -> None:
        _normalized(self.x, "x")
        _normalized(self.y, "y")

    def as_json(self) -> Mapping[str, JsonValue]:
        """Return the stable JSON representation."""
        return MappingProxyType({"type": "point", "x": float(self.x), "y": float(self.y)})


@dataclass(frozen=True, slots=True)
class NormalizedBoundingBox:
    """A normalized top-left-origin bounding box contained by the image frame."""

    x: float
    y: float
    width: float
    height: float

    def __post_init__(self) -> None:
        for field_name in ("x", "y", "width", "height"):
            _normalized(getattr(self, field_name), field_name)
        if self.width <= 0 or self.height <= 0:
            raise ValueError("normalized bounding-box width and height must be positive")
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("normalized bounding box must remain within the image frame")

    def as_json(self) -> Mapping[str, JsonValue]:
        """Return the stable JSON representation."""
        return MappingProxyType(
            {
                "type": "bounding_box",
                "x": float(self.x),
                "y": float(self.y),
                "width": float(self.width),
                "height": float(self.height),
            }
        )


type VisualValue = JsonValue | NormalizedPoint | NormalizedBoundingBox


@dataclass(frozen=True, slots=True)
class VisualResult:
    """One durable measurement or model classification."""

    name: str
    kind: VisualResultKind
    value: VisualValue
    method_name: str
    method_version: str
    unit: str | None = None
    confidence: float | None = None
    model_name: str | None = None
    model_version: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("name", "method_name", "method_version"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"visual result {field_name} must not be empty")
        if not isinstance(self.kind, VisualResultKind):
            raise ValueError("visual result kind must be a VisualResultKind")
        value = (
            self.value.as_json()
            if isinstance(self.value, NormalizedPoint | NormalizedBoundingBox)
            else self.value
        )
        if value is None:
            raise ValueError("visual result value must not be missing")
        if not _json_value(value):
            raise ValueError("visual result value must be JSON-compatible")
        if self.kind is VisualResultKind.MEASUREMENT and self.confidence is not None:
            raise ValueError("deterministic measurements must not carry confidence")
        if self.confidence is not None and (
            isinstance(self.confidence, bool)
            or not isinstance(self.confidence, int | float)
            or not isfinite(float(self.confidence))
            or not 0 <= float(self.confidence) <= 1
        ):
            raise ValueError("confidence must be between 0.0 and 1.0 or None")
        if (self.model_name is None) != (self.model_version is None):
            raise ValueError("model name and version must be supplied together")
        object.__setattr__(self, "value", _freeze_json(value))
        if self.confidence is not None:
            object.__setattr__(self, "confidence", float(self.confidence))


@dataclass(frozen=True, slots=True)
class VisualRunState:
    """Current attempt state and last successful snapshot metadata."""

    status: VisualRunStatus
    attempts: int
    updated_at: datetime | None
    started_at: datetime | None = None
    last_successful_completed_at: datetime | None = None
    error_category: str | None = None
    error_message: str | None = None
    interruption_category: str | None = None
    interrupted_at: datetime | None = None
    skip_reason: str | None = None

    @property
    def has_successful_snapshot(self) -> bool:
        """Return whether results from a prior successful completion may exist."""
        return self.last_successful_completed_at is not None


@dataclass(frozen=True, slots=True)
class VisualAnalysisSnapshot:
    """Current run state together with its last successful result snapshot."""

    identity: AnalyzerIdentity
    state: VisualRunState
    results: tuple[VisualResult, ...] = ()


def _normalized(value: object, name: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not isfinite(float(value))
        or not 0 <= float(value) <= 1
    ):
        raise ValueError(f"normalized {name} must be between 0.0 and 1.0")


def _json_value(value: object) -> bool:
    if value is None or isinstance(value, bool | int | float | str):
        return not isinstance(value, float) or isfinite(value)
    if isinstance(value, list | tuple):
        return all(_json_value(item) for item in value)
    if isinstance(value, Mapping):
        return all(isinstance(key, str) and _json_value(item) for key, item in value.items())
    return False


def _freeze_json(value: JsonValue) -> JsonValue:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze_json(item) for item in value)
    return value
