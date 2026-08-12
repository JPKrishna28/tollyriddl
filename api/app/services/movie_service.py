"""Movie lookup and search.

Search is intentionally narrow in what it returns: id, title and year only.
A richer payload would let a player mine attributes of candidate movies
without spending a guess.
"""

from __future__ import annotations

import re
import unicodedata

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Movie

_YEAR_IN_QUERY = re.compile(r"\b(19|20)\d{2}\b")


def normalize_title(title: str) -> str:
    """Fold a title into a search/dedupe key.

    Case, punctuation, diacritics and spacing are all normalised so that
    "rrr", "R.R.R." and "R R R" reach the same row. Telugu script is
    preserved -- only combining marks are stripped, never base characters.
    """
    if not title:
        return ""
    text = unicodedata.normalize("NFKD", title.strip().lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("'", "").replace("’", "").replace("&", " and ")
    kept = [ch if (ch.isalnum() or ch.isspace()) else " " for ch in text]
    return " ".join("".join(kept).split())


def search_movies(session: Session, query: str, limit: int | None = None) -> list[Movie]:
    """Find movies by partial, case-insensitive title.

    Results are ranked: exact match, then prefix match, then substring,
    so typing "rrr" surfaces *RRR* rather than an unrelated film that
    merely contains those letters.
    """
    limit = limit or settings.search_limit
    cleaned = normalize_title(query)
    if not cleaned:
        return []

    # A trailing year in the query filters rather than pollutes the match:
    # "pokiri 2006" should find Pokiri (2006).
    year_filter: int | None = None
    year_match = _YEAR_IN_QUERY.search(query)
    if year_match:
        candidate = normalize_title(_YEAR_IN_QUERY.sub("", query))
        if candidate:
            year_filter = int(year_match.group(0))
            cleaned = candidate

    # "R.R.R." normalises to "r r r" while the stored title is "rrr", so a
    # space-stripped variant is matched too. Initial-heavy Telugu titles
    # ("N.T.R", "S/O Satyamurthy") depend on this.
    compact = cleaned.replace(" ", "")
    conditions = [Movie.normalized_title.like(f"%{cleaned}%")]
    if compact and compact != cleaned:
        conditions.append(
            func.replace(Movie.normalized_title, " ", "").like(f"%{compact}%")
        )

    statement = select(Movie).where(or_(*conditions))
    if year_filter is not None:
        statement = statement.where(Movie.year == year_filter)

    # Rank in SQL so the limit applies to *sorted* results, not an
    # arbitrary slice that is then reordered.
    rank = case(
        (Movie.normalized_title == cleaned, 0),
        (func.replace(Movie.normalized_title, " ", "") == compact, 0),
        (Movie.normalized_title.like(f"{cleaned}%"), 1),
        else_=2,
    )
    statement = statement.order_by(
        rank, func.length(Movie.normalized_title), Movie.year.desc(), Movie.title
    ).limit(limit)

    return list(session.execute(statement).scalars())


def list_catalog(session: Session) -> list[tuple[int, str, str, int | None]]:
    """Every guessable title, for the client-side autocomplete index.

    Same columns `to_search_dict` exposes, plus the normalized title so the
    browser can rank matches identically to `search_movies` without asking
    the server. Still no cast or crew: the catalogue is a list of names to
    guess, not a way to mine attributes.
    """
    statement = select(
        Movie.id, Movie.title, Movie.normalized_title, Movie.year
    ).order_by(Movie.id)
    return [tuple(row) for row in session.execute(statement).all()]


def get_movie(session: Session, movie_id: int) -> Movie | None:
    return session.get(Movie, movie_id)


def movie_exists(session: Session, movie_id: int) -> bool:
    return session.get(Movie, movie_id) is not None


def count_movies(session: Session) -> int:
    return int(session.execute(select(func.count(Movie.id))).scalar_one())


def count_eligible(session: Session) -> int:
    return int(
        session.execute(
            select(func.count(Movie.id)).where(Movie.is_eligible.is_(True))
        ).scalar_one()
    )
