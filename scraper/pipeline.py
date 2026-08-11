"""Orchestration: discovery -> scrape -> validate -> export.

Kept separate from ``main.py`` so the pipeline can be driven from tests or
another program without going through argument parsing.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from requests.exceptions import RequestException
from tqdm import tqdm

from config.settings import settings
from scraper import storage
from scraper.cleaner import normalise_key, normalise_title
from scraper.extractor import MovieRecord, enrich_from_wikidata, extract_movie
from scraper.parser import (
    MovieCandidate,
    build_year_page_titles,
    deduplicate_candidates,
    parse_year_page,
)
from scraper.storage import ScraperState
from scraper.validator import (
    build_missing_report,
    deduplicate_records,
    field_coverage,
    validate_record,
)
from scraper.wikipedia import WikipediaClient

logger = logging.getLogger(__name__)


# Redirect targets that mean "this film has no article of its own".
# A title with no page frequently redirects to an aggregate page -- e.g.
# "Eureka" -> "List of Telugu films of 2020", "Sivudu" -> "List of
# Baahubali characters". Following those silently turns a list page into a
# dataset row, so such targets are treated as a miss.
_AGGREGATE_TITLE_RE = re.compile(
    r"^(?:list of |lists of )|"
    r"\b(?:filmography|discography|characters|episodes|awards and nominations)\b",
    re.I,
)


def _is_plausible_article(target: str, movie_name: str) -> bool:
    """Reject redirects that landed on an aggregate or unrelated page.

    A redirect is accepted only when the destination still looks like the
    film we asked for: either the titles agree once disambiguators are
    stripped, or the target merely adds a qualifier ("Yogi (2007 film)").
    """
    if _AGGREGATE_TITLE_RE.search(target):
        return False

    target_key = normalise_key(normalise_title(target))
    wanted_key = normalise_key(normalise_title(movie_name))
    if not target_key or not wanted_key:
        return False

    # Exact match after normalisation, or the target is the film plus a
    # parenthetical qualifier that the API appended.
    return target_key == wanted_key or target_key.startswith(f"{wanted_key} ")


@dataclass
class PipelineStats:
    """Counters accumulated across a run."""

    years_processed: list[int] = field(default_factory=list)
    discovered: int = 0
    newly_queued: int = 0
    scraped: int = 0
    failed: int = 0
    rejected: int = 0
    duplicates: int = 0
    unresolved_titles: int = 0
    year_discrepancies: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "years_processed": self.years_processed,
            "movies_discovered": self.discovered,
            "movies_newly_queued": self.newly_queued,
            "movies_scraped": self.scraped,
            "movies_failed": self.failed,
            "movies_rejected": self.rejected,
            "duplicates_merged": self.duplicates,
            "unresolved_titles": self.unresolved_titles,
            "year_discrepancies": self.year_discrepancies,
        }


class Pipeline:
    """Drives the full scrape."""

    def __init__(
        self,
        client: WikipediaClient | None = None,
        state: ScraperState | None = None,
        *,
        resolve_unlinked: bool = True,
    ) -> None:
        self.client = client or WikipediaClient()
        self.state = state or ScraperState()
        # Titles without an article link need an API lookup to find a URL.
        self.resolve_unlinked = resolve_unlinked
        self.stats = PipelineStats()

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------
    def find_year_page(self, year: int) -> tuple[str, str] | None:
        """Locate a year's list page, falling back to search.

        Returns ``(title, html)``. Multiple title patterns are tried before
        resorting to the search API, because Wikipedia page names vary.
        """
        for title in build_year_page_titles(year):
            resolved = self.client.resolve_title(title)
            if resolved:
                logger.info("Year %s -> %r", year, resolved)
                result = self.client.fetch_page_by_title(resolved)
                return resolved, result.html

        # Fallback: full-text search.
        logger.warning("No canonical page for %s; falling back to search", year)
        for candidate in self.client.search_title(f"List of Telugu films of {year}"):
            if str(year) in candidate and "telugu" in candidate.lower():
                logger.info("Year %s resolved via search -> %r", year, candidate)
                result = self.client.fetch_page_by_title(candidate)
                return candidate, result.html

        logger.error("Could not locate a list page for year %s", year)
        return None

    def discover_year(self, year: int) -> list[MovieCandidate]:
        """Parse one yearly page into film candidates."""
        logger.info("Processing year: %s", year)
        located = self.find_year_page(year)
        if located is None:
            self.state.record_year(
                year, status=storage.STATUS_FAILED, error="list page not found"
            )
            return []

        title, html = located
        url = self.client.title_to_url(title)
        try:
            candidates = parse_year_page(html, year, source_url=url)
        except Exception as exc:
            logger.exception("Failed to parse year page %s", year)
            self.state.record_year(
                year, page_title=title, page_url=url, status=storage.STATUS_FAILED,
                error=str(exc),
            )
            return []

        logger.info("Found %d movie entries for %s", len(candidates), year)
        self.state.record_year(
            year,
            page_title=title,
            page_url=url,
            discovered=len(candidates),
            status=storage.STATUS_SUCCESS,
        )
        return candidates

    def resolve_candidate_url(self, candidate: MovieCandidate) -> str | None:
        """Find an article URL for a film that was not linked on the list.

        Roughly a third of listed films carry no wikilink. Disambiguated
        titles are tried first; if nothing resolves, the film is skipped
        rather than guessed at.
        """
        if candidate.wikipedia_url:
            return candidate.wikipedia_url
        if not self.resolve_unlinked:
            return None

        attempts = [
            f"{candidate.movie_name} ({candidate.year} film)",
            f"{candidate.movie_name} (film)",
            f"{candidate.movie_name} ({candidate.year} Telugu film)",
            f"{candidate.movie_name} (Telugu film)",
            candidate.movie_name,
        ]
        for title in attempts:
            resolved = self.client.resolve_title(title)
            if resolved and _is_plausible_article(resolved, candidate.movie_name):
                candidate.wikipedia_title = resolved
                return self.client.title_to_url(resolved)

        logger.debug("Unresolved title: %r (%s)", candidate.movie_name, candidate.year)
        self.stats.unresolved_titles += 1
        return None

    def discover(self, years: Sequence[int]) -> list[MovieCandidate]:
        """Discover and queue films for every requested year."""
        collected: list[MovieCandidate] = []
        for year in years:
            collected.extend(self.discover_year(year))
            self.stats.years_processed.append(year)

        unique = deduplicate_candidates(collected)
        self.stats.duplicates += len(collected) - len(unique)
        self.stats.discovered = len(unique)
        logger.info(
            "Discovered %d unique films (%d duplicates merged)",
            len(unique),
            len(collected) - len(unique),
        )
        return unique

    def queue_candidates(self, candidates: Iterable[MovieCandidate]) -> int:
        """Persist candidates as pending work, resolving URLs as needed."""
        candidate_list = list(candidates)
        linked = [c for c in candidate_list if c.wikipedia_url]
        unlinked = [c for c in candidate_list if not c.wikipedia_url]

        if unlinked and self.resolve_unlinked:
            self._resolve_unlinked_batch(unlinked)

        queued = 0
        for candidate in linked + unlinked:
            url = candidate.wikipedia_url
            if not url:
                continue
            if self.state.add_movie(
                url, candidate.movie_name, candidate.year, candidate.wikipedia_title
            ):
                queued += 1

        self.stats.newly_queued = queued
        logger.info("Queued %d new films for scraping", queued)
        return queued

    def _resolve_unlinked_batch(self, candidates: list[MovieCandidate]) -> None:
        """Resolve wikilink-less titles using batched API lookups.

        Around a third of listed films carry no article link. Each is tried
        against progressively less specific title forms; the disambiguated
        forms come first so "Yogi (2007 film)" wins over the generic "Yogi".
        Titles that never resolve are left unset and skipped -- never guessed.
        """
        patterns = [
            "{name} ({year} film)",
            "{name} ({year} Telugu film)",
            "{name} (film)",
            "{name} (Telugu film)",
            "{name}",
        ]

        remaining = list(candidates)
        for pattern in patterns:
            if not remaining:
                break

            wanted = {
                pattern.format(name=c.movie_name, year=c.year): c for c in remaining
            }
            resolved = self.client.resolve_titles_batch(list(wanted))

            still_missing: list[MovieCandidate] = []
            for title, candidate in wanted.items():
                target = resolved.get(title)
                if target and _is_plausible_article(target, candidate.movie_name):
                    candidate.wikipedia_title = target
                    candidate.wikipedia_url = self.client.title_to_url(target)
                else:
                    still_missing.append(candidate)
            remaining = still_missing

        for candidate in remaining:
            logger.debug(
                "Unresolved title: %r (%s)", candidate.movie_name, candidate.year
            )
            self.stats.unresolved_titles += 1

    # ------------------------------------------------------------------
    # Scraping
    # ------------------------------------------------------------------
    def scrape_one(self, url: str, movie_name: str, year: int) -> MovieRecord:
        """Fetch and parse one film page."""
        logger.info("Scraping: %s", movie_name)
        result = self.client.fetch_html(url)
        record = extract_movie(
            result.html, url=url, list_year=year, fallback_title=movie_name
        )

        if settings.wikidata_enabled and not record.release_date:
            title = record.wikipedia_title or movie_name
            entity = self.client.get_wikidata_entity(title)
            enrich_from_wikidata(record, entity)

        return record

    def scrape_pending(
        self, *, years: Sequence[int] | None = None, limit: int | None = None
    ) -> None:
        """Work through the pending queue, recording every outcome."""
        pending = self.state.pending_movies(years=years, limit=limit)
        if not pending:
            logger.info("No pending movies to scrape")
            return

        logger.info("Scraping %d pending movies", len(pending))
        for row in tqdm(pending, desc="Scraping movies", unit="film"):
            url, name, year = row["url"], row["movie_name"], row["year"]
            try:
                record = self.scrape_one(url, name, year)
            except RequestException as exc:
                logger.error("Failed to scrape: %s (%s)", name, exc)
                self.state.mark_failed(url, str(exc))
                self.stats.failed += 1
                continue
            except Exception as exc:  # parser bugs must not kill the run
                logger.exception("Unexpected error scraping %s", name)
                self.state.mark_failed(url, f"{type(exc).__name__}: {exc}")
                self.stats.failed += 1
                continue

            validation = validate_record(record)
            record.language_confidence = validation.confidence
            record.language_signals = validation.signals
            if validation.is_valid:
                record.language = settings.target_language

            self.state.mark_success(
                url,
                record,
                language_confidence=validation.confidence,
                is_valid=validation.is_valid,
            )

            if validation.is_valid:
                self.stats.scraped += 1
                missing = [k for k, v in record.missing_fields().items() if v]
                logger.info(
                    "Successfully extracted %d fields: %s",
                    record.populated_field_count(),
                    record.movie_name,
                )
                for field_name in missing:
                    logger.warning(
                        "%s not found: %s",
                        field_name.replace("_", " ").title(),
                        record.movie_name,
                    )
            else:
                self.stats.rejected += 1
                logger.warning(
                    "Rejected %s: %s", record.movie_name, "; ".join(validation.reasons)
                )

            if record.year_discrepancy:
                self.stats.year_discrepancies += 1
                logger.warning("%s", record.notes[-1] if record.notes else "year mismatch")

    def retry_failed(self, *, limit: int | None = None) -> None:
        """Re-queue previously failed URLs and scrape them again."""
        count = self.state.reset_failed()
        logger.info("Re-queued %d failed movies", count)
        if count:
            self.scrape_pending(limit=limit)

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------
    def export(self) -> dict[str, Any]:
        """Write every output file and return the report."""
        valid_records = self.state.load_records(only_valid=True)
        all_records = self.state.load_records(only_valid=False)

        deduped, duplicates = deduplicate_records(valid_records)
        self.stats.duplicates += duplicates

        # Identify rejects by URL: MovieRecord holds list fields, so
        # identity/equality comparisons between instances are unreliable.
        valid_urls = {record.wikipedia_url for record in valid_records}
        rejected = [
            (
                record,
                record.notes or ["failed language/quality validation"],
                record.language_confidence,
            )
            for record in all_records
            if record.wikipedia_url not in valid_urls
        ]

        storage.write_csv(deduped)
        storage.write_json(deduped)
        storage.write_failed_csv(self.state)
        storage.write_missing_fields_csv(deduped)
        storage.write_discrepancies_csv(deduped)
        storage.write_rejected_csv(rejected)

        report = self.build_report(deduped)
        storage.write_report(report)
        return report

    def build_report(self, records: list[MovieRecord]) -> dict[str, Any]:
        """Assemble the machine-readable scraping report."""
        db_stats = self.state.stats()
        confidence_counts: dict[str, int] = {}
        for record in records:
            confidence_counts[record.language_confidence] = (
                confidence_counts.get(record.language_confidence, 0) + 1
            )

        return {
            "run": self.stats.as_dict(),
            "dataset": {
                "records": len(records),
                "years": sorted({r.year for r in records if r.year}),
                "language_confidence": confidence_counts,
            },
            "database": db_stats,
            "field_coverage_percent": field_coverage(records),
            "missing_counts": build_missing_report(records),
            "http": self.client.stats,
        }

    def close(self) -> None:
        self.client.close()
        self.state.close()


def print_summary(report: dict[str, Any]) -> None:
    """Print the human-facing end-of-run summary."""
    run = report["run"]
    dataset = report["dataset"]
    coverage = report["field_coverage_percent"]
    database = report["database"]
    years = run["years_processed"] or dataset["years"]
    year_range = f"{min(years)}-{max(years)}" if years else "n/a"

    lines = [
        "",
        "=" * 40,
        "TELUGU MOVIE SCRAPER SUMMARY",
        "=" * 40,
        "",
        f"Years processed: {year_range}",
        "",
        f"Movies discovered: {run['movies_discovered']}",
        f"Movies successfully scraped: {database.get('success', 0)}",
        f"Movies in final dataset: {dataset['records']}",
        f"Failed pages: {database.get('failed', 0)}",
        f"Rejected (non-Telugu / invalid): {run['movies_rejected']}",
        "",
        "Fields extracted:",
        "",
        f"Genre:             {coverage['genre']:.0f}%",
        f"Cast:              {coverage['cast']:.0f}%",
        f"Director:          {coverage['director']:.0f}%",
        f"Production House:  {coverage['production_house']:.0f}%",
        f"Music Director:    {coverage['music_director']:.0f}%",
        f"Writer:            {coverage['writer']:.0f}%",
        "",
        "=" * 40,
    ]
    print("\n".join(lines))


def print_validation_report(records: list[MovieRecord]) -> None:
    """Print the missing-information report."""
    missing = build_missing_report(records)
    print("")
    print("VALIDATION REPORT")
    print("-" * 40)
    print(f"Total records: {len(records)}")
    for name, count in missing.items():
        label = f"Movies missing {name.replace('_', ' ')}:"
        print(f"{label:38} {count}")
    print("-" * 40)
