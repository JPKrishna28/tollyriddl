"""Vercel serverless entry point.

Vercel's Python runtime looks for an ASGI callable named ``app`` in this
file. The application itself lives in ``backend/app`` and is installed as
a package (see ``api/requirements.txt``), so it resolves as an ordinary
import here -- no sys.path manipulation, which Vercel's dependency tracer
cannot follow.
"""

from __future__ import annotations

from app.main import app

__all__ = ["app"]
