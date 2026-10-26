# -*- coding: utf-8 -*-
"""The refiner system prompt must describe the analysis-render contract.

Iteration PNGs are rendered through the analysis channel (exportScale=1,
smart crop skipped — see ``canvas_environment.ANALYSIS_RENDER_SCALE`` and
``iterative_workflow._rerender_iteration_image``), so the prompt tells the
VLM that image pixels and manifest units are the same measurement system.
The old "disjoint coordinate space" disclaimer described the product
render (magnified export + content crop) and must not come back while the
analysis channel feeds the refiner.
"""

from __future__ import annotations

from evo_diagram.agentic_system.refinement_stage.agent.prompts import (
    REFINER_LLM_SYSTEM_PROMPT,
)


def test_prompt_declares_image_and_manifest_same_unit_system():
    prompt = REFINER_LLM_SYSTEM_PROMPT
    assert "share the same unit system" in prompt
    assert "ONE IMAGE PIXEL = ONE MANIFEST UNIT" in prompt
    assert "analysis render" in prompt


def test_prompt_restores_directly_measurable_pixel_thresholds():
    """With 1 px = 1 unit, tolerances are stated as directly checkable."""
    prompt = REFINER_LLM_SYSTEM_PROMPT
    assert '"~2 units" tolerance is a ~2 pixel difference' in prompt
    assert "~2 manifest units" in prompt  # PROACTIVE DISCOVERY keeps its threshold


def test_prompt_keeps_absolute_coordinates_grounded_in_the_manifest_summary():
    """Same units, but the image origin is the content frame, not (0,0)."""
    prompt = REFINER_LLM_SYSTEM_PROMPT
    assert "NOT manifest (0,0)" in prompt
    assert "ABSOLUTE x/y/width/height" in prompt
    assert "manifest summary" in prompt


def test_prompt_covers_the_no_rerender_fallback_to_the_product_export():
    """--no-rerender leaves the magnified product PNG in place; the prompt
    must demote it to qualitative evidence."""
    prompt = REFINER_LLM_SYSTEM_PROMPT
    assert "re-render was disabled" in prompt
    assert "magnified, cropped product export" in prompt


def test_old_disjoint_coordinate_space_disclaimer_is_gone():
    prompt = REFINER_LLM_SYSTEM_PROMPT
    assert "do NOT share a coordinate system" not in prompt
    assert "exported at a magnified scale and then cropped" not in prompt
    assert "its origin shifts from render to render" not in prompt
    assert "Never convert a measurement you made on the image" not in prompt
