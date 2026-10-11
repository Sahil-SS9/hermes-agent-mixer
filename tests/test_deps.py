"""Tests for the new-dependency guard: manifests, install commands, false-positive guards."""

from __future__ import annotations

import json

from hermes_agent_mixer.core import depsguard, decisions


def _knobs(deps="ask", edits="auto"):
    return {"edits": edits, "scope": [], "lines": "off", "deps": deps, "root": None}


def _state():
    from hermes_agent_mixer.core import mixer as mixer_mod

    return mixer_mod.Mixer()


# -- manifest detection primitives -------------------------------------------


def test_package_json_new_dep_detected():
    before = json.dumps({"dependencies": {"react": "^18"}})
    after = json.dumps({"dependencies": {"react": "^18", "lodash": "^4"}})
    assert depsguard.detect_new_deps("package.json", before, after) == ["lodash"]


def test_package_json_version_bump_allowed():
    before = json.dumps({"dependencies": {"react": "^18"}})
    after = json.dumps({"dependencies": {"react": "^19"}})
    assert depsguard.detect_new_deps("package.json", before, after) == []


def test_package_json_removal_allowed():
    before = json.dumps({"dependencies": {"react": "^18", "lodash": "^4"}})
    after = json.dumps({"dependencies": {"lodash": "^4"}})
    assert depsguard.detect_new_deps("package.json", before, after) == []


def test_package_json_reorder_allowed():
    before = json.dumps({"dependencies": {"react": "^18", "lodash": "^4"}})
    after = json.dumps({"dependencies": {"lodash": "^4", "react": "^18"}})
    assert depsguard.detect_new_deps("package.json", before, after) == []


def test_package_json_dev_and_peer_deps_watched():
    before = json.dumps({})
    after = json.dumps({"devDependencies": {"vitest": "^2"}, "peerDependencies": {"axios": "^1"}})
    assert sorted(depsguard.detect_new_deps("package.json", before, after)) == ["axios", "vitest"]


def test_pyproject_new_dep_detected():
    before = "[project]\nname = 'x'\ndependencies = ['rich>=13']\n"
    after = "[project]\nname = 'x'\ndependencies = ['rich>=13', 'httpx>=0.27']\n"
    assert depsguard.detect_new_deps("pyproject.toml", before, after) == ["httpx"]


def test_pyproject_bump_allowed():
    before = "[project]\ndependencies = ['rich>=13']\n"
    after = "[project]\ndependencies = ['rich>=14']\n"
    assert depsguard.detect_new_deps("pyproject.toml", before, after) == []


def test_pyproject_optional_dependencies_watched():
    before = "[project]\noptional-dependencies = {}\n"
    after = "[project]\noptional-dependencies = { plot = ['matplotlib>=3'] }\n"
    assert depsguard.detect_new_deps("pyproject.toml", before, after) == ["matplotlib"]


def test_pyproject_dependency_groups_watched():
    before = "[dependency-groups]\ndev = ['pytest>=8']\n"
    after = "[dependency-groups]\ndev = ['pytest>=8', 'mypy>=1']\n"
    assert depsguard.detect_new_deps("pyproject.toml", before, after) == ["mypy"]


def test_requirements_txt_new_dep_detected():
    before = "rich>=13\n# comment\n"
    after = "rich>=13\nhttpx>=0.27\n"
    assert depsguard.detect_new_deps("requirements-dev.txt", before, after) == ["httpx"]


def test_requirements_txt_removal_and_edit_allowed():
    before = "rich>=13\nhttpx>=0.27\n"
    after = "httpx>=0.27\n"
    assert depsguard.detect_new_deps("requirements.txt", before, after) == []


def test_cargo_new_dep_detected():
    before = "[dependencies]\nserde = \"1\"\n"
    after = "[dependencies]\nserde = \"1\"\ntokio = \"1\"\n"
    assert depsguard.detect_new_deps("Cargo.toml", before, after) == ["tokio"]


def test_cargo_dev_deps_watched_and_bump_allowed():
    before = "[dev-dependencies]\nserde = \"1\"\n"
    after = "[dev-dependencies]\nserde = \"1.0.5\"\n"
    assert depsguard.detect_new_deps("Cargo.toml", before, after) == []


