"""Bulk patch policy tests: each file's real before/after diff and dependencies."""
from __future__ import annotations

import pytest

from hermes_agent_mixer.core import diffcount
from tests import legacy
from tests.legacy import decisions
from tests.legacy import LinesState


def patch(body):
    return {"mode": "patch", "patch": f"*** Begin Patch\n{body}\n*** End Patch\n"}


def knobs(**changes):
    return {"edits": "auto", "scope": [], "deps": "allow", "lines": "off", **changes}


def test_bulk_diff_uses_separate_real_files(tmp_path):
    (tmp_path / "a.txt").write_text("alpha\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("bravo\n", encoding="utf-8")
    args = patch("*** Update File: a.txt\n@@\n-alpha\n+ALPHA\n"
                 "*** Update File: b.txt\n@@\n-bravo\n+BRAVO")
    assert legacy.estimate("patch", args, tmp_path) == (2, 2)
    # Simulation must never change either file.
    assert (tmp_path / "a.txt").read_text() == "alpha\n"
    assert (tmp_path / "b.txt").read_text() == "bravo\n"


@pytest.mark.parametrize("body,expected", [
    ("*** Add File: new.txt\n+one\n+two", (2, 0)),
    ("*** Delete File: old.txt", (0, 2)),
    ("*** Move File: old.txt -> moved.txt", (2, 2)),
])
def test_bulk_add_delete_and_move_use_file_diffs(tmp_path, body, expected):
    (tmp_path / "old.txt").write_text("one\ntwo\n", encoding="utf-8")
    assert legacy.estimate("patch", patch(body), tmp_path) == expected


def test_bulk_overlay_add_then_update_and_move(tmp_path):
    args = patch("*** Add File: one.txt\n+old\n"
                 "*** Update File: one.txt\n@@\n-old\n+new\n"
                 "*** Move File: one.txt -> two.txt")
    assert legacy.estimate("patch", args, tmp_path) == (1, 0)
    assert not (tmp_path / "one.txt").exists()
    assert not (tmp_path / "two.txt").exists()


@pytest.mark.parametrize("body", [
    "*** Add File: package.json\n+{\"dependencies\": {\"new-package\": \"1.0\"}}",
    "*** Update File: package.json\n@@\n-{}\n+{\"dependencies\": {\"new-package\": \"1.0\"}}",
    "*** Add File: plain.txt\n+hi\n*** Add File: package.json\n+{\"dependencies\": {\"new-package\": \"1.0\"}}",
])
def test_bulk_manifest_dependency_additions_are_blocked(tmp_path, body):
    if "*** Update File: package.json" in body:
        (tmp_path / "package.json").write_text("{}\n", encoding="utf-8")
    result = decisions.evaluate("patch", patch(body), knobs(deps="block"), LinesState(), root=tmp_path)
    assert result is not None and result["action"] == "block"
    assert "mixer:deps" in result["message"]
    assert "new-package" in result["message"]


def test_bulk_manifest_version_bump_is_allowed(tmp_path):
    (tmp_path / "package.json").write_text('{"dependencies": {"existing": "1"}}\n', encoding="utf-8")
    result = decisions.evaluate("patch", patch('*** Update File: package.json\n@@\n'
        '-{"dependencies": {"existing": "1"}}\n+{"dependencies": {"existing": "2"}}'),
        knobs(deps="block"), root=tmp_path)
    assert result is None


def test_bulk_delete_cannot_bypass_line_limit(tmp_path):
    (tmp_path / "old.txt").write_text("one\ntwo\n", encoding="utf-8")
    state = LinesState()
    result = decisions.evaluate("patch", patch("*** Delete File: old.txt"), knobs(lines=1), state, root=tmp_path)
    assert result is not None and result["action"] == "block"
    assert "mixer:lines" in result["message"]
    assert state.used("", "") == 0


def test_bulk_unmatched_anchor_is_estimated_not_blocked(tmp_path):
    """0.2 (D4): a hunk the matcher cannot place is counted from its +/- lines; the host reports the miss itself."""
    (tmp_path / "old.txt").write_text("other\n", encoding="utf-8")
    state = LinesState()
    result = decisions.evaluate("patch", patch("*** Update File: old.txt\n@@\n-missing\n+new"),
        knobs(lines=10), state, root=tmp_path, session_id="s", task_id="t")
    assert result is None
    assert state.used("s", "t") == 2
    big = decisions.evaluate("patch", patch("*** Update File: old.txt\n@@\n-a\n-b\n-c\n-d\n-e\n-f\n+g\n+h\n+i"),
        knobs(lines=10), state, root=tmp_path, session_id="s", task_id="t")
    assert big is not None and "mixer:lines" in big["message"]


def test_bulk_over_budget_beats_dependency_approval(tmp_path):
    result = decisions.evaluate("patch", patch('*** Add File: package.json\n+{\n'
        '+"dependencies": {"new-package": "1.0"}\n+}'),
        knobs(deps="ask", lines=1), LinesState(), root=tmp_path)
    assert result is not None and result["action"] == "block"
    assert "mixer:lines" in result["message"]
