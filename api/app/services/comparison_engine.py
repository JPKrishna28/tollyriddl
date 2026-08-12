"""Comparison engine: the core game logic.

Compares a guessed movie against the hidden mystery movie and returns only
the information the player has *earned* -- the intersections. Nothing about
the mystery movie leaks beyond what the two films genuinely share.

This module is deliberately pure: it takes two plain dataclasses and returns
a plain dataclass. No database, no HTTP, no framework imports. That keeps it
independently testable and prevents game logic from drifting into API
routes or React components.

Information-disclosure rules enforced here:
  * Year   -- reveals only a direction (earlier/later), never the value,
              unless the years are equal.
  * Genre  -- reveals only the intersection.
  * Cast   -- reveals only shared actors, with their billing positions in
              both films (a legitimate deduction signal).
  * Crew   -- director / production house / music director / writer reveal
              a name only when it is shared by both films.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Sequence

# ----------------------------------------------------------------------
# Status vocabulary
# ----------------------------------------------------------------------


class Status(str, Enum):
    """Outcome of comparing a single attribute."""

    CORRECT = "correct"        # exact / full match
    PARTIAL = "partial"        # some overlap
    ABSENT = "absent"          # no overlap
    UNKNOWN = "unknown"        # one side has no data -- cannot compare

    def __str__(self) -> str:  # pragma: no cover - convenience only
        return self.value


class YearDirection(str, Enum):
    """Directional hint for the year attribute."""

    SAME = "same"       # mystery year == guess year
    EARLIER = "earlier"  # mystery released before the guess  (show down arrow)
    LATER = "later"      # mystery released after the guess   (show up arrow)
    UNKNOWN = "unknown"


# ----------------------------------------------------------------------
# Inputs / outputs
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class Movie:
    """Minimal movie shape the engine needs.

    Every multi-value attribute is a list, including ``director`` -- the
    real dataset has films with co-directors, so treating it as a scalar
    would silently drop credits.
    """

    movie_id: int
    title: str
    year: int | None = None
    genres: tuple[str, ...] = ()
    cast: tuple[str, ...] = ()          # order is billing order and matters
    directors: tuple[str, ...] = ()
    production_houses: tuple[str, ...] = ()
    music_directors: tuple[str, ...] = ()
    writers: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Movie":
        """Build from a dataset/ORM dict, tolerating both field namings."""

        def multi(*keys: str) -> tuple[str, ...]:
            for key in keys:
                if key in data and data[key] is not None:
                    return _as_tuple(data[key])
            return ()

        return cls(
            movie_id=int(data.get("movie_id") or data.get("id") or 0),
            title=str(data.get("movie_name") or data.get("title") or "").strip(),
            year=_as_year(data.get("year")),
            genres=multi("genres", "genre"),
            cast=multi("cast", "cast_members"),
            directors=multi("directors", "director"),
            production_houses=multi("production_houses", "production_house"),
            music_directors=multi("music_directors", "music_director"),
            writers=multi("writers", "writer"),
        )


@dataclass
class CastMatch:
    """A shared actor and their billing position in each film."""

    name: str
    guess_position: int    # 1-indexed position in the guessed film
    mystery_position: int  # 1-indexed position in the mystery film

    def to_dict(self) -> dict[str, Any]:
        """Wire shape for a shared actor.

        ``mystery_position`` is deliberately **not** serialised. It stays on
        the dataclass for server-side use, but sending it would leak the
        mystery film's billing order to anyone reading the network response
        -- hiding it in the UI alone would not actually hide it.
        """
        return {
            "name": self.name,
            "position": self.guess_position,
            "guess_position": self.guess_position,
        }


@dataclass
class YearResult:
    guess: int | None
    status: Status
    direction: YearDirection
    mystery: int | None = None  # populated only when the years are equal

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "guess": self.guess,
            "status": self.status.value,
            "direction": self.direction.value,
        }
        # The mystery year is disclosed only on an exact match; otherwise
        # the player gets a direction and nothing more.
        if self.mystery is not None:
            payload["mystery"] = self.mystery
        return payload


@dataclass
class SetResult:
    """Result for any multi-value attribute."""

    guess: list[str]
    common: list[str]
    status: Status

    def to_dict(self) -> dict[str, Any]:
        return {
            "guess": self.guess,
            "common": self.common,
            "status": self.status.value,
        }


@dataclass
class CastResult:
    guess: list[str]
    common: list[CastMatch]
    status: Status

    def to_dict(self) -> dict[str, Any]:
        return {
            "guess": self.guess,
            "common": [match.to_dict() for match in self.common],
            "common_count": len(self.common),
            "status": self.status.value,
        }


@dataclass
class ComparisonResult:
    """Everything the player learns from one guess."""

    movie_id: int
    title: str
    is_correct: bool
    year: YearResult
    genre: SetResult
    cast: CastResult
    director: SetResult
    production_house: SetResult
    music_director: SetResult
    writer: SetResult

    def to_dict(self) -> dict[str, Any]:
        return {
            "movie_id": self.movie_id,
            "title": self.title,
            "is_correct": self.is_correct,
            "year": self.year.to_dict(),
            "genre": self.genre.to_dict(),
            "cast": self.cast.to_dict(),
            "director": self.director.to_dict(),
            "production_house": self.production_house.to_dict(),
            "music_director": self.music_director.to_dict(),
            "writer": self.writer.to_dict(),
        }

    def revealed_attributes(self) -> set[str]:
        """Attributes this guess fully revealed.

        Used by the lifeline system so a clue the player already earned is
        never offered (or wasted) as a lifeline.
        """
        revealed: set[str] = set()
        if self.year.status is Status.CORRECT:
            revealed.add("year")
        for name, result in (
            ("director", self.director),
            ("production_house", self.production_house),
            ("music_director", self.music_director),
            ("writer", self.writer),
        ):
            if result.common:
                revealed.add(name)
        return revealed

    def shared_values(self, attribute: str) -> set[str]:
        """Values of ``attribute`` this guess put on the board.

        A lifeline reveals one cell, so knowing *which* values a guess
        already surfaced is what keeps a cell from being sold twice.
        Cast matches carry position metadata, so they are flattened to
        names to match ``attribute_value`` output.
        """
        if attribute == "year":
            return {str(self.year.mystery)} if self.year.mystery is not None else set()
        if attribute == "cast":
            return {match.name for match in self.cast.common}
        result = getattr(self, attribute, None)
        if isinstance(result, SetResult):
            return set(result.common)
        return set()


# ----------------------------------------------------------------------
# Normalisation helpers
# ----------------------------------------------------------------------


def _as_tuple(value: Any) -> tuple[str, ...]:
    """Coerce a dataset value into an ordered tuple of strings.

    Accepts real lists (JSON dataset) and pipe-joined strings (CSV), so the
    engine works against either representation without a conversion layer.
    """
    if value is None:
        return ()
    if isinstance(value, str):
        parts = [part.strip() for part in value.split("|")]
        return tuple(part for part in parts if part)
    if isinstance(value, Iterable):
        parts = [str(item).strip() for item in value]
        return tuple(part for part in parts if part)
    return ()


def _as_year(value: Any) -> int | None:
    try:
        year = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return year if 1800 < year < 2200 else None


def normalise(value: str) -> str:
    """Comparison key for names.

    Case- and punctuation-insensitive, diacritic-folded, whitespace-collapsed
    so "S. S. Rajamouli" matches "S S Rajamouli". Never used for display --
    the original spelling is always what the player sees.
    """
    if not value:
        return ""
    text = unicodedata.normalize("NFKD", str(value).strip().lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    # Apostrophes are elided rather than spaced, so "D'Cruz" and "DCruz"
    # collapse to the same key; other punctuation becomes a separator.
    text = text.replace("'", "").replace("’", "")
    kept = [ch if (ch.isalnum() or ch.isspace()) else " " for ch in text]
    return " ".join("".join(kept).split())


def _intersect_ordered(
    guess: Sequence[str], mystery: Sequence[str]
) -> list[str]:
    """Values present in both, in the guess's order, de-duplicated.

    Guess order is used so the row reads naturally against what the player
    just typed; mystery ordering is never exposed here.
    """
    mystery_keys = {normalise(item) for item in mystery if normalise(item)}
    seen: set[str] = set()
    common: list[str] = []
    for item in guess:
        key = normalise(item)
        if key and key in mystery_keys and key not in seen:
            seen.add(key)
            common.append(item)
    return common


def _set_status(
    guess: Sequence[str], mystery: Sequence[str], common: Sequence[str]
) -> Status:
    """Grade a multi-value comparison."""
    if not guess or not mystery:
        # One side has no data -- "no match" would be misleading.
        return Status.UNKNOWN
    if not common:
        return Status.ABSENT
    # CORRECT only when the guess contributes nothing the mystery lacks and
    # covers everything the mystery has.
    guess_keys = {normalise(v) for v in guess if normalise(v)}
    mystery_keys = {normalise(v) for v in mystery if normalise(v)}
    return Status.CORRECT if guess_keys == mystery_keys else Status.PARTIAL


# ----------------------------------------------------------------------
# Per-attribute comparison
# ----------------------------------------------------------------------


def compare_year(guess_year: int | None, mystery_year: int | None) -> YearResult:
    """Compare release years, disclosing direction only.

    A mismatch tells the player whether the mystery film is earlier or
    later than their guess -- never the actual year.
    """
    if guess_year is None or mystery_year is None:
        return YearResult(guess=guess_year, status=Status.UNKNOWN,
                          direction=YearDirection.UNKNOWN)

    if guess_year == mystery_year:
        # Safe to echo the year: the player already knows it.
        return YearResult(guess=guess_year, status=Status.CORRECT,
                          direction=YearDirection.SAME, mystery=mystery_year)

    direction = (
        YearDirection.LATER if mystery_year > guess_year else YearDirection.EARLIER
    )
    return YearResult(guess=guess_year, status=Status.ABSENT, direction=direction)


def compare_cast(
    guess_cast: Sequence[str], mystery_cast: Sequence[str]
) -> CastResult:
    """Compare cast lists, reporting billing positions for shared actors.

    Positions are 1-indexed and deterministic: they come from the stored
    billing order, which the importer preserves from the dataset.
    """
    if not guess_cast or not mystery_cast:
        return CastResult(guess=list(guess_cast), common=[], status=Status.UNKNOWN)

    mystery_index: dict[str, int] = {}
    for position, actor in enumerate(mystery_cast, start=1):
        key = normalise(actor)
        if key and key not in mystery_index:
            mystery_index[key] = position

    matches: list[CastMatch] = []
    seen: set[str] = set()
    for position, actor in enumerate(guess_cast, start=1):
        key = normalise(actor)
        if not key or key in seen or key not in mystery_index:
            continue
        seen.add(key)
        matches.append(
            CastMatch(
                name=actor,
                guess_position=position,
                mystery_position=mystery_index[key],
            )
        )

    if not matches:
        status = Status.ABSENT
    else:
        guess_keys = {normalise(a) for a in guess_cast if normalise(a)}
        mystery_keys = set(mystery_index)
        status = Status.CORRECT if guess_keys == mystery_keys else Status.PARTIAL

    return CastResult(guess=list(guess_cast), common=matches, status=status)


def compare_multi(
    guess_values: Sequence[str], mystery_values: Sequence[str]
) -> SetResult:
    """Compare any non-cast multi-value attribute."""
    common = _intersect_ordered(guess_values, mystery_values)
    return SetResult(
        guess=list(guess_values),
        common=common,
        status=_set_status(guess_values, mystery_values, common),
    )


# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------


def compare(mystery_movie: Movie, guessed_movie: Movie) -> ComparisonResult:
    """Compare a guess against the mystery movie.

    Returns only shared information. A correct guess is decided by movie id
    so two films with the same title in different years never collide.
    """
    is_correct = mystery_movie.movie_id == guessed_movie.movie_id

    return ComparisonResult(
        movie_id=guessed_movie.movie_id,
        title=guessed_movie.title,
        is_correct=is_correct,
        year=compare_year(guessed_movie.year, mystery_movie.year),
        genre=compare_multi(guessed_movie.genres, mystery_movie.genres),
        cast=compare_cast(guessed_movie.cast, mystery_movie.cast),
        director=compare_multi(guessed_movie.directors, mystery_movie.directors),
        production_house=compare_multi(
            guessed_movie.production_houses, mystery_movie.production_houses
        ),
        music_director=compare_multi(
            guessed_movie.music_directors, mystery_movie.music_directors
        ),
        writer=compare_multi(guessed_movie.writers, mystery_movie.writers),
    )


# Attributes a lifeline may reveal, in display order.
REVEALABLE_ATTRIBUTES: tuple[str, ...] = (
    "year",
    "genre",
    "cast",
    "director",
    "production_house",
    "music_director",
    "writer",
)


def attribute_value(movie: Movie, attribute: str) -> list[str]:
    """Read one attribute off a movie as a list of display strings.

    Used by the lifeline system to reveal a single cell.
    """
    mapping: dict[str, tuple[str, ...] | list[str]] = {
        "year": [str(movie.year)] if movie.year else [],
        "genre": list(movie.genres),
        "cast": list(movie.cast),
        "director": list(movie.directors),
        "production_house": list(movie.production_houses),
        "music_director": list(movie.music_directors),
        "writer": list(movie.writers),
    }
    if attribute not in mapping:
        raise ValueError(f"Unknown attribute: {attribute!r}")
    return list(mapping[attribute])
