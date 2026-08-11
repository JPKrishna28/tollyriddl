"""Extract structured metadata from an individual film's Wikipedia page.

Design notes grounded in the structure recon:

  * Film infoboxes are ``table.infobox.vevent``. A page whose infobox is
    e.g. ``infobox ib-settlement vcard`` is a *place*, not a film -- the
    title "Balagam" resolves to a Gujarat village while the 2023 film lives
    at "Balagam (film)". Entity type is therefore checked, not assumed.
  * There is no ``Genre`` row in any film infobox sampled. Genre is mined
    from categories such as "2021 action drama films" against a controlled
    vocabulary, so category noise ("Films about funerals") cannot leak in.
  * ``Dialogues by`` is its own infobox row on many films. It is excluded
    from the writer field by policy -- dialogue writers are not the
    screenwriter unless Wikipedia says so.
  * Release date is read from the ``.dtstart`` microformat when present,
    which is already ISO-formatted and avoids date-template parsing.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from bs4 import BeautifulSoup, Tag

from config.settings import (
    CAST_LABELS,
    COUNTRY_LABELS,
    DIRECTOR_LABELS,
    GENRE_LABELS,
    GENRE_SYNONYMS,
    LANGUAGE_LABELS,
    MUSIC_LABELS,
    PRODUCTION_FALLBACK_LABELS,
    PRODUCTION_HOUSE_LABELS,
    RELEASE_DATE_LABELS,
    WRITER_EXCLUDED_LABELS,
    WRITER_LABEL_PRIORITY,
    settings,
)
from scraper.cleaner import (
    clean_name,
    clean_text,
    dedupe_preserving_order,
    is_cross_reference,
    is_placeholder,
    normalise_label,
    normalise_title,
    split_values,
)

logger = logging.getLogger(__name__)

_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_ISO_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
# "2021 action drama films" / "2000 romantic drama films" / "Indian drama films"
_GENRE_CATEGORY_RE = re.compile(
    r"^(?:\d{4}\s+)?(?:indian\s+|telugu[- ]language\s+|american\s+)?(.+?)\s+films?$",
    re.I,
)
_SORTED_GENRE_KEYS = sorted(GENRE_SYNONYMS, key=len, reverse=True)


@dataclass
class MovieRecord:
    """Structured metadata for one film."""

    movie_name: str = ""
    year: int | None = None
    language: str = ""
    genre: list[str] = field(default_factory=list)
    cast: list[str] = field(default_factory=list)
    director: list[str] = field(default_factory=list)
    production_house: list[str] = field(default_factory=list)
    music_director: list[str] = field(default_factory=list)
    writer: list[str] = field(default_factory=list)
    wikipedia_url: str = ""

    # Internal / diagnostic fields (not all are exported to the CSV).
    wikipedia_title: str = ""
    list_year: int | None = None
    infobox_year: int | None = None
    release_date: str = ""
    year_discrepancy: bool = False
    language_confidence: str = "low"
    language_signals: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    is_film: bool = False
    enrichment_sources: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def missing_fields(self) -> dict[str, bool]:
        """Report which game-relevant fields came back empty."""
        return {
            "genre": not self.genre,
            "cast": not self.cast,
            "director": not self.director,
            "production_house": not self.production_house,
            "music_director": not self.music_director,
            "writer": not self.writer,
        }

    def populated_field_count(self) -> int:
        """How many of the target fields carry data (for logging)."""
        values = (
            self.movie_name,
            self.year,
            self.language,
            self.genre,
            self.cast,
            self.director,
            self.production_house,
            self.music_director,
            self.writer,
            self.wikipedia_url,
        )
        return sum(1 for value in values if value)


def find_infobox(soup: BeautifulSoup) -> Tag | None:
    """Locate the article's infobox table, if it has one."""
    return soup.select_one("table.infobox")


