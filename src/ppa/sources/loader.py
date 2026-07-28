"""Provider-agnostic normalized portfolio composition."""

from dataclasses import replace

from ppa.models import GalleryPlacement, Portfolio
from ppa.sources.base import GallerySource


def load_portfolio(source: GallerySource) -> Portfolio:
    """Discover and fully enumerate a normalized portfolio from a source."""
    portfolio = source.discover_portfolio()
    assets = {}
    galleries = []
    for gallery in source.iter_galleries(portfolio):
        placements = []
        for asset in source.iter_assets(gallery):
            assets.setdefault(asset.source_id, asset)
            placements.append(GalleryPlacement(asset.source_id))
        galleries.append(replace(gallery, placements=tuple(placements)))
    return replace(portfolio, assets=tuple(assets.values()), galleries=tuple(galleries))
