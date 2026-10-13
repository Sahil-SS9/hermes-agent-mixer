"""Hermes panel-to-hook integration over the shared file store."""
from pathlib import Path
import os
import subprocess
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard import plugin_api as api
from hermes_agent_mixer.hermes import plugin, storage, host
from tests.conftest import FakeCtx


@pytest.fixture
def panel(monkeypatch):
    ctx = FakeCtx()
    monkeypatch.setattr(storage, 'config_context', lambda: ctx)
    plugin.reset_mixer()
    plugin.register(ctx)
    app = FastAPI()
    app.include_router(api.router)
    yield TestClient(app), ctx
    plugin.reset_mixer()


def write_hook(sid):
    return plugin._pre_tool_call(tool_name='write_file', args={'path': 'x.txt', 'content': 'x'}, session_id=sid)


def test_panel_plan_blocks_hook_and_other_session_stays_unaffected(panel, tmp_path, monkeypatch):
    client, ctx = panel
    monkeypatch.chdir(tmp_path)
    assert client.post('/command', json={'command':'edits plan','session':'durable-A'}).json()['ok']
    assert write_hook('durable-A')['action'] == 'block'
    assert write_hook('durable-B') is None
    assert client.get('/state', params={'session':'durable-A'}).json()['dials']['edits']['value'] == 'plan'
    plugin.reset_mixer()
    ctx.commands.clear()  # host unload removes registrations before reload
    plugin.register(ctx)
    assert write_hook('durable-A')['action'] == 'block'  # reload does not lose panel policy
    assert client.post('/command', json={'command':'reset','session':'durable-A'}).json()['ok']
    assert write_hook('durable-A') is None


def test_hook_command_is_visible_in_panel(panel):
    client, _ = panel
    plugin.get_mixer().set_session('durable', 'lines', 7)
    assert client.get('/state', params={'session':'durable'}).json()['dials']['lines']['value'] == 7


def test_saved_defaults_use_host_config_not_cli_files(panel):
    client, ctx = panel
    assert client.post('/command', json={'command':'edits plan','saved':True}).json()['ok']
    assert ctx.get_config('edits') == 'plan'
    assert write_hook('new-durable')['action'] == 'block'
    assert not (Path(os.environ['HERMES_HOME'])/'plugin-data/hermes-agent-mixer/settings.json').exists()
    assert client.post('/command', json={'command':'reset','saved':True}).json()['ok'] is False


def test_session_save_uses_same_host_defaults(panel):
    client, ctx = panel
    client.post('/command', json={'command':'edits plan','session':'S'})
    assert client.post('/command', json={'command':'save','session':'S'}).json()['ok']
    assert ctx.get_config('edits') == 'plan'
    assert write_hook('T')['action'] == 'block'


def test_missing_session_and_host_refuse(panel, monkeypatch):
    client, _ = panel
    assert client.post('/command', json={'command':'edits plan'}).status_code == 400
    monkeypatch.setattr(host, 'hermes_home', lambda: None)
    assert client.post('/command', json={'command':'edits plan','session':'S'}).status_code == 503
    assert write_hook('S')['action'] == 'block'


def test_legacy_cli_override_cannot_redirect_panels(panel, monkeypatch, tmp_path):
    client, _ = panel
    separate = tmp_path/'cli-only'
    monkeypatch.setenv('AGENT_MIXER_HOME', str(separate))
    client.post('/command', json={'command':'edits plan','session':'S'})
    assert write_hook('S')['action'] == 'block'
    assert not separate.exists()


def test_other_process_reads_panel_policy(panel):
    client, _ = panel
    client.post('/command', json={'command':'edits plan','session':'S'})
    code = "from hermes_agent_mixer.hermes import plugin; assert plugin.get_mixer().effective('S')['edits']=='plan'"
    subprocess.run([sys.executable, '-c', code], check=True, cwd=Path(__file__).resolve().parents[1])


def test_unknown_command_changes_nothing(panel):
    client, _ = panel
    res=client.post('/command', json={'command':'edits plna','session':'S'}).json()
    assert not res['ok'] and res['state']['dials']['edits']['value']=='auto'


def test_context_home_changes_do_not_reuse_another_profiles_store(panel, monkeypatch, tmp_path):
    client, _ = panel
    client.post('/command', json={'command':'edits plan','session':'S'})
    monkeypatch.setattr(host, 'hermes_home', lambda: str(tmp_path/'profile-B'))
    assert write_hook('S') is None


@pytest.mark.parametrize("content", ["{broken", '{"record": null}', '{"record": {"overrides": []}}'])
def test_corrupt_shared_state_blocks_instead_of_forgetting_policy(panel, content):
    client, _ = panel
    client.post('/command', json={'command':'edits plan','session':'S'})
    path = Path(storage.state_store().path_of('S'))
    path.write_text(content)
    assert write_hook('S')['action'] == 'block'
    assert path.read_text() == content  # failed read must not overwrite the policy


def test_saved_command_writes_only_its_own_key(panel, monkeypatch):
    client, ctx = panel
    ctx.set_config('lines', 9)
    calls = []
    original = ctx.set_config
    def record(key, value):
        calls.append(key)
        original(key, value)
    monkeypatch.setattr(ctx, 'set_config', record)
    assert client.post('/command', json={'command':'edits plan','saved':True}).json()['ok']
    assert calls == ['edits'] and ctx.get_config('lines') == 9


def test_scope_panel_setting_is_enforced_by_hook(panel, tmp_path, monkeypatch):
    client, _ = panel
    monkeypatch.chdir(tmp_path)
    assert client.post('/command', json={'command':'scope add src/**','session':'S'}).json()['ok']
    result = plugin._pre_tool_call(tool_name='write_file', args={'path':'outside.txt','content':'x'}, session_id='S')
    assert result is not None and result['action'] == 'block'
