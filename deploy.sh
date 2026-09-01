#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PARENT_DIR="${1:-/opt}"
TARGET="$PARENT_DIR/llm-tui"

SUDO=""
if [ ! -w "$PARENT_DIR" ] 2>/dev/null || [ ! -e "$PARENT_DIR" ]; then
    SUDO="sudo"
fi

echo "Building tarball..."
./package.sh

echo "Deploying to $TARGET ..."
$SUDO mkdir -p "$PARENT_DIR"
$SUDO tar -xzf dist/llm-tui.tar.gz -C "$PARENT_DIR"

echo "Running install.sh in $TARGET ..."
$SUDO "$TARGET/install.sh"

echo
echo "Deployed to $TARGET"
echo "Run it with: $TARGET/llm-tui.sh"
