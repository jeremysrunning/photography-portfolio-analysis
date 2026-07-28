"""Storage contracts."""

from typing import Protocol, runtime_checkable

from ppa.models import Portfolio


@runtime_checkable
class PortfolioRepository(Protocol):
    """Persist normalized datasets without storing original image content."""

    def initialize(self) -> None:
        """Create or update the datastore schema."""
        ...

    def save(self, portfolio: Portfolio) -> None:
        """Persist a complete normalized portfolio dataset."""
        ...

    def get(self, source: str, source_id: str) -> Portfolio | None:
        """Retrieve a normalized portfolio by source-scoped identity."""
        ...

    def list_keys(self) -> tuple[tuple[str, str], ...]:
        """List source-scoped portfolio identities in the datastore."""
        ...
