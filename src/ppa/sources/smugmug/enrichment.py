"""Resumable SmugMug metadata enrichment."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from ppa.models import JsonValue, MediaType
from ppa.sources import SourceError, SourceRateLimitError
from ppa.sources.smugmug.api import SmugMugApiClient
from ppa.storage import EnrichmentTarget, PortfolioRepository

ProgressCallback = Callable[[int, int, int], None]


@dataclass(frozen=True, slots=True)
class EnrichmentResult:
    """Counts from one enrichment run."""

    selected: int
    completed: int
    failed: int
    skipped_non_photos: int


class SmugMugExifEnricher:
    """Fetch public image metadata in multi-get batches and persist each result."""

    def __init__(
        self,
        client: SmugMugApiClient,
        repository: PortfolioRepository,
        *,
        batch_size: int = 25,
    ) -> None:
        if not 1 <= batch_size <= 100:
            raise ValueError("batch_size must be between 1 and 100")
        self.client = client
        self.repository = repository
        self.batch_size = batch_size

    def enrich(
        self,
        source: str,
        portfolio_source_id: str,
        targets: Sequence[EnrichmentTarget],
        progress: ProgressCallback | None = None,
    ) -> EnrichmentResult:
        """Enrich selected targets, committing successful assets immediately."""
        completed = 0
        failed = 0
        skipped = 0
        photo_targets: list[EnrichmentTarget] = []

        for target in targets:
            if target.media_type is MediaType.NON_PHOTO:
                self.repository.save_asset_enrichment(
                    source,
                    portfolio_source_id,
                    target.source_id,
                    "exif",
                    {},
                )
                completed += 1
                skipped += 1
            else:
                photo_targets.append(target)

        for start in range(0, len(photo_targets), self.batch_size):
            batch = photo_targets[start : start + self.batch_size]
            try:
                metadata_by_id = self._fetch_batch(batch)
            except SourceRateLimitError:
                raise
            except SourceError as error:
                for target in batch:
                    self.repository.fail_asset_enrichment(
                        source,
                        portfolio_source_id,
                        target.source_id,
                        "exif",
                        str(error),
                    )
                    failed += 1
            else:
                for target in batch:
                    metadata = metadata_by_id.get(target.source_id)
                    if metadata is None:
                        self.repository.fail_asset_enrichment(
                            source,
                            portfolio_source_id,
                            target.source_id,
                            "exif",
                            "SmugMug response omitted metadata for this image.",
                        )
                        failed += 1
                        continue
                    self.repository.save_asset_enrichment(
                        source,
                        portfolio_source_id,
                        target.source_id,
                        "exif",
                        metadata,
                    )
                    completed += 1
            if progress:
                progress(completed + failed, len(targets), failed)

        if progress and not photo_targets:
            progress(completed, len(targets), failed)
        return EnrichmentResult(
            selected=len(targets),
            completed=completed,
            failed=failed,
            skipped_non_photos=skipped,
        )

    def _fetch_batch(
        self,
        targets: Sequence[EnrichmentTarget],
    ) -> dict[str, dict[str, JsonValue]]:
        identifiers = ",".join(target.source_id for target in targets)
        response = self.client.get_response(f"/api/v2/image/{identifiers}!metadata")
        value = response.get("ImageMetadata")
        if isinstance(value, dict):
            objects = [value]
        elif isinstance(value, list):
            objects = [item for item in value if isinstance(item, dict)]
        else:
            raise SourceError("SmugMug response did not include ImageMetadata.")

        results: dict[str, dict[str, JsonValue]] = {}
        for index, metadata in enumerate(objects):
            source_id = _metadata_source_id(metadata)
            if source_id is None and index < len(targets):
                source_id = targets[index].source_id
            if source_id is not None:
                results[source_id] = _normalized_metadata(metadata)
        return results


def _metadata_source_id(metadata: dict[str, Any]) -> str | None:
    uri = metadata.get("Uri")
    if not isinstance(uri, str) or "/image/" not in uri:
        return None
    identifier = uri.split("/image/", 1)[1].split("!", 1)[0].split("?", 1)[0]
    return identifier or None


def _normalized_metadata(metadata: dict[str, Any]) -> dict[str, JsonValue]:
    excluded = {"Uri", "Uris", "ResponseLevel", "UriDescription"}
    return {
        key: value
        for key, value in metadata.items()
        if key not in excluded and _is_json_value(value)
    }


def _is_json_value(value: Any) -> bool:
    if value is None or isinstance(value, bool | int | float | str):
        return True
    if isinstance(value, list):
        return all(_is_json_value(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and _is_json_value(item) for key, item in value.items())
    return False
