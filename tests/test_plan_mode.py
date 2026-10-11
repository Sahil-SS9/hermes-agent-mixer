"""Plan mode is a read-only allowlist with argument checks (B8, QW5, D7)."""
from __future__ import annotations

import pytest

from hermes_agent_mixer.core import shell
from hermes_agent_mixer.core.calls import Call
from tests.helpers import action, run, shell as shell_call, write

ALLOW = [
    "ls src 2>/dev/null", "ls src 2>&1", "ls >/dev/null", "cd src && ls", 'grep -rn "return$" src',
    "git log --oneline | sort", "git grep foo", "git ls-files", "git ls-tree HEAD", "git blame src/app.py",
    "git describe --tags", "git shortlog -sn", "git remote -v", "git config --get user.name", "git tag -l",
    "git branch", "git branch -a", "git diff HEAD --stat", "git show HEAD:src/app.py", "git status",
    "git -C sub status", "git --no-pager log -3", "sed -n '1,20p' src/app.py", "sed -n '/foo/p' f",
    "sed -n '$p' f", "du -sh .", "df -h .", "stat src/app.py", "file src/app.py", "diff a.txt b.txt",
    "cmp a.txt b.txt", "jq . package.json", "echo hello", "printf '%s\\n' hi", "cat f | sort | uniq -c",
    "cut -d: -f1 /etc/passwd", "basename /a/b", "dirname /a/b", "realpath .", "wc -l src/app.py",
    "head -n 5 src/app.py", "ls -la", "rg foo | head", "find . -name '*.py'", "uniq -c f", 'echo "cost: $5"',
    "echo $HOME", "sort -n f", "git tag", "git remote", "ls; pwd", "ls && ls || ls", "tail -n 3 f < /dev/null",
]
BLOCK = [
    "python -m pytest --collect-only -q", "echo x > f.txt", "ls > out.txt", "ls >> out.txt", "sed -i s/a/b/ f.txt",
    "sed -n '1p;w out.txt' f.txt", "sed -n 'e rm f.txt' f.txt", "sed -n 's/a/b/w out.txt' f", "sort -o out.txt f.txt",
    "sort -no out.txt f", "uniq a.txt b.txt", "tee f.txt", "cat a.txt | tee b.txt", "rm f.txt", "touch f.txt",
    "mkdir d", "mv a b", "cp a b", "cd src && rm app.py", "ls $(rm -rf x)", "echo `rm f.txt`", 'echo "$(rm f)"',
    "find . -delete", "find . -name x -exec rm {} \\;", "find . -fprint out.txt", "git commit -m x",
    "git checkout -- f.txt", "git branch newbranch", "git stash", "git tag v1", "git remote add o u",
    "git config user.name x", "git config --global --unset x", "git -c core.pager=x log", "git diff --output=o.txt",
    "npm install left-pad", "pip install rich", "ls 2>out.txt", "ls &> out.txt", "cat <(ls)", "cat <<EOF\nhi\nEOF",
    "FOO=1 ls", "bash -c ls", "env ls", "xargs rm", "(ls)", "ls | tee x", "rg --pre cat foo", "tree -o out.txt",
    "file -C", "git log --ext-diff", "ls >&out.txt", "echo hi >| f",
]


@pytest.mark.parametrize("command", ALLOW)
def test_plan_mode_allows_read_only(command, tmp_path):
    assert action(run(shell_call(command), root=tmp_path, edits="plan")) == "allow", command


@pytest.mark.parametrize("command", BLOCK)
def test_plan_mode_blocks_anything_that_writes_or_runs_project_code(command, tmp_path):
    assert action(run(shell_call(command), root=tmp_path, edits="plan")) == "deny", command


def test_plan_mode_blocks_every_file_tool_and_execute_code(tmp_path):
    for call in (write("a.py"), Call("edit", path="a.py", old="a", new="b"), Call("patch", patch_text="*** Begin Patch\n*** End Patch\n"),
                 Call("code", tool="execute_code")):
        assert action(run(call, root=tmp_path, edits="plan")) == "deny", call


def test_plan_block_message_names_the_fix_and_the_workaround_ban(tmp_path):
    message = run(write("a.py"), root=tmp_path, edits="plan").message.lower()
    assert "terminal" in message and "execute_code" in message and "/mixer edits" in message


def test_the_first_unsafe_segment_is_named(tmp_path):
    message = run(shell_call("ls && rm x"), root=tmp_path, edits="plan").message
    assert "segment 2" in message


def test_quoted_operators_are_literals_not_syntax(tmp_path):
    assert action(run(shell_call("grep 'a > b' f"), root=tmp_path, edits="plan")) == "allow"
    assert action(run(shell_call('grep "a; rm x" f'), root=tmp_path, edits="plan")) == "allow"
    assert action(run(shell_call("echo 'a $(b)'"), root=tmp_path, edits="plan")) == "allow"


# -- PowerShell (Claude Code's PowerShell tool) ---------------------------------------------------


@pytest.mark.parametrize("command", [
    "Get-ChildItem src", "Get-Content src/app.py", "Select-String -Path src/*.py -Pattern foo",
    "get-childitem src | Select-String foo", "Get-ChildItem; Get-Location",
])
def test_powershell_allows_get_cmdlets_and_select_string(command, tmp_path):
    assert action(run(shell_call(command, flavour="powershell"), root=tmp_path, edits="plan")) == "allow"


@pytest.mark.parametrize("command", [
    "Remove-Item src/app.py", "Set-Content a.txt hi", "Get-Content a | Set-Content b", "Get-Content a > b",
    "Get-ChildItem $(Remove-Item x)", "Get-ChildItem `\nRemove-Item x", "& Get-ChildItem", "ls", "cat a", "Out-File x",
    "Invoke-Expression 'ls'", "Get-ChildItem; Remove-Item x",
])
def test_powershell_blocks_everything_else(command, tmp_path):
    assert action(run(shell_call(command, flavour="powershell"), root=tmp_path, edits="plan")) == "deny"


def test_classify_returns_the_first_bad_segment_index():
    assert shell.classify_plan("ls; cat x; rm y") == (False, 2)
    assert shell.classify_plan("ls; cat x") == (True, -1)
