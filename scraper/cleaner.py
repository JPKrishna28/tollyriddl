"""Text normalisation shared across the scraper.

Everything here is deliberately conservative: the rules strip Wikipedia
artefacts (citation markers, edit links, NBSPs) but never touch legitimate
punctuation inside names. "S. S. Rajamouli", "Nenu.. Sailaja...",
"Haarika & Hassine Creations" and "N.T.R: Kathanayakudu" must all survive
unchanged.
"""

from __future__ import annotations

import html
import re
import unicodedata
from typing import Iterable

from config.settings import CROSS_REFERENCE_VALUES, PLACEHOLDER_VALUES

# [1], [2], [a], [note 3], [citation needed] ...
_CITATION_RE = re.compile(r"\[\s*(?:\d+|[a-z]|note\s*\d+|citation needed|clarify|sic)\s*\]", re.I)
# Bare bracket leftovers such as "[ ]" produced by get_text(" ") on refs.
_EMPTY_BRACKET_RE = re.compile(r"\[\s*\]")
# Trailing "[edit]" / "( edit )" section artefacts.
_EDIT_RE = re.compile(r"\[\s*edit\s*\]|\(\s*edit\s*\)", re.I)
# Parenthesised ISO date emitted by Wikipedia's date template:
# "12 January 2020 ( 2020-01-12 )" -> drop the redundant tail.
_ISO_PAREN_RE = re.compile(r"\(\s*\d{4}-\d{2}-\d{2}\s*\)")
_WHITESPACE_RE = re.compile(r"\s+")
# "AlluArjunRashmika" style runs when Wikipedia omits separators entirely.
_CAMEL_RUN_RE = re.compile(r"(?<=[a-z])(?=[A-Z])")
# Separators that split a multi-value infobox cell.
_VALUE_SPLIT_RE = re.compile(r"\s*(?:[\n\r|·•;]|,|\band\b)\s*", re.I)


def clean_text(value: str | None) -> str:
    """Normalise a raw string scraped from Wikipedia.

    Unescapes entities, removes citation/edit artefacts, normalises unicode
    spaces, and collapses runs of whitespace. Returns "" for falsy input.
    """
    if not value:
        return ""

    text = html.unescape(str(value))
    # NBSP and friends -> plain space before any further processing.
    text = text.replace("\xa0", " ").replace("​", "").replace("‎", "")
    text = unicodedata.normalize("NFC", text)

    text = _CITATION_RE.sub(" ", text)
    text = _EDIT_RE.sub(" ", text)
    text = _EMPTY_BRACKET_RE.sub(" ", text)
    # Wikipedia's date template renders "12 January 2020 (2020-01-12)";
    # the parenthesised ISO copy is redundant noise once parsed.
    text = _ISO_PAREN_RE.sub(" ", text)

    text = _WHITESPACE_RE.sub(" ", text).strip()
    # Strip separator debris left at the edges after removals.
    text = text.strip(" ,;|·•–—-").strip()
    return text


def is_placeholder(value: str | None) -> bool:
    """True when a value means "no data" and should be stored as NULL."""
    if not value:
        return True
    normalised = clean_text(value).lower().strip(" .")
    if not normalised:
        return True
    if normalised in PLACEHOLDER_VALUES:
        return True
    # Values that are only punctuation or only digits-as-dashes.
    return not any(ch.isalnum() for ch in normalised)


def is_cross_reference(value: str | None) -> bool:
    """True for infobox values that point elsewhere instead of naming anyone.

    e.g. "see below", "see distribution" -- storing these would be worse
    than storing nothing, because they read as real data downstream.
    """
    if not value:
        return False
    return clean_text(value).lower().strip(" .") in CROSS_REFERENCE_VALUES


def clean_name(value: str | None) -> str:
    """Clean a single person/company name.

    Keeps internal punctuation (initials, ampersands, colons) intact and
    only removes bracketed annotations and role suffixes.
    """
    text = clean_text(value)
    if not text:
        return ""

    # Drop parenthetical role notes: "Prakash Raj (special appearance)".
    text = re.sub(r"\s*\([^)]*\)\s*$", "", text).strip()
    # Drop a trailing role after a dash: "Ravi Teja - guest".
    text = re.sub(r"\s+[-–—]\s+(?:as|guest|cameo|special appearance).*$", "", text, flags=re.I)
    # Leading list bullets.
    text = text.lstrip("*•-–— ").strip()
    return text.strip(" ,;|").strip()


def split_camel_run(value: str) -> list[str]:
    """Split a separator-less run such as "Ravi TejaPrakash Raj".

    Only applied when a cell yielded a single suspiciously long token; a
    normal name is returned unchanged as a one-item list.
    """
    text = clean_text(value)
    if not text:
        return []
    parts = [p.strip() for p in _CAMEL_RUN_RE.split(text) if p.strip()]
    return parts or [text]


def split_values(value: str | None) -> list[str]:
    """Split a multi-value infobox string into individual entries.

    Splitting happens *before* whitespace collapsing, because newlines are
    the separator Wikipedia uses for <br>-delimited infobox lists (observed
    on films whose cast row carries no <li> markup). Collapsing first would
    fuse "Priyadarshi\\nKavya Kalyanram" into a single bogus name.
    """
    if not value:
        return []
    # Only pre-clean entities/citations; keep line structure intact.
    text = html.unescape(str(value)).replace("\xa0", " ")
    text = _CITATION_RE.sub(" ", text)
    text = _EDIT_RE.sub(" ", text)
    if not text.strip():
        return []
    parts = [clean_name(part) for part in _VALUE_SPLIT_RE.split(text)]
    return [p for p in parts if p and not is_placeholder(p)]


def dedupe_preserving_order(values: Iterable[str]) -> list[str]:
    """Remove case-insensitive duplicates while preserving first-seen order.

    Order matters for cast: billing order is a real signal for the game.
    """
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = clean_name(value)
        if not cleaned or is_placeholder(cleaned):
            continue
        key = normalise_key(cleaned)
        if key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result


def normalise_key(value: str | None) -> str:
    """Aggressive normalisation used only for comparison/deduplication.

    Never stored -- this strips punctuation and diacritics so that
    "Nenu.. Sailaja..." and "Nenu Sailaja" compare equal.
    """
    text = clean_text(value).lower()
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return _WHITESPACE_RE.sub(" ", text).strip()


def normalise_label(label: str | None) -> str:
    """Normalise an infobox row label for alias matching."""
    text = clean_text(label).lower()
    text = text.replace(":", " ").strip(" .")
    return _WHITESPACE_RE.sub(" ", text).strip()


def normalise_title(title: str | None) -> str:
    """Normalise a film title for display.

    Removes Wikipedia disambiguation suffixes -- "(2000 film)", "(film)",
    "(2023 Telugu film)" -- which are URL artefacts, not part of the name.
    """
    text = clean_text(title)
    if not text:
        return ""
    text = re.sub(
        r"\s*\((?:\d{4}\s+)?(?:[A-Za-z]+\s+)?film\)\s*$", "", text, flags=re.I
    ).strip()
    return text


def title_sort_key(title: str | None) -> str:
    """Comparison key for a film title, ignoring disambiguators and case."""
    return normalise_key(normalise_title(title))
