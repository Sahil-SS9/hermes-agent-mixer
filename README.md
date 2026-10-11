# Agent Mixer

A mixing desk for how much a Hermes agent may change. Four knobs (edits, scope, lines, deps) you set up front or turn mid-session with `/mixer`.

Hermes can already ask before dangerous terminal commands (`approvals.mode`, `/yolo`). It has no permission modes for file edits, no write scope, no enforced read-only plan mode, no per-turn change budget and no new-dependency guard. Agent Mixer adds those five things as a plugin, using only public Hermes plugin APIs and the Python standard library.

The board:

```
Agent Mixer · session 3f2a9c1e
  edits   ask  [ACTIVE]  auto  plan
  scope   src/**, tests/**  (writes elsewhere: blocked)
  lines   87 / 200 this turn
  deps    allow  [ACTIVE]  ask  block
  Hermes approvals: manual.  (/yolo or approvals.mode to change; not a Mixer knob)
```

Requirements: Python 3.12+ and a current Hermes Agent (hooks and plugin commands need a 2026-era build).

## Install

With a git checkout (the repo layout is what `hermes plugins install` clones):

```bash
hermes plugins install <owner>/<repo> --enable      # from GitHub
hermes plugins install file:///path/to/hermes-agent-mixer --enable --yes-deps   # from a local clone
```

Notes:

- The installer asks about Python dependencies because the repo carries a `pyproject.toml`; the runtime uses only the standard library, so answering yes installs nothing extra. `--yes-deps` answers that prompt for non-interactive installs.
- If your build's installer refuses a local `file://` source with a dependency-consent error, run `hermes plugins install file://... --enable --yes-deps` exactly as above; a bare local path (no `file://`) is treated as a GitHub URL.
- Verify the load with `hermes plugins list` (shows `hermes-agent-mixer  enabled`) and `hermes plugins doctor hermes-agent-mixer --ci`.

The plugin also declares a pip entry point in the `hermes_agent.plugins` group (module `hermes_agent_mixer`). This works when the installation owner supplies an unmanaged Python environment. For a managed Hermes install, use the directory-plugin installer so its environment manager admits the plugin; do not inject packages into a live managed generation.

Developer checks (use disposable HOME, HERMES_HOME and TMPDIR, not your live profile):

```bash
uv run --locked pytest -q
bash scripts/sandbox_install_load_check.sh /path/to/evidence
bash scripts/e2e_run.sh /path/to/evidence
```

The receipt scripts create fresh sandboxes and stop on any failed command. The E2E script uses only `http://127.0.0.1:8091/v1`, model `auto`, and requires the host's actual `write_file` scope-block error, not a prose claim in the chat output.

## Commands

| Command | Effect |
|---|---|
| `/mixer` | Show the board. |
| `/mixer edits ask\|auto\|plan` | Set the edits knob. |
| `/mixer scope add <glob>` / `remove <glob>` / `clear` / `show` | Manage the write-scope glob list. |
| `/mixer lines <N>\|off` | Set the per-turn lines budget, or switch it off. |
| `/mixer deps allow\|ask\|block` | Set the dependencies knob. |
| `/mixer save` | Persist the current settings as the plugin defaults via `ctx.set_config`. |
| `/mixer reset` | Drop this session's overrides, back to the saved defaults. |

State is per session. Changes only touch the current session until you `/mixer save`, which writes the plugin config defaults (so one-shot runs like `hermes chat -q` get them too). Saved line limits are text (`"off"` or `"200"`) to match the host's settings schema; enforcement still uses an integer budget. Existing integer config values remain readable. Settings also come straight from plugin config without any command:

```yaml
plugins:
  enabled:
    - hermes-agent-mixer
  entries:
    hermes-agent-mixer:
      settings:
        edits: auto
        scope: ["src/**", "tests/**"]
        lines: "off"        # or a quoted positive number, e.g. "200"
        deps: ask
```

## Knobs

| Knob | Values (default) | Effect |
|---|---|---|
| `edits` | `ask` · `auto` · `plan` (`auto`) | `ask`: every `write_file`/`patch` goes to Hermes' own approval prompt. `auto`: edits allowed inside scope. `plan`: read-only: file writes blocked, `execute_code` blocked, `terminal` limited to read-only commands. |
| `scope` | list of globs (default: empty = everything inside the project root) | Writes outside scope are blocked with a message naming the scope. Writes outside the project root are always blocked unless an absolute glob allows them. Symlinks are resolved before checking. |
| `lines` | `N` · `off` (`off`) | Max lines changed per turn across `write_file`/`patch`, counted from a real diff of before/after (added + removed). A call that would go over is blocked; the message gives the remaining budget and suggests stopping to summarise. |
| `deps` | `allow` · `ask` · `block` (`ask`) | New dependencies: manifest edits and install commands are judged against the previous state, so removing, re-ordering or version-bumping existing entries is allowed. Note: version bumps pass the guard by design. |