def is_film_infobox(infobox: Tag | None) -> bool:
    """True when the infobox describes a film rather than another entity.

    Film infoboxes are emitted with the ``vevent`` microformat class.
    Settlement/person/album infoboxes use different classes, which is how
    "Balagam" (a village) is told apart from "Balagam (film)".
    """
    if infobox is None:
        return False
    classes = {cls.lower() for cls in infobox.get("class", [])}
    if {"ib-settlement", "vcard", "biography", "ib-album"} & classes:
        # vcard alone appears on some film infoboxes, so only reject when
        # it is paired with a clearly non-film variant.
        if "vevent" not in classes:
            return False
    return "vevent" in classes


def parse_infobox(infobox: Tag | None) -> dict[str, Tag]:
    """Map normalised infobox labels to their value cells."""
    if infobox is None:
        return {}

    rows: dict[str, Tag] = {}
    for row in infobox.find_all("tr"):
        header = row.find("th")
        value = row.find("td")
        if not header or not value:
            continue
        label = normalise_label(header.get_text(" ", strip=True))
        if label and label not in rows:
            rows[label] = value
    return rows


def cell_values(cell: Tag | None) -> list[str]:
    """Read a multi-value infobox cell, preserving source order.

    Handles both shapes seen live: ``.plainlist`` markup with ``<li>``
    items, and plain ``<br>``-separated text with no list markup at all.
    """
    if cell is None:
        return []

    # Drop reference superscripts before reading text.
    working = _strip_noise(cell)

    items = [li.get_text(" ", strip=True) for li in working.find_all("li")]
    if not items:
        items = split_values(working.get_text("\n", strip=True))

    values = dedupe_preserving_order(items)
    return [v for v in values if not is_cross_reference(v) and not is_placeholder(v)]


def _strip_noise(cell: Tag) -> Tag:
    """Return a copy of the cell without refs, images and hidden spans."""
    import copy

    clone = copy.copy(cell)
    try:
        clone = BeautifulSoup(str(cell), "lxml")
    except Exception:  # pragma: no cover - defensive
        return cell

    for tag in clone.select("sup.reference, sup, style, .noprint, .mw-editsection"):
        tag.decompose()
    # Hidden accessibility copies of dates would duplicate the visible text.
    for tag in clone.select(".bday, .published, .dtstart"):
        if tag.get("style") and "display:none" in tag.get("style", "").replace(" ", ""):
            tag.decompose()
    return clone


def _lookup(rows: dict[str, Tag], labels: tuple[str, ...]) -> Tag | None:
    """Find the first infobox cell whose label matches an alias."""
    for label in labels:
        if label in rows:
            return rows[label]
    # Fall back to prefix matching ("music by (score)" style labels).
    for label in labels:
        for key, cell in rows.items():
            if key.startswith(label):
                return cell
    return None


def extract_director(rows: dict[str, Tag]) -> list[str]:
    """Extract director credits."""
    return cell_values(_lookup(rows, DIRECTOR_LABELS))


def extract_writer(rows: dict[str, Tag]) -> list[str]:
    """Extract writing credits, excluding dialogue/lyrics/camera roles.

    Wikipedia lists "Dialogues by" as a distinct credit on many Telugu
    films. Treating it as the writer would misattribute the screenplay, so
    excluded labels are never consulted -- only explicit writing credits,
    in priority order (written by > screenplay > story).
    """
    values: list[str] = []
    for label in WRITER_LABEL_PRIORITY:
        if label in WRITER_EXCLUDED_LABELS:
            continue
        cell = rows.get(label)
        if cell is None:
            continue
        values.extend(cell_values(cell))
    return _drop_role_captions(dedupe_preserving_order(values))


# Sub-role captions used inside a single infobox cell, e.g.
# "Songs: Radhan / Score: Harshavardhan Rameshwar". These are labels, not
# people, and must not be stored as the music director.
_ROLE_CAPTION_RE = re.compile(
    r"^(?:songs?|scores?|background\s+score|music|bgm|original\s+score|"
    r"soundtrack|composer|lyrics?)\s*[:\-]?$",
    re.I,
)


def _drop_role_captions(values: list[str]) -> list[str]:
    """Remove sub-role captions that share a cell with real names."""
    return [value for value in values if not _ROLE_CAPTION_RE.match(value.strip())]


