"""Movie search endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response
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


@router.get("/catalog")
def catalog(response: Response, db: Session = Depends(get_db)) -> dict:
    """The full guessable title list, fetched once and searched in the browser.

    This exists to kill the per-keystroke round trip, not to widen what the
    client knows: the payload carries exactly what `/search` already returns
    (id, title, year) plus the normalized title used for ranking. Cast and
    crew stay server-side, so the mystery movie is still only discoverable
    by spending a guess.

    Rows are arrays rather than objects -- with ~10k titles the repeated JSON
    keys would roughly double the transfer for no benefit.
    """
    rows = movie_service.list_catalog(db)
    # The catalogue only changes when the dataset is re-imported, so let the
    # browser and any CDN keep it for a day and revalidate in the background.
    response.headers["Cache-Control"] = "public, max-age=86400, stale-while-revalidate=604800"
    return {
        "version": settings.catalog_version,
        "movies": [[id_, title, normalized, year] for id_, title, normalized, year in rows],
    }
