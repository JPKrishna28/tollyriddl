"""Parse Wikipedia yearly 'List of Telugu films of YEAR' pages.

The hard part is table geometry, not text. Observed on real pages:

  * "Opening" is a ``colspan=2`` header (month + day), so every column
    after it is offset by one relative to a naive header enumeration.
  * Month cells carry ``rowspan`` up to 7, day cells up to 3, and the
    production-house column spans rows too. A row therefore has fewer
    ``<td>`` elements than the table has columns, and positional indexing
    silently returns the *wrong field* (a director where a title belongs).

Both are solved by expanding the table into a virtual grid where every
logical cell coordinate maps to the element that occupies it.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Iterable

from bs4 import BeautifulSoup, Tag

from config.settings import (
    LIST_CAST_HEADERS,
    LIST_DATE_HEADERS,
    LIST_DIRECTOR_HEADERS,
    LIST_PRODUCTION_HEADERS,
    LIST_REJECT_HEADERS,
    LIST_TITLE_HEADERS,
    NON_MOVIE_TITLE_MARKERS,
    settings,
)
from scraper.cleaner import (
    clean_text,
    dedupe_preserving_order,
    is_placeholder,
    normalise_key,
    normalise_label,
    normalise_title,
    split_values,
)

logger = logging.getLogger(__name__)

# Accepts both relative (/wiki/X) and absolute (https://en.wikipedia.org/wiki/X)
# hrefs -- live pages use the absolute form, which a /wiki/-only selector misses.
_WIKI_HREF_RE = re.compile(r"^(?:https?://en\.wikipedia\.org)?/wiki/([^#?]+)")
_NON_ARTICLE_PREFIXES = (
    "Wikipedia:",
    "Category:",
    "Template:",
    "Help:",
    "File:",
    "Portal:",
    "Special:",
    "Talk:",
    "Draft:",
)
_MONTH_NAMES = (
    "january february march april may june july august september "
    "october november december"
).split()


@dataclass
class MovieCandidate:
    """A film discovered on a yearly list page, before its page is scraped."""

    movie_name: str
    year: int
    wikipedia_url: str | None = None
    wikipedia_title: str | None = None
    list_director: str = ""
    list_cast: list[str] = field(default_factory=list)
    list_production_house: str = ""
    release_date_text: str = ""
    source_year_page: str = ""

    @property
    def dedupe_key(self) -> tuple[str, int]:
        """Primary key: normalised title + year.

        Year is part of the key on purpose -- remakes and reused titles
        ("Postman", "Yogi") are genuinely different films across years and
        must never be merged.
        """
        return (normalise_key(normalise_title(self.movie_name)), self.year)


def build_table_grid(table: Tag) -> list[list[Tag]]:
    """Expand a table into a rectangular grid honouring row/colspans.

    Each returned coordinate holds the ``Tag`` that visually occupies it,
    so spanned cells appear once per covered position.
    """
    occupied: dict[tuple[int, int], Tag] = {}
    grid: list[list[Tag]] = []

    for row_index, row in enumerate(table.find_all("tr")):
        cells = row.find_all(["th", "td"], recursive=False)
        line: list[Tag] = []
        col_index = 0

        for cell in cells:
            # Skip columns already claimed by a rowspan from an earlier row.
            while (row_index, col_index) in occupied:
                line.append(occupied[(row_index, col_index)])
                col_index += 1

            rowspan = _positive_int(cell.get("rowspan"), default=1)
            colspan = _positive_int(cell.get("colspan"), default=1)

            for row_offset in range(rowspan):
                for col_offset in range(colspan):
                    if row_offset or col_offset:
                        occupied[(row_index + row_offset, col_index + col_offset)] = cell

            for _ in range(colspan):
                line.append(cell)
                col_index += 1

        # Trailing spans that reach past the last physical cell in this row.
        while (row_index, col_index) in occupied:
            line.append(occupied[(row_index, col_index)])
            col_index += 1

        grid.append(line)

    return grid


def _positive_int(value: object, *, default: int = 1) -> int:
    """Parse a span attribute defensively; malformed markup is common."""
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    # Cap runaway spans (seen as typos like rowspan="99") to keep the grid sane.
    return max(1, min(parsed, 100)) if parsed else default


def map_header_columns(grid: list[list[Tag]]) -> tuple[dict[str, int], int]:
    """Map normalised header labels to column indices.

    Returns the mapping and the index of the header row. The header is not
    always row 0 -- some tables open with a caption or a spanning title row.
    """
    for row_index, line in enumerate(grid[:3]):
        header_cells = [cell for cell in line if cell.name == "th"]
        # A real header row is mostly <th> and mentions a title-ish column.
        if len(header_cells) < 2:
            continue

        mapping: dict[str, int] = {}
        for col_index, cell in enumerate(line):
            if cell.name != "th":
                continue
            label = normalise_label(cell.get_text(" ", strip=True))
            if label and label not in mapping:
                mapping[label] = col_index

        if any(_matches(label, LIST_TITLE_HEADERS) for label in mapping):
            return mapping, row_index

    return {}, -1


def _matches(label: str, candidates: Iterable[str]) -> bool:
    """True when a normalised header label matches one of the candidates."""
    label = label.strip()
    return any(label == candidate or label.startswith(candidate) for candidate in candidates)


def _find_column(mapping: dict[str, int], candidates: Iterable[str]) -> int | None:
    """Locate the column index for the first matching header alias."""
    for candidate in candidates:
        for label, index in mapping.items():
            if label == candidate:
                return index
    for candidate in candidates:
        for label, index in mapping.items():
            if label.startswith(candidate) or candidate in label:
                return index
    return None


def is_release_table(mapping: dict[str, int]) -> bool:
    """Decide whether a wikitable lists releases rather than box office/awards.

    Yearly pages carry 3-5 wikitables. Box-office tables
    ("Rank | Title | Worldwide gross") and award tables
    ("Date | Event | Host") also have a Title column, so a title check alone
    would pull in non-films and duplicates.
    """
    if not mapping:
        return False

    labels = set(mapping)
    if not any(_matches(label, LIST_TITLE_HEADERS) for label in labels):
        return False
    if any(label in LIST_REJECT_HEADERS for label in labels):
        return False

    # A release table pairs the title with a date/crew column.
    supporting = (
        LIST_DATE_HEADERS + LIST_DIRECTOR_HEADERS + LIST_CAST_HEADERS + LIST_PRODUCTION_HEADERS
    )
    return any(_matches(label, supporting) for label in labels)


def extract_wiki_link(cell: Tag) -> tuple[str | None, str | None]:
    """Return ``(url, title)`` of the first real article link in a cell.

    Red links (articles that do not exist) and non-article namespaces are
    ignored so we never queue a page that cannot be scraped.
    """
    for anchor in cell.find_all("a"):
        href = anchor.get("href") or ""
        if "redlink=1" in href:
            continue
        match = _WIKI_HREF_RE.match(href)
        if not match:
            continue

        from urllib.parse import unquote

        title = unquote(match.group(1)).replace("_", " ")
        if title.startswith(_NON_ARTICLE_PREFIXES):
            continue
        if any(marker in title.lower() for marker in NON_MOVIE_TITLE_MARKERS):
            continue

        url = href if href.startswith("http") else f"https://en.wikipedia.org{href}"
        return url.split("#")[0], title

    return None, None


def _looks_like_month_or_day(text: str) -> bool:
    """True for the month/day marker cells that pad release tables.

    Month markers render letter-spaced ("J A N U A R Y"), so the check
    strips spaces before comparing.
    """
    compact = re.sub(r"\s+", "", text).lower()
    if not compact:
        return True
    if compact.isdigit():
        return True
    return any(compact.startswith(month[:3]) and len(compact) <= len(month) for month in _MONTH_NAMES)


def parse_year_page(
    html: str, year: int, *, source_url: str = ""
) -> list[MovieCandidate]:
    """Extract every film listed on a yearly Telugu-film page."""
    soup = BeautifulSoup(html, "lxml")
    content = soup.select_one("#mw-content-text") or soup
    candidates: list[MovieCandidate] = []
    seen: set[tuple[str, int]] = set()

    for table in content.find_all("table", class_="wikitable"):
        grid = build_table_grid(table)
        if len(grid) < 2:
            continue

        mapping, header_row = map_header_columns(grid)
        if not is_release_table(mapping):
            continue

        title_col = _find_column(mapping, LIST_TITLE_HEADERS)
        if title_col is None:
            continue
        director_col = _find_column(mapping, LIST_DIRECTOR_HEADERS)
        cast_col = _find_column(mapping, LIST_CAST_HEADERS)
        production_col = _find_column(mapping, LIST_PRODUCTION_HEADERS)
        date_col = _find_column(mapping, LIST_DATE_HEADERS)

        for line in grid[header_row + 1 :]:
            if title_col >= len(line):
                continue

            title_cell = line[title_col]
            # Sub-header rows repeat <th> inside the body; skip them.
            if title_cell.name == "th":
                continue

            raw_title = clean_text(title_cell.get_text(" ", strip=True))
            if is_placeholder(raw_title) or _looks_like_month_or_day(raw_title):
                continue

            url, wiki_title = extract_wiki_link(title_cell)
            movie_name = normalise_title(wiki_title or raw_title)
            if not movie_name or _is_non_movie(movie_name):
                continue

            candidate = MovieCandidate(
                movie_name=movie_name,
                year=year,
                wikipedia_url=url,
                wikipedia_title=wiki_title,
                list_director=_cell_text(line, director_col),
                list_cast=_cell_values(line, cast_col),
                list_production_house=_clean_production(
                    _cell_text(line, production_col)
                ),
                release_date_text=_release_text(line, date_col, title_col),
                source_year_page=source_url,
            )

            if candidate.dedupe_key in seen:
                continue
            seen.add(candidate.dedupe_key)
            candidates.append(candidate)

    logger.info("Year %s: parsed %d unique film entries", year, len(candidates))
    return candidates


def _release_text(line: list[Tag], date_col: int | None, title_col: int) -> str:
    """Reconstruct "MONTH DAY" from the spanned Opening column.

    "Opening" is a ``colspan=2`` header covering a letter-spaced month cell
    ("J A N U A R Y") and a day cell. Reading only the header's own column
    yields the month marker, so every column between the date header and the
    title is collected and the letter-spacing is compacted.
    """
    if date_col is None:
        return ""

    parts: list[str] = []
    for index in range(date_col, min(title_col, len(line))):
        text = clean_text(line[index].get_text(" ", strip=True))
        if not text or is_placeholder(text):
            continue
        compact = re.sub(r"\s+", "", text)
        # Letter-spaced month names compact into a real word.
        if compact.isalpha():
            text = compact.title()
        parts.append(text)

    return " ".join(parts).strip()


def _clean_production(value: str) -> str:
    """Strip credit prefixes some years prepend to the production column.

    2010's table renders "Produced by Laughing Leaf Films"; the label is
    markup, not part of the company name.
    """
    if not value:
        return ""
    cleaned = re.sub(
        r"^\s*(?:produced\s+by|production(?:\s+house)?|banner)\s*[:\-]?\s*",
        "",
        value,
        flags=re.I,
    ).strip()
    return "" if is_placeholder(cleaned) else cleaned


def _cell_text(line: list[Tag], index: int | None) -> str:
    """Safely read a cell's cleaned text from a grid row."""
    if index is None or index >= len(line):
        return ""
    value = clean_text(line[index].get_text(" ", strip=True))
    return "" if is_placeholder(value) else value


