"""Recorded orientation and exact aspect-ratio portfolio analysis."""

from collections import Counter, defaultdict
from dataclasses import dataclass
from fractions import Fraction
from math import gcd

from ppa.analysis.assets import camera_name, is_photograph
from ppa.analysis.baseline import Coverage
from ppa.models import Asset, Portfolio

MIN_SEGMENT_SAMPLE = 20
MIN_GALLERY_COVERAGE = 0.5


@dataclass(frozen=True, slots=True)
class AspectRatio:
    """One exact directional width-to-height ratio in reduced terms."""

    width: int
    height: int

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("aspect-ratio terms must be positive")
        divisor = gcd(self.width, self.height)
        object.__setattr__(self, "width", self.width // divisor)
        object.__setattr__(self, "height", self.height // divisor)

    @property
    def exact_value(self) -> Fraction:
        return Fraction(self.width, self.height)

    def __str__(self) -> str:
        return f"{self.width}:{self.height}"


@dataclass(frozen=True, slots=True)
class AspectRatioFrequency:
    ratio: AspectRatio
    count: int


@dataclass(frozen=True, slots=True)
class OrientationSegment:
    key: str
    label: str
    photograph_count: int
    coverage: Coverage
    landscape: int
    portrait: int
    square: int
    aspect_ratios: tuple[AspectRatioFrequency, ...]
    qualifies_for_default: bool


@dataclass(frozen=True, slots=True)
class OrientationReport:
    title: str
    photograph_count: int
    width_coverage: Coverage
    height_coverage: Coverage
    pair_coverage: Coverage
    width_only: int
    height_only: int
    dimensions_missing: int
    landscape: int
    portrait: int
    square: int
    aspect_ratios: tuple[AspectRatioFrequency, ...]
    year_segments: tuple[OrientationSegment, ...]
    gallery_segments: tuple[OrientationSegment, ...]
    camera_segments: tuple[OrientationSegment, ...]


def recorded_orientation(asset: Asset) -> str | None:
    """Classify the orientation implied by typed source-reported dimensions."""
    width, height = asset.metadata.width_px, asset.metadata.height_px
    if width is None or height is None:
        return None
    if width > height:
        return "landscape"
    if height > width:
        return "portrait"
    return "square"


def analyze_orientation(portfolio: Portfolio) -> OrientationReport:
    """Describe recorded orientation and exact aspect ratios for unique photographs."""
    photographs = tuple(asset for asset in portfolio.assets if is_photograph(asset))
    total = len(photographs)
    width_count = sum(asset.metadata.width_px is not None for asset in photographs)
    height_count = sum(asset.metadata.height_px is not None for asset in photographs)
    pair_count = sum(
        asset.metadata.width_px is not None and asset.metadata.height_px is not None
        for asset in photographs
    )
    summary = _segment("portfolio", portfolio.title, photographs)

    years: dict[str, list[Asset]] = defaultdict(list)
    cameras: dict[str, list[Asset]] = defaultdict(list)
    for asset in photographs:
        if asset.captured_at is not None:
            years[str(asset.captured_at.year)].append(asset)
        if (camera := camera_name(asset)) is not None:
            cameras[camera].append(asset)

    assets_by_id = {asset.source_id: asset for asset in photographs}
    galleries = []
    for gallery in portfolio.galleries:
        gallery_assets = tuple(
            assets_by_id[placement.asset_source_id]
            for placement in gallery.placements
            if placement.asset_source_id in assets_by_id
        )
        galleries.append(
            _segment(
                gallery.source_id,
                gallery.title,
                gallery_assets,
                require_gallery_coverage=True,
            )
        )

    return OrientationReport(
        title=portfolio.title,
        photograph_count=total,
        width_coverage=Coverage(width_count, total),
        height_coverage=Coverage(height_count, total),
        pair_coverage=Coverage(pair_count, total),
        width_only=width_count - pair_count,
        height_only=height_count - pair_count,
        dimensions_missing=total - (width_count + height_count - pair_count),
        landscape=summary.landscape,
        portrait=summary.portrait,
        square=summary.square,
        aspect_ratios=summary.aspect_ratios,
        year_segments=tuple(
            _segment(key, key, tuple(assets)) for key, assets in sorted(years.items())
        ),
        gallery_segments=tuple(galleries),
        camera_segments=tuple(
            _segment(key, key, tuple(assets))
            for key, assets in sorted(cameras.items(), key=lambda item: item[0].casefold())
        ),
    )


def _segment(
    key: str,
    label: str,
    assets: tuple[Asset, ...],
    *,
    require_gallery_coverage: bool = False,
) -> OrientationSegment:
    orientations = Counter(filter(None, (recorded_orientation(asset) for asset in assets)))
    ratios = Counter(
        AspectRatio(asset.metadata.width_px, asset.metadata.height_px)
        for asset in assets
        if asset.metadata.width_px is not None and asset.metadata.height_px is not None
    )
    frequencies = tuple(
        AspectRatioFrequency(ratio, count)
        for ratio, count in sorted(
            ratios.items(), key=lambda item: (-item[1], item[0].exact_value, item[0].width)
        )
    )
    coverage = Coverage(sum(ratios.values()), len(assets))
    qualifies = coverage.available >= MIN_SEGMENT_SAMPLE
    if require_gallery_coverage:
        qualifies = qualifies and coverage.percent >= MIN_GALLERY_COVERAGE * 100
    return OrientationSegment(
        key,
        label,
        len(assets),
        coverage,
        orientations["landscape"],
        orientations["portrait"],
        orientations["square"],
        frequencies,
        qualifies,
    )
