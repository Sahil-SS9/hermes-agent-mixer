"""Drifted patch anchors (B4, D4) and approval grain (B6, D5)."""
from __future__ import annotations

import pytest

from hermes_agent_mixer.core.calls import Call
from tests.helpers import Counter, action, edit, run, write

PYPROJECT = '[project]\nname = "demo"\nversion = "0.1.0"\ndependencies = [\n    "requests>=2",\n]\n'
PACKAGE = '{\n  "name": "demo",\n  "dependencies": {\n    "express": "^4.0.0"\n  }\n}\n'


@pytest.fixture
def proj(tmp_path):
    p = tmp_path / "proj"
    (p / "src").mkdir(parents=True)
    (p / "src" / "app.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (p / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    (p / "package.json").write_text(PACKAGE, encoding="utf-8")
    return p


DRIFT = ("def f():\n  return 1", "def f():\n  return 2")


def test_a_whitespace_drifted_patch_is_counted_not_blocked(proj):
    assert action(run(edit("src/app.py", *DRIFT), root=proj, lines=50)) == "allow"


def test_a_drifted_patch_is_counted_with_the_host_fuzzy_matcher(proj, host_shim):
    from hermes_agent_mixer.core import decisions
    from hermes_agent_mixer.hermes.ports import HermesPorts
    from tests.helpers import knobs

    budget = Counter()
    decisions.decide(edit(proj / "src" / "app.py", *DRIFT), knobs(lines=50), HermesPorts(), budget)
    assert budget.n == 2  # one line out, one line in


def test_an_unmatched_anchor_never_blocks_and_is_estimated_from_line_counts(proj):
    budget = Counter()
    call = edit("src/app.py", "nothing like this\nat all\nreally", "x")
    assert action(run(call, root=proj, lines=50, budget=budget)) == "allow"
    assert budget.n == 3  # larger of the old (3) and new (1) line counts


def test_an_unmatched_anchor_over_the_budget_is_blocked_by_the_estimate(proj):
    call = edit("src/app.py", "a\nb\nc\nd", "x")
    assert action(run(call, root=proj, lines=3)) == "deny"


def test_a_missing_file_is_estimated_too(proj):
    assert action(run(edit("src/nope.py", "a", "b"), root=proj, lines=5)) == "allow"


def test_a_dependency_bump_in_a_drifted_patch_is_allowed_under_default_deps(proj):
    call = edit("pyproject.toml", 'dependencies = [\n  "requests>=2",', 'dependencies = [\n  "requests>=2.31",')
    assert action(run(call, root=proj)) == "allow"


def test_a_new_dependency_in_a_drifted_patch_asks_with_the_package_in_the_key(proj):
    call = edit("pyproject.toml", 'dependencies = [\n  "requests>=2",', 'dependencies = [\n  "requests>=2",\n  "rich>=13",')
    decision = run(call, root=proj)
    assert decision.action == "ask" and decision.rule_key == "mixer:dep:pypi:rich"


def test_a_removal_or_reformat_is_not_a_new_dependency(proj):
    gone = edit("pyproject.toml", '    "requests>=2",\n', "")
    assert action(run(gone, root=proj)) == "allow"


def test_when_the_text_cannot_be_simulated_new_names_in_new_string_trigger_deps(proj):
    call = edit("pyproject.toml", 'zzz = ["requests>=2"]', 'zzz = ["requests>=2", "rich>=13"]')
    decision = run(call, root=proj)
    assert decision.action == "ask" and "rich" in decision.rule_key


def test_when_the_text_cannot_be_simulated_a_bump_is_still_allowed(proj):
    call = edit("pyproject.toml", 'zzz = ["requests>=2"]', 'zzz = ["requests>=2.31"]')
    assert action(run(call, root=proj)) == "allow"


def test_deps_block_blocks_a_new_name_in_a_drifted_package_json_patch(proj):
    call = edit("package.json", '"express": "^4.0.0"', '"express": "^4.0.0",\n    "left-pad": "^1.3.0"')
    assert action(run(call, root=proj, deps="block")) == "deny"


# -- approval grain (B6 / D5) --------------------------------------------------------------------


def test_every_file_gets_its_own_rule_key_with_the_absolute_posix_path(proj):
    a = run(write(proj / "src" / "a.py"), root=proj, edits="ask")
    b = run(write(proj / "src" / "b.py"), root=proj, edits="ask")
    assert a.action == "ask" and b.action == "ask"
    assert a.rule_key == f"mixer:edit:{(proj / 'src' / 'a.py').as_posix()}"
    assert a.rule_key != b.rule_key


def test_a_relative_target_is_keyed_by_its_resolved_absolute_path(proj):
    assert run(write("src/a.py"), root=proj, edits="ask").rule_key == f"mixer:edit:{(proj / 'src' / 'a.py').as_posix()}"


def test_the_same_relative_name_in_two_projects_never_shares_a_key(proj, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    one = run(write("a.py"), root=proj, edits="ask").rule_key
    two = run(write("a.py"), root=other, edits="ask").rule_key
    assert one != two


def test_each_package_gets_its_own_dep_key_per_ecosystem(proj):
    py = run(edit("pyproject.toml", '    "requests>=2",', '    "requests>=2",\n    "rich>=13",'), root=proj)
    js = run(edit("package.json", '    "express": "^4.0.0"', '    "express": "^4.0.0",\n    "left-pad": "^1.3.0"'), root=proj)
    assert py.rule_key == "mixer:dep:pypi:rich" and js.rule_key == "mixer:dep:npm:left-pad"


def test_install_commands_key_by_ecosystem_and_package(proj):
    from tests.helpers import shell

    assert run(shell("npm install left-pad"), root=proj).rule_key == "mixer:dep:npm:left-pad"
    assert run(shell("pip install rich"), root=proj).rule_key == "mixer:dep:pypi:rich"


def test_windows_keys_use_forward_slashes():
    key = run(write("C:\\Users\\dev\\proj\\a.py"), root="C:/Users/dev/proj", windows=True, edits="ask").rule_key
    assert key == "mixer:edit:C:/Users/dev/proj/a.py"
