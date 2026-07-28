"""Shared normalized-asset selection helpers."""

from typing import Any

from ppa.models import Asset, MediaType


def unique_assets(assets: list[Asset]) -> list[Asset]:
    """Return the first placement of each source asset."""
    unique: dict[str, Asset] = {}
    for asset in assets:
        unique.setdefault(asset.source_id, asset)
    return list(unique.values())


def unique_photographs(assets: list[Asset]) -> list[Asset]:
    """Return unique normalized assets that represent photographs."""
    return [asset for asset in unique_assets(assets) if is_photograph(asset)]


def is_photograph(asset: Asset) -> bool:
    """Return whether normalized metadata identifies the asset as a photograph."""
    return asset.media_type is MediaType.PHOTOGRAPH


def asset_value(asset: Asset, *names: str) -> Any:
    """Read the first available field, preferring enriched EXIF."""
    for mapping in (asset.exif, asset.values):
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


def camera_name(asset: Asset) -> str | None:
    """Return the normalized available camera make and model."""
    make = text_value(asset, "Make", "CameraMake", "make")
    model = text_value(asset, "Model", "CameraModel", "model", "camera_model")
    if not model:
        return make
    if make and not model.casefold().startswith(make.casefold()):
        return f"{make} {model}"
    return model