def test_gomod_new_require_detected():
    before = "module example.com/m\n\ngo 1.22\n"
    after = "module example.com/m\n\ngo 1.22\n\nrequire github.com/x/y v1.2.3\n"
    assert depsguard.detect_new_deps("go.mod", before, after) == ["github.com/x/y"]


def test_gomod_removal_allowed():
    before = "require (\n\tgithub.com/x/y v1.2.3\n\tgithub.com/a/b v0.1.0\n)\n"
    after = "require (\n\tgithub.com/x/y v1.2.3\n)\n"
    assert depsguard.detect_new_deps("go.mod", before, after) == []


def test_unparseable_after_is_not_judged():
    """A half-written manifest mid-patch is not a new-dep verdict (documented limit)."""
    assert depsguard.detect_new_deps("pyproject.toml", "[project]\ndependencies=[]\n", "[proj") == []


def test_non_manifest_paths_are_ignored():
    assert depsguard.detect_new_deps("notes.md", "a", "b\nhttpx\n") == []


# -- install command classification ------------------------------------------


def test_npm_install_pkg_is_new():
    assert depsguard.classify_install("npm install react") == ("new", ["react"])
    assert depsguard.classify_install("pnpm add react lodash") == ("new", ["react", "lodash"])
    assert depsguard.classify_install("bun add axios") == ("new", ["axios"])
    assert depsguard.classify_install("npm i react --save-dev") == ("new", ["react"])


def test_bare_install_commands_restore():
    assert depsguard.classify_install("npm install") == ("restore", [])
    assert depsguard.classify_install("pnpm i") == ("restore", [])
    assert depsguard.classify_install("bun install") == ("restore", [])
    assert depsguard.classify_install("yarn") == ("restore", [])
    assert depsguard.classify_install("yarn install") == ("restore", [])
    assert depsguard.classify_install("uv sync") == ("restore", [])
    assert depsguard.classify_install("poetry install") == ("restore", [])
    assert depsguard.classify_install("pip install -r requirements.txt") == ("restore", [])
    assert depsguard.classify_install("uv pip install -r requirements.txt") == ("restore", [])
    assert depsguard.classify_install("go get ./...") == ("restore", [])


def test_pip_uv_add_commands_are_new():
    assert depsguard.classify_install("pip install httpx") == ("new", ["httpx"])
    assert depsguard.classify_install("pip3 install requests urllib3") == ("new", ["requests", "urllib3"])
    assert depsguard.classify_install("uv pip install --upgrade httpx") == ("new", ["httpx"])
    assert depsguard.classify_install("uv add httpx") == ("new", ["httpx"])
    assert depsguard.classify_install("poetry add httpx") == ("new", ["httpx"])
    assert depsguard.classify_install("cargo add tokio") == ("new", ["tokio"])
    assert depsguard.classify_install("go get github.com/x/y") == ("new", ["github.com/x/y"])


def test_non_install_commands_ignored():
    assert depsguard.classify_install("npm test") is None
    assert depsguard.classify_install("git status") is None
    assert depsguard.classify_install("ls -la") is None
    assert depsguard.classify_install("npm run build") is None


def test_flag_only_pip_install_is_restore():
    assert depsguard.classify_install("pip install -U") in (None, ("restore", []))


# -- integration through the decision engine ---------------------------------


