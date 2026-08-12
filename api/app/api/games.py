"""Game endpoints.

Every route treats the client as untrusted. Dates, movie ids, attempt
counts and lifeline availability are all re-derived server-side; nothing
the browser sends is taken at face value.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import DailyGame, GameSession, GameStatus
from app.schemas import GuessRequest, LifelineRequest, StartGameRequest
from app.services import daily_movie as daily_movie_service
from app.services import game_service
from app.services.game_service import GameError

router = APIRouter(prefix="/games", tags=["games"])


def _handle(error: GameError) -> HTTPException:
    return HTTPException(
        status_code=error.status, detail={"detail": error.message, "code": error.code}
    )


def _commit(db: Session) -> None:
    """Commit inside the request so failures are still catchable.

    ``get_db`` deliberately does not commit: doing so during dependency
    teardown happens after the response exists, so a dropped connection
    there escapes as an opaque 500. Committing here turns the same failure
    into a structured 503 the client can act on.
    """
    try:
        db.commit()
    except Exception as error:
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail={
                "detail": "Could not save your progress. Please retry.",
                "code": "commit_failed",
            },
        ) from error


def _resolve_today(client_date: date | None) -> date:
    """Decide what 'today' means.

    The player's local date is honoured so the puzzle rolls over at their
    local midnight, but it is clamped to +/-1 day around UTC. Without the
    clamp, setting the system clock forward would unlock future puzzles.
    """
    server_today = datetime.now(timezone.utc).date()
    if client_date is None:
        return server_today
    delta = (client_date - server_today).days
    if -1 <= delta <= 1:
        return client_date
    return server_today


@router.get("/today")
def today(
    client_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    """Metadata for today's puzzle.

    Announces that a puzzle exists and its rules -- never which movie it is.
    """
    game_date = _resolve_today(client_date)
    daily = daily_movie_service.get_or_create_daily_game(db, game_date)
    if daily is None:
        raise HTTPException(
            status_code=503,
            detail={"detail": "No eligible movies available.", "code": "no_eligible_movies"},
        )

    # This GET can lazily pin a new daily row, which must be persisted.
    _commit(db)

    return {
        "game_date": game_date.isoformat(),
        "available": True,
        "base_attempts": settings.base_attempts,
        "bonus_attempts": settings.bonus_attempts,
        "lifeline_1_after": settings.lifeline_1_after,
        "lifeline_2_after": settings.lifeline_2_after,
    }


@router.post("/start")
def start(
    payload: StartGameRequest | None = None,
    db: Session = Depends(get_db),
) -> dict:
    """Begin a session for a date's puzzle."""
    payload = payload or StartGameRequest()
    today_date = _resolve_today(payload.client_date)
    game_date = payload.game_date or today_date

    try:
        game = game_service.start_session(db, game_date, today_date)
    except GameError as error:
        raise _handle(error) from error

    payload = game_service.serialize_game(db, game)
    _commit(db)
    return payload


@router.get("/archive")
def archive(
    client_date: date | None = Query(default=None),
    limit: int = Query(default=settings.archive_max_days, ge=1, le=365),
    db: Session = Depends(get_db),
) -> dict:
    """Playable past dates, newest first.

    Lists only which dates exist and how sessions there ended. It never
    includes the mystery movie for a date the player has not finished.
    """
    today_date = _resolve_today(client_date)
    dates = daily_movie_service.archive_dates(today_date, limit=limit)

    # One join for every date in the window. Querying sessions per date
    # inside the loop below meant up to ``limit`` sequential round-trips,
    # which overran the function timeout and returned a 504.
    rows = db.execute(
        select(DailyGame.game_date, GameSession.status)
        .select_from(DailyGame)
        .outerjoin(GameSession, GameSession.daily_game_id == DailyGame.id)
        .where(DailyGame.game_date.in_(dates))
    ).all()

    statuses_by_date: dict[date, set[str]] = {}
    for game_date, session_status in rows:
        bucket = statuses_by_date.setdefault(game_date, set())
        if session_status is None:
            continue
        bucket.add(
            session_status.value
            if isinstance(session_status, GameStatus)
            else session_status
        )

    entries: list[dict] = []
    for game_date in dates:
        statuses = statuses_by_date.get(game_date, set())
        status = "not_played"

        if GameStatus.WON.value in statuses:
            status = "won"
        elif GameStatus.LOST.value in statuses:
            status = "lost"
        elif GameStatus.ACTIVE.value in statuses:
            status = "in_progress"

        entries.append(
            {
                "game_date": game_date.isoformat(),
                "is_today": game_date == today_date,
                "status": status,
            }
        )

    return {"today": today_date.isoformat(), "entries": entries}


@router.get("/archive/{game_date}")
def archive_date(
    game_date: date,
    client_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    """Confirm a past date is playable, without revealing its answer."""
    today_date = _resolve_today(client_date)
    if game_date > today_date:
        raise HTTPException(
            status_code=400,
            detail={"detail": "Game not available yet.", "code": "future_date"},
        )

    daily = daily_movie_service.get_or_create_daily_game(db, game_date)
    if daily is None:
        raise HTTPException(
            status_code=503,
            detail={"detail": "No eligible movies available.", "code": "no_eligible_movies"},
        )

    # As with /today, this may have pinned a new daily row.
    _commit(db)

    return {"game_date": game_date.isoformat(), "available": True}


@router.get("/{game_id}")
def get_game(game_id: str, db: Session = Depends(get_db)) -> dict:
    """Current state of a session, for resuming after a refresh."""
    try:
        game = game_service.get_session(db, game_id)
    except GameError as error:
        raise _handle(error) from error
    return game_service.serialize_game(db, game)


@router.post("/{game_id}/guess")
def guess(game_id: str, payload: GuessRequest, db: Session = Depends(get_db)) -> dict:
    """Submit a guess and receive only the shared attributes."""
    try:
        outcome = game_service.submit_guess(db, game_id, payload.guess_movie_id)
    except GameError as error:
        raise _handle(error) from error

    response = {
        "attempt": outcome.attempt_number,
        "result": outcome.result,
        "game": game_service.serialize_game(db, outcome.session, include_history=False),
    }
    _commit(db)
    return response


@router.post("/{game_id}/lifeline")
def lifeline(
    game_id: str, payload: LifelineRequest, db: Session = Depends(get_db)
) -> dict:
    """Spend a lifeline to reveal a single cell."""
    try:
        revealed = game_service.use_lifeline(
            db, game_id, payload.attribute, payload.value_index
        )
        game = game_service.get_session(db, game_id)
    except GameError as error:
        raise _handle(error) from error

    response = {
        "revealed": revealed,
        "game": game_service.serialize_game(db, game, include_history=False),
    }
    _commit(db)
    return response


@router.post("/{game_id}/unlock-bonus")
def unlock_bonus(game_id: str, db: Session = Depends(get_db)) -> dict:
    """Unlock three additional attempts after the base seven."""
    try:
        game = game_service.unlock_bonus(db, game_id)
    except GameError as error:
        raise _handle(error) from error

    payload = game_service.serialize_game(db, game)
    _commit(db)
    return payload
