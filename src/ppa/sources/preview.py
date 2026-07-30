"""Source-agnostic temporary preview contracts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from PIL import Image

PRODUCTION_PREVIEW_MAXIMUM_EDGE = 1024
PRODUCTION_PREVIEW_MAXIMUM_BYTES = 8_000_000
DEFAULT_PREVIEW_CONTENT_TYPES = frozenset(
    {
        "image/jpeg",
        "image/png",
        "image/webp",
    }
)

CancellationCheck = Callable[[], bool]


class PreviewStorageMode(StrEnum):
    """How a temporary preview is exposed during its owned lifecycle."""

    MEMORY = "memory"
    TEMPORARY_FILE = "temporary_file"


@dataclass(frozen=True, slots=True)
class PreviewRequest:
    """Bounded, provider-independent preview requirements."""

    maximum_edge: int
    maximum_bytes: int = PRODUCTION_PREVIEW_MAXIMUM_BYTES
    accepted_content_types: frozenset[str] = DEFAULT_PREVIEW_CONTENT_TYPES
    storage_mode: PreviewStorageMode = PreviewStorageMode.MEMORY

    def __post_init__(self) -> None:
        if not 1 <= self.maximum_edge <= PRODUCTION_PREVIEW_MAXIMUM_EDGE:
            raise ValueError(
                f"maximum_edge must be between 1 and {PRODUCTION_PREVIEW_MAXIMUM_EDGE}"
            )
        if not 1 <= self.maximum_bytes <= PRODUCTION_PREVIEW_MAXIMUM_BYTES:
            raise ValueError(
                f"maximum_bytes must be between 1 and {PRODUCTION_PREVIEW_MAXIMUM_BYTES}"
            )
        normalized = frozenset(item.casefold() for item in self.accepted_content_types)
        if not normalized or any(not item.startswith("image/") for item in normalized):
            raise ValueError("accepted_content_types must contain image media types")
        object.__setattr__(self, "accepted_content_types", normalized)
        if not isinstance(self.storage_mode, PreviewStorageMode):
            raise ValueError("storage_mode must be a PreviewStorageMode")


@dataclass(frozen=True, slots=True)
class PreviewMetadata:
    """Immutable facts about one validated temporary preview."""

    requested_maximum_edge: int
    width: int
    height: int
    content_type: str
    downloaded_content_type: str
    downloaded_encoded_byte_count: int
    provenance: str
    storage_mode: PreviewStorageMode
    provider_reported_width: int | None = None
    provider_reported_height: int | None = None
    orientation_swap_applied: bool = False
    temporary_file_byte_count: int | None = None

    def __post_init__(self) -> None:
        if not 1 <= self.requested_maximum_edge <= PRODUCTION_PREVIEW_MAXIMUM_EDGE:
            raise ValueError("requested_maximum_edge is outside the production bound")
        if self.width < 1 or self.height < 1:
            raise ValueError("preview dimensions must be positive")
        if max(self.width, self.height) > self.requested_maximum_edge:
            raise ValueError("preview dimensions exceed the requested maximum edge")
        if self.downloaded_encoded_byte_count < 1:
            raise ValueError("downloaded_encoded_byte_count must be positive")
        if not self.content_type.startswith("image/"):
            raise ValueError("content_type must be an image media type")
        if not self.downloaded_content_type.startswith("image/"):
            raise ValueError("downloaded_content_type must be an image media type")
        if not self.provenance.strip():
            raise ValueError("provenance must not be empty")
        reported = (self.provider_reported_width, self.provider_reported_height)
        if (reported[0] is None) != (reported[1] is None):
            raise ValueError("provider-reported dimensions must be supplied together")
        if any(value is not None and value < 1 for value in reported):
            raise ValueError("provider-reported dimensions must be positive")
        if self.storage_mode is PreviewStorageMode.MEMORY:
            if self.temporary_file_byte_count is not None:
                raise ValueError("memory-backed previews have no temporary-file byte count")
        elif self.temporary_file_byte_count is None or self.temporary_file_byte_count < 1:
            raise ValueError("temporary-file previews require a positive file byte count")


@dataclass(slots=True)
class PreviewResource:
    """Own one decoded image or temporary path until explicitly closed."""

    metadata: PreviewMetadata
    _image: Image.Image | None = field(default=None, repr=False)
    _temporary_path: Path | None = field(default=None, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        has_image = self._image is not None
        has_path = self._temporary_path is not None
        if has_image == has_path:
            raise ValueError("preview resource must own exactly one image or temporary path")
        if has_image and self.metadata.storage_mode is not PreviewStorageMode.MEMORY:
            raise ValueError("memory-backed metadata must accompany a decoded image")
        if has_path and self.metadata.storage_mode is not PreviewStorageMode.TEMPORARY_FILE:
            raise ValueError("temporary-file metadata must accompany a path")

    @classmethod
    def memory(cls, metadata: PreviewMetadata, image: Image.Image) -> PreviewResource:
        """Create a resource that owns one decoded image."""
        return cls(metadata=metadata, _image=image)

    @classmethod
    def temporary_file(cls, metadata: PreviewMetadata, path: Path) -> PreviewResource:
        """Create a resource that owns one temporary path."""
        return cls(metadata=metadata, _temporary_path=path)

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def image(self) -> Image.Image:
        """Return the shared decoded image while this resource is open."""
        if self._closed:
            raise RuntimeError("preview resource is closed")
        if self._image is None:
            raise RuntimeError("preview resource is temporary-file-backed")
        return self._image

    @property
    def temporary_path(self) -> Path:
        """Return the owned path while this resource is open."""
        if self._closed:
            raise RuntimeError("preview resource is closed")
        if self._temporary_path is None:
            raise RuntimeError("preview resource is memory-backed")
        return self._temporary_path

    def close(self) -> None:
        """Release owned resources; repeated cleanup is safe."""
        if self._closed:
            return
        image = self._image
        path = self._temporary_path
        if image is not None:
            image.close()
            self._image = None
        if path is not None:
            path.unlink(missing_ok=True)
            self._temporary_path = None
        self._closed = True

    def __enter__(self) -> PreviewResource:
        if self._closed:
            raise RuntimeError("preview resource is closed")
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
