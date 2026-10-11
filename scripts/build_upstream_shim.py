"""Vendor the verbatim upstream Hermes host modules the tests may import into tests/upstream_shim/.

Usage: python scripts/build_upstream_shim.py <hermes checkout> [ref]   (default ref: upstream/main)

Copies gateway/session_context.py, tools/fuzzy_match.py, tools/file_tools_paths.py,
agent/runtime_self_protection.py and agent/runtime_cwd.py unchanged (Hermes is MIT licensed, see
tests/upstream_shim/NOTICE), plus a trimmed tools/environments/local.py holding the two names
file_tools_paths needs. Tests import host internals; the runtime never does outside hermes/host.py.
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

FILES = ("gateway/session_context.py", "tools/fuzzy_match.py", "tools/file_tools_paths.py",
         "agent/runtime_self_protection.py", "agent/runtime_cwd.py")
DEST = Path(__file__).resolve().parents[1] / "tests" / "upstream_shim"


def git(upstream: str, *args: str) -> str:
    return subprocess.run(["git", "-C", upstream, *args], capture_output=True, text=True, check=True).stdout


def main(upstream: str, ref: str = "upstream/main") -> None:
    for pkg in ("gateway", "tools", "tools/environments", "agent"):
        (DEST / pkg).mkdir(parents=True, exist_ok=True)
        (DEST / pkg / "__init__.py").write_text("", encoding="utf-8")
    for rel in FILES:
        (DEST / rel).write_text(git(upstream, "show", f"{ref}:{rel}"), encoding="utf-8")
    src = git(upstream, "show", f"{ref}:tools/environments/local.py")
    keep = [ast.get_source_segment(src, node) for node in ast.parse(src).body
            if (isinstance(node, ast.FunctionDef) and node.name == "_msys_to_windows_path")
            or (isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "_IS_WINDOWS" for t in node.targets))]
    if len(keep) != 2:
        raise SystemExit("upstream tools/environments/local.py changed shape")
    (DEST / "tools/environments/local.py").write_text(
        "import platform\nimport re\n\n" + "\n\n".join(keep) + "\n", encoding="utf-8")
    sha = git(upstream, "rev-parse", "--short", ref).strip()
    (DEST / "UPSTREAM.txt").write_text(f"{ref} {sha}\n", encoding="utf-8")
    (DEST / "NOTICE").write_text(
        "Verbatim copies of NousResearch/hermes-agent modules (MIT License, Copyright (c) 2025 Nous Research),\n"
        f"taken from {ref} at {sha} by scripts/build_upstream_shim.py. Used only by tests.\n", encoding="utf-8")
    print(f"vendored {ref} {sha} into {DEST}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
