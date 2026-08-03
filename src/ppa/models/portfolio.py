"""Normalized portfolio data structures."""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from fractions import Fraction
from math import isfinite
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

_FOCAL_LENGTH = re.compile(
    r"^\s*(?P<numerator>[+]?(?:\d+(?:\.\d*)?|\.\d+))"
    r"(?:\s*/\s*(?P<denominator>[+]?(?:\d+(?:\.\d*)?|\.\d+)))?"
    r"\s*(?:mm)?\s*$",
    re.IGNORECASE,
)
_NUMBER_COMPONENT = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)"
_RATIONAL_VALUE = re.compile(
    rf"^\s*(?P<numerator>{_NUMBER_COMPONENT})"
    rf"(?:\s*/\s*(?P<denominator>{_NUMBER_COMPONENT}))?\s*$"
)
_APERTURE = re.compile(r"^\s*(?:f\s*/\s*)?(?P<value>.+?)\s*$", re.IGNORECASE)
_EXPOSURE_TIME = re.compile(
    r"^\s*(?P<value>.+?)\s*(?:s|sec|second|seconds)?\s*$",
    re.IGNORECASE,
)
_EXPOSURE_COMPENSATION = re.compile(
    r"^\s*(?P<value>.+?)\s*(?:ev)?\s*$",
    re.IGNORECASE,
)
_INTEGER_TEXT = re.compile(rf"^\s*(?P<value>{_NUMBER_COMPONENT})\s*$")
_MAX_NUMERIC_TEXT_LENGTH = 128
_MAX_INTEGER = 2**63 - 1


@dataclass(frozen=True, slots=True)
class RationalValue:
    """One exact reduced rational value with a positive denominator."""

    numerator: int
    denominator: int = 1

    def __post_init__(self) -> None:
        if (
            isinstance(self.numerator, bool)
            or not isinstance(self.numerator, int)
            or isinstance(self.denominator, bool)
            or not isinstance(self.denominator, int)
        ):
            raise ValueError("rational components must be integers")
        if self.denominator == 0:
            raise ValueError("rational denominator must not be zero")
        value = Fraction(self.numerator, self.denominator)
        if abs(value.numerator) > _MAX_INTEGER or value.denominator > _MAX_INTEGER:
            raise ValueError("rational components exceed the supported integer range")
        object.__setattr__(self, "numerator", value.numerator)
        object.__setattr__(self, "denominator", value.denominator)

    def __float__(self) -> float:
        return self.numerator / self.denominator


def _rational(value: object) -> RationalValue | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        try:
            return RationalValue(value)
        except ValueError:
            return None
    if isinstance(value, float):
        if not isfinite(value):
            return None
        value = str(value)
    if not isinstance(value, str) or len(value) > _MAX_NUMERIC_TEXT_LENGTH:
        return None
    match = _RATIONAL_VALUE.fullmatch(value)
    if match is None:
        return None
    try:
        numerator = Fraction(Decimal(match.group("numerator")))
        denominator_text = match.group("denominator")
        result = numerator
        if denominator_text is not None:
            denominator = Fraction(Decimal(denominator_text))
            if denominator == 0:
                return None
            result /= denominator
        return RationalValue(result.numerator, result.denominator)
    except (InvalidOperation, ValueError, ZeroDivisionError):
        return None


def normalize_aperture_f_number(value: object) -> float | None:
    """Return a positive finite f-number from an explicitly recorded value."""
    if isinstance(value, str):
        if len(value) > _MAX_NUMERIC_TEXT_LENGTH:
            return None
        match = _APERTURE.fullmatch(value)
        if match is None:
            return None
        value = match.group("value")
    rational = _rational(value)
    if rational is None or rational.numerator <= 0:
        return None
    result = float(rational)
    return result if isfinite(result) and result > 0 else None


def normalize_exposure_time(value: object) -> RationalValue | None:
    """Return an exact positive exposure time in seconds."""
    if isinstance(value, str):
        if len(value) > _MAX_NUMERIC_TEXT_LENGTH:
            return None
        match = _EXPOSURE_TIME.fullmatch(value)
        if match is None:
            return None
        value = match.group("value")
    result = _rational(value)
    return result if result is not None and result.numerator > 0 else None


