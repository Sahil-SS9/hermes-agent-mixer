"""The steering console (X8): server wiring, API behaviour and the page asset."""
from __future__ import annotations

import json
import threading
import urllib.request

import pytest


def _pick_free_port() -> int:
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Server:
    """Run `agent-mixer ui` in a daemon thread against the rig's throwaway home."""

    def __init__(self, rig, argv: list[str]) -> None:
        port = _pick_free_port()
        self.url = f"http://127.0.0.1:{port}"
        self.thread = threading.Thread(
            target=lambda: rig.run(["ui", "--port", str(port), "--no-open", *argv], cwd=rig.proj),
            daemon=True)
        self.thread.start()

    def get(self, path: str, headers: dict | None = None) -> tuple[int, bytes, dict]:
        request = urllib.request.Request(self.url + path, headers=headers or {})
        try:
            with urllib.request.urlopen(request, timeout=5) as resp:
                return resp.status, resp.read(), dict(resp.headers)
        except urllib.error.HTTPError as err:
            return err.code, err.read(), dict(err.headers)

    def post(self, path: str, payload: dict, headers: dict | None = None) -> tuple[int, dict | bytes]:
        data = json.dumps(payload).encode()
        request = urllib.request.Request(self.url + path, data=data, method="POST",
                                         headers={"Content-Type": "application/json", **(headers or {})})
        try:
            with urllib.request.urlopen(request, timeout=5) as resp:
                body = resp.read()
                return resp.status, json.loads(body) if body.strip() else {}
        except urllib.error.HTTPError as err:
            body = err.read()
            if err.code == 404:
                return 404, {}
            return err.code, json.loads(body or b"{}")


def _wait_server(server: Server, timeout: float = 5.0) -> None:
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            code, _, _ = server.get("/")
            if code == 200:
                return
        except Exception:  # noqa: BLE001 - not up yet
            time.sleep(0.05)
    pytest.fail("ui server did not come up")


@pytest.fixture
def ui(rig):
    server = Server(rig, ["--session", "SESS1"])
    _wait_server(server)
    yield server


def _token(server: Server) -> str:
    code, html, _ = server.get("/")
    assert code == 200
    marker = 'const TOKEN = "'
    start = html.decode().index(marker) + len(marker)
    return html.decode()[start:html.decode().index('"', start)]


def test_page_serves_with_the_console_design(ui):
    code, html, headers = ui.get("/")
    text = html.decode()
    assert code == 200
    assert headers["Content-Type"].startswith("text/html")
    assert "__TOKEN__" not in text  # the placeholder was replaced
    for expected in ("AGENT MIXER", "// STEERING CONSOLE", "STEERING POLICY (PREVIEW)",
                     "Copy steering policy", "Open in terminal", "LESS CONSERVATIVE",
                     "MORE PERMISSIVE", "New libraries"):
        assert expected in text


def test_state_reports_the_session_dials(ui):
    code, body, headers = ui.get("/api/state")
    assert code == 200 and headers["Content-Type"].startswith("application/json")
    data = json.loads(body)
    assert data["session"] == "SESS1"
    assert data["dials"]["edits"]["value"] == "auto"
    assert data["dials"]["edits"]["source"] == "default"
    assert data["dials"]["deps"]["value"] == "ask"


def test_command_changes_a_dial_and_state_follows(ui):
    token = _token(ui)
    code, data = ui.post("/api/command", {"token": token, "command": "edits plan"})
    assert code == 200 and data["ok"] and "plan" in data["reply"]
    code, body, _ = ui.get("/api/state")
    assert json.loads(body)["dials"]["edits"]["value"] == "plan"
    # and the change is real: the hook path sees the same session state
    code, data = ui.post("/api/command", {"token": token, "command": "lines 30"})
    _, body, _ = ui.get("/api/state")
    assert json.loads(body)["dials"]["lines"]["value"] == 30


def test_bad_command_reports_and_does_not_crash(ui):
    token = _token(ui)
    code, data = ui.post("/api/command", {"token": token, "command": "edits plna"})
    assert code == 200 and data["ok"] is False and "unknown" in data["reply"].lower()
    code, body, _ = ui.get("/api/state")
    assert json.loads(body)["dials"]["edits"]["value"] == "auto"


def test_post_without_the_token_is_refused(ui):
    code, _data = ui.post("/api/command", {"token": "wrong", "command": "edits plan"})
    assert code == 403
    code, body, _ = ui.get("/api/state")
    assert json.loads(body)["dials"]["edits"]["value"] == "auto"


def test_cross_origin_state_request_is_refused(ui):
    code, _, _ = ui.get("/api/state", headers={"Origin": "http://evil.example",
                                               "Sec-Fetch-Site": "cross-site"})
    assert code == 403


def test_unknown_paths_404(ui):
    assert ui.get("/nope")[0] == 404
    code, _body = ui.post("/nope", {"token": "x"})
    assert code == 404


def test_long_command_is_rejected(ui):
    token = _token(ui)
    code, _ = ui.post("/api/command", {"token": token, "command": "x" * 501})
    assert code == 400


def test_ui_refuses_without_any_session(rig):
    rc, _out, err = rig.run(["ui", "--port", str(_pick_free_port()), "--no-open"])
    assert rc == 1
    assert "no session" in err


def test_ui_saved_mode(rig):
    rig.run(["--saved", "edits", "plan"])
    server = Server(rig, ["--saved"])
    _wait_server(server)
    _code, body, _ = server.get("/api/state")
    data = json.loads(body)
    assert data["saved_mode"] and data["session"] == "saved settings"
    assert data["dials"]["edits"]["value"] == "plan"


def test_page_asset_is_self_contained_and_token_free():
    from hermes_agent_mixer import ui_asset

    text = ui_asset.PAGE
    assert "__TOKEN__" in text  # the template keeps its slot
    assert "<script" in text and "</html>" in text.strip().lower() or "</html>" in text
    for banned in ("localhost:", "file://", "TODO"):
        assert banned not in text


def test_usage_lists_ui():
    from hermes_agent_mixer import cli

    assert "agent-mixer ui" in cli.USAGE
