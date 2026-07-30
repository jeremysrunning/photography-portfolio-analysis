"""Contracts and registration for production visual analyzers."""

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from PIL import Image

from ppa.models import Asset
from ppa.sources import PreviewMetadata, PreviewRequest, PreviewStorageMode
from ppa.visual import AnalyzerIdentity, VisualResult


@runtime_checkable
class VisualAnalyzer(Protocol):
    """Measure one normalized asset from one bounded decoded preview."""

    @property
    def identity(self) -> AnalyzerIdentity:
        """Return the immutable analyzer and configuration identity."""
        ...

    @property
    def preview_request(self) -> PreviewRequest:
        """Return the bounded preview required by this analyzer."""
        ...

    @property
    def allows_empty_results(self) -> bool:
        """Return whether successful analysis may intentionally emit no results."""
        ...

    def analyze(
        self,
        asset: Asset,
        image: Image.Image,
        metadata: PreviewMetadata,
    ) -> Sequence[VisualResult]:
        """Return derived results without retaining the image."""
        ...


_ANALYZERS: dict[str, VisualAnalyzer] = {}


def register_visual_analyzer(analyzer: VisualAnalyzer) -> None:
    """Register one production analyzer under its stable analyzer name."""
    if analyzer.preview_request.storage_mode is not PreviewStorageMode.MEMORY:
        raise ValueError("visual analyzers must use memory-backed previews")
    allows_empty_results(analyzer)
    name = analyzer.identity.name
    if name in _ANALYZERS:
        raise ValueError(f"visual analyzer is already registered: {name}")
    _ANALYZERS[name] = analyzer


def get_visual_analyzer(name: str) -> VisualAnalyzer | None:
    """Return a registered analyzer by exact stable name."""
    return _ANALYZERS.get(name)


def list_visual_analyzers() -> tuple[str, ...]:
    """List registered analyzer names deterministically."""
    return tuple(sorted(_ANALYZERS))


def allows_empty_results(analyzer: VisualAnalyzer) -> bool:
    """Return an analyzer's explicit empty-output policy, defaulting to false."""
    value = getattr(analyzer, "allows_empty_results", False)
    if not isinstance(value, bool):
        raise ValueError("allows_empty_results must be a boolean")
    return value
