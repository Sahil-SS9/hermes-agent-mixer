"""Runs INSIDE the sandbox Hermes interpreter (``hermes --run-module unittest discover``).

Loads Agent Mixer through the real Hermes plugin loader (``PluginManager.discover_and_load``) and drives
the real hook dispatch (``manager.invoke_hook``) and the real registered ``/mixer`` handler on each
surface. The session binding mirrors upstream/main (Hermes calls these the same way):

* cli      gateway/session_context.py:81 ``set_current_session_id`` publishes ``HERMES_SESSION_ID`` to
           ``os.environ``; the classic CLI binds no ContextVars.
* tui      tui_gateway/server.py:1374 ``set_session_vars(session_key=..., session_id=..., source=...)``.
* gateway  gateway/run.py:4204-4227 ``_set_session_env`` -> ``set_session_vars(platform=..., chat_id=...,
           session_key=...)``: the key is bound and ``HERMES_SESSION_ID`` is bound to ``""``; the same
           binding wraps plugin commands (``_session_env_scope``, line 4235) and the agent turn.
* subagent tools/delegate_tool.py:327-335 ``invoke_hook("subagent_start", parent_session_id=...,
           parent_turn_id=..., parent_subagent_id=..., child_session_id=..., child_subagent_id=...,
           child_role=..., child_goal=...)``.

Each surface prints ``NATIVE HOST PASS <surface> <short sha>``. No model calls, agents or live config.
"""
import os
import unittest

from gateway.session_context import clear_session_vars, reset_session_vars, set_session_vars
from hermes_cli.plugins import PluginManager

SHA = os.environ.get("MIXER_REPO_SHA", "unknown")
WRITE = {"path": "src/new.py", "content": "x\n"}


