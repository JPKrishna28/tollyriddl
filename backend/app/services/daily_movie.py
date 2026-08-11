"""Deterministic daily mystery-movie selection.

Requirements this satisfies:
  * The same date always yields the same movie, in every process and on
    every machine. Python's ``hash()`` is randomised per interpreter run
    (PYTHONHASHSEED), so selection uses SHA-256 instead.
  * Selection draws only from movies with enough metadata to be solvable.
  * A movie is not reused until the eligible pool has been exhausted, so
    consecutive days never repeat.
"""

from __future__ import annotations

import hashlib
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import DailyGame, Movie


# ----------------------------------------------------------------------
# Quality scoring
# ----------------------------------------------------------------------


def quality_score(
    *,
    year: int | None,
    genres: list[str],
    cast: list[str],
    director: str | None,
    production_house: str | None,
    music_director: str | None,
    writer: str | None,
) -> int:
    """Score how playable a movie is as a puzzle (0-8).

    Cast is weighted double: with no shared actors the game gives the
    player very little to reason about.
    """
    score = 0
    score += 1 if year else 0
    score += 1 if genres else 0
    score += 2 if len(cast) >= 2 else (1 if cast else 0)
    score += 1 if director else 0
    score += 1 if production_house else 0
    score += 1 if music_director else 0
    score += 1 if writer else 0
    return score


def is_eligible(
    *,
    year: int | None,
    genres: list[str],
    cast: list[str],
    director: str | None,
    score: int,
) -> bool:
    """Hard gate for daily-puzzle candidates.

    A movie missing year, cast, genre or director cannot be deduced
    fairly, regardless of its total score.
    """
    if not year or not director:
        return False
    if len(cast) < settings.min_cast:
        return False
    if len(genres) < settings.min_genres:
        return False
    return score >= settings.min_quality_score


# ----------------------------------------------------------------------
# Deterministic selection
# ----------------------------------------------------------------------


def date_seed(game_date: date, salt: str | None = None) -> int:
    """Stable integer derived from the date.

    SHA-256 of "<seed>-<YYYY-MM-DD>" -- reproducible across processes,
    machines and Python versions.
    """
    base = f"{salt or settings.daily_seed}-{game_date.isoformat()}"
    digest = hashlib.sha256(base.encode("utf-8")).hexdigest()
    return int(digest, 16)


def eligible_movie_ids(session: Session) -> list[int]:
    """All puzzle-eligible movie ids in a stable order.

    Ordered by id so the sequence does not shift when unrelated rows are
    added, which would otherwise change historical puzzles.
    """
    rows = session.execute(
        select(Movie.id).where(Movie.is_eligible.is_(True)).order_by(Movie.id)
    ).scalars()
    return list(rows)


def pick_movie_id(game_date: date, movie_ids: list[int]) -> int | None:
    """Choose the movie for a date without repeating recent picks.

    The pool is deterministically shuffled once, then indexed by the day
    offset. Every movie is used before any repeats, and the mapping stays
    identical on every call.
    """
    if not movie_ids:
        return None

    ordered = _deterministic_shuffle(movie_ids, settings.daily_seed)
    epoch = date.fromisoformat(settings.archive_start_date)
    offset = (game_date - epoch).days
    # Dates before the epoch wrap backwards consistently.
    return ordered[offset % len(ordered)]


def _deterministic_shuffle(items: list[int], salt: str) -> list[int]:
    """Shuffle by sorting on a per-item cryptographic hash.

    Equivalent to a seeded shuffle but independent of any RNG
    implementation, so results never change across Python versions.
    """
    def sort_key(item: int) -> str:
        return hashlib.sha256(f"{salt}:{item}".encode("utf-8")).hexdigest()

    return sorted(items, key=sort_key)


def get_daily_movie_id(session: Session, game_date: date) -> int | None:
    """Resolve the mystery movie id for a date."""
    return pick_movie_id(game_date, eligible_movie_ids(session))


def get_or_create_daily_game(session: Session, game_date: date) -> DailyGame | None:
    """Fetch (or pin) the daily game row for a date.

    Once a date's puzzle has been played it is stored, so later changes to
    the movie pool cannot retroactively alter a past day's answer.
    """
    existing = session.execute(
        select(DailyGame).where(DailyGame.game_date == game_date)
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    movie_id = get_daily_movie_id(session, game_date)
    if movie_id is None:
        return None

    daily = DailyGame(game_date=game_date, mystery_movie_id=movie_id)
    session.add(daily)
    session.flush()
    return daily


def archive_dates(today: date, limit: int | None = None) -> list[date]:
    """Playable dates, newest first, never including the future."""
    start = date.fromisoformat(settings.archive_start_date)
    span = limit or settings.archive_max_days
    dates: list[date] = []
    cursor = today
    while cursor >= start and len(dates) < span:
        dates.append(cursor)
        cursor -= timedelta(days=1)
    return dates
