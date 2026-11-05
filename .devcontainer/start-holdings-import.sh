#!/usr/bin/env bash
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
if pgrep -f '[u]vicorn mfhelper.holdings_import_app:app' >/dev/null 2>&1; then
  exit 0
fi
nohup python -m uvicorn mfhelper.holdings_import_app:app \
  --host 0.0.0.0 --port 8765 \
  >/tmp/mfhelper-holdings-import.log 2>&1 &
