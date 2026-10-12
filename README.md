# Agent Mixer

A mixing desk for how much a coding agent may change. Four dials (edits, scope, lines, deps) you set up front or turn mid-session with `/mixer`. Hermes is the first-class host; the same dials also work in Claude Code, Codex and Gemini CLI through an `agent-mixer` hook command.

Hermes can already ask before dangerous terminal commands (`approvals.mode`, `/yolo`). It has no permission modes for file edits, no write scope, no enforced read-only plan mode, no per-turn change budget and no new-dependency guard. Agent Mixer adds those as a plugin, using only public Hermes plugin APIs (plus three guarded host reads, listed below) and the Python standard library.

The board (every value says where it comes from, and the line budget says how much is left this turn):

```
Agent Mixer · sess_3f2a9c1e
  edits   ask  [ACTIVE] auto  plan  (session)
  scope   src/**, tests/**  (saved)
  lines   200 per turn, 113 left this turn  (saved)
  deps    allow  [ACTIVE] ask  block  (default)
  ask uses the host's approvals gate; always-allow remembers one file or one package. ...
```

Requirements: Python 3.12+. Hermes needs a 2026-era build (hooks, plugin commands, subagent hooks). The CLI harnesses need only the `agent-mixer` command.

## Install

### Hermes

With a git checkout (the repo layout is what `hermes plugins install` clones):

```bash
hermes plugins install <owner>/<repo> --enable      # from GitHub
hermes plugins install file:///path/to/hermes-agent-mixer --enable --yes-deps   # from a local clone
```

- The installer asks about Python dependencies because the repo carries a `pyproject.toml`; the runtime uses only the standard library, so answering yes installs nothing extra. `--yes-deps` answers that prompt for non-interactive installs.
- A bare local path (no `file://`) is treated as a GitHub URL.
- Verify with `hermes plugins list` (shows `hermes-agent-mixer  enabled`) and `hermes plugins doctor hermes-agent-mixer --ci`.
- The plugin also declares a pip entry point in the `hermes_agent.plugins` group (module `hermes_agent_mixer`). That suits an unmanaged Python environment; for a managed Hermes install use the directory-plugin installer so its environment manager admits the plugin.

### Claude Code, Codex and Gemini CLI

```bash
uv tool install /path/to/hermes-agent-mixer      # or: pip install /path/to/hermes-agent-mixer
agent-mixer install claude                       # prints the plan, writes nothing
agent-mixer install claude --yes                 # merges the hooks into ~/.claude/settings.json
agent-mixer install claude --project --yes       # .claude/settings.local.json for this folder only
agent-mixer install codex --yes                  # ~/.codex/hooks.json
agent-mixer install gemini --yes                 # ~/.gemini/settings.json
agent-mixer doctor                               # what is installed, where settings live, what is wrong
agent-mixer uninstall claude --yes               # removes only Mixer's entries
```

Installs are idempotent, merge into existing files and keep your own hooks. Hook commands use the absolute path of the `agent-mixer` executable, so they do not depend on `PATH`. `agent-mixer install claude --settings-json` prints the hook JSON for a one-off `claude --settings <file>` run.

### Developer checks

Use disposable HOME, HERMES_HOME and TMPDIR, never your live profile:

```bash
uv run --locked pytest -q
bash scripts/sandbox_install_load_check.sh /path/to/evidence
bash scripts/e2e_run.sh /path/to/evidence
```

The slow tests, the receipts and the native-host test share one cached base Hermes home under `MIXER_SANDBOX_CACHE` (default `$XDG_CACHE_HOME/agent-mixer-tests`): `tools/`, `cache/` and `installs/` are built once (about 1.6 GB) and symlinked into thin per-run homes. Never move the base home; the managed environments inside it record absolute paths. The native test (`tests/native/test_host_contract.py`) loads Mixer through the real Hermes plugin loader and runs only when `MIXER_NATIVE_PYTHON` points at the sandbox Hermes interpreter. The E2E script uses only `http://127.0.0.1:8091/v1`, model `auto`.

