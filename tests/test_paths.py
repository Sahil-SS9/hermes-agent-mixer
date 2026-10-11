"""Paths and scope (B3, B5, QW9, D3): the host resolves the target, an empty scope means no limit,
relative globs anchor at the workspace root, absolute globs match anywhere, Windows follows ntpath."""
from __future__ import annotations

import pytest

from tests.helpers import action, run, write


@pytest.fixture
def proj(tmp_path):
    p = tmp_path / "proj"
    (p / "src").mkdir(parents=True)
    other = tmp_path / "elsewhere"
    other.mkdir()
    return p


def test_empty_scope_means_no_restriction(proj, tmp_path):
    for target in (proj / "src" / "a.py", tmp_path / "scratch.txt", "/tmp/mixer-x.txt", "notes.txt"):
        assert action(run(write(target), root=proj)) == "allow", target


def test_relative_glob_anchors_at_the_workspace_root_not_the_process_cwd(proj, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    scope = ["src/**"]
    assert action(run(write("src/new.py"), root=proj, scope=scope)) == "allow"
    assert action(run(write("README.md"), root=proj, scope=scope)) == "deny"
    assert action(run(write(proj / "src" / "x.py"), root=proj, scope=scope)) == "allow"
    assert action(run(write(proj / "README.md"), root=proj, scope=scope)) == "deny"
    assert action(run(write("/tmp/mixer-x.txt"), root=proj, scope=scope)) == "deny"


def test_absolute_glob_matches_wherever_the_agent_runs(proj, tmp_path):
    glob = f"{proj.as_posix()}/src/**"
    other_cwd = tmp_path / "elsewhere"
    assert action(run(write(proj / "src" / "x.py"), root=other_cwd, scope=[glob])) == "allow"
    assert action(run(write(proj / "README.md"), root=other_cwd, scope=[glob])) == "deny"
    assert action(run(write("src/new.py"), root=other_cwd, scope=[glob])) == "deny"


def test_tilde_glob_is_absolute(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "notes").mkdir()
    assert action(run(write(tmp_path / "notes" / "a.md"), root=tmp_path / "x", scope=["~/notes/**"])) == "allow"
    assert action(run(write(tmp_path / "other.md"), root=tmp_path / "x", scope=["~/notes/**"])) == "deny"


def test_symlink_escape_is_resolved_before_matching(proj, tmp_path):
    (proj / "src" / "out").symlink_to(tmp_path / "elsewhere", target_is_directory=True)
    assert action(run(write("src/out/leak.txt"), root=proj, scope=["src/**"])) == "deny"


def test_double_star_spans_directories_and_single_star_does_not(proj):
    assert action(run(write("src/a/b/c.py"), root=proj, scope=["src/**"])) == "allow"
    assert action(run(write("src/a/b.py"), root=proj, scope=["src/*.py"])) == "deny"
    assert action(run(write("src/b.py"), root=proj, scope=["src/*.py"])) == "allow"


def test_block_message_names_the_path_the_globs_and_the_fix(proj):
    decision = run(write("README.md"), root=proj, scope=["src/**"])
    assert decision.message.startswith("blocked by mixer:scope")
    assert "README.md" in decision.message and "src/**" in decision.message
    assert "/mixer scope add" in decision.message


# -- Windows (B5): monkeypatched host OS, ntpath semantics, case-insensitive ----------------------

WIN_ROOT = "C:/Users/dev/proj"


def test_windows_default_settings_never_block_a_drive_path():
    assert action(run(write("C:\\Users\\dev\\proj\\notes.txt"), root=WIN_ROOT, windows=True)) == "allow"
    assert action(run(write("D:\\scratch\\x.txt"), root=WIN_ROOT, windows=True)) == "allow"


def test_windows_scope_matches_backslash_paths_case_insensitively():
    scope = ["src/**"]
    assert action(run(write("C:\\Users\\dev\\proj\\src\\a.py"), root=WIN_ROOT, windows=True, scope=scope)) == "allow"
    assert action(run(write("c:\\users\\DEV\\Proj\\SRC\\a.py"), root=WIN_ROOT, windows=True, scope=scope)) == "allow"
    assert action(run(write("C:\\Users\\dev\\proj\\README.md"), root=WIN_ROOT, windows=True, scope=scope)) == "deny"
    assert action(run(write("src\\new.py"), root=WIN_ROOT, windows=True, scope=scope)) == "allow"


def test_windows_absolute_drive_glob():
    scope = ["D:\\work\\**"]
    assert action(run(write("D:\\work\\a\\b.txt"), root=WIN_ROOT, windows=True, scope=scope)) == "allow"
    assert action(run(write("C:\\work\\a.txt"), root=WIN_ROOT, windows=True, scope=scope)) == "deny"


def test_windows_dotdot_is_normalised():
    scope = ["src/**"]
    assert action(run(write("src\\..\\README.md"), root=WIN_ROOT, windows=True, scope=scope)) == "deny"


def test_posix_host_treats_a_drive_path_as_a_relative_file_name(proj):
    assert action(run(write("C:\\proj\\notes.txt"), root=proj)) == "allow"
    assert action(run(write("C:\\proj\\notes.txt"), root=proj, scope=["src/**"])) == "deny"
    assert action(run(write("C:\\proj\\notes.txt"), root=proj, scope=["*"])) == "allow"


# -- the host resolver and workspace root (D3) ---------------------------------------------------


def test_hermes_ports_use_the_host_resolver_and_workspace_root(host_shim, proj, tmp_path, monkeypatch):
    from hermes_agent_mixer.hermes.ports import HermesPorts

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TERMINAL_CWD", str(proj))
    ports = HermesPorts()
    assert ports.resolve("src/a.py", "task-1") == (proj / "src" / "a.py").as_posix()
    assert ports.workspace_root("task-1") == proj.as_posix()


@pytest.mark.parametrize("sentinel", ["", ".", "auto", "cwd", "relative/dir"])
def test_hermes_ports_fall_back_to_the_process_cwd_for_a_sentinel_terminal_cwd(
        host_shim, tmp_path, monkeypatch, sentinel):
    from hermes_agent_mixer.hermes.ports import HermesPorts

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TERMINAL_CWD", sentinel)
    assert HermesPorts().workspace_root("t") == tmp_path.resolve().as_posix()


def test_without_any_host_the_same_order_is_used(no_host, proj, tmp_path, monkeypatch):
    from hermes_agent_mixer.hermes.ports import HermesPorts

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TERMINAL_CWD", str(proj))
    assert HermesPorts().resolve("src/a.py", "t") == (proj / "src" / "a.py").as_posix()
    monkeypatch.setenv("TERMINAL_CWD", "auto")
    assert HermesPorts().resolve("a.py", "t") == (tmp_path.resolve() / "a.py").as_posix()
