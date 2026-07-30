"""Run a bounded aggregate-only validation of production preview access."""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from pathlib import Path
from statistics import median

from ppa.models import MediaType
from ppa.sources import PreviewRequest, PreviewStorageMode, SourceError
from ppa.sources.smugmug import SmugMugSource
from ppa.storage import SQLitePortfolioRepository
from research.visual_preview.sampling import select_sample

_EDGES = (256, 512, 1024)


def main() -> int:
    """Validate a small real sample without emitting identifying records."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("--sample-size", type=int, default=12)
    args = parser.parse_args()
    if not 1 <= args.sample_size <= 20:
        parser.error("--sample-size must be between 1 and 20")
    api_key = os.environ.get("PPA_SMUGMUG_API_KEY", "")
    if not api_key.strip():
        parser.error("PPA_SMUGMUG_API_KEY is required")

    with SQLitePortfolioRepository(args.database) as repository:
        keys = repository.list_keys()
        if len(keys) != 1:
            parser.error("validation requires a database containing exactly one portfolio")
        portfolio = repository.get(*keys[0])
    if portfolio is None:
        parser.error("the selected portfolio could not be loaded")
    if portfolio.source_name != "smugmug":
        parser.error("production preview validation currently supports SmugMug")

    sample = select_sample(portfolio, args.sample_size, seed="issue-18-production-v1")
    source = SmugMugSource(portfolio.source_url, api_key)
    completed = 0
    failures: Counter[str] = Counter()
    decoded_edges: Counter[int] = Counter()
    content_types: Counter[str] = Counter()
    storage_modes: Counter[str] = Counter()
    byte_counts: list[int] = []
    residual_files = 0

    for index, record in enumerate(sample):
        if record.asset.media_type is not MediaType.PHOTOGRAPH:
            continue
        edge = _EDGES[index % len(_EDGES)]
        mode = PreviewStorageMode.TEMPORARY_FILE if index % 4 == 3 else PreviewStorageMode.MEMORY
        path: Path | None = None
        try:
            with source.open_preview(
                record.asset,
                PreviewRequest(edge, storage_mode=mode),
            ) as preview:
                if mode is PreviewStorageMode.MEMORY:
                    decoded_edges[max(preview.image.size)] += 1
                else:
                    path = preview.temporary_path
                    decoded_edges[max(preview.metadata.width, preview.metadata.height)] += 1
                completed += 1
                content_types[preview.metadata.content_type] += 1
                storage_modes[preview.metadata.storage_mode.value] += 1
                byte_counts.append(preview.metadata.encoded_byte_count)
        except SourceError as error:
            failures[type(error).__name__] += 1
        if path is not None and path.exists():
            residual_files += 1

    result = {
        "artifact_kind": "aggregate_non_identifying_production_preview_validation",
        "sample_size": len(sample),
        "requested_edges": list(_EDGES),
        "completed": completed,
        "failure_categories": dict(sorted(failures.items())),
        "decoded_longest_edges": {str(key): value for key, value in sorted(decoded_edges.items())},
        "content_types": dict(sorted(content_types.items())),
        "storage_modes": dict(sorted(storage_modes.items())),
        "encoded_bytes": {
            "count": len(byte_counts),
            "minimum": min(byte_counts) if byte_counts else None,
            "median": median(byte_counts) if byte_counts else None,
            "maximum": max(byte_counts) if byte_counts else None,
        },
        "temporary_files_remaining": residual_files,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if completed and not residual_files else 1


if __name__ == "__main__":
    raise SystemExit(main())
