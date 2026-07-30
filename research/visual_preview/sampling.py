"""Deterministic metadata-stratified sample selection."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from ppa.analysis.assets import camera_name
from ppa.models import Asset, MediaType, Portfolio


@dataclass(frozen=True, slots=True)
class SampleRecord:
    """One locally selected asset and non-visual sampling strata."""

    asset: Asset
    orientation: str
    year_band: str
    camera: str
    focal_band: str
    gallery: str


def select_sample(
    portfolio: Portfolio,
    sample_size: int = 48,
    *,
    seed: str = "issue-19-v1",
) -> tuple[SampleRecord, ...]:
    """Select photographs by deterministic round-robin metadata strata."""
    if sample_size < 1:
        raise ValueError("sample_size must be positive")
    gallery_by_asset: dict[str, str] = {}
    for gallery in portfolio.galleries:
        for placement in gallery.placements:
            gallery_by_asset.setdefault(placement.asset_source_id, gallery.source_id)

    buckets: dict[tuple[str, str, str, str], list[SampleRecord]] = {}
    for asset in portfolio.assets:
        if asset.media_type is not MediaType.PHOTOGRAPH:
            continue
        record = SampleRecord(
            asset=asset,
            orientation=_orientation(asset),
            year_band=_year_band(asset),
            camera=camera_name(asset) or "camera-missing",
            focal_band=_focal_band(asset),
            gallery=gallery_by_asset.get(asset.source_id, "gallery-missing"),
        )
        key = (
            record.orientation,
            record.year_band,
            record.camera,
            record.focal_band,
        )
        buckets.setdefault(key, []).append(record)

    ordered_buckets = []
    for key, records in buckets.items():
        records.sort(key=lambda item: _rank(seed, item.asset.source_id))
        ordered_buckets.append((key, records))
    ordered_buckets.sort(key=lambda item: (_rank(seed, repr(item[0])), item[0]))

    selected: list[SampleRecord] = []
    offset = 0
    while len(selected) < sample_size:
        added = False
        for _, records in ordered_buckets:
            if offset < len(records):
                selected.append(records[offset])
                added = True
                if len(selected) == sample_size:
                    break
        if not added:
            break
        offset += 1
    return tuple(selected)


def sample_summary(records: tuple[SampleRecord, ...]) -> dict[str, object]:
    """Return aggregate, non-identifying metadata representation."""
    return {
        "sample_size": len(records),
        "orientations": _counts(record.orientation for record in records),
        "year_bands": _counts(record.year_band for record in records),
        "camera_count": len({record.camera for record in records}),
        "gallery_count": len({record.gallery for record in records}),
        "focal_bands": _counts(record.focal_band for record in records),
    }


def _rank(seed: str, value: str) -> str:
    return hashlib.sha256(f"{seed}:{value}".encode()).hexdigest()


def _orientation(asset: Asset) -> str:
    width = _positive_number(asset, "OriginalWidth")
    height = _positive_number(asset, "OriginalHeight")
    if width is None or height is None:
        return "orientation-missing"
    if width > height:
        return "landscape"
    if height > width:
        return "portrait"
    return "square"


def _year_band(asset: Asset) -> str:
    if asset.captured_at is None:
        return "year-missing"
    return f"{asset.captured_at.year // 5 * 5}-{asset.captured_at.year // 5 * 5 + 4}"


def _focal_band(asset: Asset) -> str:
    value = asset.metadata.focal_length_35mm or asset.metadata.focal_length_mm
    if value is None:
        return "focal-missing"
    if value < 35:
        return "<35"
    if value < 85:
        return "35-84"
    if value < 200:
        return "85-199"
    return ">=200"


def _positive_number(asset: Asset, name: str) -> float | None:
    value = asset.values.get(name)
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        return None
    return float(value)


def _counts(values) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        result[value] = result.get(value, 0) + 1
    return dict(sorted(result.items()))
