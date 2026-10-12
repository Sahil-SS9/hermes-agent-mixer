"""The agent-mixer steering console: a tiny localhost web UI over the real dial store (X8).

    agent-mixer ui [--session ID | --saved] [--port N] [--no-open]

One HTML page (ui_asset.py) + a JSON API. The UI is a view and a remote control for the same
grammar the CLI exposes: every change goes through core.board, so the console can never drift
from the CLI or the /mixer command. Standard library only; binds 127.0.0.1 by default.

Security posture: this is a local control panel for the dials. It binds loopback, refuses
Cross-Origin requests, and performs no writes beyond what the dial grammar already allows.
"""
from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

USAGE = "Usage: agent-mixer ui [--session ID | --saved] [--port N] [--no-open]"

_HTML_TYPE = "text/html; charset=utf-8"
_JSON_TYPE = "application/json; charset=utf-8"


def _session_target(paths, session: str | None, saved_mode: bool):
    """Build the board Target the same way cli._command does."""
    from hermes_agent_mixer.core import board
    from hermes_agent_mixer.core.store import file_lock
    from hermes_agent_mixer.core.targets import SavedTarget, SessionTarget
    from hermes_agent_mixer.harness.common import load_saved, make_mixer, store_saved

    if saved_mode:
        def read():
            return load_saved(paths)

        def write(data):
            with file_lock(paths.settings_file + ".lock"):
                store_saved(paths, data)

        return SavedTarget(read, write)
    mixer = make_mixer(paths)
    if not session:
        session = mixer.latest_session(os.getcwd())
    if not session:
        raise board.Refusal(
            "no session has been seen in this folder yet. Pass --session ID, start an agent here, "
            "or use --saved to edit the saved defaults.")
    return SessionTarget(mixer, session, write_saved=lambda k, v: _update_saved(paths, k, v))


def _update_saved(paths, key: str, value) -> None:
    from hermes_agent_mixer.harness.common import update_saved

    update_saved(paths, key, value)


def api_state(target, paths) -> dict:
    """Everything the page needs for one render: dials, sources, warnings, session name, versions."""
    from hermes_agent_mixer import __version__
    from hermes_agent_mixer.core import board, settings

    eff = target.effective()
    lines = eff.values["lines"]
    return {
        "session": target.name,
        "saved_mode": target.name == "saved settings",
        "version": __version__,
        "dials": {
            "edits": {"value": eff.values["edits"], "source": eff.sources["edits"],
                      "choices": list(settings.EDIT_MODES)},
            "deps": {"value": eff.values["deps"], "source": eff.sources["deps"],
                     "choices": list(settings.DEPS_MODES)},
            "lines": {"value": lines, "source": eff.sources["lines"],
                      "left": eff.left, "off": lines == 0},
            "scope": {"value": eff.values["scope"], "source": eff.sources["scope"]},
            "extra_write_tools": {"value": eff.values["extra_write_tools"],
                                  "source": eff.sources["extra_write_tools"]},
        },
        "warnings": list(eff.warnings),
        "board": board.render_board(eff, target.name),
    }


def api_command(target, raw_args: str) -> dict:
    """One /mixer-grammar command; the reply text is shown in the console log."""
    from hermes_agent_mixer.core import board

    reply = board.handle_command(raw_args, target)
    return {"reply": reply, "ok": not reply.lower().startswith(("unknown", "usage")) and "needs" not in reply.lower()}


def _body(handler: BaseHTTPRequestHandler) -> bytes:
    length = int(handler.headers.get("Content-Length") or 0)
    return handler.rfile.read(length) if length else b""


def _send(handler: BaseHTTPRequestHandler, code: int, body: bytes, ctype: str) -> None:
    handler.send_response(code)
    handler.send_header("Content-Type", ctype)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    if handler.command != "HEAD":
        handler.wfile.write(body)


