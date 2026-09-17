#!/bin/bash
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR"

python3 -m pip install --quiet -e ".[dev]" --ignore-installed

echo 'export PYTHONPATH=.' >> "$CLAUDE_ENV_FILE"
