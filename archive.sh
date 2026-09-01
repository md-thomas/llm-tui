#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

OUT_DIR="$SCRIPT_DIR/dist"
mkdir -p "$OUT_DIR"

OUT_FILE="$OUT_DIR/llm-tui-full.tar.gz"

tar -czf "$OUT_FILE" \
    --exclude='__pycache__' \
    --exclude='.git' \
    --exclude='.pytest_cache' \
    --exclude='.venv' \
    --exclude='dist' \
    --exclude='archive.sh' \
    -C "$SCRIPT_DIR/.." "$(basename "$SCRIPT_DIR")"

echo "Built $OUT_FILE"
