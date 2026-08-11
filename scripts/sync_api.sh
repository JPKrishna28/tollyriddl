#!/usr/bin/env bash
# Sync backend/app -> api/app for the Vercel Python function.
#
# Why this exists: Vercel installs api/requirements.txt with the function
# directory as the working directory, so a relative path dependency
# ("../backend") cannot be resolved, and its dependency tracer cannot
# follow a runtime sys.path hack either. The application package must
# physically live under api/.
#
# backend/app remains the single source of truth. api/app is generated,
# and tests/test_api_sync.py fails the build if the two ever diverge.
#
# Usage:  ./scripts/sync_api.sh

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/backend/app"
DEST="$ROOT/api/app"

if [[ ! -d "$SRC" ]]; then
    echo "error: source package not found: $SRC" >&2
    exit 1
fi

rm -rf "$DEST"
mkdir -p "$DEST"

# Copy only Python sources; caches and test artefacts stay out of the
# serverless bundle.
(cd "$SRC" && find . -name '*.py' -print0 | while IFS= read -r -d '' f; do
    mkdir -p "$DEST/$(dirname "$f")"
    cp "$f" "$DEST/$f"
done)

count=$(find "$DEST" -name '*.py' | wc -l | tr -d ' ')
echo "Synced $count Python files: backend/app -> api/app"
