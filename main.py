#!/usr/bin/env python3
"""Command-line entry point for the Telugu movie dataset scraper.

Examples
--------
    python main.py --start-year 2000 --end-year 2023
    python main.py --year 2015
    python main.py --start-year 2020 --end-year 2020 --limit 20
    python main.py --retry-failed
    python main.py --validate
    python main.py --stats
"""

from __future__ import annotations

import argparse
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from config.settings import settings
from scraper import storage
from scraper.pipeline import Pipeline, print_summary, print_validation_report
from scraper.storage import ScraperState
from scraper.wikipedia import WikipediaClient


def configure_logging(verbose: bool = False, quiet: bool = False) -> None:
    """Send INFO+ to the log file and a friendlier level to the console."""
    settings.ensure_dirs()

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    file_handler = RotatingFileHandler(
        settings.log_file, maxBytes=10 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    root.addHandler(file_handler)

    console = logging.StreamHandler(sys.stderr)
    console.setLevel(
        logging.ERROR if quiet else (logging.DEBUG if verbose else logging.WARNING)
    )
    console.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    root.addHandler(console)

    # tqdm writes the progress bar itself; keep urllib3 chatter out of it.
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="Scrape a Telugu-language movie dataset (2000-2023) from Wikipedia.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    years = parser.add_argument_group("year selection")
    years.add_argument(
        "--start-year",
        type=int,
        default=None,
        help=f"first year to scrape (default {settings.default_start_year})",
    )
    years.add_argument(
        "--end-year",
        type=int,
        default=None,
        help=f"last year to scrape (default {settings.default_end_year})",
    )
    years.add_argument(
        "--year", type=int, default=None, help="scrape a single year (overrides range)"
    )

    modes = parser.add_argument_group("modes")
    modes.add_argument(
        "--retry-failed", action="store_true", help="retry previously failed pages"
    )
    modes.add_argument(
        "--validate",
        action="store_true",
        help="re-run validation over stored data and rewrite reports",
    )
    modes.add_argument(
        "--stats", action="store_true", help="print progress statistics and exit"
    )
    modes.add_argument(
        "--discover-only",
        action="store_true",
        help="build the master film list without scraping individual pages",
    )
    modes.add_argument(
        "--export-only",
        action="store_true",
        help="regenerate output files from stored data (no network)",
    )

    options = parser.add_argument_group("options")
    options.add_argument(
        "--limit", type=int, default=None, help="scrape at most N movies (test runs)"
    )
    options.add_argument(
        "--no-cache", action="store_true", help="bypass the HTML cache"
    )
    options.add_argument(
        "--no-resolve",
        action="store_true",
        help="skip API lookups for films without a wikilink",
    )
    options.add_argument(
        "--enrich-tmdb",
        action="store_true",
        help="enrich empty fields via TMDB (requires TMDB_API_KEY)",
    )
    options.add_argument(
        "--min-delay", type=float, default=None, help="minimum seconds between requests"
    )
    options.add_argument(
        "--max-delay", type=float, default=None, help="maximum seconds between requests"
    )
    options.add_argument(
        "--db", type=Path, default=None, help="path to the state database"
    )
    options.add_argument("--verbose", "-v", action="store_true", help="debug logging")
    options.add_argument("--quiet", "-q", action="store_true", help="errors only")

    return parser


def resolve_years(args: argparse.Namespace) -> list[int]:
    """Turn the year flags into a concrete, validated list of years."""
    if args.year is not None:
        start = end = args.year
    else:
        start = args.start_year or settings.default_start_year
        end = args.end_year or settings.default_end_year

    if start > end:
        raise SystemExit(f"--start-year ({start}) must not exceed --end-year ({end})")

    out_of_range = [
        year
        for year in (start, end)
        if not (settings.min_valid_year <= year <= settings.max_valid_year)
    ]
    if out_of_range:
        raise SystemExit(
            f"Years must fall within {settings.min_valid_year}-{settings.max_valid_year}; "
            f"got {out_of_range}"
        )

    return list(range(start, end + 1))


def command_stats(state: ScraperState) -> int:
    """Print queue statistics."""
    stats = state.stats()
    print("")
    print("SCRAPER STATE")
    print("-" * 46)
    print(f"Total films tracked : {stats['total']}")
    print(f"  success           : {stats['success']}")
    print(f"  pending           : {stats['pending']}")
    print(f"  failed            : {stats['failed']}")
    print("")
    if stats["per_year"]:
        print(f"{'Year':<8}{'Total':>8}{'OK':>8}{'Failed':>8}")
        print("-" * 46)
        for row in stats["per_year"]:
            print(
                f"{row['year']:<8}{row['total']:>8}{row['ok'] or 0:>8}{row['failed'] or 0:>8}"
            )
    print("-" * 46)
    return 0


def command_validate(state: ScraperState) -> int:
    """Re-validate stored records and rewrite the reports."""
    records = state.load_records(only_valid=True)
    if not records:
        print("No records stored yet - run a scrape first.")
        return 1

    print_validation_report(records)
    storage.write_missing_fields_csv(records)
    storage.write_discrepancies_csv(records)
    print(f"\nWrote {settings.output_dir / settings.missing_csv_name}")
    print(f"Wrote {settings.output_dir / settings.discrepancies_csv_name}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(verbose=args.verbose, quiet=args.quiet)
    settings.ensure_dirs()

    state = ScraperState(args.db)

    # Read-only modes need no network client.
    if args.stats:
        try:
            return command_stats(state)
        finally:
            state.close()

    if args.validate:
        try:
            return command_validate(state)
        finally:
            state.close()

    client = WikipediaClient(
        use_cache=not args.no_cache,
        min_delay=args.min_delay,
        max_delay=args.max_delay,
    )
    pipeline = Pipeline(client, state, resolve_unlinked=not args.no_resolve)
    run_id = state.start_run(" ".join(argv or sys.argv[1:]))

    try:
        if args.export_only:
            report = pipeline.export()
            print_summary(report)
            state.finish_run(run_id, report)
            return 0

        if args.retry_failed:
            pipeline.retry_failed(limit=args.limit)
        else:
            years = resolve_years(args)
            candidates = pipeline.discover(years)
            pipeline.queue_candidates(candidates)

            if args.discover_only:
                print(f"\nDiscovered {len(candidates)} films across {len(years)} years.")
                print("Run again without --discover-only to scrape their pages.")
                state.finish_run(run_id, pipeline.stats.as_dict())
                return 0

            pipeline.scrape_pending(years=years, limit=args.limit)

        if args.enrich_tmdb:
            from scraper.tmdb import enrich_records

            enriched = enrich_records(state.load_records(only_valid=True))
            for record in enriched:
                state.mark_success(
                    record.wikipedia_url,
                    record,
                    language_confidence=record.language_confidence,
                    is_valid=True,
                )

        report = pipeline.export()
        print_summary(report)
        state.finish_run(run_id, report)
        return 0

    except KeyboardInterrupt:
        # Progress is committed per movie, so a Ctrl-C is always resumable.
        logging.getLogger(__name__).warning("Interrupted by user")
        print("\nInterrupted. Progress saved - rerun the same command to resume.")
        return 130
    finally:
        pipeline.close()


if __name__ == "__main__":
    raise SystemExit(main())
