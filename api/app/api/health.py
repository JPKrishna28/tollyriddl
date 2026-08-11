"""Health and statistics endpoints."""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
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

    # Which backend actually got resolved. A deployment that falls back to
    # SQLite means DATABASE_URL never reached the function -- reporting the
    # driver name (never the URL, which holds credentials) makes that
    # visible without shell access to the container.
    payload["backend"] = "sqlite" if settings.is_sqlite else "postgres"
    payload["database_url_set"] = bool(os.environ.get("DATABASE_URL"))
    if database_ok:
        payload["movies"] = movie_service.count_movies(db)
        payload["eligible_movies"] = movie_service.count_eligible(db)
    return payload


@router.get("/stats")
def stats(db: Session = Depends(get_db)) -> dict:
    """Anonymous aggregate statistics."""
    return game_service.get_stats(db)
