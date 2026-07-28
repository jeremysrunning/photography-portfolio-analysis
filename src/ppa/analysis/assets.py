"""Shared normalized-asset selection helpers."""

from typing import Any

from ppa.models import Asset

_VIDEO_FORMATS = {
    "3GP",
    "AVI",
    "M4V",
    "MOV",
    "MP4",
    "MPEG",
    "MPG",
    "WEBM",
    "WMV",
}


def unique_assets(assets: list[Asset]) -> list[Asset]:
    """Return the first placement of each source asset."""
    unique: dict[str, Asset] = {}
    for asset in assets:
        key = text_value(asset, "ImageKey") or asset.source_id
        unique.setdefault(key, asset)
    return list(unique.values())


def unique_photographs(assets: list[Asset]) -> list[Asset]:
    """Return unique normalized assets that represent photographs."""
    return [asset for asset in unique_assets(assets) if is_photograph(asset)]


def is_photograph(asset: Asset) -> bool:
    """Return whether normalized metadata identifies the asset as a photograph."""
    if asset_value(asset, "IsVideo", "is_video") is True:
        return False
    image_format = text_value(asset, "Format", "format")
    return image_format is None or image_format.upper() not in _VIDEO_FORMATS


def asset_value(asset: Asset, *names: str) -> Any:
    """Read the first available field, preferring enriched EXIF."""
    for mapping in (asset.exif, asset.metadata):
        for name in names:
            value = mapping.get(name)
            if value is not None:
                return value
    return None


def text_value(asset: Asset, *names: str) -> str | None:
    """Read a non-empty string value."""
    value = asset_value(asset, *names)
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None
