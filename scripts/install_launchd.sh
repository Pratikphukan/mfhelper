#!/usr/bin/env bash
#
# Install the MFHelper launchd agent.
#
# Templates scripts/com.mfhelper.daily.plist with this project's absolute
# path, copies it into ~/Library/LaunchAgents, and loads it so the job
# fires every day at 10:30 AM local (IST) time.
#
# Re-run this whenever you move the project directory.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TEMPLATE_PLIST="$SCRIPT_DIR/com.mfhelper.daily.plist"
DEST_DIR="$HOME/Library/LaunchAgents"
DEST_PLIST="$DEST_DIR/com.mfhelper.daily.plist"
LABEL="com.mfhelper.daily"

if [[ ! -x "$PROJECT_ROOT/.venv/bin/python" ]]; then
  echo "Error: $PROJECT_ROOT/.venv/bin/python not found or not executable."
  echo "Create the venv and install deps first:"
  echo "    python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi

mkdir -p "$DEST_DIR"
mkdir -p "$PROJECT_ROOT/logs"

sed "s|__PROJECT_ROOT__|$PROJECT_ROOT|g" "$TEMPLATE_PLIST" > "$DEST_PLIST"
echo "Installed plist -> $DEST_PLIST"

if launchctl list | grep -q "$LABEL"; then
  echo "Unloading existing agent..."
  launchctl unload "$DEST_PLIST" 2>/dev/null || true
fi

echo "Loading agent..."
launchctl load "$DEST_PLIST"

echo ""
echo "Done. The job is scheduled daily at 10:30 AM local time."
echo "Verify with: launchctl list | grep $LABEL"
echo "Trigger a manual test: launchctl start $LABEL"
echo "Tail logs:    tail -f $PROJECT_ROOT/logs/stdout.log $PROJECT_ROOT/logs/stderr.log"
