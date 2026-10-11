"""Repo-root plugin entry file.

The Hermes directory-plugin loader imports this file as ``hermes_plugins.<slug>``
with the repo root as ``__path__``; siblings must therefore be imported
relatively. The absolute fallback covers the pip entry-point install and dev
checkouts where the package is importable by name.
"""


def register(ctx):
    """Delegate to the mixer package's register()."""
    try:
        from .hermes_agent_mixer.hermes.plugin import register as _register
    except ImportError:
        from hermes_agent_mixer.hermes.plugin import register as _register
    _register(ctx)