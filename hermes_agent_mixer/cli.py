"""The ``agent-mixer`` command (X2).

    agent-mixer [--session ID | --saved] <dial> <value>     same grammar as /mixer
    agent-mixer [--session ID] board
    agent-mixer hook claude|codex|gemini                    one hook event on stdin
    agent-mixer install|uninstall claude|codex|gemini [--project] [--yes] [--settings-json]
    agent-mixer doctor

Startup is paid on every tool call, so this module imports only the standard library's light parts;
installers, doctor and the harness adapters load on demand.
"""
from __future__ import annotations

import os
import sys

USAGE = """Usage:
  agent-mixer [--session ID | --saved] <dial> <value>   dials: edits ask|auto|plan, scope add|remove|clear <glob>,
                                                      lines N|off, deps allow|ask|block, save <dial> <value>,
                                                      preset builder|auditor|explorer|surgical (or preset show)
  agent-mixer [--session ID] board                       show the dials and where each value comes from
  agent-mixer hook claude|codex|gemini                    one hook event on stdin
  agent-mixer install|uninstall claude|codex|gemini [--project] [--yes] [--settings-json]
  agent-mixer doctor                                     check installs, settings and state
  agent-mixer ui [--session ID | --saved] [--port N] [--no-open]   the steering console in a browser
  agent-mixer --version
With neither --session nor --saved, the latest session seen in this folder is used."""

HARNESSES = ("claude", "codex", "gemini")


def _version() -> str:
    from . import __version__

    return __version__


def main(argv: list[str] | None = None, *, stdin: str | None = None, env: dict | None = None,
         cwd: str | None = None) -> int:
    """Entry point. ``stdin``, ``env`` and ``cwd`` can be passed in for tests; the console script passes none."""
    args = list(sys.argv[1:] if argv is None else argv)
    environ = os.environ if env is None else env
    here = cwd if cwd is not None else os.getcwd()
    if not args or args[0] in ("-h", "--help", "help"):
        out = sys.stdout if args else sys.stderr
        print(USAGE, file=out)
        return 0 if args else 2
    if args[0] == "--version":
        print(f"agent-mixer {_version()}")
        return 0
    if args[0] == "hook":
        return _hook(args[1:], stdin, environ)
    if args[0] in ("install", "uninstall"):
        from .harness import install

        return install.run(args[0], args[1:], environ, here)
    if args[0] == "doctor":
        from .harness import doctor

        return doctor.run(environ, here)
    if args[0] == "ui":
        from . import ui

        return ui.run(args[1:], environ, here)
    return _command(args, environ, here)


def _hook(args: list[str], stdin: str | None, environ) -> int:
    from .harness.common import HARNESSES as KNOWN
    from .harness.common import Paths, run_hook

    if len(args) != 1 or args[0] not in KNOWN:
        print(f"agent-mixer: hook needs one of {', '.join(KNOWN)}\n{USAGE}", file=sys.stderr)
        return 2
    raw = stdin if stdin is not None else sys.stdin.read()
    code, out, err = run_hook(args[0], raw, Paths(environ), environ)
    if out:
        sys.stdout.write(out)
        sys.stdout.flush()
    if err:
        sys.stderr.write(err)
    return code


class _NoSession:
    """A board target for commands that only read (preset show): refuses any change."""

    name = "no session"

    def effective(self):
        from .core import settings

        return settings.resolve({}, None, session=self.name)

    def set(self, knob, value):
        raise RuntimeError("no session")


def _command(args: list[str], environ, here: str) -> int:
    from .core import board
    from .core.targets import SavedTarget, SessionTarget
    from .harness.common import (
        Paths,
        SettingsError,
        load_saved,
        make_mixer,
        store_saved,
        update_saved,
    )

    session = None
    saved_mode = False
    rest = list(args)
    while rest and rest[0] in ("--session", "--saved"):
        flag = rest.pop(0)
        if flag == "--saved":
            saved_mode = True
        elif rest:
            session = rest.pop(0)
        else:
            print("agent-mixer: --session needs an ID", file=sys.stderr)
            return 2
    if not rest or (saved_mode and session):
        print(USAGE, file=sys.stderr)
        return 2
    if rest[0] not in ("edits", "scope", "lines", "deps", "save", "preset", "reset", "board", "show"):
        print(f"agent-mixer: unknown command '{rest[0]}'\n{USAGE}", file=sys.stderr)
        return 2
    paths = Paths(environ)
    try:
        if saved_mode:
            def write(data):
                from .core.store import file_lock

                with file_lock(paths.settings_file + ".lock"):
                    store_saved(paths, data)

            def read():
                return load_saved(paths)

            if rest[0] in ("board", "show"):
                print(board.handle_command("show", SavedTarget(read, write)))
                return 0
            print(board.handle_command(" ".join(rest), SavedTarget(read, write)))
            return 0
        mixer = make_mixer(paths)
        note = ""
        show_only = rest[0] == "preset" and (len(rest) < 2 or rest[1] in ("show", "list"))
        if session is None and not show_only:
            session = mixer.latest_session(here)
        if session is None:
            if show_only:
                # `preset show` needs no session: it lists the bundles, it changes nothing.
                print(board.handle_command(" ".join(rest), _NoSession()))
                return 0
            print("agent-mixer: no session has been seen in this folder yet. Use --session ID to name one, "
                  "or --saved to change the saved defaults.", file=sys.stderr)
            return 1
        note = f"(session {session}, the latest seen in this folder)\n"
        target = SessionTarget(mixer, session, write_saved=lambda k, v: update_saved(paths, k, v))
        print(note + board.handle_command(" ".join(rest), target))
        return 0
    except SettingsError as exc:
        print(f"agent-mixer: {exc}. Run `agent-mixer doctor`.", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - report, never traceback at the user
        print(f"agent-mixer: {type(exc).__name__}: {exc}. Run `agent-mixer doctor`.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