def _cell_values(line: list[Tag], index: int | None) -> list[str]:
    """Read a multi-value cell (cast) preserving order.

    Uses ``<br>``-aware text extraction: the list pages separate names with
    line breaks rather than list markup.
    """
    if index is None or index >= len(line):
        return []
    cell = line[index]
    items = [li.get_text(" ", strip=True) for li in cell.find_all("li")]
    if not items:
        items = split_values(cell.get_text("\n", strip=True))
    return dedupe_preserving_order(items)


def _is_non_movie(title: str) -> bool:
    """Filter out list/portal/section entries that are not films."""
    lowered = title.lower().strip()
    if not lowered:
        return True
    if any(marker in lowered for marker in NON_MOVIE_TITLE_MARKERS):
        return True
    # Bare month or year headings that leaked through as titles.
    if lowered in _MONTH_NAMES or re.fullmatch(r"(19|20)\d{2}", lowered):
        return True
    return False


def deduplicate_candidates(
    candidates: Iterable[MovieCandidate],
) -> list[MovieCandidate]:
    """Merge duplicates across tables and years.

    Two passes:
      1. by ``(normalised title, year)`` -- the primary key;
      2. by Wikipedia URL -- catches the same film listed under alternate
         spellings that both link to one article.

    Entries are merged (richer record wins) rather than dropped, so list
    metadata gathered in one table is not lost because another table
    mentioned the film first.
    """
    by_key: dict[tuple[str, int], MovieCandidate] = {}
    by_url: dict[str, tuple[str, int]] = {}

    for candidate in candidates:
        key = candidate.dedupe_key
        url = (candidate.wikipedia_url or "").split("#")[0]

        # A URL already claimed by another key means alternate spellings of
        # the same film -- but only merge when the years agree.
        if url and url in by_url:
            existing_key = by_url[url]
            if existing_key[1] == candidate.year:
                key = existing_key

        if key in by_key:
            by_key[key] = _merge_candidates(by_key[key], candidate)
        else:
            by_key[key] = candidate

        if url:
            by_url.setdefault(url, key)

    return list(by_key.values())


def _merge_candidates(base: MovieCandidate, other: MovieCandidate) -> MovieCandidate:
    """Combine two records of the same film, preferring populated fields."""
    return MovieCandidate(
        movie_name=base.movie_name or other.movie_name,
        year=base.year,
        wikipedia_url=base.wikipedia_url or other.wikipedia_url,
        wikipedia_title=base.wikipedia_title or other.wikipedia_title,
        list_director=base.list_director or other.list_director,
        list_cast=base.list_cast or other.list_cast,
        list_production_house=base.list_production_house or other.list_production_house,
        release_date_text=base.release_date_text or other.release_date_text,
        source_year_page=base.source_year_page or other.source_year_page,
    )


def build_year_page_titles(year: int) -> list[str]:
    """Candidate titles for a year's list page, most likely first.

    ``List of Telugu films of YEAR`` resolved for every year sampled during
    recon; the rest are fallbacks so a renamed page does not break the run.
    """
    return [
        f"List of Telugu films of {year}",
        f"List of Telugu-language films of {year}",
        f"Telugu films of {year}",
        f"{year} in Telugu cinema",
        f"List of Telugu films of {year} (India)",
    ]
