"""Normalized portfolio data structures."""

from dataclasses import dataclass, field
from datetime import datetime

JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]


@dataclass(frozen=True, slots=True)
class Measurement:
    """An objective, reproducible value derived from an asset."""

    name: str
    value: JsonValue
    unit: str | None = None
    method: str | None = None


@dataclass(frozen=True, slots=True)
class Observation:
    """A qualitative interpretation linked to supporting evidence."""

    statement: str
    evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Finding:
    """A portfolio-level conclusion with explicit confidence and evidence."""

    statement: str
    confidence: float
    evidence: tuple[str, ...]

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")


@dataclass(frozen=True, slots=True)
class Asset:
    """A photograph reference and its normalized metadata."""

    source_id: str
    source_url: str
    gallery_source_id: str
    preview_url: str | None = None
    captured_at: datetime | None = None
    metadata: dict[str, JsonValue] = field(default_factory=dict)
    exif: dict[str, JsonValue] = field(default_factory=dict)
    measurements: tuple[Measurement, ...] = ()


@dataclass(frozen=True, slots=True)
class Gallery:
    """A logical grouping of assets from a portfolio source."""

    source_id: str
    title: str
    source_url: str
    parent_source_id: str | None = None
    metadata: dict[str, JsonValue] = field(default_factory=dict)
    assets: tuple[Asset, ...] = ()


@dataclass(frozen=True, slots=True)
class Portfolio:
    """A normalized body of photographic work."""

    source: str
    source_id: str
    title: str
    source_url: str
    metadata: dict[str, JsonValue] = field(default_factory=dict)
    galleries: tuple[Gallery, ...] = ()
    observations: tuple[Observation, ...] = ()
    findings: tuple[Finding, ...] = ()
