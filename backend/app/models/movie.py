"""Movie catalogue models.

Multi-value attributes are split across child tables so they can be
indexed and joined. Cast keeps an explicit ``cast_position`` because
billing order is a real deduction signal in the game and must be stable.
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Movie(Base):
    __tablename__ = "movies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    # Punctuation/case-folded copy of the title, used for search and for
    # duplicate detection during import. Never displayed.
    normalized_title: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    year: Mapped[int | None] = mapped_column(Integer, index=True)
    language: Mapped[str] = mapped_column(String(64), default="Telugu", nullable=False)

    # Crew fields are pipe-joined strings: they are read as a unit and never
    # queried individually, so child tables would add joins for no benefit.
    director: Mapped[str | None] = mapped_column(Text)
    production_house: Mapped[str | None] = mapped_column(Text)
    music_director: Mapped[str | None] = mapped_column(Text)
    writer: Mapped[str | None] = mapped_column(Text)
    wikipedia_url: Mapped[str | None] = mapped_column(Text)

    # Precomputed at import time so daily selection does not recompute it
    # for every candidate on every request.
    quality_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False, index=True)
    is_eligible: Mapped[bool] = mapped_column(default=False, nullable=False, index=True)

    genres: Mapped[list["MovieGenre"]] = relationship(
        back_populates="movie", cascade="all, delete-orphan", lazy="selectin"
    )
    cast: Mapped[list["MovieCast"]] = relationship(
        back_populates="movie",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="MovieCast.cast_position",
    )

    __table_args__ = (
        # Same title in different years is a different film; the pair is unique.
        UniqueConstraint("normalized_title", "year", name="uq_movie_title_year"),
        Index("ix_movies_eligible_year", "is_eligible", "year"),
    )

    def genre_list(self) -> list[str]:
        return [row.genre for row in self.genres]

    def cast_list(self) -> list[str]:
        return [row.actor_name for row in sorted(self.cast, key=lambda c: c.cast_position)]

    def to_engine_dict(self) -> dict:
        """Shape expected by the comparison engine."""
        return {
            "movie_id": self.id,
            "movie_name": self.title,
            "year": self.year,
            "genre": self.genre_list(),
            "cast": self.cast_list(),
            "director": self.director or "",
            "production_house": self.production_house or "",
            "music_director": self.music_director or "",
            "writer": self.writer or "",
        }

    def to_public_dict(self) -> dict:
        """Full movie detail. Only sent once a game is over."""
        return {
            "id": self.id,
            "title": self.title,
            "year": self.year,
            "language": self.language,
            "genre": self.genre_list(),
            "cast": self.cast_list(),
            "director": _split(self.director),
            "production_house": _split(self.production_house),
            "music_director": _split(self.music_director),
            "writer": _split(self.writer),
            "wikipedia_url": self.wikipedia_url,
        }

    def to_search_dict(self) -> dict:
        """Lightweight shape for autocomplete.

        Deliberately excludes crew/cast: the search endpoint must not become
        a way to dump attributes of every candidate movie.
        """
        return {"id": self.id, "title": self.title, "year": self.year}


class MovieGenre(Base):
    __tablename__ = "movie_genres"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    movie_id: Mapped[int] = mapped_column(
        ForeignKey("movies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    genre: Mapped[str] = mapped_column(String(120), nullable=False, index=True)

    movie: Mapped[Movie] = relationship(back_populates="genres")

    __table_args__ = (
        UniqueConstraint("movie_id", "genre", name="uq_movie_genre"),
    )


class MovieCast(Base):
    __tablename__ = "movie_cast"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    movie_id: Mapped[int] = mapped_column(
        ForeignKey("movies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    actor_name: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    # 1-indexed billing order, preserved from the dataset.
    cast_position: Mapped[int] = mapped_column(Integer, nullable=False)

    movie: Mapped[Movie] = relationship(back_populates="cast")

    __table_args__ = (
        UniqueConstraint("movie_id", "cast_position", name="uq_movie_cast_position"),
        Index("ix_movie_cast_actor", "actor_name"),
    )


def _split(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split("|") if part.strip()]
