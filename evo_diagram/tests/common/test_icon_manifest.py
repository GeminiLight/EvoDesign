"""Icon manifest integrity contract.

``manifest_icon_names()`` must not report "no manifest installed" (which is
permissive) when the tracked manifest exists but cannot be trusted.
"""

from __future__ import annotations

import json

import pytest

from evo_diagram.agentic_system.common import icon_assets


def _use_icon_root(monkeypatch, tmp_path):
    root = tmp_path / "material-design-icons"
    root.mkdir()
    monkeypatch.setattr(icon_assets, "icon_assets_root", lambda: root)
    icon_assets.manifest_icon_names.cache_clear()
    return root


@pytest.fixture(autouse=True)
def _clear_manifest_cache():
    icon_assets.manifest_icon_names.cache_clear()
    yield
    icon_assets.manifest_icon_names.cache_clear()


def test_missing_manifest_stays_permissive(monkeypatch, tmp_path):
    _use_icon_root(monkeypatch, tmp_path)

    assert icon_assets.manifest_icon_names() == frozenset()
    assert icon_assets.icon_name_exists("anything") is True


def test_corrupt_manifest_raises_instead_of_allowing_every_name(monkeypatch, tmp_path):
    root = _use_icon_root(monkeypatch, tmp_path)
    (root / "manifest.json").write_text('{"colors": {"blue": ', encoding="utf-8")

    with pytest.raises(icon_assets.IconManifestError, match="unreadable"):
        icon_assets.manifest_icon_names()

    with pytest.raises(icon_assets.IconManifestError):
        icon_assets.icon_name_exists("made_up_icon")


def test_manifest_without_icon_names_raises(monkeypatch, tmp_path):
    root = _use_icon_root(monkeypatch, tmp_path)
    (root / "manifest.json").write_text('{"colors": {}}', encoding="utf-8")

    with pytest.raises(icon_assets.IconManifestError, match="no icon names"):
        icon_assets.manifest_icon_names()


def test_manifest_failure_is_not_cached_for_the_process(monkeypatch, tmp_path):
    root = _use_icon_root(monkeypatch, tmp_path)
    manifest_path = root / "manifest.json"
    manifest_path.write_text("not json", encoding="utf-8")

    with pytest.raises(icon_assets.IconManifestError):
        icon_assets.manifest_icon_names()

    manifest_path.write_text(
        json.dumps({"colors": {"blue": {"icons": [{"name": "settings"}]}}}),
        encoding="utf-8",
    )

    assert icon_assets.manifest_icon_names() == frozenset({"settings"})


def test_require_icon_assets_available_rejects_corrupt_manifest(monkeypatch, tmp_path):
    root = _use_icon_root(monkeypatch, tmp_path)
    (root / "manifest.json").write_text("{broken", encoding="utf-8")
    (root / "blue").mkdir()
    (root / "blue" / "settings.svg").write_text("<svg />", encoding="utf-8")

    with pytest.raises(icon_assets.IconManifestError, match="unreadable"):
        icon_assets.require_icon_assets_available()
