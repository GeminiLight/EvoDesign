"""Filesystem artifact helpers for backend workflow runs."""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any


STRUCTURE_STAGE_DIR = "1_structure"
STYLING_STAGE_DIR = "2_styling"
LAYOUT_STAGE_DIR = "3_layout"
RENDER_STAGE_DIR = "4_render"
VERIFICATION_STAGE_DIR = "6_verification"
REFINER_STAGE_DIR = "7_refiner"
FINAL_VERIFICATION_STAGE_DIR = "8_final_verification"


def _to_plain(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return value


def _request_scoped_stream_dir(results_dir: str, request_id: str) -> str:
    """Return a per-request workdir for streaming artifacts."""
    safe_request_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(request_id)).strip("._")
    if not safe_request_id:
        safe_request_id = "request"
    return os.path.join(results_dir, "stream_runs", safe_request_id)


def _cleanup_stream_dir(save_dir: str) -> None:
    """Remove a per-request streaming workdir once its run is finished."""
    shutil.rmtree(save_dir, ignore_errors=True)


def _save_json(filepath: str, data: Any) -> None:
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(_to_plain(data) or {}, f, indent=2, ensure_ascii=False)


def _run_stage_dir(save_dir: str, stage_dir: str) -> str:
    return os.path.join(save_dir, stage_dir)


def _stage_artifact_path(save_dir: str, stage_dir: str, artifact_name: str) -> str:
    return os.path.join(_run_stage_dir(save_dir, stage_dir), f"{artifact_name}.json")


def _structure_instantiation_path(save_dir: str) -> str:
    return _stage_artifact_path(
        save_dir,
        STRUCTURE_STAGE_DIR,
        "structure_instantiation",
    )


def _layout_instantiation_path(save_dir: str) -> str:
    return _stage_artifact_path(
        save_dir,
        LAYOUT_STAGE_DIR,
        "layout_instantiation",
    )


def _render_output_dir(save_dir: str) -> str:
    return _run_stage_dir(save_dir, RENDER_STAGE_DIR)


def _verification_output_dir(save_dir: str) -> str:
    return _run_stage_dir(save_dir, VERIFICATION_STAGE_DIR)


def _final_verification_output_dir(save_dir: str) -> str:
    return _run_stage_dir(save_dir, FINAL_VERIFICATION_STAGE_DIR)


def _verifier_report_path(verification_dir: str) -> str:
    return os.path.join(verification_dir, "verifier_report.json")


def _refiner_output_dir(save_dir: str) -> str:
    return _run_stage_dir(save_dir, REFINER_STAGE_DIR)


def _save_stage_artifact(
    save_dir: str,
    stage_dir: str,
    artifact_name: str,
    data: Any,
) -> None:
    if data is None:
        return
    _save_json(_stage_artifact_path(save_dir, stage_dir, artifact_name), data)
