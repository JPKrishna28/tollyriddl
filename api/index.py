"""Vercel serverless entry point.

Vercel's Python runtime looks for an ASGI callable named ``app`` in this
file. The real application lives in ``backend/app`` so it stays testable
and runnable with plain uvicorn locally.
"""

from __future__ import annotations

import sys
from pathlib import Path

# The backend package sits outside this directory in the deployment bundle.
BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.main import app  # noqa: E402

__all__ = ["app"]
