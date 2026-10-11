#!/usr/bin/env bash
# Install Agent Mixer into a sandbox HERMES_HOME from the committed repo and
# record the load evidence. Usage:
#   bash scripts/sandbox_install_load_check.sh <evidence-dir>
# Writes <evidence-dir>/plugin-load.log and <evidence-dir>/hermes-version.txt.
# Never touches the real HOME or the live ~/.hermes.
set -uo pipefail

EVIDENCE="${1:?usage: sandbox_install_load_check.sh <evidence-dir>}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
HERMES_BIN="${HERMES_BIN:-/home/kensei/.local/bin/hermes}"

SBX="$EVIDENCE/s1-install"
rm -rf "$SBX"
mkdir -p "$SBX/home" "$SBX/hermes-home" "$SBX/tmp"

cat > "$SBX/hermes-home/config.yaml" <<'CFG'
plugins:
  enabled:
    - hermes-agent-mixer
  scan_on_install: false
CFG

export HOME="$SBX/home"
export HERMES_HOME="$SBX/hermes-home"
export TMPDIR="$SBX/tmp"
export GIT_CEILING_DIRECTORIES="$SBX/tmp"
export XDG_CONFIG_HOME="$HOME/.config"
export XDG_DATA_HOME="$HOME/.local/share"
export XDG_STATE_HOME="$HOME/.local/state"
export XDG_CACHE_HOME="$HOME/.cache"
unset DISPLAY WAYLAND_DISPLAY

LOG="$EVIDENCE/plugin-load.log"
{
  echo "# S1 plugin-load receipt - $(date -Is)"
  echo "# repo: $REPO"
  echo "# sandbox: HOME=$HOME HERMES_HOME=$HERMES_HOME"
  echo
  echo "## hermes --version"
} > "$LOG"

"$HERMES_BIN" --version >> "$LOG" 2>&1
"$HERMES_BIN" --version > "$EVIDENCE/hermes-version.txt" 2>&1

{
  echo
  echo "## hermes plugins install file://$REPO --enable --yes-deps"
} >> "$LOG"
"$HERMES_BIN" plugins install "file://$REPO" --enable --yes-deps >> "$LOG" 2>&1
echo "install exit=$?" >> "$LOG"

{
  echo
  echo "## hermes plugins list"
} >> "$LOG"
"$HERMES_BIN" plugins list >> "$LOG" 2>&1
echo "list exit=$?" >> "$LOG"

{
  echo
  echo "## hermes plugins doctor hermes-agent-mixer --ci"
} >> "$LOG"
"$HERMES_BIN" plugins doctor hermes-agent-mixer --ci >> "$LOG" 2>&1 || true
echo "doctor exit=$?" >> "$LOG"

echo "receipts: $LOG, $EVIDENCE/hermes-version.txt"
grep -c "hermes-agent-mixer" "$LOG"