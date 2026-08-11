"""Optional TMDB enrichment.

Wikipedia stays the primary source. This module only fills fields the
Wikipedia pass left empty, and it is inert unless a TMDB API key is
present, so the scraper is fully functional without it:

    Wikipedia -> base dataset -> [optional TMDB] -> validation -> output

Enable with ``--enrich-tmdb`` and ``TMDB_API_KEY`` in the environment.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import requests

from config.settings import settings
from scraper.cleaner import dedupe_preserving_order, normalise_key
from scraper.extractor import MovieRecord

logger = logging.getLogger(__name__)

TMDB_BASE = "https://api.themoviedb.org/3"
# TMDB's documented ceiling is ~50 req/s; this is far below it.
TMDB_MIN_DELAY = 0.3


class TMDBUnavailable(RuntimeError):
    """Raised when TMDB enrichment is requested without credentials."""


@dataclass
class TMDBConfig:
    api_key: str
    language: str = "en-US"
    timeout: int = 20
    max_cast: int = 10


class TMDBClient:
    """Minimal TMDB client covering search + credits."""

    def __init__(self, config: TMDBConfig | None = None) -> None:
        api_key = (config.api_key if config else None) or settings.tmdb_api_key
        if not api_key:
            raise TMDBUnavailable(
                "TMDB enrichment requires TMDB_API_KEY; "
                "the Wikipedia pipeline works without it."
            )
        self.config = config or TMDBConfig(api_key=api_key)
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": settings.user_agent})
        self._last_request = 0.0
        self.stats = {"searches": 0, "hits": 0, "misses": 0, "errors": 0}

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if self._last_request and elapsed < TMDB_MIN_DELAY:
            time.sleep(TMDB_MIN_DELAY - elapsed)
        self._last_request = time.monotonic()

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any] | None:
        self._throttle()
        query = {"api_key": self.config.api_key, "language": self.config.language}
        query.update(params)
        try:
            response = self.session.get(
                f"{TMDB_BASE}{path}", params=query, timeout=self.config.timeout
            )
            if response.status_code == 429:
                retry_after = float(response.headers.get("Retry-After", "2"))
                logger.warning("TMDB rate limited; sleeping %.1fs", retry_after)
                time.sleep(retry_after)
                return self._get(path, params)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            self.stats["errors"] += 1
            logger.warning("TMDB request failed for %s: %s", path, exc)
            return None

    def find_movie(self, title: str, year: int | None) -> dict[str, Any] | None:
        """Search TMDB for a film, requiring a confident title match."""
        self.stats["searches"] += 1
        params: dict[str, Any] = {"query": title, "include_adult": "false"}
        if year:
            params["year"] = year

        payload = self._get("/search/movie", params)
        if not payload or not payload.get("results"):
            self.stats["misses"] += 1
            return None

        wanted = normalise_key(title)
        for result in payload["results"]:
            for key in ("title", "original_title"):
                if normalise_key(result.get(key, "")) == wanted:
                    self.stats["hits"] += 1
                    return result

        self.stats["misses"] += 1
        return None

    def get_credits(self, movie_id: int) -> dict[str, Any] | None:
        return self._get(f"/movie/{movie_id}/credits", {})


def enrich_record(record: MovieRecord, client: TMDBClient) -> MovieRecord:
    """Fill only the gaps Wikipedia left, never overwrite scraped values."""
    match = client.find_movie(record.movie_name, record.year)
    if not match:
        return record

    filled: list[str] = []
    credits = client.get_credits(match["id"]) or {}

    if not record.cast:
        cast = [
            member.get("name", "")
            for member in credits.get("cast", [])[: client.config.max_cast]
        ]
        cast = dedupe_preserving_order([name for name in cast if name])
        if cast:
            record.cast = cast
            filled.append("cast")

    crew = credits.get("crew", [])

    if not record.director:
        directors = dedupe_preserving_order(
            [m.get("name", "") for m in crew if m.get("job") == "Director"]
        )
        if directors:
            record.director = directors
            filled.append("director")

    if not record.writer:
        writers = dedupe_preserving_order(
            [
                m.get("name", "")
                for m in crew
                if m.get("job") in {"Writer", "Screenplay", "Story"}
            ]
        )
        if writers:
            record.writer = writers
            filled.append("writer")

    if not record.music_director:
        composers = dedupe_preserving_order(
            [m.get("name", "") for m in crew if m.get("job") == "Original Music Composer"]
        )
        if composers:
            record.music_director = composers
            filled.append("music_director")

    if not record.genre:
        genres = dedupe_preserving_order(
            [g.get("name", "") for g in match.get("genres", [])]
        )
        if genres:
            record.genre = genres
            filled.append("genre")

    if filled:
        record.enrichment_sources.append("tmdb")
        record.notes.append(f"TMDB filled: {', '.join(filled)}")
        logger.debug("TMDB enriched %s: %s", record.movie_name, filled)

    return record


def enrich_records(records: list[MovieRecord]) -> list[MovieRecord]:
    """Enrich a batch; returns the input unchanged when TMDB is unavailable."""
    try:
        client = TMDBClient()
    except TMDBUnavailable as exc:
        logger.warning("Skipping TMDB enrichment: %s", exc)
        return records

    for record in records:
        try:
            enrich_record(record, client)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("TMDB enrichment failed for %s: %s", record.movie_name, exc)

    logger.info("TMDB stats: %s", client.stats)
    return records
