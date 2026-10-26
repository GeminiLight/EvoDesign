from __future__ import annotations

import pytest

from evo_diagram.agentic_system.common import icon_assets
from evo_diagram.agentic_system.render_engine.shared.icon_url_adder import add_icon_urls


def test_add_icon_urls_only_updates_canonical_icon_entries(monkeypatch, tmp_path):
    root = tmp_path / "material-design-icons"
    (root / "light_violet").mkdir(parents=True)
    (root / "light_violet" / "settings.svg").write_text("<svg />", encoding="utf-8")
    monkeypatch.setattr(icon_assets, "icon_assets_root", lambda: root)

    styling = {
        "node:svc:icon": {
            "type": "icon",
            "props": {"icon": "settings", "color": "light-violet"},
        },
        "node:svc_icon": {
            "type": "icon",
            "props": {"icon": "legacy", "color": "red"},
        },
        "loose_icon_payload": {
            "type": "icon",
            "props": {"icon": "loose", "color": "green"},
        },
    }

    out = add_icon_urls(
        styling,
        base_url="http://example.test/icons/material-design-icons/{color}/{icon}.svg",
    )

    assert (
        out["node:svc:icon"]["props"]["url"]
        == "http://example.test/icons/material-design-icons/light_violet/settings.svg"
    )
    assert "url" not in out["node:svc_icon"]["props"]
    assert "url" not in out["loose_icon_payload"]["props"]
    assert "url" not in styling["node:svc:icon"]["props"]


def test_add_icon_urls_fails_fast_for_missing_local_icon_asset(monkeypatch, tmp_path):
    root = tmp_path / "material-design-icons"
    root.mkdir()
    monkeypatch.setattr(icon_assets, "icon_assets_root", lambda: root)

    styling = {
        "node:svc:icon": {
            "type": "icon",
            "props": {"icon": "not_bundled_or_installed", "color": "light-violet"},
        },
    }

    with pytest.raises(RuntimeError, match="Icon asset not found.*node:svc:icon"):
        add_icon_urls(
            styling,
            base_url="http://localhost:3000/icons/material-design-icons/{color}/{icon}.svg",
        )


def test_add_icon_urls_rejects_non_material_remote_icon_templates(monkeypatch, tmp_path):
    root = tmp_path / "material-design-icons"
    root.mkdir()
    monkeypatch.setattr(icon_assets, "icon_assets_root", lambda: root)

    styling = {
        "node:svc:icon": {
            "type": "icon",
            "props": {"icon": "settings", "color": "light-violet"},
        },
    }

    with pytest.raises(ValueError, match="bundled Material icon route"):
        add_icon_urls(
            styling,
            base_url="https://cdn.example.test/icons/{color}/{icon}.svg",
        )
