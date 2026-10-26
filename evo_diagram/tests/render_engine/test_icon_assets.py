from __future__ import annotations

import json

from evo_diagram.agentic_system.common import icon_assets
from evo_diagram.agentic_system.render_engine.excalidraw import converter as excalidraw_converter
from evo_diagram.agentic_system.render_engine.tldraw.converter import (
    InstantiationToTldrawConverter,
)


def _use_icon_root(monkeypatch, tmp_path):
    root = tmp_path / "material-design-icons"
    root.mkdir()
    monkeypatch.setattr(icon_assets, "icon_assets_root", lambda: root)
    icon_assets.manifest_icon_names.cache_clear()
    return root


def test_icon_asset_helpers_format_canonical_url_and_legacy_hints():
    base_url = "http://localhost:3000/icons/material-design-icons/{color}/{icon}.svg"

    assert (
        icon_assets.format_icon_url("settings.svg", "light-violet", base_url)
        == "http://localhost:3000/icons/material-design-icons/light_violet/settings.svg"
    )
    assert (
        icon_assets.format_icon_url("nested/cloud.svg", "teal", base_url)
        == "http://localhost:3000/icons/material-design-icons/light_blue/cloud.svg"
    )
    assert (
        icon_assets.icon_folder_hint(
            "http://localhost:3000/icons/material-design-icons/light_blue/cloud.svg"
        )
        == "light_blue"
    )
    assert (
        icon_assets.icon_folder_hint("http://localhost:3000/material-icons/filled/cloud.svg")
        == "filled"
    )


def test_manifest_icon_names_are_loaded_from_tool_service_manifest(monkeypatch, tmp_path):
    root = _use_icon_root(monkeypatch, tmp_path)
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "colors": {
                    "blue": {
                        "icons": [
                            {"name": "settings"},
                            {"name": "cloud_queue"},
                        ],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    icon_assets.manifest_icon_names.cache_clear()

    assert icon_assets.icon_name_exists("settings")
    assert icon_assets.icon_name_exists("cloud_queue")
    assert not icon_assets.icon_name_exists("not_in_manifest")


def test_resolve_icon_svg_path_uses_canonical_color_then_fallback_folder(
    monkeypatch,
    tmp_path,
):
    root = _use_icon_root(monkeypatch, tmp_path)
    (root / "blue").mkdir()
    (root / "filled").mkdir()
    canonical = root / "blue" / "settings.svg"
    legacy = root / "filled" / "settings.svg"
    canonical.write_text("<svg />", encoding="utf-8")
    legacy.write_text("<svg />", encoding="utf-8")

    assert icon_assets.resolve_icon_svg_path("settings", ["blue", "filled"]) == canonical
    assert icon_assets.resolve_icon_svg_path("settings.svg", ["filled"]) == legacy


def test_require_icon_assets_available_fails_without_generated_svgs(monkeypatch, tmp_path):
    import pytest

    root = _use_icon_root(monkeypatch, tmp_path)
    (root / "manifest.json").write_text('{"colors": {}}', encoding="utf-8")

    with pytest.raises(RuntimeError, match="no Material icon SVG files"):
        icon_assets.require_icon_assets_available()


def test_require_icon_assets_available_accepts_manifest_and_svg(monkeypatch, tmp_path):
    root = _use_icon_root(monkeypatch, tmp_path)
    (root / "manifest.json").write_text(
        json.dumps({"colors": {"blue": {"icons": [{"name": "settings"}]}}}),
        encoding="utf-8",
    )
    (root / "blue").mkdir()
    (root / "blue" / "settings.svg").write_text("<svg />", encoding="utf-8")

    icon_assets.require_icon_assets_available()


def test_excalidraw_icon_resolver_uses_shared_canonical_asset_root(
    monkeypatch,
    tmp_path,
):
    root = _use_icon_root(monkeypatch, tmp_path)
    (root / "light_violet").mkdir()
    icon_path = root / "light_violet" / "settings.svg"
    icon_path.write_text("<svg />", encoding="utf-8")

    resolved = icon_assets.require_icon_svg_path(
        "settings",
        icon_color="light-violet",
    )

    assert resolved == icon_path


def test_excalidraw_icon_resolver_accepts_legacy_material_icons_url_hint(
    monkeypatch,
    tmp_path,
):
    root = _use_icon_root(monkeypatch, tmp_path)
    (root / "filled").mkdir()
    icon_path = root / "filled" / "settings.svg"
    icon_path.write_text("<svg />", encoding="utf-8")

    resolved = icon_assets.require_icon_svg_path(
        "settings",
        icon_url="http://localhost:3000/material-icons/filled/settings.svg",
    )

    assert resolved == icon_path


def test_tldraw_icon_file_check_uses_shared_canonical_asset_root(
    monkeypatch,
    tmp_path,
):
    root = _use_icon_root(monkeypatch, tmp_path)
    (root / "light_blue").mkdir()
    (root / "light_blue" / "cloud.svg").write_text("<svg />", encoding="utf-8")
    converter = object.__new__(InstantiationToTldrawConverter)

    assert converter._require_icon_file_exists(
        {
            "props": {
                "icon": "cloud",
                "color": "teal",
            }
        },
        element_id="node:cloud:icon",
    ) is None


def test_excalidraw_icon_conversion_fails_for_missing_svg_asset(monkeypatch, tmp_path):
    import pytest

    _use_icon_root(monkeypatch, tmp_path)

    with pytest.raises(RuntimeError, match="Icon asset not found.*node:svc:icon"):
        excalidraw_converter._icon_to_data_url(
            {
                "props": {
                    "icon": "settings",
                    "color": "light-violet",
                }
            },
            element_id="node:svc:icon",
        )


def test_tldraw_icon_conversion_fails_for_missing_svg_asset(monkeypatch, tmp_path):
    import pytest

    _use_icon_root(monkeypatch, tmp_path)
    converter = object.__new__(InstantiationToTldrawConverter)

    with pytest.raises(RuntimeError, match="Icon asset not found.*node:svc:icon"):
        converter._require_icon_file_exists(
            {
                "props": {
                    "icon": "settings",
                    "color": "light-violet",
                }
            },
            element_id="node:svc:icon",
        )
