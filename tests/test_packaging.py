"""Distribution metadata: no runtime libraries and a non-deprecated MIT licence."""
from pathlib import Path
import tomllib


def test_distribution_metadata_is_standard_library_only_and_spdx_licensed():
    data = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text())
    assert data["project"]["dependencies"] == []
    assert data["project"]["license"] == "MIT"
    assert data["project"]["entry-points"]["hermes_agent.plugins"]["hermes-agent-mixer"] == "hermes_agent_mixer"