def extract_music_director(rows: dict[str, Tag]) -> list[str]:
    """Extract the composer / music director.

    Some infoboxes split the credit inside one cell ("Songs: X / Score: Y");
    the captions are stripped so only names survive.
    """
    return _drop_role_captions(cell_values(_lookup(rows, MUSIC_LABELS)))


def extract_production_house(rows: dict[str, Tag]) -> list[str]:
    """Extract the production company.

    "Produced by" names individual producers rather than a company on most
    Indian film infoboxes, so it is only used when no company row exists.
    """
    for label in PRODUCTION_HOUSE_LABELS:
        if label in PRODUCTION_FALLBACK_LABELS:
            continue
        cell = rows.get(label)
        if cell is not None:
            values = cell_values(cell)
            if values:
                return values

    for label in PRODUCTION_FALLBACK_LABELS:
        cell = rows.get(label)
        if cell is not None:
            values = cell_values(cell)
            if values:
                return values
    return []


def extract_cast(rows: dict[str, Tag]) -> list[str]:
    """Extract the principal cast in billing order.

    Only the infobox 'Starring' row is used. Crew rows are never merged in,
    and the article body is not scanned, so no non-actor is picked up.
    """
    return cell_values(_lookup(rows, CAST_LABELS))


def extract_language(rows: dict[str, Tag]) -> list[str]:
    """Extract declared languages from the infobox."""
    return cell_values(_lookup(rows, LANGUAGE_LABELS))


def extract_country(rows: dict[str, Tag]) -> list[str]:
    """Extract the country of production."""
    return cell_values(_lookup(rows, COUNTRY_LABELS))


def extract_release_date(soup: BeautifulSoup, rows: dict[str, Tag]) -> tuple[str, int | None]:
    """Return ``(release_date_text, year)``.

    Prefers the ``.dtstart`` microformat, which Wikipedia renders as a
    machine-readable ISO date, over parsing the human-facing date text.
    """
    cell = _lookup(rows, RELEASE_DATE_LABELS)

    if cell is not None:
        microformat = cell.select_one(".dtstart, .bday, time[datetime]")
        if microformat is not None:
            raw = microformat.get("datetime") or microformat.get_text(strip=True)
            match = _ISO_DATE_RE.search(raw or "")
            if match:
                return match.group(0), int(match.group(1))

    # Fall back to the page-level microformat, then to visible text.
    microformat = soup.select_one(".infobox .dtstart, .infobox .bday")
    if microformat is not None:
        match = _ISO_DATE_RE.search(microformat.get_text(strip=True))
        if match:
            return match.group(0), int(match.group(1))

    if cell is not None:
        text = clean_text(cell.get_text(" ", strip=True))
        year_match = _YEAR_RE.search(text)
        if year_match:
            return text, int(year_match.group(0))
        return text, None

    return "", None


def extract_categories(soup: BeautifulSoup) -> list[str]:
    """Read the visible category links from a rendered page."""
    return [
        clean_text(anchor.get_text(strip=True))
        for anchor in soup.select("#mw-normal-catlinks ul li a")
        if anchor.get_text(strip=True)
    ]


def extract_genres(categories: list[str], rows: dict[str, Tag]) -> list[str]:
    """Derive genres from categories (and a Genre row if one ever exists).

    Film infoboxes carry no Genre field, so categories are the real source:
    "2021 action drama films" -> Action, Drama. Matching is restricted to a
    controlled vocabulary so descriptive categories such as
    "Films about funerals" contribute nothing.
    """
    genres: list[str] = []

    # Honour an explicit Genre row if a template ever provides one.
    genre_cell = _lookup(rows, GENRE_LABELS)
    if genre_cell is not None:
        for value in cell_values(genre_cell):
            genres.extend(_map_genre_phrase(value))

    for category in categories:
        match = _GENRE_CATEGORY_RE.match(category.strip())
        if not match:
            continue
        phrase = match.group(1).lower()
        # Skip categories that describe subject matter or provenance
        # rather than genre ("films about funerals", "films directed by X").
        if any(
            marker in phrase
            for marker in (" about ", " directed by ", " scored by ", " set in ", " based on ", " shot in ")
        ):
            continue
        genres.extend(_map_genre_phrase(phrase))

    return dedupe_preserving_order(genres)


