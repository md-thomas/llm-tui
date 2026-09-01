#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

OUT_DIR="$SCRIPT_DIR/dist"
STAGE="$(mktemp -d)/llm-tui"

mkdir -p "$OUT_DIR" "$STAGE"

cp app.py commands.py config.py llm_client.py main.py paths.py tools.py version.py \
   requirements.txt README.md config.yaml system_prompt.txt help.txt \
   llm-tui.sh install.sh deploy.sh package.sh .env.example \
   "$STAGE/"

mkdir -p "$STAGE/widgets" "$STAGE/css" "$STAGE/personas"
cp widgets/chat_history.py widgets/chat_input.py widgets/spinner.py widgets/status_bar.py widgets/tool_confirm.py "$STAGE/widgets/"
cp css/app.tcss "$STAGE/css/"
cp personas/*.yaml personas/*.txt "$STAGE/personas/"

chmod +x "$STAGE/llm-tui.sh" "$STAGE/install.sh"

tar -czf "$OUT_DIR/llm-tui.tar.gz" -C "$(dirname "$STAGE")" llm-tui
rm -rf "$(dirname "$STAGE")"

echo "Built $OUT_DIR/llm-tui.tar.gz"
echo "Install with: sudo tar -xzf dist/llm-tui.tar.gz -C /opt && sudo /opt/llm-tui/install.sh"