def make_handler(target, paths, token: str):
    class Handler(BaseHTTPRequestHandler):
        server_version = "agent-mixer"
        sys_version = ""

        def log_message(self, fmt, *args):  # quiet: the console prints its own log
            pass

        def _origin_ok(self) -> bool:
            """Block cross-origin browsers: no Origin/Sec-Fetch-Site means curl or same-origin."""
            origin = self.headers.get("Origin")
            site = self.headers.get("Sec-Fetch-Site")
            host = self.headers.get("Host") or ""
            if origin:
                return origin == f"http://{host}"
            return site in (None, "same-origin", "same-site", "none")

        def do_GET(self) -> None:
            url = urlparse(self.path)
            if url.path == "/":
                from hermes_agent_mixer import ui_asset

                body = ui_asset.PAGE.replace("__TOKEN__", token).encode("utf-8")
                _send(self, 200, body, _HTML_TYPE)
                return
            if url.path != "/api/state":
                _send(self, 404, b"not found", "text/plain; charset=utf-8")
                return
            if not self._origin_ok():
                _send(self, 403, b"cross-origin refused", "text/plain; charset=utf-8")
                return
            _send(self, 200, json.dumps(api_state(target, paths)).encode("utf-8"), _JSON_TYPE)

        def do_POST(self) -> None:
            url = urlparse(self.path)
            if url.path != "/api/command":
                _send(self, 404, b"not found", "text/plain; charset=utf-8")
                return
            if not self._origin_ok():
                _send(self, 403, b"cross-origin refused", "text/plain; charset=utf-8")
                return
            try:
                payload = json.loads(_body(self) or b"{}")
            except ValueError:
                _send(self, 400, json.dumps({"error": "bad JSON"}).encode("utf-8"), _JSON_TYPE)
                return
            if payload.get("token") != token:
                _send(self, 403, json.dumps({"error": "bad token"}).encode("utf-8"), _JSON_TYPE)
                return
            raw = str(payload.get("command") or "")
            if len(raw) > 500:
                _send(self, 400, json.dumps({"error": "command too long"}).encode("utf-8"), _JSON_TYPE)
                return
            try:
                result = api_command(target, raw)
            except Exception as exc:  # noqa: BLE001 - show the failure in the UI, never crash the server
                result = {"reply": f"agent-mixer: {type(exc).__name__}: {exc}", "ok": False}
            _send(self, 200, json.dumps(result).encode("utf-8"), _JSON_TYPE)

    return Handler


def run(argv: list[str], environ, here: str) -> int:
    import secrets
    import threading
    import webbrowser

    from hermes_agent_mixer.harness.common import Paths

    session: str | None = None
    saved_mode = False
    port = 8377
    open_browser = True
    rest = list(argv)
    while rest:
        flag = rest.pop(0)
        if flag == "--session" and rest:
            session = rest.pop(0)
        elif flag == "--saved":
            saved_mode = True
        elif flag == "--port" and rest:
            try:
                port = int(rest.pop(0))
            except ValueError:
                print(f"agent-mixer ui: --port needs a number\n{USAGE}", file=sys.stderr)
                return 2
        elif flag == "--no-open":
            open_browser = False
        else:
            print(f"agent-mixer ui: unknown argument '{flag}'\n{USAGE}", file=sys.stderr)
            return 2
    if saved_mode and session:
        print("agent-mixer ui: choose either --saved or --session, not both", file=sys.stderr)
        return 2
    paths = Paths(environ)
    try:
        target = _session_target(paths, session, saved_mode)
    except Exception as exc:  # noqa: BLE001 - the user gets the message, not a traceback
        print(f"agent-mixer ui: {exc}", file=sys.stderr)
        return 1
    token = secrets.token_urlsafe(24)
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(target, paths, token))
    except OSError as exc:
        print(f"agent-mixer ui: cannot bind 127.0.0.1:{port} ({exc}); try --port N", file=sys.stderr)
        return 1
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    where = target.name if saved_mode else f"session {target.name}"
    print(f"Agent Mixer console ({where}) at {url}  (Ctrl-C to stop)")
    if open_browser and environ.get("DISPLAY") is not None and not environ.get("SSH_CONNECTION"):
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nAgent Mixer console stopped.")
    finally:
        server.server_close()
    return 0
