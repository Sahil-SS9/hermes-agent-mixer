"""New-dependency detection for manifests and install commands.

Manifest edits are judged by comparing dependency NAMES before and after
(bumps, removals and reorders pass; brand-new names trip the knob).
Install commands in terminal are classified as new deps or restoration.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import PurePosixPath

_MANIFEST_BASENAMES = {"package.json", "pyproject.toml", "cargo.toml", "go.mod"}

# Pip requirement line: name before any version/extra/whitespace.
_PIP_NAME_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
_PEP508_NAME_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)\s*[\[\(=>~<!; ]|$")

_GOMOD_SINGLE = re.compile(r"^\s*require\s+([^\s]+)\s+(v[\w.]+|-)")
_GOMOD_BLOCK_LINE = re.compile(r"^\s*([A-Za-z0-9][^\s/]*/[^\s]+)\s+(v[\w.]+|-)")


def detect_new_deps(path_name: str, before_text: str | None, after_text: str | None) -> list[str]:
    """Names of dependencies that appear after but not before. [] for non-manifests."""
    name = (path_name or "").replace("\\", "/").split("/")[-1].lower()
    before = _dep_names(name, before_text)
    after = _dep_names(name, after_text)
    if before is None or after is None:
        return []  # unparseable side: not judged (documented limit)
    return sorted(after - before)


def _dep_names(name: str, text: str | None) -> set[str] | None:
    if name == "package.json":
        return _package_json_names(text)
    if name == "pyproject.toml":
        return _pyproject_names(text)
    if name.startswith("requirements") and name.endswith(".txt"):
        return _requirements_names(text)
    if name == "cargo.toml":
        return _cargo_names(text)
    if name == "go.mod":
        return _gomod_names(text)
    return set()


def _require_parseable(text: str | None):
    if text is None:
        return {}  # nothing existed before: no baseline
    return None


def _package_json_names(text: str | None) -> set[str] | None:
    if text is None:
        return set()
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    names: set[str] = set()
    for section in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        block = data.get(section)
        if isinstance(block, dict):
            names.update(str(k) for k in block)
    return names


def _pyproject_names(text: str | None) -> set[str] | None:
    if text is None:
        return set()
    try:
        data = tomllib.loads(text)
    except (tomllib.TOMLDecodeError, UnicodeError):
        return None
    if not isinstance(data, dict):
        return None
    names: set[str] = set()
    project = data.get("project")
    if isinstance(project, dict):
        deps = project.get("dependencies")
        if isinstance(deps, list):
            names.update(_pep508_names(deps))
        optional = project.get("optional-dependencies")
        if isinstance(optional, dict):
            for group in optional.values():
                if isinstance(group, list):
                    names.update(_pep508_names(group))
    groups = data.get("dependency-groups")
    if isinstance(groups, dict):
        for group_deps in groups.values():
            if isinstance(group_deps, list):
                names.update(_pep508_names(group_deps))
    return names


def _pep508_names(items: list) -> set[str]:
    out: set[str] = set()
    for item in items:
        if isinstance(item, dict):  # uv-style {name = "x"} entries
            first = next(iter(item), None)
            if isinstance(first, str):
                out.add(first)
        elif isinstance(item, str):
            match = _PEP508_NAME_RE.match(item.strip())
            if match:
                out.add(match.group(1))
    return out


def _requirements_names(text: str | None) -> set[str] | None:
    if text is None:
        return set()
    names: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        match = _PIP_NAME_RE.match(line)
        if match:
            names.add(match.group(1).lower())
    return names


def _cargo_names(text: str | None) -> set[str] | None:
    if text is None:
        return set()
    try:
        data = tomllib.loads(text)
    except (tomllib.TOMLDecodeError, UnicodeError):
        return None
    if not isinstance(data, dict):
        return None
    names: set[str] = set()
    for section in ("dependencies", "dev-dependencies", "build-dependencies"):
        block = data.get(section)
        if isinstance(block, dict):
            names.update(str(k) for k in block)
    return names


def _gomod_names(text: str | None) -> set[str] | None:
    if text is None:
        return set()
    names: set[str] = set()
    in_block = False
    for raw in (text or "").splitlines():
        line = raw.rstrip()
        if line.strip().startswith("require ("):
            in_block = True
            continue
        if in_block:
            if line.strip() == ")":
                in_block = False
                continue
            match = _GOMOD_BLOCK_LINE.match(line)
            if match:
                names.add(match.group(1))
            continue
        match = _GOMOD_SINGLE.match(line)
        if match:
            names.add(match.group(1))
    return names


# -- install commands ---------------------------------------------------------


_PACKAGE_MANAGERS = {"npm", "pnpm", "yarn", "bun", "pip", "pip3", "uv", "poetry", "cargo", "go"}

_NPM_INSTALL_ALIASES = {"i", "install"}
_ADD_ALIASES = {"add"}


def _split(command: str) -> list[str]:
    import shlex

    try:
        return shlex.split(command or "")
    except ValueError:
        return (command or "").split()


def classify_install(command: str) -> tuple[str, list[str]] | None:
    """Classify a terminal segment: ("new", names) / ("restore", []) / None."""
    tokens = _split(command or "")
    if not tokens:
        return None
    program = tokens[0].rsplit("/", 1)[-1]
    if program not in _PACKAGE_MANAGERS:
        return None
    rest = tokens[1:]

    if program in ("npm", "pnpm", "bun", "yarn"):
        if not rest:
            # bare yarn runs `yarn install` (lockfile restore); bare npm/pnpm/bun need their verb
            return ("restore", []) if program == "yarn" else None
        verb = rest[0]
        packages = [t for t in rest[1:] if not t.startswith("-")]
        if program == "yarn":
            if verb == "add":
                return ("new", packages) if packages else ("restore", [])
            if verb in ("install",):
                return ("restore", [])
            if verb.startswith(("--",)) and packages:
                return ("new", packages)
            return None
        if verb in _ADD_ALIASES:
            return ("new", packages) if packages else None
        if verb in _NPM_INSTALL_ALIASES:
            return ("new", packages) if packages else ("restore", [])
        return None

    if program in ("pip", "pip3", "uv"):
        if program == "uv" and rest and rest[0] == "sync":
            return ("restore", [])
        # normalise "uv pip install X" to "pip install X"
        if program == "uv" and len(rest) >= 2 and rest[0] == "pip":
            rest = rest[1:]
        if not rest or rest[0] != "install":
            if program == "uv" and rest and rest[0] == "add":
                packages = [t for t in rest[1:] if not t.startswith("-")]
                return ("new", packages) if packages else None
            return None
        packages = []
        index = 1
        skip_file_req = False
        while index < len(rest):
            token = rest[index]
            if token.startswith("-"):
                if token in ("-r", "--requirement", "-c", "--constraint", "--index-url",
                             "-i", "--extra-index-url", "-f", "--find-links", "-e", "--editable", "--target", "-t"):
                    if token in ("-r", "--requirement", "-c", "--constraint"):
                        skip_file_req = True
                    index += 2
                    continue
                index += 1
                continue
            packages.append(_pip_name(token))
            index += 1
        if skip_file_req and not packages:
            return ("restore", [])
        return ("new", [p for p in packages if p]) if packages else None

    if program == "poetry":
        if rest and rest[0] == "add":
            packages = [t for t in rest[1:] if not t.startswith("-")]
            return ("new", packages) if packages else None
        if rest and rest[0] == "install":
            return ("restore", [])
        return None

    if program == "cargo":
        if rest and rest[0] == "add":
            packages = [t for t in rest[1:] if not t.startswith("-")]
            return ("new", packages) if packages else None
        return None

    if program == "go":
        if not rest or rest[0] != "get":
            return None
        modules = [t for t in rest[1:] if not t.startswith("-") and t != "./..." and t != "."]
        return ("new", modules) if modules else ("restore", [])

    return None


def _pip_name(token: str) -> str:
    match = _PEP508_NAME_RE.match(token.strip())
    return (match.group(1).lower() if match else token.strip().lower())