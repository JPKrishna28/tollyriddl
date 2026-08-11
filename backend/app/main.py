"""FastAPI application entry point."""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.requests import Request

from app.api import games, health, movies
from app.config import settings

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = FastAPI(
    title=settings.app_name,
    description=(
        "Guess the hidden Telugu movie in 7 attempts. "
        "The mystery movie is resolved server-side and never sent to the "
        "browser while a game is in progress."
    ),
    version="1.0.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix=settings.api_prefix)
app.include_router(movies.router, prefix=settings.api_prefix)
app.include_router(games.router, prefix=settings.api_prefix)


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    """Turn stray ValueErrors into a structured 400 rather than a 500."""
    return JSONResponse(
        status_code=400, content={"detail": str(exc), "code": "invalid_input"}
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Log the traceback before returning 500.

    Without this, an unexpected error propagates into the serverless
    runtime and the platform logs only the bare status line -- the
    traceback is lost, which makes production 500s undiagnosable.
    """
    logging.getLogger("app").exception(
        "Unhandled error on %s %s", request.method, request.url.path
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error.", "code": "internal_error"},
    )


@app.get("/api")
def api_root() -> dict:
    return {
        "name": settings.app_name,
        "version": "1.0.0",
        "docs": "/api/docs",
    }
