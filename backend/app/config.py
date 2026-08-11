"""Backend configuration, driven entirely by environment variables."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

# Load a local .env when present so `python scripts/import_movies.py` works
# without exporting variables by hand. On Vercel the platform injects real
# environment variables and no .env file exists, so this is a no-op there.
try:
    from dotenv import load_dotenv

    for _candidate in (
        Path(__file__).resolve().parents[2] / ".env",  # repository root
        Path(__file__).resolve().parents[1] / ".env",  # backend/
    ):
        if _candidate.exists():
            load_dotenv(_candidate, override=False)
            break
except ImportError:  # python-dotenv is optional
    pass


def _bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    """Runtime settings.

    ``DATABASE_URL`` points at Supabase in deployment. For serverless the
    *pooled* connection string (port 6543) is required -- the direct
    connection exhausts Postgres slots once functions scale out.
    """

    def __init__(self) -> None:
        self.database_url: str = _normalise_db_url(
            os.environ.get("DATABASE_URL", "sqlite+pysqlite:///./tollyriddl.db")
        )
        self.app_name: str = os.environ.get("APP_NAME", "Telugu Riddle")
        self.api_prefix: str = "/api"

        # Deterministic daily-puzzle seed. Changing it reshuffles the whole
        # schedule, so it stays fixed per deployment.
        self.daily_seed: str = os.environ.get("DAILY_SEED", "telugu-mystery")

        # Gameplay rules.
        self.base_attempts: int = int(os.environ.get("BASE_ATTEMPTS", "7"))
        self.bonus_attempts: int = int(os.environ.get("BONUS_ATTEMPTS", "3"))
        self.lifeline_1_after: int = int(os.environ.get("LIFELINE_1_AFTER", "4"))
        self.lifeline_2_after: int = int(os.environ.get("LIFELINE_2_AFTER", "6"))
        self.max_lifelines: int = 2

        # Daily-movie eligibility.
        self.min_quality_score: int = int(os.environ.get("MIN_QUALITY_SCORE", "6"))
        self.min_cast: int = int(os.environ.get("MIN_CAST", "2"))
        self.min_genres: int = int(os.environ.get("MIN_GENRES", "1"))

        # Earliest date an archive puzzle exists for.
        self.archive_start_date: str = os.environ.get(
            "ARCHIVE_START_DATE", "2026-01-01"
        )
        self.archive_max_days: int = int(os.environ.get("ARCHIVE_MAX_DAYS", "30"))

        self.cors_origins: list[str] = [
            origin.strip()
            for origin in os.environ.get("CORS_ORIGINS", "*").split(",")
            if origin.strip()
        ]
        self.debug: bool = _bool("DEBUG", False)
        self.search_limit: int = int(os.environ.get("SEARCH_LIMIT", "12"))

    @property
    def max_attempts(self) -> int:
        return self.base_attempts + self.bonus_attempts

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


def _normalise_db_url(url: str) -> str:
    """Normalise a database URL for SQLAlchemy 2.x + psycopg 3.

    Supabase hands out ``postgresql://`` (and some tools ``postgres://``);
    both must be steered to the psycopg driver explicitly.
    """
    url = url.strip()
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
