"""Guard against drift between backend/app and the vendored api/app.

The Vercel Python function cannot import backend/app directly: pip runs
with the function directory as its working directory (so a "../backend"
path dependency fails to resolve), and Vercel's dependency tracer cannot
follow a runtime sys.path hack. The package is therefore vendored into
api/app by scripts/sync_api.sh.

Duplicated code rots silently, so these tests fail the moment the copies
diverge -- catching "fixed it locally but deployed the old code" before
it reaches production.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "backend" / "app"
VENDORED = ROOT / "api" / "app"

SYNC_HINT = "Run ./scripts/sync_api.sh to regenerate api/app."


def python_files(base: Path) -> dict[str, Path]:
    """Map relative POSIX path -> file, for every .py under ``base``."""
    return {
        str(path.relative_to(base).as_posix()): path
        for path in base.rglob("*.py")
        if "__pycache__" not in path.parts
    }


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.skipif(not VENDORED.exists(), reason="api/app not generated yet")
class TestApiSync:
    def test_no_files_missing_from_vendored_copy(self) -> None:
        missing = sorted(set(python_files(SOURCE)) - set(python_files(VENDORED)))
        assert not missing, (
            f"api/app is missing {len(missing)} file(s): {missing[:5]}. {SYNC_HINT}"
        )

    def test_no_stale_files_in_vendored_copy(self) -> None:
        """A file deleted from backend/app must not linger in api/app."""
        stale = sorted(set(python_files(VENDORED)) - set(python_files(SOURCE)))
        assert not stale, (
            f"api/app has {len(stale)} stale file(s): {stale[:5]}. {SYNC_HINT}"
        )

    def test_file_contents_are_identical(self) -> None:
        source_files = python_files(SOURCE)
        vendored_files = python_files(VENDORED)

        differing = [
            name
            for name, path in sorted(source_files.items())
            if name in vendored_files and digest(path) != digest(vendored_files[name])
        ]
        assert not differing, (
            f"{len(differing)} file(s) differ between backend/app and api/app: "
            f"{differing[:5]}. {SYNC_HINT}"
        )

    def test_entry_point_imports_the_package_plainly(self) -> None:
        """api/index.py must not reintroduce a sys.path hack.

        Vercel's tracer cannot follow one, which is what caused the
        original all-routes-500 deployment failure.
        """
        entry = (ROOT / "api" / "index.py").read_text(encoding="utf-8")

        # Inspect executable code only -- the module docstring legitimately
        # *mentions* sys.path to explain why it is not used.
        code_lines = [
            line
            for line in entry.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        body = "\n".join(code_lines)
        marker = '"""'
        if body.count(marker) >= 2:
            body = body.split(marker, 2)[2]

        assert "sys.path" not in body, (
            "api/index.py must import app.main directly; a sys.path hack is "
            "invisible to Vercel's dependency tracer."
        )
        assert "from app.main import app" in entry
