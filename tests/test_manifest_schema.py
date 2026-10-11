"""Saved line budgets use one host-supported type for both N and off.

Unit tests cover the plugin's real save/reset behaviour. The complementary
native test uses Hermes' actual YAML loader, schema validator and settings writer.
No imitation YAML parser or copied host type validator is used here.
"""
from pathlib import Path

import pytest

from hermes_agent_mixer.core import board, settings
from hermes_agent_mixer.core.mixer import Mixer


@pytest.mark.parametrize('value,normalised', [('off', 'off'), ('120', 120)])
def test_saved_line_value_is_text_and_reload_preserves_policy(value, normalised):
    stored = {}
    mixer = Mixer(config_get=lambda key, default=None: stored.get(key, default))
    board.handle_command('lines ' + value, mixer, 's')
    assert mixer.settings_for('s')['lines'] == normalised
    assert 'saved' in board.handle_command('save', mixer, 's', save=stored.__setitem__)
    assert stored['lines'] == value
    assert isinstance(stored['lines'], str)
    board.handle_command('lines 1' if value == 'off' else 'lines off', mixer, 's')
    board.handle_command('reset', mixer, 's')
    assert mixer.settings_for('s')['lines'] == normalised
    assert Mixer(config_get=lambda key, default=None: stored.get(key, default)).settings_for('new')['lines'] == normalised


def test_manifest_declares_text_for_line_setting():
    # Narrow check of this repository's authored block, not a YAML parser.
    # Actual parsing/type admission is exercised by the native-host test.
    text = (Path(__file__).resolve().parents[1] / 'plugin.yaml').read_text()
    block = text.split('\n  lines:\n', 1)[1].split('\n  deps:\n', 1)[0]
    assert '    type: str\n' in block
    assert '    default: "off"\n' in block
    assert settings.defaults()['lines'] == 'off'
