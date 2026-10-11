#!/usr/bin/env bash
# Real install/list/doctor receipts in a fresh, retained evidence sandbox.
set -euo pipefail
exec python3 -B "$(dirname "$0")/sandbox_probe.py" install "${1:?usage: sandbox_install_load_check.sh <evidence-dir>}"