def test_manifest_write_new_dep_asks(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    decision = decisions.evaluate(
        "write_file",
        {"path": "package.json", "content": json.dumps({"dependencies": {"lodash": "^4"}})},
        _knobs(deps="ask"),
        _state(),
        root=tmp_path,
    )
    assert decision is not None
    assert decision["action"] == "approve"
    assert decision["rule_key"] == "mixer:deps"
    assert "lodash" in decision["message"]


def test_manifest_write_new_dep_block(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    decision = decisions.evaluate(
        "write_file",
        {"path": "package.json", "content": json.dumps({"dependencies": {"lodash": "^4"}})},
        _knobs(deps="block"),
        _state(),
        root=tmp_path,
    )
    assert decision is not None
    assert decision["action"] == "block"
    assert "lodash" in decision["message"]


def test_manifest_write_new_dep_allow(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    decision = decisions.evaluate(
        "write_file",
        {"path": "package.json", "content": json.dumps({"dependencies": {"lodash": "^4"}})},
        _knobs(deps="allow"),
        _state(),
        root=tmp_path,
    )
    assert decision is None


def test_manifest_patch_new_dep_asks(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text("[project]\ndependencies = ['rich>=13']\n", encoding="utf-8")
    decision = decisions.evaluate(
        "patch",
        {"path": "pyproject.toml", "old_string": "dependencies = ['rich>=13']", "new_string": "dependencies = ['rich>=13', 'httpx>=0.27']"},
        _knobs(deps="ask"),
        _state(),
        root=tmp_path,
    )
    assert decision is not None
    assert decision["action"] == "approve"
    assert "httpx" in decision["message"]


def test_manifest_version_bump_passes_through(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "requirements.txt").write_text("rich>=13\n", encoding="utf-8")
    decision = decisions.evaluate(
        "write_file",
        {"path": "requirements.txt", "content": "rich>=14\n"},
        _knobs(deps="block"),
        _state(),
        root=tmp_path,
    )
    assert decision is None


def test_new_requirements_file_is_a_new_dep(tmp_path, monkeypatch):
    """A dependency file created from nothing introduces new deps (block/ask applies)."""
    monkeypatch.chdir(tmp_path)
    decision = decisions.evaluate(
        "write_file",
        {"path": "requirements.txt", "content": "rich>=13\n"},
        _knobs(deps="block"),
        _state(),
        root=tmp_path,
    )
    assert decision is not None
    assert decision["action"] == "block"


def test_terminal_install_command_blocked_on_deps(tmp_path, monkeypatch):
    decision = decisions.evaluate(
        "terminal", {"command": "npm install lodash"}, _knobs(deps="block"), _state(), root=tmp_path
    )
    assert decision is not None
    assert decision["action"] == "block"


def test_terminal_install_command_asks_on_deps(tmp_path, monkeypatch):
    decision = decisions.evaluate(
        "terminal", {"command": "uv add httpx"}, _knobs(deps="ask"), _state(), root=tmp_path
    )
    assert decision is not None
    assert decision["action"] == "approve"
    assert decision["rule_key"] == "mixer:deps"


def test_terminal_bare_install_allowed_on_deps_block(tmp_path, monkeypatch):
    decision = decisions.evaluate(
        "terminal", {"command": "npm install && npm test"}, _knobs(deps="block"), _state(), root=tmp_path
    )
    assert decision is None


def test_terminal_uv_sync_allowed_on_deps_block(tmp_path, monkeypatch):
    decision = decisions.evaluate(
        "terminal", {"command": "uv sync"}, _knobs(deps="block"), _state(), root=tmp_path
    )
    assert decision is None


def test_terminal_second_segment_install_still_caught(tmp_path, monkeypatch):
    decision = decisions.evaluate(
        "terminal", {"command": "git status && npm install lodash"}, _knobs(deps="block"), _state(), root=tmp_path
    )
    assert decision is not None
    assert "lodash" in decision["message"]


def test_deps_stage_runs_after_scope(tmp_path, monkeypatch, tmp_path_factory):
    """A scope-blocked manifest edit must not trigger the deps ask."""
    monkeypatch.chdir(tmp_path)
    outside = tmp_path_factory.mktemp("deps-out")
    decision = decisions.evaluate(
        "write_file",
        {"path": str(outside / "package.json"), "content": json.dumps({"dependencies": {"lodash": "^4"}})},
        _knobs(deps="ask"),
        _state(),
        root=tmp_path,
    )
    assert decision is not None
    assert decision["action"] == "block"
    assert "scope" in decision["message"]


def test_deps_stage_runs_before_ask(tmp_path, monkeypatch):
    """deps ask wins over the edits ask (earlier stage)."""
    monkeypatch.chdir(tmp_path)
    decision = decisions.evaluate(
        "write_file",
        {"path": "package.json", "content": json.dumps({"dependencies": {"lodash": "^4"}})},
        _knobs(deps="ask", edits="ask"),
        _state(),
        root=tmp_path,
    )
    assert decision["rule_key"] == "mixer:deps"


def test_dep_manifest_outside_root_still_checked_needs_scope(tmp_path, monkeypatch, tmp_path_factory):
    monkeypatch.chdir(tmp_path)
    decision = decisions.evaluate(
        "write_file",
        {"path": str(tmp_path_factory.mktemp("out") / "package.json"), "content": "{}"},
        _knobs(deps="block"),
        _state(),
        root=tmp_path,
    )
    assert decision is not None
    assert decision["action"] == "block"