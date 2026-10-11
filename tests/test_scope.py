"""Tests for the scope knob: glob matching, containment, symlinks, absolute globs, Windows paths."""

from __future__ import annotations

import os
from pathlib import Path

from hermes_agent_mixer import scope


def test_relative_path_inside_scope_glob(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert scope.check_scope("src/a.py", ["src/**"], root=tmp_path) is None


def test_path_outside_scope_names_the_allowed_globs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    message = scope.check_scope("nope/x.txt", ["src/**", "tests/**"], root=tmp_path)
    assert message is not None
    assert "src/**" in message
    assert "tests/**" in message


def test_empty_scope_allows_everything_inside_root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert scope.check_scope("anywhere/file.txt", [], root=tmp_path) is None


def test_write_outside_project_root_blocked(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    message = scope.check_scope("../escape.txt", [], root=tmp_path)
    assert message is not None
    assert "project" in message.lower()


def test_absolute_glob_allows_outside_root(tmp_path, monkeypatch, tmp_path_factory):
    monkeypatch.chdir(tmp_path)
    outside = tmp_path_factory.mktemp("outside")
    assert scope.check_scope(f"{outside}/x.txt", [f"{outside}/**"], root=tmp_path) is None


def test_outside_root_needs_an_absolute_glob(tmp_path, monkeypatch, tmp_path_factory):
    monkeypatch.chdir(tmp_path)
    outside = tmp_path_factory.mktemp("outside")
    message = scope.check_scope(f"{outside}/x.txt", ["src/**"], root=tmp_path)
    assert message is not None


def test_symlink_escape_blocked(tmp_path, monkeypatch, tmp_path_factory):
    monkeypatch.chdir(tmp_path)
    outside = tmp_path_factory.mktemp("outside")
    (tmp_path / "link-dir").symlink_to(outside, target_is_directory=True)
    message = scope.check_scope("link-dir/x.txt", ["link-dir/**"], root=tmp_path)
    assert message is not None, "symlink resolving outside the project root must be blocked"
    assert "scope" in message.lower() or "root" in message.lower()


def test_symlink_to_inside_scope_allowed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "target").mkdir()
    (tmp_path / "alias").symlink_to(tmp_path / "src" / "target", target_is_directory=True)
    assert scope.check_scope("alias/file.txt", ["src/**"], root=tmp_path) is None


def test_windows_drive_letter_rejected_cleanly(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    message = scope.check_scope("C:\\Users\\x\\file.txt", [], root=tmp_path)
    assert message is not None
    assert "windows" in message.lower()


def test_windows_backslash_path_rejected_cleanly(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    message = scope.check_scope("dir\\file.txt", [], root=tmp_path)
    assert message is not None
    assert "windows" in message.lower()


def test_scope_glob_with_backslashes_is_normalised(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert scope.check_scope("src/a.py", ["src\\**"], root=tmp_path) is None


def test_dot_slash_prefix_resolves_and_matches(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert scope.check_scope("./src/a.py", ["src/**"], root=tmp_path) is None


def test_missing_scope_components_reported(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    message = scope.check_scope("a/b.py", ["**"], root=tmp_path)
    assert message is None


def test_scope_message_names_the_knob(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    message = scope.check_scope("x/y.txt", ["src/**"], root=tmp_path)
    assert message is not None
    assert "scope" in message.lower()


def test_patch_tool_path_checked(tmp_path, monkeypatch, tmp_path_factory):
    monkeypatch.chdir(tmp_path)
    outside = tmp_path_factory.mktemp("outside")
    message = scope.check_scope(str(Path(outside) / "a.py"), [], root=tmp_path)
    assert message is not None


def test_nested_glob_does_not_cross_siblings(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    message = scope.check_scope("srcx/a.py", ["src/**"], root=tmp_path)
    assert message is not None, "src/** must not match srcx/"


def test_absolute_glob_in_nested_form(tmp_path, monkeypatch, tmp_path_factory):
    monkeypatch.chdir(tmp_path)
    nested = tmp_path_factory.mktemp("nested") / "proj" / "docs"
    nested.mkdir(parents=True)
    assert scope.check_scope(str(nested / "d.md"), ["/nonexistent/**"], root=tmp_path) is not None
    assert scope.check_scope(str(nested / "d.md"), [f"{nested.parent}/**"], root=tmp_path) is None


def test_resolved_symlink_target_used_for_glob(tmp_path, monkeypatch, tmp_path_factory):
    monkeypatch.chdir(tmp_path)
    outside = tmp_path_factory.mktemp("outside")
    (outside / "real").mkdir()
    (tmp_path / "jump").symlink_to(outside / "real")
    # Even though the glob names the link path, resolution lands outside root:
    # only an absolute glob naming the REAL path can allow it.
    message = scope.check_scope("jump/a.txt", ["jump/**"], root=tmp_path)
    assert message is not None


def test_absolute_glob_allows_resolved_symlink_target(tmp_path, monkeypatch, tmp_path_factory):
    monkeypatch.chdir(tmp_path)
    outside = tmp_path_factory.mktemp("outside")
    (outside / "real").mkdir()
    (tmp_path / "jump").symlink_to(outside / "real")
    assert scope.check_scope("jump/a.txt", [f"{(outside / 'real').resolve()}/**"], root=tmp_path) is None