class NativeHost(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manager = PluginManager()
        cls.manager.discover_and_load()
        loaded = cls.manager._plugins["hermes-agent-mixer"]
        if loaded.error:
            raise AssertionError(f"plugin failed to load: {loaded.error}")
        cls.command = staticmethod(cls.manager._plugin_commands["mixer"]["handler"])

    def setUp(self):
        reset_session_vars()  # back to "never bound" (gateway/session_context.py), as in a fresh CLI process

    # -- helpers ---------------------------------------------------------------------
    def tool(self, name, args, session, task="task-1", turn="t1"):
        return self.manager.invoke_hook("pre_tool_call", tool_name=name, args=args, task_id=task,
                                        session_id=session, tool_call_id="call-1", turn_id=turn)

    def begin(self, session, turn="t1", parent="", platform="cli"):
        return self.manager.invoke_hook("pre_llm_call", session_id=session, task_id="task-1", turn_id=turn,
                                        user_message="go", conversation_history=[], is_first_turn=turn == "t1",
                                        model="m", platform=platform, parent_session_id=parent, sender_id="")

    def verdict(self, results):
        return results[0]["action"] if results else "allow"

    def done(self, surface):
        print(f"NATIVE HOST PASS {surface} {SHA}", flush=True)

    # -- surfaces ----------------------------------------------------------------------
    def test_cli(self):
        os.environ["HERMES_SESSION_ID"] = "native-cli-1"
        try:
            self.assertIn("Agent Mixer", self.command(""))
            self.command("edits plan")
            self.begin("native-cli-1")
            self.assertEqual(self.verdict(self.tool("write_file", WRITE, "native-cli-1")), "block")
            os.environ["HERMES_SESSION_ID"] = "native-cli-2"  # /new
            self.begin("native-cli-2")
            self.assertEqual(self.verdict(self.tool("write_file", WRITE, "native-cli-2")), "allow")
            self.assertIn("(default)", self.command(""))
        finally:
            os.environ.pop("HERMES_SESSION_ID", None)
        self.done("cli")

    def test_tui(self):
        def bound(key, session):
            return set_session_vars(session_key=key, session_id=session, source="tui", cron_session="")

        tokens = bound("native-tui-key-1", "native-tui-1")
        try:
            self.assertIn("native-tui-1", self.command("edits plan"))
            self.begin("native-tui-1", platform="tui")
            self.assertEqual(self.verdict(self.tool("write_file", WRITE, "native-tui-1")), "block")
        finally:
            clear_session_vars(tokens)
        tokens = bound("native-tui-key-2", "native-tui-2")
        try:
            self.begin("native-tui-2", platform="tui")
            self.assertEqual(self.verdict(self.tool("write_file", WRITE, "native-tui-2")), "allow")
        finally:
            clear_session_vars(tokens)
        self.done("tui")

    def test_gateway(self):
        os.environ["HERMES_SESSION_ID"] = "native-gw-leftover"  # the last agent built: chat B's
        key_a, key_b = "agent:main:discord:group:111", "agent:main:discord:group:222"

        def bound(key):
            return set_session_vars(platform="discord", chat_id=key[-3:], chat_type="group", session_key=key,
                                    cron_session="")  # session_id is left at its "" default

        try:
            tokens = bound(key_a)
            try:
                reply = self.command("edits plan")  # a plugin command before chat A's first turn
            finally:
                clear_session_vars(tokens)
            self.assertNotIn("native-gw-leftover", reply)
            self.assertIn(key_a, reply)
            tokens = bound(key_a)
            try:
                self.begin("native-gw-a", platform="discord")
                self.assertEqual(self.verdict(self.tool("write_file", WRITE, "native-gw-a")), "block")
            finally:
                clear_session_vars(tokens)
            tokens = bound(key_b)
            try:
                self.begin("native-gw-b", platform="discord")
                self.assertEqual(self.verdict(self.tool("write_file", WRITE, "native-gw-b")), "allow")
            finally:
                clear_session_vars(tokens)
            tokens = bound(key_b)
            try:  # a mid-conversation command from chat B reaches B and not A
                self.command("deps block")
                self.begin("native-gw-b", turn="t2", platform="discord")
                self.assertIn("(session)", self.command(""))
            finally:
                clear_session_vars(tokens)
            tokens = bound(key_a)
            try:
                self.assertIn("[ACTIVE] plan", self.command(""))
            finally:
                clear_session_vars(tokens)
            tokens = bound(key_b)
            try:
                self.assertIn("[ACTIVE] block", self.command(""))
            finally:
                clear_session_vars(tokens)
        finally:
            os.environ.pop("HERMES_SESSION_ID", None)
        self.done("gateway")

    def test_subagent(self):
        tokens = set_session_vars(session_key="native-sa-key", session_id="native-sa-parent", source="tui", cron_session="")
        try:
            self.command("lines 5")
            self.begin("native-sa-parent", turn="p-t1", platform="tui")
            three = "1\n2\n3\n"
            self.assertEqual(self.verdict(self.tool("write_file", {"path": "src/a.py", "content": three},
                                                    "native-sa-parent", turn="p-t1")), "allow")
            self.manager.invoke_hook("subagent_start", parent_session_id="native-sa-parent", parent_turn_id="p-t1",
                                     parent_subagent_id="", child_session_id="native-sa-child",
                                     child_subagent_id="sa-1", child_role="leaf", child_goal="probe")
        finally:
            clear_session_vars(tokens)
        # the child runs in its own task without the parent's context
        result = self.tool("write_file", {"path": "src/b.py", "content": three}, "native-sa-child", task="child-task",
                           turn="c-t1")
        self.assertEqual(self.verdict(result), "block")  # 3 + 3 > 5: the budget is shared
        self.assertIn("mixer:lines", result[0]["message"])
        self.manager.invoke_hook("subagent_stop", parent_session_id="native-sa-parent", child_session_id="native-sa-child")
        self.done("subagent")

    def test_z_settings_round_trip_through_the_real_config_writer(self):
        os.environ["HERMES_SESSION_ID"] = "native-save-1"
        try:
            self.command("edits ask")
            self.command("lines 12")
            self.assertIn("saved", self.command("save"))
            self.assertIn("saved", self.command("save deps block"))
            from hermes_cli.config import load_config_readonly

            saved = load_config_readonly()["plugins"]["entries"]["hermes-agent-mixer"]["settings"]
            self.assertEqual(saved["edits"], "ask")
            self.assertEqual(saved["lines"], 12)
            self.assertEqual(saved["deps"], "block")
            self.assertIn("(saved)", self.command("show"))
        finally:
            os.environ.pop("HERMES_SESSION_ID", None)
        print(f"NATIVE HOST PASS settings {SHA}", flush=True)
