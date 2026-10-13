"""Real upstream PluginContext and panel API, isolated from the user's config."""
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.native
def test_real_host_config_and_cross_process_panel_policy(tmp_path):
    upstream = os.environ.get('MIXER_UPSTREAM_ROOT')
    if not upstream:
        pytest.skip('set MIXER_UPSTREAM_ROOT to a read-only upstream checkout')
    repo = Path(__file__).resolve().parents[1]
    env = dict(os.environ, HERMES_HOME=str(tmp_path/'home'),
               PYTHONPATH=os.pathsep.join([str(repo), upstream]))
    env.pop('AGENT_MIXER_HOME', None)
    script = '''
from pathlib import Path
import os, subprocess, sys
from dashboard import plugin_api as api
from hermes_agent_mixer.hermes import plugin, storage
ctx=storage.config_context()
assert ctx.__class__.__module__=='hermes_cli.plugins'
plugin.register(ctx)
# Native defaults writer; no fake config or substitute JSON file.
assert api.post_command(api.CommandBody(command='lines 4', saved=True))['ok']
assert ctx.get_config('lines')==4
assert Path(os.environ['HERMES_HOME'], 'config.yaml').is_file()
assert plugin.get_mixer().effective('NEW')['lines']==4
assert api.post_command(api.CommandBody(command='edits plan', session='durable-S'))['ok']
code="from hermes_agent_mixer.hermes import plugin; r=plugin._pre_tool_call(tool_name='write_file', args={'path':'blocked.txt','content':'x'}, session_id='durable-S'); assert r['action']=='block',r; print('fresh-process hook BLOCK')"
subprocess.run([sys.executable, '-c', code], check=True)
assert api.post_command(api.CommandBody(command='save', session='durable-S'))['ok']
assert ctx.get_config('edits')=='plan'
assert plugin._pre_tool_call(tool_name='write_file', args={'path':'x','content':'x'}, session_id='NEW')['action']=='block'
print('real host defaults + cross-process session enforcement PASS')
'''
    result = subprocess.run([sys.executable, '-c', script], env=env, cwd=tmp_path,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode==0, result.stdout+'\n'+result.stderr
    print(result.stdout)
