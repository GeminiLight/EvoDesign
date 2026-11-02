"""The packaged defaults must stay byte-identical to the repo-root configs.

``configs/`` is what a checkout edits; ``evo_diagram/config/defaults/`` is what
an installed package falls back to. Drift silently changes behavior between the
two, so any edit must be made to both copies.
"""

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("name", ["models.yaml", "settings.yaml"])
def test_packaged_defaults_match_repo_configs(name):
    repo_copy = _REPO_ROOT / "configs" / name
    packaged_copy = _REPO_ROOT / "evo_diagram" / "config" / "defaults" / name
    assert repo_copy.read_bytes() == packaged_copy.read_bytes(), (
        f"configs/{name} and evo_diagram/config/defaults/{name} have drifted; "
        "apply the same edit to both files."
    )