def normalize_iso(value: object) -> int | None:
    """Return a positive integral ISO value when explicitly recorded."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        result = value
    else:
        if isinstance(value, float):
            if not isfinite(value):
                return None
            value = str(value)
        if not isinstance(value, str) or len(value) > _MAX_NUMERIC_TEXT_LENGTH:
            return None
        match = _INTEGER_TEXT.fullmatch(value)
        if match is None:
            return None
        try:
            decimal = Decimal(match.group("value"))
        except InvalidOperation:
            return None
        if not decimal.is_finite() or decimal != decimal.to_integral_value():
            return None
        result = int(decimal)
    return result if 0 < result <= _MAX_INTEGER else None


def normalize_exposure_compensation(value: object) -> RationalValue | None:
    """Return an exact signed exposure-compensation value in EV."""
    if isinstance(value, str):
        if len(value) > _MAX_NUMERIC_TEXT_LENGTH:
            return None
        match = _EXPOSURE_COMPENSATION.fullmatch(value)
        if match is None:
            return None
        value = match.group("value")
    return _rational(value)


def normalize_flash_fired(value: object) -> bool | None:
    """Return whether confirmed descriptive source evidence says flash fired."""
    if not isinstance(value, str):
        return None
    normalized = value.strip().casefold()
    if normalized == "on, fired":
        return True
    if normalized in {"off, did not fire", "no flash"}:
        return False
    return None


def normalize_focal_length(value: object) -> float | None:
    """Return a positive focal length in millimeters when explicitly recorded."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        result = float(value)
    elif isinstance(value, str):
        match = _FOCAL_LENGTH.fullmatch(value)
        if match is None:
            return None
        numerator = float(match.group("numerator"))
        denominator_text = match.group("denominator")
        if denominator_text is None:
            result = numerator
        else:
            denominator = float(denominator_text)
            if denominator == 0:
                return None
            result = numerator / denominator
    else:
        return None
    return result if isfinite(result) and result > 0 else None


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
    focal_length_mm: float | None = None
    focal_length_35mm: float | None = None
    aperture_f_number: float | None = None
    exposure_time: RationalValue | None = None
    iso: int | None = None
    exposure_compensation_ev: RationalValue | None = None
    flash_fired: bool | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.media_type, MediaType):
            raise ValueError("media_type must be a MediaType")
        _metadata(self.values, "metadata values")
        _metadata(self.exif, "EXIF metadata")
        for name in ("focal_length_mm", "focal_length_35mm"):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, int | float)
                or not isfinite(float(value))
                or value <= 0
            ):
                raise ValueError(f"{name} must be a positive finite number or None")
            if value is not None:
                object.__setattr__(self, name, float(value))
        if self.aperture_f_number is not None and (
            isinstance(self.aperture_f_number, bool)
            or not isinstance(self.aperture_f_number, int | float)
            or not isfinite(float(self.aperture_f_number))
            or self.aperture_f_number <= 0
        ):
            raise ValueError("aperture_f_number must be a positive finite number or None")
        if self.aperture_f_number is not None:
            object.__setattr__(self, "aperture_f_number", float(self.aperture_f_number))
        if self.exposure_time is not None and (
            not isinstance(self.exposure_time, RationalValue) or self.exposure_time.numerator <= 0
        ):
            raise ValueError("exposure_time must be a positive RationalValue or None")
        if self.iso is not None and (
            isinstance(self.iso, bool)
            or not isinstance(self.iso, int)
            or not 0 < self.iso <= _MAX_INTEGER
        ):
            raise ValueError("iso must be a positive integer or None")
        if self.exposure_compensation_ev is not None and not isinstance(
            self.exposure_compensation_ev, RationalValue
        ):
            raise ValueError("exposure_compensation_ev must be a RationalValue or None")
        if self.flash_fired is not None and not isinstance(self.flash_fired, bool):
            raise ValueError("flash_fired must be a boolean or None")
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