## Commands

| Command | Effect |
|---|---|
| `/mixer` | Show the board. |
| `/mixer edits ask\|auto\|plan` | Set the edits dial for this session. |
| `/mixer scope add <glob>` / `remove <glob>` / `clear` / `show` | Manage the write-scope glob list. |
| `/mixer lines <N>\|off` | Set the per-turn lines budget (`0` also means off). |
| `/mixer deps allow\|ask\|block` | Set the dependencies dial. |
| `/mixer save` | Persist the current set as the saved defaults. |
| `/mixer save <dial> <value>` | Set one saved default directly, with no session needed (`save deps block`, `save lines 40`, `save scope src/** docs/**`, `save scope add <glob>`). |
| `/mixer reset` | Drop this session's overrides, back to the saved defaults. |

The same grammar works in a shell, and `/mixer` typed in any harness is handled by its prompt hook (the change is applied, the prompt is blocked, and the board comes back as the reason, so no model turn is spent):

```
agent-mixer [--session ID | --saved] <dial> <value>
agent-mixer [--session ID] board
agent-mixer ui [--session ID | --saved] [--port N] [--no-open]
```

- With `--session ID` the change goes to that session (it need not have been seen yet). With `--saved` it edits the saved defaults. With neither, it acts on the latest session seen in the current folder and says which; if none has been seen it fails and suggests `--saved`.
- Saved settings (Hermes): the plugin settings, written by the Desktop form and `ctx.set_config`. Saved settings (CLI harnesses): `$AGENT_MIXER_HOME/settings.json`, default `$XDG_CONFIG_HOME/agent-mixer/` (`%APPDATA%\agent-mixer\` on Windows). Per-session CLI state lives in `$AGENT_MIXER_HOME/state/`, default `$XDG_STATE_HOME/agent-mixer/` (`%LOCALAPPDATA%\agent-mixer\state\`). The two sets of saved values are separate; `agent-mixer doctor` says so.
- Saved keys: `edits`, `scope`, `lines` (an int, `0` = off; the 0.1 text forms `"off"` and `"50"` still load), `deps`, and `extra_write_tools`.

### Desktop settings

The manifest declares every setting with a label, a description and its type, so Hermes Desktop (Settings, Plugins) shows a real form: `edits` and `deps` are dropdowns, `lines` is a number field, `scope` and `extra_write_tools` are lists. An invalid saved `edits` or `deps` never weakens a dial: it falls back to `ask`, is logged, and shows on the board with a warning.

### Steering console (browser)

`agent-mixer ui` opens a local steering console in the same retro style as the project artwork: the four dials as segmented sliders, a live `STEERING POLICY (PREVIEW)` JSON panel, and buttons for copy / save / reset. It is a real control panel, not a mock: every change goes through the same grammar and store as the CLI, and the page polls the dials every few seconds.

- Binds `127.0.0.1` only; pass `--port N` to change the port (default 8377), `--no-open` to skip opening a browser.
- `--session ID` steers that session; `--saved` steers the saved defaults; with neither it picks the latest session seen in this folder.
- The write endpoint requires a per-run token and refuses cross-origin requests, so another site cannot drive your dials. It changes dials only — it can never run tools or touch files.
- Hermes plugin users: the console edits the CLI harness's saved settings (`settings.json`), which are separate from the Hermes plugin settings (see above). Steer a Hermes session's dials with `/mixer` in that chat.

```yaml
plugins:
  enabled: [hermes-agent-mixer]
  entries:
    hermes-agent-mixer:
      settings:
        edits: auto
        scope: ["src/**", "tests/**"]
        lines: 0            # 0 = off; or a number such as 200
        deps: ask
        extra_write_tools: ["mcp__fs__write*"]
```

## Knobs

| Dial | Values (default) | Effect |
|---|---|---|
| `edits` | `ask` · `auto` · `plan` (`auto`) | `ask`: every file change waits for approval. `auto`: changes go ahead. `plan`: read-only; see Plan mode. |
| `scope` | list of globs (default: empty = no restriction) | Writes outside the scope are blocked with a message naming the scope. A relative glob anchors at the workspace root (not the process cwd); an absolute glob (`/...`, `~/...`, a drive path on Windows) matches absolute paths anywhere. Symlinks are resolved before checking. |
| `lines` | `N` · `0` (`0` = off) | Most lines changed per turn across file edits, counted from a real diff (added + removed). A call that would go over is blocked, naming what remains. Subagents share their parent's budget. |
| `deps` | `allow` · `ask` · `block` (`ask`) | New dependencies in manifests and install commands. Bumps, removals and reorders pass. |
| `extra_write_tools` | list of tool-name globs (empty) | Tools such as `mcp__fs__write*` are treated like `write_file`, using their `path`, `file_path`, `filename` or `target` argument. |

What counts as a new dependency:

- Manifest edits that add a name: `package.json` (dependencies, devDependencies, peerDependencies, optionalDependencies); `pyproject.toml` `[project] dependencies`, `optional-dependencies` and `[dependency-groups]`; `requirements*.txt`; `Cargo.toml` `[dependencies]` and `[dev-dependencies]`; `go.mod` `require`. Names are compared before and after the change (on the post-patch text; when that cannot be worked out, the names in the call's old text against its new text).
- Install commands in the shell: `npm|pnpm|yarn|bun add|install <pkg>`, `pip|pip3|uv pip install <pkg>`, `uv add`, `poetry add`, `cargo add`, `go get`. A bare `npm install`, `uv sync`, `yarn`, `poetry install`, `pip install -r ...` or `go get ./...` restores existing deps and is allowed.

## How it decides

Every tool call runs the stages in a fixed order - plan, scope, deps, lines, ask - and the first deny wins. Mixer only restricts: it denies, asks, or says nothing. It never emits "allow", because that would override a harness's own permission prompts.

- File tools (`write_file`, `patch`, Claude Code `Write`/`Edit`/`MultiEdit`/`NotebookEdit`, Codex `apply_patch`, Gemini `write_file`/`replace`, plus `extra_write_tools`): the host resolves the target path; scope checks every target including patch sources and destinations; the deps guard checks every affected manifest; the lines guard counts the real diff. Hard blocks come before any approval, so approving a dependency cannot override a line limit.
- Patches the host fuzzy-matches (drifted whitespace and so on) are counted with the host's own matcher when it can be imported, otherwise with an exact-then-line-trimmed match. If no anchor matches, the changed lines are estimated as the larger of the old and new line counts and the call is never blocked just for that; the host reports a bad anchor itself.
- Approval grain: `ask` uses one rule key per absolute file (`mixer:edit:<absolute posix path>`) and one per package (`mixer:dep:<ecosystem>:<name>`), so Hermes' "always" approves that file or package, not every edit forever and not another project.
- Shell commands: in `plan` mode only a read-only allowlist runs. In any other mode, if a scope is set, Mixer reads the write targets it can see - redirects (`>`, `>>`), `tee`, `sed -i`, `cp`/`mv`/`ln`/`install` destinations, `touch`, `rm`, `rmdir`, `mkdir`, `truncate`, `dd of=` - resolves relative ones against the command's cwd, and checks them against the scope. Opaque commands (`bash -c "$X"`, `eval`, running a script) are allowed.
- Rules line: when a dial is off its default, the turn starts with one line (under 300 characters, starting "Agent Mixer:") saying so and asking the model not to work around blocks with terminal or `execute_code`. Hermes returns it as `pre_llm_call` context; CLI harnesses add it as `additionalContext`. With every dial at its default nothing is injected. Every block message repeats the "don't retry through terminal or execute_code" line and names the `/mixer` fix.
- `execute_code`: blocked in plan mode, otherwise untouched (its writes cannot be scoped statically).
- The per-turn counter resets at the turn boundary. Parallel calls reserve budget atomically, and usage is reserved before execution or approval, so a denied or failed call can consume budget until the next turn.
- Failure (CLI harnesses): unreadable hook input exits 2 with the reason on stderr (all three harnesses treat that as blocking). An internal error while any dial is off its default denies, naming the error and `agent-mixer doctor`. With every dial at its default Mixer stays silent.

### Host modules imported (Hermes)

Everything Hermes-specific lives in `hermes_agent_mixer/hermes/host.py`. Each import is guarded, and each has a fallback that follows the same order:

| Module | Why | Fallback |
|---|---|---|
| `gateway.session_context.get_session_env` | The ContextVar-aware reader of `HERMES_SESSION_ID` and `HERMES_SESSION_KEY` (the ContextVar if bound, `os.environ` only when nothing is bound). | `os.environ` |
| `tools.file_tools_paths._resolve_path_for_task`, `_authoritative_workspace_root` | How the file tools turn a path into a real one, and the workspace root they anchor to (session cwd, registered override, `TERMINAL_CWD`). | an absolute, non-sentinel `TERMINAL_CWD`, then the process cwd |
| `tools.fuzzy_match.fuzzy_find_and_replace` | The matcher the patch tool applies, to count what a drifted patch really changes. | exact match, then line-trimmed |

No `hermes_cli` import. Tests may import host internals; a verbatim copy of the upstream modules is vendored in `tests/upstream_shim/` (see its `NOTICE`).

## Harnesses

| Harness | Config | Events | Turn | `ask` |
|---|---|---|---|---|
| Hermes | plugin install | `pre_tool_call`, `pre_llm_call`, `subagent_start`, `subagent_stop` + `/mixer` | per `pre_llm_call` | native approval prompt |
| Claude Code | `~/.claude/settings.json` (`.claude/settings.local.json` with `--project`) + `~/.claude/commands/mixer.md` | `PreToolUse`, `UserPromptSubmit`, `UserPromptExpansion` | `prompt_id` | native `ask` |
| Codex | `~/.codex/hooks.json` | `PreToolUse` (`Bash`, `apply_patch`, `mcp__*`), `UserPromptSubmit` | `turn_id` | becomes deny |
| Gemini CLI | `~/.gemini/settings.json` | `BeforeTool`, `BeforeAgent` | each `BeforeAgent` | becomes deny |

- **Claude Code** (2.1.x, tested live): `agent-mixer install claude --yes`. Scope globs anchor at `$CLAUDE_PROJECT_DIR`. `PowerShell` is read-only (`Get-*`, `Select-String`) in plan mode. `/mixer` is handled in the prompt hook; the command file is only there so the command exists, and tells the user to run `agent-mixer doctor` if they ever see it. Subagents keep the parent's `session_id`, so they share its dials and budget.
- **Codex**: `agent-mixer install codex --yes`, then open `/hooks` in Codex and trust the new hooks. Trust is keyed to the hook's hash, so reinstalls are byte-stable and a changed hook must be trusted again. Codex treats `permissionDecision: "ask"` (and `continue`, `stopReason`, `suppressOutput` on PreToolUse) as a failed hook and runs the tool, so Mixer never emits them: `ask` becomes deny, with a reason saying why and how to change it (`agent-mixer edits auto`). Codex describes hooks as "a useful guardrail, not a complete enforcement boundary".
- **Gemini CLI**: `agent-mixer install gemini --yes` (hook timeouts are in milliseconds). `ask` becomes deny as for Codex. There is no turn id, so every `BeforeAgent` starts a new turn for that session. stdout is JSON only; Mixer never crashes with a non-2 exit, which Gemini would treat as a warning and fail open.
- **Contract-tested only**: Codex and Gemini CLI are not installed on the machine this was built on. Their adapters are tested against the documented payload and output shapes (`tests/harness/`), not against the programs. Claude Code is exercised live (see the evidence in the run report).

## Sessions and subagents

- **Hermes hooks** use the hook's own `session_id`; they never read environment variables or ContextVars for it.
- **`/mixer` on the classic CLI** takes `HERMES_SESSION_ID` from the ContextVar-aware reader, which falls back to `os.environ` (the CLI publishes the id there) only when nothing is bound.
- **TUI and Desktop** bind both the chat key and the session id; `/mixer` applies to that session.
- **Messaging gateway** binds the chat key and an empty session id. `/mixer` takes the key, maps it to a session through the key-to-session pairs recorded at `pre_llm_call`, and if that chat has not had a turn yet, parks the change under the key and applies it at that chat's next turn. The reply names only this chat's key or session, never another's.
- **Nothing bound** (for example `api_server`): `/mixer` changes nothing, says it cannot tell which chat this is, and points to `/mixer save <dial> <value>` and the plugin settings.
- **Subagents**: `subagent_start` links the child to its parent; a child whose `pre_llm_call` names `parent_session_id` is linked too. Children read the parent's effective dials live (not a copy), draw from the parent's current-turn line budget, never reset it, and grandchildren resolve to the root session. `subagent_stop` unlinks the child.
- **Clean-up**: Hermes drops session state idle for more than 24 hours and keeps at most 1,000 sessions. The CLI store drops state idle for more than 7 days.
- **CLI harnesses**: every hook is a separate process, so state is one file per session under the state directory, guarded by one store-wide lock (`fcntl.flock` on the fixed file `<state dir>/.lock`, `msvcrt.locking` on Windows). A hook waits up to 5 seconds for it, then fails closed. Files are written by atomic replace, so parallel tool calls never lose an update.

## Not a sandbox

Mixer sees tool calls, not system calls. A terminal command, a script or a subprocess can still write anywhere it is not parsed: `bash -c "$X"`, `eval`, running a script, a build step. Shell write-target checking is best effort on commands it can read. `execute_code` can write anything. The deps guard watches the listed manifests and install commands only, so copying a requirements file, vendoring, or an install helper it does not recognise will pass. The lines budget counts the calls Mixer can see, not total repository churn. For hard isolation use a container backend or an OS sandbox.

## Plan mode

`/mixer edits plan` is a tool-level gate, not a prompt convention. File tools and `execute_code` are blocked outright and the shell is limited to a read-only allowlist with argument checks:

- General: `ls`, `cat`, `head`, `tail`, `wc`, `grep`, `rg`, `find` (without `-delete`, `-exec`, `-execdir`, `-ok`, `-fprint*`), `sed -n` (no `w`, `W`, `e`, no `-i`), `sort` (no `-o`), `uniq` (at most one file), `cut`, `diff`, `cmp`, `stat`, `du`, `df`, `file`, `jq`, `echo`, `printf`, `basename`, `dirname`, `realpath`, `cd`.
- Git, read-only forms: `status`, `log`, `diff`, `show`, `grep`, `ls-files`, `ls-tree`, `blame`, `describe`, `shortlog`, `remote -v`, `config --get`, `tag -l`, `branch` (listing only).
- Allowed redirects: `>/dev/null`, `2>/dev/null`, `2>&1`. `$` inside quotes is fine; `$(...)`, backticks, process substitution, heredocs, subshells and other redirects are not.
- Interpreters stay blocked, including `pytest --collect-only`, because they run project code.
- Claude Code's `PowerShell` tool: `Get-*` cmdlets and `Select-String` only.

To leave plan mode: `/mixer edits auto` (or `ask`), or `/mixer reset`. A `/yolo` or `approvals.mode: off` Hermes session bypasses Mixer's `ask` approvals (the approve directive runs through Hermes' gate, which yolo skips); plan blocks still apply because they are deny directives.

## Changelog

### 0.2.0

Fixes (IDs refer to the review in the 02b handoff):

- **B1** The messaging gateway no longer locks the wrong chat: `/mixer` identifies the chat from its bound key and the session recorded for it at turn start, parks a change that arrives before the first turn, and never falls back to `os.environ` once a ContextVar is bound.
- **B2** Subagents no longer escape the dials: they inherit the parent's live dials and share its per-turn line budget (`subagent_start`/`subagent_stop`, `parent_session_id`).
- **B3** The "project root" is no longer the process cwd. An empty scope means no restriction; relative globs anchor at the host's workspace root; absolute globs match anywhere. Defaults no longer block `/tmp`, scratch or gateway project writes.
- **B4** Drifted patch anchors are counted with the host's fuzzy matcher (or an exact-then-line-trimmed fallback) and are never blocked just because the anchor was not found; manifest patches compare dependency names before and after, so only new names trigger `deps`.
- **B5** Windows paths: no more blanket rejection. Windows hosts use `ntpath` semantics and case-insensitive matching; on POSIX `C:\x` is an ordinary relative file name. (A Windows CI job waits for the public repo.)
- **B6** "Always" no longer approves everything forever: rule keys are per absolute file and per package.
- **B7** A saved typo can no longer weaken a dial: invalid `edits`/`deps` fall back to `ask`, are logged and show on the board. The settings form has dropdowns, labels and an int `lines`.
- **B8** Plan mode allows everyday read-only commands (29 of 39 were blocked before) and still blocks anything that writes or runs project code.
- **B9** The terminal / `execute_code` gap is narrowed (best effort, documented): rules line, block messages, shell write targets.
- **QW1** Manifest v2 with tags, labels and descriptions, dropdowns, an int `lines`, the new hooks in `provides_hooks` and an `args_hint` on `/mixer`.
- **QW2** A rules line of under 300 characters is injected only when a dial is off its default.
- **QW3** Every block message says not to retry through terminal or `execute_code`, and names the `/mixer` fix.
- **QW4, QW5** The finer "always" grain (B6) and the wider plan-mode allowlist (B8).
- **QW6** The board labels each value as session, saved or default, shows lines left this turn, and flags invalid saved values.
- **QW7** `extra_write_tools` treats chosen MCP tools like `write_file`.
- **QW8** Best-effort shell write targets are checked against the scope.
- **QW9** Absolute scope globs, so a scope set from Discord means something.
- **QW10** `/mixer save <dial> <value>` sets a saved default directly.
- **QW11** Idle sessions are pruned (24 hours, at most 1,000, on Hermes).
- **P1** No `hermes_cli` import; every host import is guarded and lives in `hermes/host.py`.
- **P2** One cached sandbox Hermes home serves every slow lane.

New:

- **X1** The engine moved to `core/`, the Hermes adapter to `hermes/`, harness payload mapping to `harness/`.
- **X2** The `agent-mixer` CLI.
- **X3** A file-backed session store with one lock, so parallel hook calls never lose an update.
- **X4, X5, X6** Claude Code, Codex and Gemini CLI hook adapters (Codex and Gemini contract-tested only; `ask` becomes deny there).
- **X7** `agent-mixer install`, `uninstall` and `doctor`.
- **X8** `agent-mixer ui`: a local browser steering console (loopback-only, token-guarded) over the same grammar and store; the four dials as segmented sliders with a live steering-policy JSON preview.

Compatibility: the `/mixer` grammar and the saved-setting keys are unchanged; saved 0.1 configs (including text `lines`) keep working.

### 0.1.0

First release: the edits, scope, lines and deps dials for Hermes, enforced in `pre_tool_call`, with `/mixer`, a board and plan mode.
