"""Game orchestration: sessions, guesses, lifelines, bonus attempts.

Every rule is enforced here, server-side. The frontend is treated as
untrusted: it may send any ``movie_id``, replay a request, or ask for a
lifeline early, and each of those is rejected with a specific error.

The mystery movie never appears in a response while a session is active.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.models import DailyGame, GameSession, GameStatus, Guess, Lifeline, Movie
from app.services import daily_movie as daily_movie_service
from app.services.comparison_engine import (
    REVEALABLE_ATTRIBUTES,
    Movie as EngineMovie,
    attribute_value,
    compare,
)


class GameError(Exception):
    """Domain error carrying an HTTP status and a stable error code."""

    def __init__(self, message: str, *, code: str = "game_error", status: int = 400):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


@dataclass
class GuessOutcome:
    session: GameSession
    result: dict[str, Any]
    attempt_number: int


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _engine_movie(movie: Movie) -> EngineMovie:
    return EngineMovie.from_dict(movie.to_engine_dict())


# ----------------------------------------------------------------------
# Session lifecycle
# ----------------------------------------------------------------------


def start_session(session: Session, game_date: date, today: date) -> GameSession:
    """Create a session for a date's puzzle.

    Future dates are refused: a puzzle that has not been released yet must
    not be playable, or the archive becomes a way to see tomorrow's answer.
    """
    if game_date > today:
        raise GameError(
            "Game not available yet.", code="future_date", status=400
        )

    archive_start = date.fromisoformat(settings.archive_start_date)
    if game_date < archive_start:
        raise GameError(
            f"No puzzle exists before {archive_start.isoformat()}.",
            code="before_archive_start",
            status=400,
        )

    daily = daily_movie_service.get_or_create_daily_game(session, game_date)
    if daily is None:
        raise GameError(
            "No eligible movies available for a puzzle.",
            code="no_eligible_movies",
            status=503,
        )

    game = GameSession(
        id=secrets.token_urlsafe(16),
        daily_game_id=daily.id,
        status=GameStatus.ACTIVE,
        attempts_used=0,
        started_at=_utcnow(),
    )
    session.add(game)
    session.flush()
    return game


def get_session(session: Session, game_id: str) -> GameSession:
    game = session.get(GameSession, game_id)
    if game is None:
        raise GameError("Game not found.", code="game_not_found", status=404)
    return game


def _mystery_movie(session: Session, game: GameSession) -> Movie:
    daily = session.get(DailyGame, game.daily_game_id)
    if daily is None:  # pragma: no cover - FK makes this unreachable
        raise GameError("Daily game missing.", code="daily_missing", status=500)
    movie = session.get(Movie, daily.mystery_movie_id)
    if movie is None:  # pragma: no cover - FK makes this unreachable
        raise GameError("Mystery movie missing.", code="movie_missing", status=500)
    return movie


# ----------------------------------------------------------------------
# Attempts
# ----------------------------------------------------------------------


def max_attempts(game: GameSession) -> int:
    """Attempt ceiling for a session (7, or 10 once bonus is unlocked)."""
    return settings.base_attempts + (
        settings.bonus_attempts if game.bonus_unlocked else 0
    )


def attempts_remaining(game: GameSession) -> int:
    return max(0, max_attempts(game) - game.attempts_used)


def submit_guess(session: Session, game_id: str, movie_id: int) -> GuessOutcome:
    """Validate and record a guess, returning only shared information."""
    game = get_session(session, game_id)

    if not game.is_active:
        raise GameError(
            "This game is already complete.", code="game_complete", status=409
        )

    if attempts_remaining(game) <= 0:
        raise GameError("No attempts remaining.", code="no_attempts", status=409)

    guessed = session.get(Movie, movie_id)
    if guessed is None:
        # Arbitrary ids from the client are rejected, not looked past.
        raise GameError("Movie not found.", code="movie_not_found", status=404)

    already = {row.movie_id for row in game.guesses}
    if movie_id in already:
        raise GameError(
            "You already guessed that movie.", code="duplicate_guess", status=409
        )

    mystery = _mystery_movie(session, game)
    comparison = compare(_engine_movie(mystery), _engine_movie(guessed))

    attempt_number = game.attempts_used + 1
    session.add(
        Guess(
            game_session_id=game.id,
            movie_id=movie_id,
            attempt_number=attempt_number,
            created_at=_utcnow(),
        )
    )
    game.attempts_used = attempt_number

    if comparison.is_correct:
        game.status = GameStatus.WON
        game.completed_at = _utcnow()
    elif attempts_remaining(game) <= 0 and game.bonus_unlocked:
        # Out of attempts with the extension already spent -> the game ends.
        game.status = GameStatus.LOST
        game.completed_at = _utcnow()

    try:
        session.flush()
    except IntegrityError as error:
        # Same race as the lifeline path: concurrent submissions can pick
        # the same ``attempt_number`` (or resubmit the same movie), and the
        # unique constraints reject the loser.
        session.rollback()
        raise GameError(
            "That guess was already recorded.",
            code="guess_conflict",
            status=409,
        ) from error

    return GuessOutcome(
        session=game, result=comparison.to_dict(), attempt_number=attempt_number
    )


def unlock_bonus(session: Session, game_id: str) -> GameSession:
    """Grant three extra attempts after the base seven are spent."""
    game = get_session(session, game_id)

    if game.bonus_unlocked:
        raise GameError(
            "Bonus attempts already unlocked.", code="bonus_already", status=409
        )
    if game.status == GameStatus.WON:
        raise GameError("Game already won.", code="game_complete", status=409)
    if game.attempts_used < settings.base_attempts:
        raise GameError(
            f"Bonus unlocks after {settings.base_attempts} guesses.",
            code="bonus_too_early",
            status=409,
        )

    game.bonus_unlocked = True
    # A game that ended by exhausting the base attempts becomes playable
    # again -- this is the only path back from a completed-by-attrition state.
    if game.status == GameStatus.LOST:
        game.status = GameStatus.ACTIVE
        game.completed_at = None
    session.flush()
    return game


# ----------------------------------------------------------------------
# Lifelines
# ----------------------------------------------------------------------


def revealed_attributes(session: Session, game: GameSession) -> set[str]:
    """Attributes the player knows *in full*.

    Combines clues earned through matching guesses with cells already
    spent on a lifeline. A lifeline now buys a single cell, so an attribute
    only counts as known here once every one of its cells is uncovered --
    a partially revealed cast is still worth spending on.
    """
    mystery_movie = _mystery_movie(session, game)
    known: set[str] = set()

    # A single-celled attribute is fully known the moment its one cell is
    # bought; a multi-celled one needs every cell.
    by_attribute: dict[str, set[int]] = {}
    for row in game.lifelines:
        by_attribute.setdefault(row.attribute, set()).add(row.value_index)
    for attribute, indexes in by_attribute.items():
        total = len(attribute_value(_engine_movie(mystery_movie), attribute))
        if total and len(indexes) >= total:
            known.add(attribute)

    if not game.guesses:
        return known

    mystery = _engine_movie(mystery_movie)

    # Bulk-load for the same reason as build_guess_history: one query with
    # the child collections joined, not three round-trips per guess.
    rows = session.execute(
        select(Movie)
        .where(Movie.id.in_([guess.movie_id for guess in game.guesses]))
        .options(selectinload(Movie.genres), selectinload(Movie.cast))
    ).scalars()

    for movie in rows:
        known |= compare(mystery, _engine_movie(movie)).revealed_attributes()
    return known


def revealed_cells(session: Session, game: GameSession) -> dict[str, set[int]]:
    """Per-cell map of what the player knows, keyed by attribute.

    Indexes are positions in ``attribute_value`` order. Values learned from
    a matching guess are resolved back to their index so a lifeline is never
    sold a cell the board already shows.
    """
    mystery = _engine_movie(_mystery_movie(session, game))
    cells: dict[str, set[int]] = {}

    for row in game.lifelines:
        cells.setdefault(row.attribute, set()).add(row.value_index)

    # Attributes known outright from guesses count as every cell revealed.
    for attribute in revealed_attributes(session, game):
        total = len(attribute_value(mystery, attribute))
        cells.setdefault(attribute, set()).update(range(total))

    if not game.guesses:
        return cells

    rows = session.execute(
        select(Movie)
        .where(Movie.id.in_([guess.movie_id for guess in game.guesses]))
        .options(selectinload(Movie.genres), selectinload(Movie.cast))
    ).scalars()

    # A guess sharing an actor already puts that name on the board, so the
    # matching cell must not be resold as a lifeline.
    for movie in rows:
        comparison = compare(mystery, _engine_movie(movie))
        for attribute in REVEALABLE_ATTRIBUTES:
            shared = comparison.shared_values(attribute)
            if not shared:
                continue
            values = attribute_value(mystery, attribute)
            for index, value in enumerate(values):
                if value in shared:
                    cells.setdefault(attribute, set()).add(index)
    return cells


def available_lifeline_attributes(session: Session, game: GameSession) -> list[str]:
    """Attributes with at least one cell a lifeline could still reveal.

    Excludes attributes the player already knows in full and anything the
    mystery movie has no data for -- revealing an empty cell would waste
    the lifeline.
    """
    mystery = _mystery_movie(session, game)
    engine_movie = _engine_movie(mystery)
    known = revealed_cells(session, game)

    available: list[str] = []
    for attribute in REVEALABLE_ATTRIBUTES:
        values = attribute_value(engine_movie, attribute)
        if not values:
            continue
        if len(known.get(attribute, set())) >= len(values):
            continue
        available.append(attribute)
    return available


def lifelines_unlocked(game: GameSession) -> int:
    """How many lifeline slots the attempt count has unlocked (0-2)."""
    unlocked = 0
    if game.attempts_used >= settings.lifeline_1_after:
        unlocked += 1
    if game.attempts_used >= settings.lifeline_2_after:
        unlocked += 1
    return unlocked


def use_lifeline(
    session: Session,
    game_id: str,
    attribute: str,
    value_index: int | None = None,
) -> dict[str, Any]:
    """Spend a lifeline to reveal a single cell of the mystery movie.

    ``value_index`` picks which cell of a multi-valued attribute to uncover.
    Omitting it takes the first cell the player does not already know, which
    keeps single-valued attributes (year, director) a one-argument call.
    """
    game = get_session(session, game_id)

    if not game.is_active:
        raise GameError(
            "This game is already complete.", code="game_complete", status=409
        )

    # Read the count from the database rather than the cached relationship:
    # a second lifeline spent in the same session would otherwise reuse a
    # stale ``lifeline_number`` and collide on the unique constraint.
    session.refresh(game, ["lifelines"])
    used = len(game.lifelines)
    unlocked = lifelines_unlocked(game)

    if used >= settings.max_lifelines:
        raise GameError("No lifelines left.", code="no_lifelines", status=409)
    if used >= unlocked:
        needed = (
            settings.lifeline_1_after if used == 0 else settings.lifeline_2_after
        )
        raise GameError(
            f"Lifeline unlocks after {needed} guesses.",
            code="lifeline_locked",
            status=409,
        )

    if attribute not in REVEALABLE_ATTRIBUTES:
        raise GameError(
            f"Unknown attribute: {attribute!r}", code="bad_attribute", status=400
        )

    available = available_lifeline_attributes(session, game)
    if attribute not in available:
        # Either already known or empty on the mystery movie; refusing
        # protects the player from burning a lifeline for nothing.
        raise GameError(
            "That clue is already known or unavailable.",
            code="attribute_unavailable",
            status=409,
        )

    mystery = _mystery_movie(session, game)
    values = attribute_value(_engine_movie(mystery), attribute)
    known = revealed_cells(session, game).get(attribute, set())

    if value_index is None:
        # Default to the first cell the player has not earned. ``available``
        # guarantees one exists.
        target = next(index for index in range(len(values)) if index not in known)
    else:
        if not 0 <= value_index < len(values):
            raise GameError(
                f"{attribute} has no cell at position {value_index}.",
                code="bad_value_index",
                status=400,
            )
        if value_index in known:
            raise GameError(
                "That cell is already revealed.",
                code="cell_already_revealed",
                status=409,
            )
        target = value_index

    session.add(
        Lifeline(
            game_session_id=game.id,
            lifeline_number=used + 1,
            attribute=attribute,
            value_index=target,
            created_at=_utcnow(),
        )
    )
    try:
        session.flush()
    except IntegrityError as error:
        # Two in-flight requests (a double-tap, or a retry) both read the
        # same ``used`` count and pick the same ``lifeline_number``. The
        # unique constraints then reject the loser. Postgres surfaces this
        # as IntegrityError rather than blocking, so it must be turned into
        # a normal 409 instead of escaping as a 500.
        session.rollback()
        raise GameError(
            "That lifeline was already spent.",
            code="lifeline_conflict",
            status=409,
        ) from error

    # The cached collection predates the insert above. Anything reading
    # ``game.lifelines`` later in this request -- notably serialize_game --
    # would otherwise miss the cell just bought.
    session.expire(game, ["lifelines"])

    return {
        "attribute": attribute,
        # A list of one: the client renders clue values uniformly, and the
        # shape stays stable for attributes that are genuinely single-celled.
        "values": [values[target]],
        "value_index": target,
        "lifeline_number": used + 1,
    }


# ----------------------------------------------------------------------
# Serialisation
# ----------------------------------------------------------------------


def build_guess_history(session: Session, game: GameSession) -> list[dict[str, Any]]:
    """Replay every guess so a refreshed client can rebuild the board.

    Every guessed movie is loaded in **one** query with its genres and cast
    eagerly joined. Fetching them one at a time issued three round-trips
    per guess (the row, then its genres, then its cast); against a remote
    pooler that grew linearly with the guess count until the request
    exceeded the function's time budget and returned a 500.
    """
    mystery = _engine_movie(_mystery_movie(session, game))

    movie_ids = [guess.movie_id for guess in game.guesses]
    movies: dict[int, Movie] = {}
    if movie_ids:
        rows = session.execute(
            select(Movie)
            .where(Movie.id.in_(movie_ids))
            .options(selectinload(Movie.genres), selectinload(Movie.cast))
        ).scalars()
        movies = {movie.id: movie for movie in rows}

    history: list[dict[str, Any]] = []
    for guess in game.guesses:
        movie = movies.get(guess.movie_id)
        if movie is None:  # pragma: no cover
            continue
        payload = compare(mystery, _engine_movie(movie)).to_dict()
        payload["attempt"] = guess.attempt_number
        history.append(payload)
    return history


def _lifeline_values(
    session: Session, game: GameSession, row: Lifeline
) -> list[str]:
    """The single value one spent lifeline uncovered.

    Returns a list to match the shape ``use_lifeline`` returns. An empty
    list means the movie's data shrank under a stored index, which should
    not happen but must not break the board.
    """
    values = attribute_value(_engine_movie(_mystery_movie(session, game)), row.attribute)
    if 0 <= row.value_index < len(values):
        return [values[row.value_index]]
    return []


def serialize_game(
    session: Session, game: GameSession, *, include_history: bool = True
) -> dict[str, Any]:
    """Public game state.

    The mystery movie is attached **only** once the game is over. While a
    session is active this payload contains nothing that identifies it.
    """
    daily = session.get(DailyGame, game.daily_game_id)
    payload: dict[str, Any] = {
        "game_id": game.id,
        "game_date": daily.game_date.isoformat() if daily else None,
        "status": game.status.value if isinstance(game.status, GameStatus) else game.status,
        "attempts_used": game.attempts_used,
        "attempts_remaining": attempts_remaining(game),
        "max_attempts": max_attempts(game),
        "base_attempts": settings.base_attempts,
        "bonus_attempts": settings.bonus_attempts,
        "bonus_unlocked": game.bonus_unlocked,
        "bonus_available": (
            not game.bonus_unlocked
            and game.attempts_used >= settings.base_attempts
            and game.status != GameStatus.WON
        ),
        # Includes the value bought, so a refreshed client can rebuild the
        # revealed cells. This discloses only what the player already paid
        # for -- never an unbought cell.
        "lifelines_used": [
            {
                "lifeline_number": row.lifeline_number,
                "attribute": row.attribute,
                "value_index": row.value_index,
                "values": _lifeline_values(session, game, row),
            }
            for row in game.lifelines
        ],
        "lifelines_unlocked": lifelines_unlocked(game),
        "lifelines_total": settings.max_lifelines,
        "started_at": game.started_at.isoformat() if game.started_at else None,
        "completed_at": game.completed_at.isoformat() if game.completed_at else None,
        "duration_seconds": game.duration_seconds(),
    }

    if include_history:
        payload["guesses"] = build_guess_history(session, game)

    if game.is_active:
        payload["lifelines_available"] = available_lifeline_attributes(session, game)
    else:
        # Game over: the answer may now be shown in full.
        payload["lifelines_available"] = []
        payload["mystery_movie"] = _mystery_movie(session, game).to_public_dict()

    return payload


def get_stats(session: Session) -> dict[str, Any]:
    """Aggregate anonymous statistics."""
    from sqlalchemy import func

    rows = session.execute(
        select(GameSession.status, func.count(GameSession.id)).group_by(GameSession.status)
    ).all()
    counts = {str(status): int(total) for status, total in rows}

    started = sum(counts.values())
    won = counts.get(GameStatus.WON.value, 0) + counts.get("GameStatus.WON", 0)
    lost = counts.get(GameStatus.LOST.value, 0) + counts.get("GameStatus.LOST", 0)

    average = session.execute(
        select(func.avg(GameSession.attempts_used)).where(
            GameSession.status == GameStatus.WON
        )
    ).scalar()

    return {
        "games_started": started,
        "games_completed": won + lost,
        "games_won": won,
        "games_lost": lost,
        "average_attempts": round(float(average), 2) if average is not None else None,
    }