What counts as a new dependency:

- Manifest edits that add an entry: `package.json` (dependencies, devDependencies, peerDependencies, optionalDependencies); `pyproject.toml` `[project] dependencies`, `optional-dependencies` and `[dependency-groups]`; `requirements*.txt`; `Cargo.toml` `[dependencies]` and `[dev-dependencies]`; `go.mod` `require`.
- Install commands in `terminal`: `npm|pnpm|yarn|bun add|install <pkg>`, `pip|pip3|uv pip install <pkg>`, `uv add`, `poetry add`, `cargo add`, `go get`.

False-positive guards: a bare `npm install` or `uv sync` restores existing deps and is allowed; so are `yarn`/`bun install`, `poetry install`, `pip install -r requirements.txt` and `go get ./...`. Removing or re-ordering entries is allowed. Version bumps of an existing dependency are allowed (deliberate: the guard watches for NEW dependency declarations, not upgrades).

## How it decides

Every `pre_tool_call` runs the stages in a fixed order - plan, scope, deps, lines, ask - and the first block wins.

- `write_file` / `patch`: plan blocks; scope checks every target, including bulk patch Add/Update/Delete/Move sources and destinations, after resolving symlinks. The deps guard checks every affected manifest. The lines guard checks per-file before/after diffs. All hard blocks are checked before returning an approval, so approving a dependency cannot override a line limit. Approval requests use `rule_key: mixer:deps` or `mixer:edits`.
- `execute_code`: blocked in plan mode, otherwise untouched (its writes cannot be scoped statically).
- `terminal`: the quote-aware scanner splits shell chains even without spaces. Redirects, `tee`, background jobs, substitutions, commands launched through `env`, branch creation and known writing options are blocked in plan mode. Quoted operator characters remain literal data. The allowlist includes ordinary reads and non-writing forms of `find` and `git`; unknown forms are blocked. In auto mode terminal commands are not scope-checked.
- The turn counter resets in `pre_llm_call`, including when the host changes the task ID. Parallel calls reserve budget atomically. Usage is reserved before execution or approval: a denied or failed call can conservatively consume budget until the next turn. Bulk moves count as removal at the source plus addition at the destination. A patch that cannot be simulated is blocked when a line budget or affected-manifest guard is active; use an exact path-based edit instead.
- State is per session: the host's session ID takes precedence over its task ID, with a process-wide fallback when both are absent. In-process child agents pass through the same hooks with separate IDs, so they use saved defaults and a fresh counter, not the parent's unsaved overrides. Save the intended defaults before delegating. Session isolation is tested without spawning an agent; the child dispatch path is also checked against host source. An external agent process must load the plugin separately.
- Messages to the model are short and actionable: what was blocked, which knob, what to do instead.

## Not a sandbox

Mixer sees tool calls, not system calls. A terminal command, a script or a subprocess can still write anywhere: in `auto` mode, `echo x > /etc/hosts` is not scope-checked, `execute_code` can write anything, and any Python the agent runs is unrestricted. The deps guard watches the listed manifests and install commands only, so copying a requirements file, vendoring, or an install helper it does not recognise will pass. The lines budget is a count of the tool calls Mixer can see, not a guarantee about total repository churn. For hard isolation use Hermes' container backends, or run with `approvals.mode` that suits you and `/yolo` only when you mean it.

## Plan mode

`/mixer edits plan` is a tool-level gate, not a prompt convention:

- It blocks `write_file`, `patch` and `execute_code` outright, and limits `terminal` to read-only commands, so the agent can explore but not change anything through the tools it can see.
- Hermes' built-in plan skill writes a plan file but does not block tools; Claude Code's plan mode is a host feature of a different product. Mixer's plan mode is enforced inside `pre_tool_call` of THIS agent, whatever the model promises in prose.
- To leave it: `/mixer edits auto` (or `ask`), or `/mixer reset`. A `/yolo` or `approvals.mode: off` session bypasses Mixer's `ask` approvals (the approve directive runs through Hermes' gate, which yolo skips) - plan mode blocks still apply, because they are block directives, not approvals.