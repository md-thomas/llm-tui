#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "Installing llm-tui into $SCRIPT_DIR"

if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi

source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
deactivate

chmod -R a+rX .
chmod +x llm-tui.sh install.sh

echo "Done."
echo "Users can now run: $SCRIPT_DIR/llm-tui.sh"
echo "Tip: symlink it onto \$PATH, e.g. sudo ln -s $SCRIPT_DIR/llm-tui.sh /usr/local/bin/llm-tui"
