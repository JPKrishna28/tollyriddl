"""Telugu-language validation and data-quality gating.

Membership of a yearly "List of Telugu films" page is treated as evidence,
not proof. Recon showed why: the bare title "Balagam" resolves to a village
in Gujarat, while the film lives at "Balagam (film)". Several independent
signals are therefore combined into a confidence grade.

Signals, strongest first:
  1. Category "<year> Telugu-language films" (or any Telugu-language film
     category) -- an explicit, curated statement.
  2. Infobox ``Language`` row equal to Telugu.
  3. Presence on the yearly Telugu-film list, combined with confirmation
     that the page is a film at all.
  4. Lead-section / title mentions of Telugu cinema.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from config.settings import settings
from scraper.cleaner import clean_text, normalise_key
from scraper.extractor import MovieRecord

logger = logging.getLogger(__name__)

_TELUGU_CATEGORY_RE = re.compile(r"telugu[- ]language\s+films?", re.I)
_TELUGU_GENERIC_RE = re.compile(r"\btelugu\b", re.I)
_FILM_CATEGORY_RE = re.compile(r"\bfilms?\b", re.I)

HIGH = "high"
MEDIUM = "medium"
LOW = "low"


@dataclass
class ValidationResult:
    """Outcome of validating one record."""

    is_valid: bool
    confidence: str
    signals: list[str]
    reasons: list[str]


def assess_language(record: MovieRecord) -> ValidationResult:
    """Grade how confident we are that a record is a Telugu film."""
    signals: list[str] = []
    reasons: list[str] = []

    categories = record.categories or []
    has_film_category = any(_FILM_CATEGORY_RE.search(c) for c in categories)

    # Signal 1: explicit Telugu-language film category.
    telugu_category = any(_TELUGU_CATEGORY_RE.search(c) for c in categories)
    if telugu_category:
        signals.append("category:telugu-language-film")

    # Signal 2: infobox language row.
    language_value = clean_text(record.language).lower()
    infobox_telugu = bool(language_value) and "telugu" in language_value
    if infobox_telugu:
        signals.append("infobox:language")
    elif language_value:
        signals.append(f"infobox:language={language_value}")

    # Signal 3: the page is recognisably a film.
    if record.is_film:
        signals.append("entity:film")
    if has_film_category:
        signals.append("category:film")

    # Signal 4: weaker textual mention of Telugu anywhere in categories.
    if not telugu_category and any(_TELUGU_GENERIC_RE.search(c) for c in categories):
        signals.append("category:telugu-mention")

    # ------------------------------------------------------------------
    # Grade
    # ------------------------------------------------------------------
    is_film = record.is_film or has_film_category

    if not is_film:
        reasons.append("Page does not describe a film")
        return ValidationResult(False, LOW, signals, reasons)

    if telugu_category or (infobox_telugu and has_film_category):
        confidence = HIGH
    elif infobox_telugu or "category:telugu-mention" in signals:
        confidence = MEDIUM
    elif language_value and "telugu" not in language_value:
        # The page states a different language outright.
        reasons.append(f"Infobox language is {record.language!r}, not Telugu")
        return ValidationResult(False, LOW, signals, reasons)
    else:
        # Only the yearly-list membership backs this one.
        confidence = MEDIUM
        reasons.append("Telugu inferred from yearly list membership only")

    return ValidationResult(True, confidence, signals, reasons)


# Article titles that are aggregates, not individual films. A redirect can
# land on one of these ("Eureka" -> "List of Telugu films of 2020"); the
# pipeline guards against following them, but this is the last line of
# defence so such a page can never be marked valid, however it got here.
_AGGREGATE_PAGE_RE = re.compile(
    r"(?:^|/)(?:list_of|lists_of)|"
    r"(?:^|\b)(?:list of|lists of)\b|"
    r"\b(?:filmography|discography|characters|episodes)\b",
    re.I,
)


def is_aggregate_page(record: MovieRecord) -> bool:
    """True when the record points at a list/index page rather than a film."""
    slug = (record.wikipedia_url or "").split("/wiki/", 1)[-1]
    return bool(
        _AGGREGATE_PAGE_RE.search(record.movie_name or "")
        or _AGGREGATE_PAGE_RE.search(slug)
    )


def validate_record(record: MovieRecord) -> ValidationResult:
    """Apply language and data-quality rules to a record.

    Quality rules (from the spec):
      * ``movie_name`` must not be empty
      * ``year`` must fall inside the configured range
      * ``wikipedia_url`` must be a valid Wikipedia article URL
      * language should be Telugu, graded by confidence
    """
    result = assess_language(record)
    reasons = list(result.reasons)
    signals = list(result.signals)
    valid = result.is_valid

    if not clean_text(record.movie_name):
        valid = False
        reasons.append("Empty movie_name")

    if is_aggregate_page(record):
        valid = False
        reasons.append("Aggregate/list page, not an individual film")

    if record.year is None:
        valid = False
        reasons.append("Missing year")
    elif not (settings.min_valid_year <= record.year <= settings.max_valid_year):
        valid = False
        reasons.append(
            f"Year {record.year} outside {settings.min_valid_year}-{settings.max_valid_year}"
        )

    if not is_valid_wikipedia_url(record.wikipedia_url):
        valid = False
        reasons.append(f"Invalid wikipedia_url: {record.wikipedia_url!r}")

    if valid and result.confidence not in settings.accepted_confidences:
        valid = False
        reasons.append(f"Language confidence {result.confidence!r} below threshold")

    return ValidationResult(valid, result.confidence, signals, reasons)


_NAMESPACE_PREFIX_RE = re.compile(
    r"^(?:Wikipedia|Category|Template|Help|File|Portal|Special|Talk|Draft|"
    r"User|Module|MediaWiki)_?:",
    re.I,
)


def is_valid_wikipedia_url(url: str | None) -> bool:
    """True for a well-formed English Wikipedia article URL.

    Colons are legal in article titles ("Pushpa:_The_Rise"), so only real
    namespace prefixes are rejected -- not every colon.
    """
    if not url:
        return False
    if not re.match(r"^https://en\.wikipedia\.org/wiki/\S+$", url.strip()):
        return False
    slug = url.strip().split("/wiki/", 1)[-1]
    return not _NAMESPACE_PREFIX_RE.match(slug)


def deduplicate_records(records: list[MovieRecord]) -> tuple[list[MovieRecord], int]:
    """Drop duplicate films, keeping the richest record for each key.

    Keyed on ``(normalised title, year)`` so that two different films that
    happen to share a title in different years are both preserved, and
    secondarily on URL so alternate spellings collapse together.
    """
    by_key: dict[tuple[str, int | None], MovieRecord] = {}
    url_to_key: dict[str, tuple[str, int | None]] = {}
    duplicates = 0

    for record in records:
        key: tuple[str, int | None] = (normalise_key(record.movie_name), record.year)
        url = (record.wikipedia_url or "").split("#")[0]

        if url and url in url_to_key:
            existing = url_to_key[url]
            # Same article and same year -> genuinely the same film.
            if existing[1] == record.year:
                key = existing

        if key in by_key:
            duplicates += 1
            if record.populated_field_count() > by_key[key].populated_field_count():
                by_key[key] = record
        else:
            by_key[key] = record

        if url:
            url_to_key.setdefault(url, key)

    return list(by_key.values()), duplicates


def build_missing_report(records: list[MovieRecord]) -> dict[str, int]:
    """Count how many records lack each game-relevant field."""
    counters = {
        "genre": 0,
        "cast": 0,
        "director": 0,
        "production_house": 0,
        "music_director": 0,
        "writer": 0,
    }
    for record in records:
        for field_name, missing in record.missing_fields().items():
            if missing:
                counters[field_name] += 1
    return counters


def field_coverage(records: list[MovieRecord]) -> dict[str, float]:
    """Percentage of records carrying each field."""
    total = len(records)
    if not total:
        return {name: 0.0 for name in
                ("genre", "cast", "director", "production_house", "music_director", "writer")}

    missing = build_missing_report(records)
    return {
        name: round(100.0 * (total - count) / total, 1)
        for name, count in missing.items()
    }
