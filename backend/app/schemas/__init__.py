"""Pydantic request/response schemas."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class MovieSearchItem(BaseModel):
    """Autocomplete result. Deliberately minimal -- see movie_service."""

    id: int
    title: str
    year: int | None = None


class StartGameRequest(BaseModel):
    game_date: date | None = Field(
        default=None,
        description="Puzzle date (defaults to today). Future dates are rejected.",
    )
    client_date: date | None = Field(
        default=None,
        description="The player's local date, used to decide what 'today' is.",
    )


class GuessRequest(BaseModel):
    """Only an id crosses the wire -- the server resolves everything else."""

    guess_movie_id: int = Field(..., ge=1)


class LifelineRequest(BaseModel):
    attribute: str = Field(..., min_length=1, max_length=64)


class ErrorResponse(BaseModel):
    detail: str
    code: str
