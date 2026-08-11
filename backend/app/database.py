"""Database engine and session management.

Tuned for serverless: on Vercel each function invocation may get a cold
container, so the engine uses ``NullPool`` against Supabase's own pooler
rather than keeping client-side connections that would be orphaned.
"""

from __future__ import annotations

from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.config import settings
from app.models.base import Base


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Create (once per process) the SQLAlchemy engine."""
    if settings.is_sqlite:
        return create_engine(
            settings.database_url,
            echo=settings.debug,
            # Serverless/threaded access to a file DB needs this off.
            connect_args={"check_same_thread": False},
        )

    return create_engine(
        settings.database_url,
        echo=settings.debug,
        # Supabase's transaction pooler already pools; a client-side pool
        # on top of it leaks connections across cold starts.
        poolclass=NullPool,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 10},
    )


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a request-scoped session."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def create_all() -> None:
    """Create tables if they do not exist.

    Used by the importer and the test suite. Production schema changes
    should go through the SQL migration in ``backend/sql/schema.sql``.
    """
    Base.metadata.create_all(bind=get_engine())
