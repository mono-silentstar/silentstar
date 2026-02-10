#!/usr/bin/env bash
# Start the silentstar bridge worker.
# Run from anywhere — it finds its own way home.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "starting silentstar worker..."
python3 worker/worker.py --config worker/config.json
