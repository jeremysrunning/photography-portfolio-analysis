"""Command-line entry point."""

import argparse
import logging
import os
import time
from collections.abc import Sequence
from pathlib import Path

from ppa import __version__
from ppa.analysis import (
    PRODUCTION_IDENTITIES,
    VisualAnalyzerDataset,
    analyze_baseline,
    analyze_equipment,
    analyze_focal_lengths,
    analyze_timeline,
    analyze_visual_habits,
    get_visual_analyzer,
    list_visual_analyzers,
)
from ppa.core.logging import configure_logging
from ppa.core.visual_workflow import (
    VisualAnalysisOptions,
    VisualProgress,
    VisualWorkflowError,
    run_visual_analysis,
)
from ppa.core.workflows import (
    EnrichmentSnapshot,
    ExifWorkflowResult,
    InspectionResult,
    PersistenceError,
    PersistenceResult,
    enrich_portfolio_exif,
    enrichment_snapshot,
    inspect_public_portfolio,
    persist_portfolio,
)
from ppa.models import Portfolio
from ppa.reports import (
    render_baseline,
    render_equipment,
    render_focal_lengths,
    render_timeline,
    render_visual_habits,
)
from ppa.sources import SourceError, SourceRateLimitError
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
    import_command = commands.add_parser(
        "import",
        help="Inspect, persist, and enrich a public SmugMug portfolio.",
    )
    import_command.add_argument("url", help="Public SmugMug site URL.")
    import_command.add_argument(
        "--database",
        type=Path,
        required=True,
        help="SQLite dataset path.",
    )
    import_command.add_argument(
        "--api-key",
        default=os.environ.get("PPA_SMUGMUG_API_KEY"),
        help="SmugMug API key (prefer PPA_SMUGMUG_API_KEY).",
    )
    import_command.add_argument(
        "--retry-failed",
        action="store_true",
        help="Retry assets that failed in an earlier run.",
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
    equipment = report_commands.add_parser(
        "equipment",
        help="Measure equipment and exposure metadata patterns.",
    )
    _add_database_selection(equipment)
    focal_length = report_commands.add_parser(
        "focal-length",
        help="Measure recorded focal-length use.",
    )
    _add_database_selection(focal_length)
    focal_length.add_argument(
        "--details",
        action="store_true",
        help="Include complete primary focal-length and range distributions.",
    )
    focal_length.add_argument(
        "--camera-breakdown",
        action="store_true",
        help="Include complete per-camera focal-length measurements.",
    )
    focal_length.add_argument(
        "--lens-breakdown",
        action="store_true",
        help="Include complete per-lens native focal-length measurements.",
    )
    focal_length.add_argument(
        "--gallery-breakdown",
        action="store_true",
        help="Include complete per-gallery focal-length measurements.",
    )
    focal_length.add_argument(
        "--year-breakdown",
        action="store_true",
        help="Include complete per-year focal-length measurements.",
    )
    timeline = report_commands.add_parser(
        "timeline",
        help="Measure recorded capture dates and hours.",
    )
    _add_database_selection(timeline)
    timeline.add_argument(
        "--details",
        action="store_true",
        help="Include complete yearly, monthly, and recorded-hour distributions.",
    )
    timeline.add_argument(
        "--camera-breakdown",
        action="store_true",
        help="Include complete per-camera timeline distributions.",
    )
    timeline.add_argument(
        "--gallery-breakdown",
        action="store_true",
        help="Include complete per-gallery timeline distributions.",
    )
    visual_habits = report_commands.add_parser(
        "visual-habits",
        help="Aggregate persisted deterministic visual measurements.",
    )
    _add_database_selection(visual_habits)
    visual_habits.add_argument(
        "--details",
        action="store_true",
        help="Include detailed measurement evidence and provenance.",
    )
    for option, help_text in (
        ("gallery", "Include qualifying per-gallery visual measurements."),
        ("year", "Include qualifying per-capture-year visual measurements."),
        ("camera", "Include qualifying per-camera visual measurements."),
        ("lens", "Include qualifying per-lens visual measurements."),
        ("orientation", "Include qualifying per-orientation visual measurements."),
    ):
        visual_habits.add_argument(
            f"--{option}-breakdown",
            action="store_true",
            help=help_text,
        )
    analyze = commands.add_parser("analyze", help="Run persisted portfolio analyzers.")
    analyze_commands = analyze.add_subparsers(dest="analyze_command", required=True)
    visual = analyze_commands.add_parser(
        "visual",
        help="Run one resumable visual analyzer over stored photographs.",
    )
    _add_database_selection(visual)
    visual.add_argument("--analyzer", help="Exact registered visual analyzer name.")
    visual.add_argument("--list-analyzers", action="store_true")
    visual.add_argument(
        "--api-key",
        default=os.environ.get("PPA_SMUGMUG_API_KEY"),
        help="SmugMug API key (prefer PPA_SMUGMUG_API_KEY).",
    )
    visual.add_argument("--limit", type=int, help="Maximum sorted photographs to select.")
    visual.add_argument(
        "--workers", type=int, default=1, help="Concurrent asset workers (1-4; default: 1)."
    )
    visual.add_argument("--refresh", action="store_true", help="Refresh completed work.")
    visual.add_argument(
        "--retry-failed",
        action="store_true",
        help="Retry failed and cancellation-interrupted pending work.",
    )
    visual.add_argument(
        "--only-failed", action="store_true", help="Select only durable failed work."
    )
    visual.add_argument(
        "--gallery",
        dest="gallery_source_id",
        help="Select this exact gallery source ID.",
    )
    visual.add_argument("--year", type=int, help="Select this recorded capture year.")
    enrich = commands.add_parser("enrich", help="Add source metadata to a saved dataset.")
    enrich_commands = enrich.add_subparsers(dest="enrich_command", required=True)
    exif = enrich_commands.add_parser(
        "exif",
        help="Fetch public SmugMug image metadata.",
    )
    _add_database_selection(exif)
    exif.add_argument(
        "--api-key",
        default=os.environ.get("PPA_SMUGMUG_API_KEY"),
        help="SmugMug API key (prefer PPA_SMUGMUG_API_KEY).",
    )
    exif.add_argument(
        "--batch-size",
        type=int,
        default=25,
        help="Images per SmugMug multi-get request (1-100; default: 25).",
    )
    exif.add_argument(
        "--limit",
        type=int,
        help="Maximum unique assets to process in this run.",
    )
    exif.add_argument(
        "--retry-failed",
        action="store_true",
        help="Retry assets that failed in an earlier run.",
    )
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
            inspection = inspect_public_portfolio(args.url, args.api_key)
        except (SourceError, ValueError) as error:
            logger.error("portfolio_inspection_failed", extra={"reason": str(error)})
            return 1
        if args.database:
            try:
                persist_portfolio(inspection.portfolio, args.database)
            except PersistenceError as error:
                logger.error("portfolio_persistence_failed", extra={"reason": str(error)})
                return 1
            logger.info("portfolio_saved", extra={"path": str(args.database)})
        _print_summary(inspection.portfolio)
        return 0
    if args.command == "import":
        if not args.api_key:
            parser.error(
                "import requires --api-key or the PPA_SMUGMUG_API_KEY environment variable"
            )
        return _import_portfolio(args)
    if args.command == "analyze" and args.analyze_command == "visual":
        return _analyze_visual(args, parser)
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
        if args.report_command == "equipment":
            print(render_equipment(analyze_equipment(portfolio)))
            return 0
        if args.report_command == "focal-length":
            print(
                render_focal_lengths(
                    analyze_focal_lengths(portfolio),
                    details=args.details,
                    camera_breakdown=args.camera_breakdown,
                    lens_breakdown=args.lens_breakdown,
                    gallery_breakdown=args.gallery_breakdown,
                    year_breakdown=args.year_breakdown,
                )
            )
            return 0
        if args.report_command == "timeline":
            print(
                render_timeline(
                    analyze_timeline(portfolio),
                    details=args.details,
                    camera_breakdown=args.camera_breakdown,
                    gallery_breakdown=args.gallery_breakdown,
                )
            )
            return 0
        if args.report_command == "visual-habits":
            report = _analyze_stored_visual_habits(portfolio, args.database)
            print(
                render_visual_habits(
                    report,
                    details=args.details,
                    gallery_breakdown=args.gallery_breakdown,
                    year_breakdown=args.year_breakdown,
                    camera_breakdown=args.camera_breakdown,
                    lens_breakdown=args.lens_breakdown,
                    orientation_breakdown=args.orientation_breakdown,
                )
            )
            return 0
    if args.command == "enrich" and args.enrich_command == "exif":
        if not args.api_key:
            parser.error(
                "enrich exif requires --api-key or the PPA_SMUGMUG_API_KEY environment variable"
            )
        if args.batch_size < 1 or args.batch_size > 100:
            parser.error("--batch-size must be between 1 and 100")
        if args.limit is not None and args.limit < 1:
            parser.error("--limit must be greater than zero")
        try:
            portfolio = _load_stored_portfolio(args.database, args.source, args.source_id)
            if portfolio.source_name != "smugmug":
                raise SourceError(
                    f"EXIF enrichment is not implemented for source: {portfolio.source_name}"
                )
            return _enrich_exif(portfolio, args)
        except SourceRateLimitError as error:
            logger.warning("exif_enrichment_rate_limited", extra={"reason": str(error)})
            print(str(error))
            print("Progress was saved. Run the same command again after the retry interval.")
            return 2
        except (OSError, SourceError, ValueError) as error:
            logger.error("exif_enrichment_failed", extra={"reason": str(error)})
            return 1

    parser.print_help()
    return 0


def _print_summary(portfolio: Portfolio) -> None:
    asset_count = sum(len(gallery.placements) for gallery in portfolio.galleries)
    print(f"Portfolio: {portfolio.title}")
    print(f"Source ID: {portfolio.source_id}")
    print(f"Galleries: {len(portfolio.galleries)}")
    print(f"Photograph references: {asset_count}")
    for gallery in portfolio.galleries:
        print(f"  {gallery.title}: {len(gallery.placements)}")


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
    print(f"Source: {portfolio.source_name}")
    print(f"Source ID: {portfolio.source_id}")
    print(f"Source URL: {portfolio.source_url}")
    print(f"Galleries: {baseline.gallery_count:,}")
    print(f"Media references: {baseline.media_references:,}")
    print(f"Unique media: {baseline.unique_media:,}")
    print(f"Unique photographs: {baseline.unique_photographs:,}")
    print(f"Non-photo media excluded: {baseline.excluded_non_photographs:,}")
    print(f"Additional gallery placements: {baseline.duplicate_references:,}")


def _analyze_stored_visual_habits(portfolio: Portfolio, database: Path):
    with SQLitePortfolioRepository(database) as repository:
        persisted_identities = repository.list_visual_analysis_identities(portfolio)
        datasets = tuple(
            VisualAnalyzerDataset(
                identity,
                repository.list_visual_analysis_records(portfolio, identity),
            )
            for identity in PRODUCTION_IDENTITIES
        )
    return analyze_visual_habits(portfolio, datasets, persisted_identities)


def _enrich_exif(portfolio: Portfolio, args: argparse.Namespace) -> int:
    before = enrichment_snapshot(portfolio, args.database)
    print(
        "EXIF enrichment status: "
        f"{before.status.completed:,} completed, {before.status.pending:,} pending, "
        f"{before.status.failed:,} failed"
    )
    progress_interval = args.batch_size * 10

    def show_progress(processed: int, total: int, failed: int) -> None:
        if processed == total or processed % progress_interval == 0:
            print(f"Processed {processed:,} / {total:,} ({failed:,} failed)")

    result = enrich_portfolio_exif(
        portfolio,
        args.database,
        args.api_key,
        retry_failed=args.retry_failed,
        batch_size=args.batch_size,
        limit=args.limit,
        progress=show_progress,
    )
    if result.run.selected == 0:
        print("No eligible assets need EXIF enrichment.")
        return 0
    print(
        "Run complete: "
        f"{result.run.completed:,} completed, {result.run.failed:,} failed, "
        f"{result.run.skipped_non_photos:,} non-photo assets marked not applicable"
    )
    print(
        "Overall status: "
        f"{result.after.status.completed:,} completed, "
        f"{result.after.status.pending:,} pending, "
        f"{result.after.status.failed:,} failed"
    )
    return 1 if result.run.failed else 0


def _import_portfolio(args: argparse.Namespace) -> int:
    started = time.perf_counter()
    print("Stage 1/3: Inspecting portfolio")
    try:
        inspection = inspect_public_portfolio(args.url, args.api_key)
    except (SourceError, ValueError) as error:
        logger.error("portfolio_import_inspection_failed", extra={"reason": str(error)})
        print(f"Inspection failed: {error}")
        return 1
    _print_import_counts(inspection)

    print("Stage 2/3: Persisting normalized metadata")
    try:
        persistence = persist_portfolio(inspection.portfolio, args.database)
    except PersistenceError as error:
        logger.error("portfolio_import_persistence_failed", extra={"reason": str(error)})
        print(f"Persistence failed: {error}")
        print("EXIF enrichment was not started.")
        return 1
    print(f"Saved normalized metadata to {args.database}")

    print("Stage 3/3: Enriching EXIF")
    before = enrichment_snapshot(persistence.portfolio, args.database)
    _print_enrichment_start(before)
    progress_interval = 250

    def show_progress(processed: int, total: int, failed: int) -> None:
        if processed == total or processed % progress_interval == 0:
            print(f"Processed {processed:,} / {total:,} ({failed:,} failed)")

    try:
        result = enrich_portfolio_exif(
            persistence.portfolio,
            args.database,
            args.api_key,
            retry_failed=args.retry_failed,
            progress=show_progress,
        )
    except SourceRateLimitError as error:
        after = enrichment_snapshot(persistence.portfolio, args.database)
        logger.warning("portfolio_import_rate_limited", extra={"reason": str(error)})
        print(str(error))
        _print_import_summary(inspection, persistence, before, after, args.database, started)
        _print_resume_guidance()
        return 2
    except (OSError, SourceError, ValueError) as error:
        after = enrichment_snapshot(persistence.portfolio, args.database)
        logger.error("portfolio_import_enrichment_failed", extra={"reason": str(error)})
        print(f"EXIF enrichment stopped: {error}")
        _print_import_summary(inspection, persistence, before, after, args.database, started)
        _print_resume_guidance()
        return 1

    _print_import_summary(
        inspection,
        persistence,
        result.before,
        result.after,
        args.database,
        started,
        result,
    )
    if result.after.status.failed or result.after.status.pending:
        _print_resume_guidance()
        return 1
    return 0


def _print_import_counts(inspection: InspectionResult) -> None:
    counts = inspection.counts
    print(
        f"Found {counts.galleries:,} galleries, {counts.media_references:,} media "
        f"references, and {counts.unique_media:,} unique assets "
        f"({counts.photographs:,} photographs, {counts.non_photos:,} non-photo, "
        f"{counts.unknown:,} unknown)."
    )


def _print_enrichment_start(before: EnrichmentSnapshot) -> None:
    print(
        f"Before this run: {before.photographs_complete:,} photographs enriched, "
        f"{before.non_photos_complete:,} non-photo assets marked not applicable, "
        f"{before.status.pending:,} pending, {before.status.failed:,} failed."
    )


def _print_import_summary(
    inspection: InspectionResult,
    persistence: PersistenceResult,
    before: EnrichmentSnapshot,
    after: EnrichmentSnapshot,
    database: Path,
    started: float,
    result: ExifWorkflowResult | None = None,
) -> None:
    newly_enriched = after.photographs_complete - before.photographs_complete
    newly_non_photos = after.non_photos_complete - before.non_photos_complete
    print("Import summary")
    print(f"  Database: {database}")
    print(f"  Galleries inspected: {inspection.counts.galleries:,}")
    print(f"  Unique assets discovered in this inspection: {inspection.counts.unique_media:,}")
    print(f"  Total assets currently persisted: {persistence.counts.unique_media:,}")
    print(f"  Photographs newly enriched during this run: {newly_enriched:,}")
    print(f"  Photographs already enriched before this run: {before.photographs_complete:,}")
    print(
        "  Non-photo assets marked complete because EXIF is not applicable: "
        f"{after.non_photos_complete:,} ({newly_non_photos:,} during this run)"
    )
    if inspection.counts.unknown:
        newly_unknown = after.unknown_complete - before.unknown_complete
        print(
            f"  Unknown-media assets completed: {after.unknown_complete:,} "
            f"({newly_unknown:,} during this run)"
        )
    print(f"  Failed assets: {after.status.failed:,}")
    print(f"  Pending or remaining assets: {after.status.pending:,}")
    if result is not None and result.run.failed:
        print(f"  Item failures during this run: {result.run.failed:,}")
    print(f"  Elapsed: {_format_elapsed(time.perf_counter() - started)}")


def _print_resume_guidance() -> None:
    print("The database remains usable and successful enrichment was preserved.")
    print("The import can be resumed safely by running the same command again.")
    print("Use --retry-failed when failed records need another attempt.")


def _analyze_visual(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    names = list_visual_analyzers()
    if args.list_analyzers:
        if names:
            print("Registered visual analyzers:")
            for name in names:
                print(f"  {name}")
        else:
            print("No production visual analyzers are registered.")
        return 0
    if not names:
        print("No production visual analyzers are registered.")
        print("Issue #37 will provide the first production analyzer.")
        return 1
    if not args.analyzer:
        parser.error("analyze visual requires --analyzer")
    analyzer = get_visual_analyzer(args.analyzer)
    if analyzer is None:
        print(f"Unknown visual analyzer: {args.analyzer}")
        print("Registered visual analyzers: " + ", ".join(names))
        return 1
    if not args.api_key:
        parser.error(
            "analyze visual requires --api-key or the PPA_SMUGMUG_API_KEY environment variable"
        )
    try:
        options = VisualAnalysisOptions(
            limit=args.limit,
            workers=args.workers,
            refresh=args.refresh,
            retry_failed=args.retry_failed,
            only_failed=args.only_failed,
            gallery_source_id=args.gallery_source_id,
            capture_year=args.year,
        )
        portfolio = _load_stored_portfolio(args.database, args.source, args.source_id)
    except (OSError, SourceError, ValueError, VisualWorkflowError):
        logger.error("visual_analysis_setup_failed")
        print("Visual analysis did not start: database or selection configuration is invalid.")
        return 1

    def show_progress(progress: VisualProgress) -> None:
        rate = (
            f"{progress.processing_rate:.2f}/s"
            if progress.processing_rate is not None
            else "not yet meaningful"
        )
        eta = (
            _format_elapsed(progress.estimated_seconds_remaining)
            if progress.estimated_seconds_remaining is not None
            else "not yet meaningful"
        )
        print(
            f"Processed {progress.processed:,} / {progress.selected:,}: "
            f"{progress.completed:,} completed, {progress.skipped:,} skipped, "
            f"{progress.failed:,} failed; rate {rate}; ETA {eta}"
        )

    try:
        result = run_visual_analysis(
            portfolio,
            args.database,
            args.api_key,
            analyzer,
            options=options,
            progress=show_progress,
        )
    except VisualWorkflowError:
        logger.error("visual_analysis_setup_failed")
        print("Visual analysis did not start: source preview access is unavailable.")
        return 1

    print("Visual analysis summary")
    print(f"  Analyzer: {analyzer.identity.name}")
    print(f"  Analyzer version: {analyzer.identity.version}")
    print(f"  Configuration version: {analyzer.identity.configuration_version}")
    print(f"  Eligible photographs: {result.eligible_photographs:,}")
    print(f"  Photographs matching asset filters: {result.filter_matched_photographs:,}")
    print(f"  Work items selected by state: {result.selected_work_items:,}")
    print(f"  Work items processed: {result.processed_work_items:,}")
    print(f"  Completed during this run: {result.completed:,}")
    print(f"  Already completed but excluded: {result.already_completed_excluded:,}")
    print(f"  Skipped during this run: {result.skipped:,}")
    print(f"  Previously skipped and excluded: {result.skipped_excluded:,}")
    print(f"  Failed during this run: {result.failed:,}")
    print(f"  Existing failed but excluded: {result.failed_excluded:,}")
    print(f"  Pending but excluded by state selection: {result.pending_excluded:,}")
    print(f"  Running elsewhere or left running: {result.running_excluded:,}")
    print(f"  Cancellation-interrupted: {result.cancelled:,}")
    print(f"  Remaining selected work: {result.remaining_selected_work:,}")
    print(f"  Downloaded preview bytes: {result.downloaded_bytes:,}")
    print(f"  Elapsed: {_format_elapsed(result.elapsed_seconds)}")
    if result.processing_rate is None:
        print("  Processing rate: not yet meaningful")
    else:
        print(f"  Processing rate: {result.processing_rate:.2f} photographs/second")
    if result.running_excluded:
        print(
            "Running work was not reclaimed. Recovery requires a separately scoped "
            "stale-run policy."
        )
    if result.cancelled or result.failed or result.remaining_selected_work:
        print("Completed results were preserved and the database can be resumed safely.")
    if result.rate_limited:
        return 2
    if result.configuration_failed:
        return 1
    if result.cancelled_by_user:
        return 130
    return 1 if result.failed or result.remaining_selected_work else 0


def _format_elapsed(seconds: float) -> str:
    total = max(0, round(seconds))
    minutes, seconds = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"
