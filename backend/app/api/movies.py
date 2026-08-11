"""Movie search endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.schemas import MovieSearchItem
from app.services import movie_service

router = APIRouter(prefix="/movies", tags=["movies"])


@router.get("/search", response_model=list[MovieSearchItem])
def search(
    q: str = Query("", max_length=200, description="Partial movie title"),
    limit: int = Query(default=settings.search_limit, ge=1, le=50),
    db: Session = Depends(get_db),
) -> list[dict]:
    """Autocomplete Telugu movie titles.

    Returns id/title/year only. The full dataset is never shipped to the
    browser, and no crew or cast data is exposed here -- that would let a
    player deduce the answer without spending guesses.
    """
    if not q.strip():
        return []
    movies = movie_service.search_movies(db, q, limit=limit)
    return [movie.to_search_dict() for movie in movies]