def _map_genre_phrase(phrase: str) -> list[str]:
    """Map a category phrase onto canonical genre names."""
    lowered = f" {phrase.lower().strip()} "
    found: list[tuple[int, str]] = []
    for key in _SORTED_GENRE_KEYS:
        position = lowered.find(f" {key} ")
        if position == -1 and len(key) > 4:
            # Allow hyphenated/compound forms ("action-drama").
            position = lowered.find(key)
        if position != -1:
            found.append((position, GENRE_SYNONYMS[key]))
    return [genre for _, genre in sorted(found)]


def extract_title(soup: BeautifulSoup, fallback: str = "") -> str:
    """Read the article's display title."""
    heading = soup.select_one("h1#firstHeading, h1.firstHeading")
    if heading is not None:
        title = clean_text(heading.get_text(" ", strip=True))
        if title:
            return normalise_title(title)
    return normalise_title(fallback)


def extract_movie(
    html: str,
    *,
    url: str,
    list_year: int | None = None,
    fallback_title: str = "",
) -> MovieRecord:
    """Parse a film page into a :class:`MovieRecord`.

    Missing fields stay empty -- nothing is inferred or invented.
    """
    soup = BeautifulSoup(html, "lxml")
    infobox = find_infobox(soup)
    rows = parse_infobox(infobox)
    categories = extract_categories(soup)

    record = MovieRecord(
        movie_name=extract_title(soup, fallback_title),
        wikipedia_url=url,
        wikipedia_title=fallback_title or extract_title(soup, ""),
        list_year=list_year,
        categories=categories,
        is_film=is_film_infobox(infobox) or _has_film_category(categories),
    )

    release_text, infobox_year = extract_release_date(soup, rows)
    record.release_date = release_text
    record.infobox_year = infobox_year

    # The list page's year is authoritative for the dataset; a differing
    # infobox year is flagged rather than silently overwritten.
    record.year = list_year if list_year is not None else infobox_year
    if list_year is not None and infobox_year is not None and infobox_year != list_year:
        record.year_discrepancy = True
        record.notes.append(
            f"Year mismatch: list page says {list_year}, infobox says {infobox_year}"
        )

    record.director = extract_director(rows)
    record.writer = extract_writer(rows)
    record.music_director = extract_music_director(rows)
    record.production_house = extract_production_house(rows)
    record.cast = extract_cast(rows)
    record.genre = extract_genres(categories, rows)

    languages = extract_language(rows)
    if languages:
        record.language = languages[0]

    record.enrichment_sources.append("wikipedia")
    return record


def _has_film_category(categories: list[str]) -> bool:
    """True when categories mark the page as a film."""
    return any(
        re.search(r"\bfilms?\b", category, re.I) for category in categories
    )


def enrich_from_wikidata(record: MovieRecord, entity: dict[str, Any] | None) -> MovieRecord:
    """Fill gaps from Wikidata claims. Wikipedia values always win.

    Wikidata is a *secondary* source: it only populates fields the HTML
    infobox left empty, and only with entity labels we can resolve.
    """
    if not entity:
        return record

    claims = entity.get("claims", {})
    if not claims:
        return record

    filled: list[str] = []

    # P577 publication date -- only used when no release date was found.
    if not record.release_date:
        for claim in claims.get("P577", []):
            value = _claim_time(claim)
            if value:
                record.release_date = value
                match = _ISO_DATE_RE.search(value)
                if match and record.year is None:
                    record.year = int(match.group(1))
                filled.append("release_date")
                break

    if filled:
        record.enrichment_sources.append("wikidata")
        record.notes.append(f"Wikidata filled: {', '.join(filled)}")
    return record


def _claim_time(claim: dict[str, Any]) -> str:
    """Extract an ISO date from a Wikidata time claim."""
    try:
        value = claim["mainsnak"]["datavalue"]["value"]["time"]
    except (KeyError, TypeError):
        return ""
    match = _ISO_DATE_RE.search(value or "")
    return match.group(0) if match else ""
