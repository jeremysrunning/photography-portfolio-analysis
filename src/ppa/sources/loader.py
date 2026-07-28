"""Provider-agnostic normalized portfolio composition."""

from dataclasses import replace

from ppa.models import Portfolio
from ppa.sources.base import GallerySource


def load_portfolio(source: GallerySource) -> Portfolio:
    """Discover and fully enumerate a normalized portfolio from a source."""
    portfolio = source.discover_portfolio()
    galleries = tuple(
        replace(gallery, assets=tuple(source.iter_assets(gallery)))
        for gallery in source.iter_galleries(portfolio)
    )
    return replace(portfolio, galleries=galleries)
