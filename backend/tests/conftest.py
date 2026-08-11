"""Shared test fixtures.

Each test module gets its own throwaway SQLite database seeded with a
small, fully-controlled movie set, so assertions never depend on the real
scraped dataset.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(scope="session", autouse=True)
def _configure_env(tmp_path_factory: pytest.TempPathFactory) -> None:
    """Point the app at a temporary database before it is imported."""
    db_path = tmp_path_factory.mktemp("db") / "test.db"
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{db_path}"
    os.environ["ARCHIVE_START_DATE"] = "2026-01-01"
    os.environ["DAILY_SEED"] = "test-seed"


@pytest.fixture()
def db_session(_configure_env):
    """A clean database session with the schema created."""
    from app.database import create_all, get_engine, get_session_factory
    from app.models import Base

    engine = get_engine()
    Base.metadata.drop_all(bind=engine)
    create_all()

    session = get_session_factory()()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture()
def sample_movies(db_session):
    """Seed a handful of movies with known, contrasting attributes."""
    from app.models import Movie, MovieCast, MovieGenre

    definitions = [
        # (title, year, genres, cast, director, house, music, writer)
        ("Mystery Film", 2015, ["Action", "Drama"],
         ["Actor A", "Actor B", "Actor C"], "Director One", "House One",
         "Composer One", "Writer One"),
        ("Shares Cast And Year", 2015, ["Comedy"],
         ["Actor C", "Actor D"], "Director Two", "House Two",
         "Composer Two", "Writer Two"),
        ("Shares Director", 2010, ["Thriller"],
         ["Actor E"], "Director One", "House Three",
         "Composer Three", "Writer Three"),
        ("Shares Nothing", 2020, ["Horror"],
         ["Actor X", "Actor Y"], "Director Nine", "House Nine",
         "Composer Nine", "Writer Nine"),
        ("Sparse Film", 2008, [], [], None, None, None, None),
    ]

    created = []
    for title, year, genres, cast, director, house, music, writer in definitions:
        movie = Movie(
            title=title,
            normalized_title=title.lower(),
            year=year,
            language="Telugu",
            director=director,
            production_house=house,
            music_director=music,
            writer=writer,
            quality_score=8 if cast else 1,
            # Only the first film is a valid daily puzzle, which makes the
            # mystery movie deterministic for these tests.
            is_eligible=title == "Mystery Film",
        )
        db_session.add(movie)
        db_session.flush()

        for genre in genres:
            db_session.add(MovieGenre(movie_id=movie.id, genre=genre))
        for position, actor in enumerate(cast, start=1):
            db_session.add(
                MovieCast(movie_id=movie.id, actor_name=actor, cast_position=position)
            )
        created.append(movie)

    db_session.commit()
    return created


@pytest.fixture()
def client(db_session, sample_movies):
    """TestClient whose requests share the seeded database."""
    from fastapi.testclient import TestClient

    from app.database import get_db
    from app.main import app

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
