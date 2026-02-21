#!/usr/bin/env bash
# Re-sync venv dependencies with pyproject.toml
set -e
VENV="$(dirname "$0")/venv"
if [ ! -d "$VENV" ]; then
    echo "Creating venv..."
    python3 -m venv "$VENV"
fi
echo "Syncing dependencies..."
"$VENV/bin/pip" install -e "$(dirname "$0")" --quiet
echo "Done. Restart Claude Desktop to pick up changes."
