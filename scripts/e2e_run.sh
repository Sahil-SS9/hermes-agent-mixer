#!/usr/bin/env bash
# End-to-end check: real hermes chat -q against the local OpenAI-compatible
# server (127.0.0.1:8091/v1, model "auto"), with the plugin installed and the
# plugin config defaults set to scope: ["src/**"]. The write_file for
# notes.txt (project root) must be blocked with the Mixer scope message.
# Usage: bash scripts/e2e_run.sh <evidence-dir>
# Writes <evidence-dir>/e2e.log, last line E2E PASS on success.
set -uo pipefail

EVIDENCE="${1:?usage: e2e_run.sh <evidence-dir>}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
HERMES_BIN="${HERMES_BIN:-/home/kensei/.local/bin/hermes}"
BASE_URL="${MIXER_E2E_BASE_URL:-http://127.0.0.1:8091/v1}"
MODEL="${MIXER_E2E_MODEL:-auto}"

SBX="$EVIDENCE/e2e-sandbox"
rm -rf "$SBX"
mkdir -p "$SBX/home" "$SBX/hermes-home" "$SBX/tmp" "$SBX/project/src"

cat > "$SBX/hermes-home/config.yaml" <<CFG
model:
  provider: custom
  default: $MODEL
  base_url: $BASE_URL
plugins:
  enabled:
    - hermes-agent-mixer
  scan_on_install: false
  entries:
    hermes-agent-mixer:
      settings:
        edits: auto
        scope: ["src/**"]
        lines: "off"
        deps: ask
CFG

FIXTURE="$SBX/e2e-fixture-repo"
mkdir -p "$FIXTURE"
tar --exclude=.git --exclude=.venv --exclude=__pycache__ --exclude=.pytest_cache \
    -cf - -C "$REPO" . | tar -xf - -C "$FIXTURE"
git -C "$FIXTURE" init -q
git -C "$FIXTURE" add -A
git -C "$FIXTURE" -c user.email=e@l -c user.name=e commit -qm fixture

export HOME="$SBX/home"
export HERMES_HOME="$SBX/hermes-home"
export TMPDIR="$SBX/tmp"
export GIT_CEILING_DIRECTORIES="$SBX/tmp"
export XDG_CONFIG_HOME="$HOME/.config"
export XDG_DATA_HOME="$HOME/.local/share"
export XDG_STATE_HOME="$HOME/.local/state"
export XDG_CACHE_HOME="$HOME/.cache"
unset DISPLAY WAYLAND_DISPLAY

LOG="$EVIDENCE/e2e.log"
{
  echo "# Agent Mixer E2E - $(date -Is)"
  echo "# model endpoint: $BASE_URL (model: $MODEL), local only"
  echo "# sandbox: HOME=$HOME HERMES_HOME=$HERMES_HOME project=$SBX/project"
  echo
} > "$LOG"

"$HERMES_BIN" plugins install "file://$FIXTURE" --enable --yes-deps >> "$LOG" 2>&1
echo "install exit=$?" >> "$LOG"

( cd "$SBX/project" && "$HERMES_BIN" chat -q "Create notes.txt in the project root containing hi" --max-turns 6 ) >> "$LOG" 2>&1
CHAT_EXIT=$?
echo "chat exit=$CHAT_EXIT" >> "$LOG"

# The TUI hides the tool-result JSON; the host's own agent.log records exactly
# what the tool returned to the model. Pull that line as evidence.
{
  echo ""
  echo "## tool result delivered to the model (from the sandbox agent.log)"
  grep -h "returned error" "$HERMES_HOME/logs/agent.log" 2>/dev/null | grep "blocked by mixer:" || true
} >> "$LOG"

if [ -f "$SBX/project/notes.txt" ]; then
  echo "note: notes.txt exists after the run (terminal write; the documented Not-a-sandbox gap)" >> "$LOG"
  echo "content: $(cat "$SBX/project/notes.txt" 2>/dev/null | head -1)" >> "$LOG"
fi

if grep -q "blocked by mixer:scope" "$LOG"; then
  echo "E2E PASS (write_file blocked with the Mixer scope message; any terminal workaround is the documented Not-a-sandbox gap)" >> "$LOG"
  exit 0
fi
echo "E2E FAIL (no Mixer scope block found in the transcript)" >> "$LOG"
exit 1