"""The scope dial: glob matching, symlinks and absolute globs (0.2 semantics: an empty scope means no
limit, relative globs anchor at the workspace root; see test_paths.py for roots and Windows)."""

from __future__ import annotations

from pathlib import Path

from hermes_agent_mixer.core import scope
from tests.helpers import action, run, write


def _allowed(path, globs, root):
    return action(run(write(path), root=root, scope=globs)) == "allow"


def test_relative_path_inside_scope_glob(tmp_path):
    assert _allowed("src/a.py", ["src/**"], tmp_path)


def test_path_outside_scope_names_the_allowed_globs(tmp_path):
    message = run(write("nope/x.txt"), root=tmp_path, scope=["src/**", "tests/**"]).message
    assert "src/**" in message and "tests/**" in message and "mixer:scope" in message


def test_empty_scope_allows_everything_even_outside_the_workspace(tmp_path):
    assert _allowed("anywhere/file.txt", [], tmp_path)
    assert _allowed("../escape.txt", [], tmp_path)


def test_a_path_outside_the_workspace_needs_an_absolute_glob(tmp_path, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside")
    assert not _allowed(f"{outside}/x.txt", ["src/**"], tmp_path)
    assert _allowed(f"{outside}/x.txt", [f"{outside}/**"], tmp_path)


def test_dotdot_cannot_climb_out_of_a_relative_glob(tmp_path):
    (tmp_path / "src").mkdir()
    assert not _allowed("src/../README.md", ["src/**"], tmp_path)


def test_symlink_escape_blocked(tmp_path, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside")
    (tmp_path / "link-dir").symlink_to(outside, target_is_directory=True)
    assert not _allowed("link-dir/x.txt", ["link-dir/**"], tmp_path)


def test_symlink_to_inside_scope_allowed(tmp_path):
    (tmp_path / "src" / "target").mkdir(parents=True)
    (tmp_path / "alias").symlink_to(tmp_path / "src" / "target", target_is_directory=True)
    assert _allowed("alias/file.txt", ["src/**"], tmp_path)


def test_dot_slash_prefix_resolves_and_matches(tmp_path):
    assert _allowed("./src/a.py", ["src/**"], tmp_path)
    assert _allowed("src/a.py", ["./src/**"], tmp_path)


def test_star_star_matches_everything_below(tmp_path):
    assert _allowed("a/b.py", ["**"], tmp_path)


def test_nested_glob_does_not_cross_siblings(tmp_path):
    assert not _allowed("srcx/a.py", ["src/**"], tmp_path)


def test_absolute_glob_in_nested_form(tmp_path, tmp_path_factory):
    nested = tmp_path_factory.mktemp("nested") / "proj" / "docs"
    nested.mkdir(parents=True)
    assert not _allowed(str(nested / "d.md"), ["/nonexistent/**"], tmp_path)
    assert _allowed(str(nested / "d.md"), [f"{nested.parent}/**"], tmp_path)


def test_a_symlinked_glob_path_is_judged_by_its_real_location(tmp_path, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside")
    (outside / "real").mkdir()
    (tmp_path / "jump").symlink_to(outside / "real")
    assert not _allowed("jump/a.txt", ["jump/**"], tmp_path)
    assert _allowed("jump/a.txt", [f"{(outside / 'real').resolve()}/**"], tmp_path)


def test_glob_regex_units():
    assert scope.allowed("/p/src/a/b.py", ["src/**"], "/p")
    assert not scope.allowed("/p/src.py", ["src/**"], "/p")
    assert scope.allowed("/p/x.md", ["*.md"], "/p")
    assert not scope.allowed("/p/d/x.md", ["*.md"], "/p")
    assert scope.allowed("/p/d/x.md", ["**/*.md"], "/p")
    assert scope.allowed("/p/x.md", ["**/*.md"], "/p")
    assert scope.allowed("/p/ab.py", ["a?.py"], "/p")
    assert not scope.allowed("/p/a/.py", ["a?.py"], "/p")


def test_root_with_regex_characters_is_matched_literally():
    assert scope.allowed("/w/proj[1]+x/src/a.py", ["src/**"], "/w/proj[1]+x")
    assert not scope.allowed("/w/projj/src/a.py", ["src/**"], "/w/proj[1]+x")
