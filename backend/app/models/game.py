"""Game state models.

``DailyGame`` pins one mystery movie per calendar date, so every player who
opens the app on the same day gets the same puzzle. ``GameSession`` is one
player's attempt at that puzzle.

The mystery movie id lives only here, server-side. It is never serialised
into any response while a session is active.
"""

from __future__ import annotations

import enum
from datetime import date, datetime, timezone

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class GameStatus(str, enum.Enum):
    ACTIVE = "active"
    WON = "won"
    LOST = "lost"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DailyGame(Base):
    __tablename__ = "daily_games"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_date: Mapped[date] = mapped_column(Date, nullable=False, unique=True, index=True)
    mystery_movie_id: Mapped[int] = mapped_column(
        ForeignKey("movies.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    sessions: Mapped[list["GameSession"]] = relationship(back_populates="daily_game")


class GameSession(Base):
    __tablename__ = "game_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    daily_game_id: Mapped[int] = mapped_column(
        ForeignKey("daily_games.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[GameStatus] = mapped_column(
        String(16), default=GameStatus.ACTIVE, nullable=False, index=True
    )
    attempts_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    bonus_unlocked: Mapped[bool] = mapped_column(default=False, nullable=False)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    daily_game: Mapped[DailyGame] = relationship(back_populates="sessions")
    guesses: Mapped[list["Guess"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="Guess.attempt_number",
    )
    lifelines: Mapped[list["Lifeline"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="Lifeline.lifeline_number",
    )

    @property
    def is_active(self) -> bool:
        return self.status == GameStatus.ACTIVE

    def duration_seconds(self) -> int | None:
        if not self.completed_at:
            return None
        started = self.started_at
        # SQLite round-trips naive datetimes; assume UTC so the subtraction
        # never raises on a mixed-awareness pair.
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        completed = self.completed_at
        if completed.tzinfo is None:
            completed = completed.replace(tzinfo=timezone.utc)
        return max(0, int((completed - started).total_seconds()))


class Guess(Base):
    __tablename__ = "guesses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_session_id: Mapped[str] = mapped_column(
        ForeignKey("game_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    movie_id: Mapped[int] = mapped_column(
        ForeignKey("movies.id", ondelete="RESTRICT"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    session: Mapped[GameSession] = relationship(back_populates="guesses")

    __table_args__ = (
        # Enforces "no duplicate guesses" at the database level, not just in
        # application code.
        UniqueConstraint("game_session_id", "movie_id", name="uq_guess_session_movie"),
        UniqueConstraint(
            "game_session_id", "attempt_number", name="uq_guess_session_attempt"
        ),
        Index("ix_guess_session_attempt", "game_session_id", "attempt_number"),
    )


class Lifeline(Base):
    __tablename__ = "lifelines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_session_id: Mapped[str] = mapped_column(
        ForeignKey("game_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    lifeline_number: Mapped[int] = mapped_column(Integer, nullable=False)
    attribute: Mapped[str] = mapped_column(String(64), nullable=False)
    # Which slot of a multi-valued attribute this bought. A lifeline reveals
    # one cell, not a whole row, so "cast" can be spent more than once and
    # each spend must record *which* actor it uncovered.
    value_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    session: Mapped[GameSession] = relationship(back_populates="lifelines")

    __table_args__ = (
        # A given lifeline slot can only be spent once.
        UniqueConstraint(
            "game_session_id", "lifeline_number", name="uq_lifeline_session_number"
        ),
        # The same cell cannot be bought twice. Scoped to the slot rather
        # than the attribute, so a second lifeline may still target another
        # cell in the same row.
        UniqueConstraint(
            "game_session_id",
            "attribute",
            "value_index",
            name="uq_lifeline_session_attribute_index",
        ),
    )
