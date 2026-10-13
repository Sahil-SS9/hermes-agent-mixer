"""Teknium-review regression gates: the sed script regex and depsguard scans stay linear.

The old _SED_SCRIPT degraded quadratically→cubically on padded address scripts
(0.3 ms @ 800 → 81 ms @ 4000 → 211 ms @ 6400 pads, 1233 ms @ 32 KB) while the
store lock was held; the fullmatch form stays ≤ 1 ms. The depsguard findall took
8.8 s on a 40 k-line blank cargo.toml; ``^[ \t]*`` is ~1 ms. These tests fail on
either regression or behaviour drift.
"""
from __future__ import annotations

import re
import time

import pytest

from hermes_agent_mixer.core import depsguard
from hermes_agent_mixer.core.shell import _read_only_sed, classify_plan

# -- parity: old regex (pre-#137449) vs the fullmatch form -----------------------------------------

_OLD = re.compile(
    r"\s*(?:(?:\d+|\$|/[^/]*/)(?:,(?:\d+|\$|/[^/]*/))?)?\s*!?\s*(?:[pPdq=l]|s/[^/]*/[^/]*/[gpiI0-9]*)\s*")


def old_script_ok(script: str) -> bool:
    """The pre-fix check: fullmatch of the anchored, whitespace-flanked form."""
    return all((not part.strip()) or bool(_OLD.fullmatch(part))
               for part in re.split(r"[;\n]", script))


def new_script_ok(script: str) -> bool:
    """The post-fix check: strip, then fullmatch the address/body form."""
    return _read_only_sed(["-e", script])


def test_sed_parity_on_review_edge_cases():
    accepted = ["p", "1,5p", "/x/p", "1!d", "s/a/b/g", "$p", "1p", "10q",
                "1,3s/a/b/", " s/a/b/gp ", "5=", "\t/regex/ p", "  1,5  p  ",
                "1,5s/a/b/gp", "/a/,/b/s/x/y/I", "s/^$/x/"]
    refused = ["w out", "1w x", "1r file", "e cmd", "F", "s/a/b/n", "1,5\np",
               "s/a", "p;x", "5a text", "/x/!s/a/b"]
    for script in accepted:
        assert new_script_ok(script), f"must accept: {script!r}"
        assert old_script_ok(script) == new_script_ok(script), f"parity: {script!r}"
    for script in refused:
        assert not new_script_ok(script), f"must refuse: {script!r}"
        assert old_script_ok(script) == new_script_ok(script), f"parity: {script!r}"


def test_sed_parity_20k_randomized_scripts():
    import random

    rng = random.Random(137449)
    atoms = ["", " ", "\t", "\v", "\f", "  ", "\t ", "1", "12", "$", "/x/", "/a b/",
             ",", ", ", " ,", "!", "! ", " p", "p", "d", "q", "=", "P", "s/a/b/",
             "s/a/b/g", "s/./x/gp", "s/^#/!/I"]
    for _ in range(20000):
        script = "".join(rng.choice(atoms) for _ in range(rng.randint(1, 7)))
        old, new = old_script_ok(script), new_script_ok(script)
        assert old == new, f"parity break: {script!r} old={old} new={new}"


def test_sed_padded_script_is_fast():
    """A padded address-pair script must still be refused, and fast (old: 1233 ms @ 32 KB)."""
    script = "/x/ " + " " * 32000 + ",/y/ " + " " * 32000 + "p"
    start = time.perf_counter()
    for _ in range(10):
        assert not new_script_ok(script)
    elapsed = (time.perf_counter() - start) / 10
    assert elapsed < 0.05, f"padded script took {elapsed * 1000:.1f} ms (limit 50 ms)"


def test_sed_classify_plan_padded_script_is_refused_quickly():
    """The whole plan classifier refuses the padded script in the same time budget."""
    plan = f"sed -n '/x/{' ' * 4000},/y/{' ' * 4000}p' big.txt"
    start = time.perf_counter()
    ok, _index = classify_plan(plan)
    elapsed = time.perf_counter() - start
    assert not ok  # refused: same verdict as the old regex, now without the blow-up
    assert elapsed < 0.05, f"classify_plan took {elapsed * 1000:.1f} ms"


# -- depsguard -------------------------------------------------------------------------------------


def test_depsguard_fragment_names_matches_old_semantics():
    cargo = "[dependencies]\nclap = \"4\"\nserde = { version = \"1\" }\n\n[target.'cfg(unix)'.dependencies]\nlibc = \"0.2\"\n"
    gomod = "module x\n\nrequire (\n\tgithub.com/a/b v1.2.3\n\t  github.com/c/d v2.0.0 // indirect\n)\n\nrequire github.com/e/f v0.1.0\n"
    old_cargo = {m for m in re.findall(r"^\s*([A-Za-z0-9_-]+)\s*=", cargo, re.M)}
    new_cargo = depsguard.fragment_names("cargo.toml", cargo)
    assert "clap" in new_cargo and "serde" in new_cargo and "libc" in new_cargo
    assert new_cargo == {n for n in old_cargo if n.lower() not in depsguard._NOT_DEPS}
    old_go = {m for m in re.findall(r"^\s*(?:require\s+)?([A-Za-z0-9][^\s/]*/[^\s]+)\s+v", gomod, re.M)}
    new_go = depsguard.fragment_names("go.mod", gomod)
    assert "github.com/a/b" in new_go and "github.com/c/d" in new_go and "github.com/e/f" in new_go
    assert new_go == old_go


def test_depsguard_indented_keys_identical_to_old():
    cargo = "\n  indented_key = \"1\"\n\ttabbed = \"2\"\nplain = \"3\"\n"
    old = {m for m in re.findall(r"^\s*([A-Za-z0-9_-]+)\s*=", cargo, re.M)}
    new = depsguard.fragment_names("cargo.toml", cargo)
    assert new == {n for n in old if n.lower() not in depsguard._NOT_DEPS}
    assert {"indented_key", "tabbed", "plain"} <= new


def test_depsguard_blank_line_file_is_fast():
    """40k blank lines must not cost seconds (was 8.8 s under ^\\s* + re.M)."""
    body = "\n" * 40000
    start = time.perf_counter()
    names = depsguard.fragment_names("cargo.toml", body)
    elapsed = time.perf_counter() - start
    assert names == set()
    assert elapsed < 0.2, f"blank-line scan took {elapsed * 1000:.0f} ms (limit 200 ms)"

@pytest.mark.parametrize("padding", [" " * 32768, "\n" * 32768])
def test_sed_single_and_multiline_input_is_bounded(padding):
    start = time.perf_counter()
    assert _read_only_sed(["-e", padding + "p"])
    assert time.perf_counter() - start < 0.2


@pytest.mark.parametrize("name", ["cargo.toml", "go.mod"])
@pytest.mark.parametrize("padding", [" " * 40000, "\n" * 40000])
def test_dependency_single_and_multiline_input_is_bounded(name, padding):
    start = time.perf_counter()
    assert depsguard.fragment_names(name, padding) == set()
    assert time.perf_counter() - start < 0.2
