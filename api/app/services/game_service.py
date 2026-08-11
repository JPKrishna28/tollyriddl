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
from sqlalchemy.orm import Session

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

    session.flush()
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
    """Attributes the player already knows.

    Combines clues earned through matching guesses with cells already
    spent on a lifeline, so a lifeline is never offered for information
    the player has.
    """
    known: set[str] = {row.attribute for row in game.lifelines}
    if not game.guesses:
        return known

    mystery = _engine_movie(_mystery_movie(session, game))
    for guess in game.guesses:
        movie = session.get(Movie, guess.movie_id)
        if movie is None:  # pragma: no cover - FK protects this
            continue
        known |= compare(mystery, _engine_movie(movie)).revealed_attributes()
    return known


def available_lifeline_attributes(session: Session, game: GameSession) -> list[str]:
    """Cells a lifeline could still usefully reveal.

    Excludes what the player already knows and anything the mystery movie
    has no data for -- revealing an empty cell would waste the lifeline.
    """
    mystery = _mystery_movie(session, game)
    engine_movie = _engine_movie(mystery)
    known = revealed_attributes(session, game)

    available: list[str] = []
    for attribute in REVEALABLE_ATTRIBUTES:
        if attribute in known:
            continue
        if not attribute_value(engine_movie, attribute):
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


def use_lifeline(session: Session, game_id: str, attribute: str) -> dict[str, Any]:
    """Spend a lifeline to reveal one attribute of the mystery movie."""
    game = get_session(session, game_id)

    if not game.is_active:
        raise GameError(
            "This game is already complete.", code="game_complete", status=409
        )

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

    session.add(
        Lifeline(
            game_session_id=game.id,
            lifeline_number=used + 1,
            attribute=attribute,
            created_at=_utcnow(),
        )
    )
    session.flush()

    return {
        "attribute": attribute,
        "values": values,
        "lifeline_number": used + 1,
    }


# ----------------------------------------------------------------------
# Serialisation
# ----------------------------------------------------------------------


def build_guess_history(session: Session, game: GameSession) -> list[dict[str, Any]]:
    """Replay every guess so a refreshed client can rebuild the board."""
    mystery = _engine_movie(_mystery_movie(session, game))
    history: list[dict[str, Any]] = []
    for guess in game.guesses:
        movie = session.get(Movie, guess.movie_id)
        if movie is None:  # pragma: no cover
            continue
        payload = compare(mystery, _engine_movie(movie)).to_dict()
        payload["attempt"] = guess.attempt_number
        history.append(payload)
    return history


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
        "lifelines_used": [
            {"lifeline_number": row.lifeline_number, "attribute": row.attribute}
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
