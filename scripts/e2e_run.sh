#!/usr/bin/env bash
# Real local-only chat; requires the host's actual write_file scope-block receipt.
set -euo pipefail
exec python3 -B "$(dirname "$0")/sandbox_probe.py" e2e "${1:?usage: e2e_run.sh <evidence-dir>}"
