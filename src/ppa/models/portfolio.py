"""Normalized portfolio data structures."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from urllib.parse import urlsplit

JsonValue = (
    None
    | bool
    | int
    | float
    | str
    | list["JsonValue"]
    | tuple["JsonValue", ...]
    | Mapping[str, "JsonValue"]
)


def _freeze_json(value: JsonValue) -> JsonValue:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze_json(item) for item in value)
    return value


def _freeze_mapping(value: Mapping[str, JsonValue]) -> Mapping[str, JsonValue]:
    frozen = _freeze_json(value)
    if not isinstance(frozen, Mapping):  # pragma: no cover - narrowed by the input type
        raise TypeError("metadata must be a mapping")
    return frozen


def _required(value: str, name: str) -> None:
    if not value.strip():
        raise ValueError(f"{name} must not be empty")


def _url(value: str, name: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{name} must be an absolute HTTP or HTTPS URL")


def _json_value(value: object) -> bool:
    if value is None or isinstance(value, bool | int | float | str):
        return True
    if isinstance(value, list | tuple):
        return all(_json_value(item) for item in value)
    if isinstance(value, Mapping):
        return all(isinstance(key, str) and _json_value(item) for key, item in value.items())
    return False


def _metadata(value: Mapping[str, JsonValue], name: str) -> None:
    if not _json_value(value):
        raise ValueError(f"{name} must contain only JSON-compatible values")


class MediaType(StrEnum):
    """The explicitly recorded kind of a normalized media asset."""

    PHOTOGRAPH = "photograph"
    NON_PHOTO = "non_photo"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class SourceReference:
    """Stable provider identity and network URL within a source namespace."""

    source_id: str
    source_url: str

    def __post_init__(self) -> None:
        _required(self.source_id, "source_id")
        _url(self.source_url, "source_url")


@dataclass(frozen=True, slots=True)
class AssetMetadata:
    """Normalized optional metadata for one unique media asset."""

    media_type: MediaType = MediaType.UNKNOWN
    captured_at: datetime | None = None
    values: Mapping[str, JsonValue] = field(default_factory=dict)
    exif: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.media_type, MediaType):
            raise ValueError("media_type must be a MediaType")
        _metadata(self.values, "metadata values")
        _metadata(self.exif, "EXIF metadata")
        object.__setattr__(self, "values", _freeze_mapping(self.values))
        object.__setattr__(self, "exif", _freeze_mapping(self.exif))


@dataclass(frozen=True, slots=True)
class Measurement:
    """An objective, reproducible value derived from an asset."""

    name: str
    value: JsonValue
    unit: str | None = None
    method: str | None = None

    def __post_init__(self) -> None:
        _required(self.name, "measurement name")
        if not _json_value(self.value):
            raise ValueError("measurement value must be JSON-compatible")


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
    """A unique media asset and its normalized metadata."""

    source: SourceReference
    metadata: AssetMetadata = field(default_factory=AssetMetadata)
    preview_url: str | None = None
    measurements: tuple[Measurement, ...] = ()

    def __post_init__(self) -> None:
        if self.preview_url is not None:
            _url(self.preview_url, "preview_url")
        names = [measurement.name for measurement in self.measurements]
        if len(names) != len(set(names)):
            raise ValueError("asset measurement names must be unique")

    @property
    def source_id(self) -> str:
        return self.source.source_id

    @property
    def source_url(self) -> str:
        return self.source.source_url

    @property
    def captured_at(self) -> datetime | None:
        return self.metadata.captured_at

    @property
    def media_type(self) -> MediaType:
        return self.metadata.media_type

    @property
    def values(self) -> Mapping[str, JsonValue]:
        return self.metadata.values

    @property
    def exif(self) -> Mapping[str, JsonValue]:
        return self.metadata.exif


@dataclass(frozen=True, slots=True)
class GalleryPlacement:
    """The ordered presence of one unique asset in one gallery."""

    asset_source_id: str

    def __post_init__(self) -> None:
        _required(self.asset_source_id, "placement asset_source_id")


@dataclass(frozen=True, slots=True)
class Gallery:
    """A logical grouping of ordered asset placements."""

    source: SourceReference
    title: str
    parent_source_id: str | None = None
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)
    placements: tuple[GalleryPlacement, ...] = ()

    def __post_init__(self) -> None:
        _required(self.title, "gallery title")
        if self.parent_source_id is not None:
            _required(self.parent_source_id, "parent_source_id")
        _metadata(self.metadata, "gallery metadata")
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))
        identities = [placement.asset_source_id for placement in self.placements]
        if len(identities) != len(set(identities)):
            raise ValueError("gallery placements must be unique")

    @property
    def source_id(self) -> str:
        return self.source.source_id

    @property
    def source_url(self) -> str:
        return self.source.source_url


@dataclass(frozen=True, slots=True)
class Portfolio:
    """A normalized body of work with unique assets and gallery placements."""

    source_name: str
    source: SourceReference
    title: str
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)
    assets: tuple[Asset, ...] = ()
    galleries: tuple[Gallery, ...] = ()
    observations: tuple[Observation, ...] = ()
    findings: tuple[Finding, ...] = ()

    def __post_init__(self) -> None:
        _required(self.source_name, "source_name")
        _required(self.title, "portfolio title")
        _metadata(self.metadata, "portfolio metadata")
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))
        asset_ids = [asset.source_id for asset in self.assets]
        if len(asset_ids) != len(set(asset_ids)):
            raise ValueError("portfolio asset source identities must be unique")
        gallery_ids = [gallery.source_id for gallery in self.galleries]
        if len(gallery_ids) != len(set(gallery_ids)):
            raise ValueError("portfolio gallery source identities must be unique")
        known_assets = set(asset_ids)
        for gallery in self.galleries:
            missing = {
                placement.asset_source_id
                for placement in gallery.placements
                if placement.asset_source_id not in known_assets
            }
            if missing:
                raise ValueError(
                    f"gallery {gallery.source_id!r} references unknown assets: "
                    f"{', '.join(sorted(missing))}"
                )

    @property
    def source_id(self) -> str:
        return self.source.source_id

    @property
    def source_url(self) -> str:
        return self.source.source_url

    def asset(self, source_id: str) -> Asset:
        """Return a unique asset by source identity."""
        for asset in self.assets:
            if asset.source_id == source_id:
                return asset
        raise KeyError(source_id)

    def gallery_assets(self, gallery: Gallery) -> tuple[Asset, ...]:
        """Resolve one gallery's ordered placements to unique assets."""
        by_id = {asset.source_id: asset for asset in self.assets}
        return tuple(by_id[placement.asset_source_id] for placement in gallery.placements)
