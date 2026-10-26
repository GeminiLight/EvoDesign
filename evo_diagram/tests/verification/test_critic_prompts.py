# -*- coding: utf-8 -*-
"""Tripwire: the critic still sees the PRODUCT render, not an analysis render.

The verification critic's image is wired in ``agentic_system/workflow.py``
(``_run_verification_phase`` passes ``render_result.png_path`` /
``finalize.png_path``), and those PNGs come from the default product
render pipeline — magnified export (scale 4) plus smart crop. Only the
refiner's intra-iteration re-renders go through the analysis channel
(``ANALYSIS_RENDER_SCALE`` + ``crop=False``).

So the critic prompt must KEEP its scaled-image disclaimer. If a future
change feeds analysis renders to the verifier, the disclaimer has to be
flipped to the same-unit wording in the SAME change — otherwise the critic
will confidently report absolute pixel measurements that are wrong by the
export-scale factor. These assertions make that coupling fail loudly.
"""

from __future__ import annotations

from evo_diagram.agentic_system.verification_stage.critic.prompts import (
    VERIFIER_CRITIC_SYSTEM_PROMPT,
)


def test_critic_prompt_keeps_magnified_export_disclaimer():
    prompt = VERIFIER_CRITIC_SYSTEM_PROMPT
    assert "NOT a 1:1 view" in prompt
    assert "exported at a magnified scale" in prompt
    assert "Do not state absolute pixel measurements" in prompt


def test_critic_prompt_does_not_claim_analysis_render_units():
    prompt = VERIFIER_CRITIC_SYSTEM_PROMPT.lower()
    assert "one image pixel" not in prompt
    assert "analysis render" not in prompt
