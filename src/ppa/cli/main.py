"""Command-line entry point."""

import argparse
import logging
import os
from collections.abc import Sequence
from pathlib import Path

from ppa import __version__
from ppa.analysis import analyze_baseline
from ppa.core.logging import configure_logging
from ppa.models import Portfolio
from ppa.reports import render_baseline
from ppa.sources import SourceError
from ppa.sources.smugmug import SmugMugSource
from ppa.storage.sqlite import SQLitePortfolioRepository

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="ppa",
        description="Discover measurable patterns in photographic portfolios.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
    )
    commands = parser.add_subparsers(dest="command")
    init_db = commands.add_parser("init-db", help="Initialize a local SQLite dataset.")
    init_db.add_argument("path", type=Path, help="Path to the SQLite database.")
    inspect = commands.add_parser("inspect", help="Inspect a public SmugMug portfolio.")
    inspect.add_argument("url", help="Public SmugMug site URL.")
    inspect.add_argument(
        "--api-key",
        default=os.environ.get("PPA_SMUGMUG_API_KEY"),
        help="SmugMug API key (prefer PPA_SMUGMUG_API_KEY).",
    )
    inspect.add_argument(
        "--database",
        type=Path,
        help="Optionally save the normalized dataset to SQLite.",
    )
    show = commands.add_parser("show", help="Show a portfolio stored in SQLite.")
    _add_database_selection(show)
    report = commands.add_parser("report", help="Generate a portfolio report.")
    report_commands = report.add_subparsers(dest="report_command", required=True)
    baseline = report_commands.add_parser(
        "baseline",
        help="Measure dataset shape and metadata coverage.",
    )
    _add_database_selection(baseline)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(args.log_level)

    if args.command == "init-db":
        with SQLitePortfolioRepository(args.path) as repository:
            repository.initialize()
        logger.info("database_initialized", extra={"path": str(args.path)})
        return 0
    if args.command == "inspect":
        if not args.api_key:
            parser.error(
                "inspect requires --api-key or the PPA_SMUGMUG_API_KEY environment variable"
            )
        try:
            portfolio = SmugMugSource(args.url, args.api_key).load_portfolio()
        except (SourceError, ValueError) as error:
            logger.error("portfolio_inspection_failed", extra={"reason": str(error)})
            return 1
        if args.database:
            with SQLitePortfolioRepository(args.database) as repository:
                repository.save(portfolio)
            logger.info("portfolio_saved", extra={"path": str(args.database)})
        _print_summary(portfolio)
        return 0
    if args.command in {"show", "report"}:
        try:
            portfolio = _load_stored_portfolio(args.database, args.source, args.source_id)
        except (OSError, SourceError) as error:
            logger.error("portfolio_load_failed", extra={"reason": str(error)})
            return 1
        if args.command == "show":
            _print_stored_portfolio(portfolio)
            return 0
        if args.report_command == "baseline":
            print(render_baseline(analyze_baseline(portfolio)))
            return 0

    parser.print_help()
    return 0


def _print_summary(portfolio: Portfolio) -> None:
    asset_count = sum(len(gallery.assets) for gallery in portfolio.galleries)
    print(f"Portfolio: {portfolio.title}")
    print(f"Source ID: {portfolio.source_id}")
    print(f"Galleries: {len(portfolio.galleries)}")
    print(f"Photograph references: {asset_count}")
    for gallery in portfolio.galleries:
        print(f"  {gallery.title}: {len(gallery.assets)}")


def _add_database_selection(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("database", type=Path, help="SQLite dataset path.")
    parser.add_argument(
        "--source", help="Source name when the database contains multiple portfolios."
    )
    parser.add_argument(
        "--source-id", help="Source ID when the database contains multiple portfolios."
    )


def _load_stored_portfolio(
    database: Path,
    source: str | None,
    source_id: str | None,
) -> Portfolio:
    if not database.is_file():
        raise SourceError(f"Database does not exist: {database}")
    if (source is None) != (source_id is None):
        raise SourceError("--source and --source-id must be provided together.")
    with SQLitePortfolioRepository(database) as repository:
        keys = repository.list_keys()
        if not keys:
            raise SourceError("Database does not contain a portfolio.")
        if source is None and source_id is None:
            if len(keys) > 1:
                choices = ", ".join(f"{item_source}/{item_id}" for item_source, item_id in keys)
                raise SourceError(
                    f"Database contains multiple portfolios ({choices}); select one with "
                    "--source and --source-id."
                )
            source, source_id = keys[0]
        portfolio = repository.get(source, source_id)
    if portfolio is None:
        raise SourceError(f"Portfolio not found: {source}/{source_id}")
    return portfolio


def _print_stored_portfolio(portfolio: Portfolio) -> None:
    baseline = analyze_baseline(portfolio)
    print(f"Portfolio: {portfolio.title}")
    print(f"Source: {portfolio.source}")
    print(f"Source ID: {portfolio.source_id}")
    print(f"Source URL: {portfolio.source_url}")
    print(f"Galleries: {baseline.gallery_count:,}")
    print(f"Media references: {baseline.media_references:,}")
    print(f"Unique media: {baseline.unique_media:,}")
    print(f"Unique photographs: {baseline.unique_photographs:,}")
    print(f"Non-photo media excluded: {baseline.excluded_non_photographs:,}")
    print(f"Additional gallery placements: {baseline.duplicate_references:,}")
