"""Vercel serverless entry point.

Vercel's Python runtime looks for an ASGI callable named ``app`` in this
file. The application package is vendored next to this file at
``api/app`` by ``scripts/sync_api.sh`` (backend/app is the source of
truth).

The runtime executes the function with the *repository root* on
``sys.path``, not this directory, so ``import app`` does not resolve on
its own -- it raises ModuleNotFoundError at cold start and every request
returns 500. Prepending this file's own directory fixes that. The
dependency tracer still bundles ``api/app`` because those modules sit
inside the function directory; the path entry only affects import
resolution at runtime, not what gets shipped.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from app.main import app  # noqa: E402  (import follows the sys.path fix)

__all__ = ["app"]
