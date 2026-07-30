"""Research-only command-line interface."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from pathlib import Path

from ppa.storage import SQLitePortfolioRepository
from research.visual_preview.benchmark import (
    BenchmarkConfiguration,
    run_benchmark,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m research.visual_preview",
        description=(
            "Run the isolated, bounded visual-preview research benchmark. "
            "Raw output is local-only and must not be committed."
        ),
    )
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument(
        "--api-key",
        default=os.environ.get("PPA_SMUGMUG_API_KEY"),
        help="SmugMug API key (prefer PPA_SMUGMUG_API_KEY).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("research-output/visual-preview-raw-local.json"),
        help="Ignored local raw-result path.",
    )
    parser.add_argument(
        "--aggregate-output",
        type=Path,
        default=Path("research-output/visual-preview-aggregate.json"),
        help="Non-identifying aggregate-result path.",
    )
    parser.add_argument("--sample-size", type=int, default=48)
    parser.add_argument("--seed", default="issue-19-v1")
    parser.add_argument("--source")
    parser.add_argument("--source-id")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.api_key:
        parser.error("the benchmark requires --api-key or PPA_SMUGMUG_API_KEY")
    if not 1 <= args.sample_size <= 60:
        parser.error("--sample-size must be between 1 and 60")
    if (args.source is None) != (args.source_id is None):
        parser.error("--source and --source-id must be supplied together")

    with SQLitePortfolioRepository(args.database) as repository:
        keys = repository.list_keys()
        if args.source is None:
            if len(keys) != 1:
                parser.error("select one portfolio with --source and --source-id")
            source, source_id = keys[0]
        else:
            source, source_id = args.source, args.source_id
        portfolio = repository.get(source, source_id)
    if portfolio is None:
        parser.error("the selected portfolio was not found")
    if portfolio.source_name != "smugmug":
        parser.error("the experimental resolver currently supports SmugMug only")

    configuration = BenchmarkConfiguration(
        sample_size=args.sample_size,
        seed=args.seed,
    )
    aggregate = run_benchmark(
        portfolio,
        portfolio.source_url,
        args.api_key,
        args.output,
        configuration=configuration,
    )
    args.aggregate_output.parent.mkdir(parents=True, exist_ok=True)
    args.aggregate_output.write_text(
        json.dumps(aggregate, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(f"Local raw results: {args.output}")
    print(f"Aggregate results: {args.aggregate_output}")
    print(f"Completed: {aggregate['outcomes']['completed']} / {configuration.sample_size}")
    return 0 if aggregate["outcomes"]["completed"] else 1
