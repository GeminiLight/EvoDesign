from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from evo_diagram.agentic_system.render_engine.tldraw.validator import validate_tldraw_manifest


_REPO_ROOT = Path(__file__).resolve().parents[3]
_VALIDATOR_MODULE = "evo_diagram.agentic_system.render_engine.tldraw.validator"


def _run_validator_cli(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = str(_REPO_ROOT)
    return subprocess.run(
        [sys.executable, "-m", _VALIDATOR_MODULE, *args],
        cwd=_REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )


def _schema_sequences() -> dict:
    return {
        "com.tldraw.store": 1,
        "com.tldraw.asset": 1,
        "com.tldraw.document": 1,
        "com.tldraw.page": 1,
        "com.tldraw.shape": 1,
        "com.tldraw.asset.image": 1,
        "com.tldraw.shape.geo": 1,
        "com.tldraw.shape.image": 1,
    }


def _base_manifest(store: dict) -> dict:
    full_store = {
        "document:document": {
            "id": "document:document",
            "typeName": "document",
            "meta": {},
        },
        "page:page": {
            "id": "page:page",
            "typeName": "page",
            "meta": {},
        },
    }
    full_store.update(store)
    return {
        "document": {
            "store": full_store,
            "schema": {"schemaVersion": 2, "sequences": _schema_sequences()},
        },
        "session": {"currentPageId": "page:page", "pageStates": []},
    }


def _geo_shape(**props_overrides) -> dict:
    props = {
        "w": 120,
        "h": 60,
        "geo": "rectangle",
        "color": "blue",
        "labelColor": "black",
        "fill": "semi",
        "text": "Node",
    }
    props.update(props_overrides)
    return {
        "id": "shape:n1",
        "typeName": "shape",
        "type": "geo",
        "x": 10,
        "y": 20,
        "rotation": 0,
        "isLocked": False,
        "opacity": 1,
        "meta": {},
        "parentId": "page:page",
        "index": "a00001",
        "props": props,
    }


def _arrow_shape(**props_overrides) -> dict:
    props = {
        "color": "green",
        "labelColor": "green",
        "kind": "curved",
        "start": {"x": 0, "y": 0},
        "end": {"x": 100, "y": 0},
        "arrowheadStart": "none",
        "arrowheadEnd": "arrow",
    }
    props.update(props_overrides)
    return {
        "id": "shape:arrow",
        "typeName": "shape",
        "type": "arrow",
        "x": 10,
        "y": 20,
        "rotation": 0,
        "isLocked": False,
        "opacity": 1,
        "meta": {"semantic_edge_id": "e1"},
        "parentId": "page:page",
        "index": "b00001",
        "props": props,
    }


def test_tldraw_validator_accepts_valid_geo_and_arrow_shapes():
    manifest = _base_manifest({
        "shape:n1": _geo_shape(),
        "shape:arrow": _arrow_shape(),
    })

    report = validate_tldraw_manifest(manifest_data=manifest)

    assert report["is_valid"] is True
    assert report["errors"] == []
    assert report["counts"]["shapes"] == 2


def test_tldraw_validator_rejects_invalid_geo_enums_and_dimensions():
    manifest = _base_manifest({
        "shape:n1": _geo_shape(
            w=-1,
            h="large",
            geo="bad-shape",
            color="#ff0000",
            labelColor="purple",
            fill="transparent",
        )
    })

    report = validate_tldraw_manifest(manifest_data=manifest)

    assert report["is_valid"] is False
    errors = "\n".join(report["errors"])
    assert "shape:n1.props.w must be positive" in errors
    assert "shape:n1.props.h must be a number" in errors
    assert "shape:n1.props.geo has invalid value 'bad-shape'" in errors
    assert "shape:n1.props.color has invalid value '#ff0000'" in errors
    assert "shape:n1.props.labelColor has invalid value 'purple'" in errors
    assert "shape:n1.props.fill has invalid value 'transparent'" in errors


def test_tldraw_validator_rejects_invalid_arrow_props():
    manifest = _base_manifest({
        "shape:arrow": _arrow_shape(
            color="#00ff00",
            kind="elbowed",
            start={"x": "left", "y": 0},
            end={},
        )
    })

    report = validate_tldraw_manifest(manifest_data=manifest)

    assert report["is_valid"] is False
    errors = "\n".join(report["errors"])
    assert "shape:arrow.props.color has invalid value '#00ff00'" in errors
    assert "shape:arrow.props.kind has invalid value 'elbowed'" in errors
    assert "shape:arrow.props.start.x must be a number" in errors
    assert "shape:arrow.props.end missing field: x" in errors
    assert "shape:arrow.props.end missing field: y" in errors


def test_tldraw_validator_cli_help_returns_zero():
    result = _run_validator_cli("--help")

    assert result.returncode == 0, result.stderr
    assert "Validate a Tldraw manifest JSON file." in result.stdout
    assert "--manifest" in result.stdout


def test_tldraw_validator_cli_valid_manifest_returns_zero_and_json(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(_base_manifest({
            "shape:n1": _geo_shape(),
            "shape:arrow": _arrow_shape(),
        })),
        encoding="utf-8",
    )

    result = _run_validator_cli("--manifest", str(manifest_path))

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["is_valid"] is True
    assert report["errors"] == []
    assert report["counts"]["shapes"] == 2
    assert report["manifest_path"] == str(manifest_path)


def test_tldraw_validator_cli_invalid_manifest_returns_one_and_json(tmp_path):
    manifest_path = tmp_path / "invalid_manifest.json"
    manifest_path.write_text(
        json.dumps(_base_manifest({
            "shape:n1": _geo_shape(color="#ff0000"),
        })),
        encoding="utf-8",
    )

    result = _run_validator_cli("--manifest", str(manifest_path))

    assert result.returncode == 1, result.stderr
    report = json.loads(result.stdout)
    assert report["is_valid"] is False
    assert report["error_count"] == 1
    assert any(
        "shape:n1.props.color has invalid value '#ff0000'" in error
        for error in report["errors"]
    )


def test_tldraw_validator_cli_missing_manifest_returns_nonzero_and_json(tmp_path):
    manifest_path = tmp_path / "missing_manifest.json"

    result = _run_validator_cli("--manifest", str(manifest_path))

    assert result.returncode != 0
    report = json.loads(result.stdout)
    assert report["is_valid"] is False
    assert report["error_count"] == 1
    assert report["manifest_path"] == str(manifest_path)
    assert f"Manifest file not found: {manifest_path}" in report["errors"]
