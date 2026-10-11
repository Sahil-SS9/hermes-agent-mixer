"""Best-effort shell write targets against the scope (QW8, D8). Opaque commands are allowed."""
from __future__ import annotations

import pytest

from hermes_agent_mixer.core import shell
from tests.helpers import action, run, shell as shell_call


@pytest.fixture
def proj(tmp_path):
    p = tmp_path / "proj"
    (p / "src").mkdir(parents=True)
    return p


CASES = [
    ("echo x > README.md", "deny"), ("echo x > src/ok.txt", "allow"), ("sed -i s/a/b/ /etc/hosts", "deny"),
    ("cp src/app.py /tmp/x.py", "deny"), ("touch docs/x.md", "deny"), ("rm README.md", "deny"),
    ("tee -a notes.txt", "deny"), ("mv src/app.py README.md", "deny"), ("mkdir -p src/new", "allow"),
    ("ls -la", "allow"), ('bash -c "$CMD"', "allow"),
    ("echo x >> src/log.txt", "allow"), ("echo x > /dev/null", "allow"), ("ls 2>&1", "allow"),
    ("cat a | tee src/out.txt", "allow"), ("cat a | tee out.txt", "deny"), ("echo x &> README.md", "deny"),
    ("sed -i -e 's/a/b/' src/a.py", "allow"), ("sed -i 's/a/b/' src/a.py README.md", "deny"),
    ("sed -n 1p src/a.py", "allow"), ("cp a.txt src/b.txt", "allow"), ("cp -t src a.txt", "allow"),
    ("cp -t docs a.txt", "deny"), ("mv src/a src/b", "allow"), ("mv README.md src/b", "deny"),
    ("ln -s src/a src/b", "allow"), ("install -m 644 a src/b", "allow"), ("install -d docs", "deny"),
    ("rm -rf src/old", "allow"), ("rm -rf src/old docs", "deny"), ("rmdir docs", "deny"), ("truncate -s 0 README.md", "deny"),
    ("truncate -s 0 src/a", "allow"), ("dd if=/dev/zero of=README.md bs=1", "deny"), ("dd if=/dev/zero of=src/z", "allow"),
    ("cd src && touch a.py", "allow"), ("cd src && touch ../README.md", "deny"), ("cd docs && touch a.py", "deny"),
    ("eval \"$X\"", "allow"), ("./build.sh", "allow"), ("echo x > $OUT", "allow"), ("python gen.py", "allow"),
    ("ls; touch README.md", "deny"), ("touch src/a && touch README.md", "deny"),
]


@pytest.mark.parametrize("command,want", CASES)
def test_scope_src_with_edits_auto(command, want, proj):
    assert action(run(shell_call(command), root=proj, scope=["src/**"])) == want, command


def test_no_scope_means_shell_writes_are_not_inspected(proj):
    assert action(run(shell_call("rm -rf README.md"), root=proj)) == "allow"


def test_edits_ask_does_not_ask_for_shell_commands(proj):
    assert action(run(shell_call("ls"), root=proj, edits="ask")) == "allow"


def test_the_command_cwd_resolves_relative_targets(proj, tmp_path):
    call = shell_call("touch a.py", cwd=str(proj / "src"))
    assert action(run(call, root=tmp_path, scope=[f"{proj.as_posix()}/src/**"])) == "allow"
    call = shell_call("touch a.py", cwd=str(proj))
    assert action(run(call, root=tmp_path, scope=[f"{proj.as_posix()}/src/**"])) == "deny"


def test_block_message_names_the_parsed_target_and_the_workaround_ban(proj):
    message = run(shell_call("echo x > README.md"), root=proj, scope=["src/**"]).message
    assert "README.md" in message and "mixer:scope" in message and "execute_code" in message


def test_write_targets_extraction_list():
    got = shell.write_targets("echo a > o1; cp s d1; touch t1 t2; rm -rf r1; mkdir m1; sed -i x f1")
    assert [t.path for t in got] == ["o1", "d1", "t1", "t2", "r1", "m1", "f1"]


def test_write_targets_skip_variables_and_dev_null():
    assert shell.write_targets("echo a > $OUT; echo b > /dev/null; rm \"$X\"") == []
