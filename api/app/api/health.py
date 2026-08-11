"""Health and statistics endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.services import game_service, movie_service

router = APIRouter(tags=["health"])


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    """Liveness probe that also confirms the database is reachable."""
    try:
        db.execute(text("SELECT 1"))
        database_ok = True
    except Exception:  # pragma: no cover - depends on deployment
        database_ok = False

    payload = {"status": "ok" if database_ok else "degraded", "database": database_ok}
    if database_ok:
        payload["movies"] = movie_service.count_movies(db)
        payload["eligible_movies"] = movie_service.count_eligible(db)
    return payload


@router.get("/stats")
def stats(db: Session = Depends(get_db)) -> dict:
    """Anonymous aggregate statistics."""
    return game_service.get_stats(db)
