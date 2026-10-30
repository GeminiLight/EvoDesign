# EvoDiagram contribution history

Eight contributions by [Yi Zhan](https://github.com/USTChandsomeboy) from the earlier EvoDiagram development repository have been imported into EvoDesign through a filtered history. The import retains the original author and committer names, emails, and timestamps, including their time zones. Each imported contribution contains a nonempty change.

## Commit mapping

Filtering changes commit IDs. Each imported commit also records its source ID in an `Original-commit` trailer. Dates below are the original author dates in UTC+08:00.

| Original commit | Imported commit | Date | Contribution |
| --- | --- | --- | --- |
| `ac882d1806c2fbc3c7ed175dbb0091a78d0d6e5e` | [`9b6a6057fa8dc91cf2022d22c55cd534c5557392`](https://github.com/GeminiLight/EvoDesign/commit/9b6a6057fa8dc91cf2022d22c55cd534c5557392) | 2026-09-08T22:49:58+08:00 | feat: distribute edge ports and detect edge-node collisions |
| `f62eb77f1fe00ae6dfb7c445826eb9a356e9b239` | [`5084edfcf41bb0b05bb970d92b5529cf7d67bae8`](https://github.com/GeminiLight/EvoDesign/commit/5084edfcf41bb0b05bb970d92b5529cf7d67bae8) | 2026-09-08T22:53:13+08:00 | chore: add gpt56 quality experiment profile |
| `8d925154c08e9cd6905af495de387dd49cd1f696` | [`63313adb69ee1ede575eacce36705b62528bfcc8`](https://github.com/GeminiLight/EvoDesign/commit/63313adb69ee1ede575eacce36705b62528bfcc8) | 2026-09-08T23:24:25+08:00 | fix: route arrows around intermediate nodes |
| `427f151a6ae2e26643780af91d59c4357cb19a75` | [`d3cb9f742c4129f991330803d928765097e623ee`](https://github.com/GeminiLight/EvoDesign/commit/d3cb9f742c4129f991330803d928765097e623ee) | 2026-09-09T20:18:15+08:00 | feat: compact and formalize architecture renders |
| `1ea1926b046434e63591ad29b7e72e26c10a0b0f` | [`14b8fb79e3eaf720b62e59443aaebd9fb703e100`](https://github.com/GeminiLight/EvoDesign/commit/14b8fb79e3eaf720b62e59443aaebd9fb703e100) | 2026-09-09T20:22:01+08:00 | tune: tighten architecture layer spacing |
| `5ecff18772cbc6fdc3105d30b965c852da01679d` | [`aea8b60bf9aa3feb7c206d8238ac52a5c4661a86`](https://github.com/GeminiLight/EvoDesign/commit/aea8b60bf9aa3feb7c206d8238ac52a5c4661a86) | 2026-09-14T13:21:31+08:00 | feat: polish architecture visual language |
| `64d2d119792e88d6b4849c6561fff1264a81a4f4` | [`e3cab08456415a9f28dd114dc2257dc16476ba18`](https://github.com/GeminiLight/EvoDesign/commit/e3cab08456415a9f28dd114dc2257dc16476ba18) | 2026-09-14T13:39:05+08:00 | fix: keep governance groups in architecture sidebar |
| `61062ae8e82ae0f2bdb5157e21324220d199c220` | [`e3ebfd31fe73d106080d938cff309ed402dd0037`](https://github.com/GeminiLight/EvoDesign/commit/e3ebfd31fe73d106080d938cff309ed402dd0037) | 2026-09-21T15:03:19+08:00 | feat: improve diagram generation quality |

## Import scope

The imported branch consists of one new filtered baseline and the eight contributions above. The baseline has no parent; no original private ancestor commit is attached. It contains only the approved files needed to represent these contributions, rather than a complete runnable historical checkout.

Filtered baseline: `fedf1b2b620df64b01bef681d5a0157a252585bf`.

The allowlist covers 75 paths already present in the public EvoDesign checkout: Python source and tests, two diagram prompt templates, five research utilities, and the experiment profile introduced by the second contribution. Training/test datasets, experiment records, images, runtime outputs, notebooks, environment files, and model/provider configuration files are excluded.

A historical custom service URL in a model-loader test was replaced with `https://provider.example/v1/responses`, using a reserved example domain. The experiment profile contains model role names and localhost renderer addresses; it contains no credentials or remote provider configuration.

<details>
<summary>Exact path allowlist</summary>

```text
configs/settings.gpt56-experiment.yaml
evo_diagram/agentic_system/common/task_prompts.py
evo_diagram/agentic_system/generation_stage/layout/layout_agent.py
evo_diagram/agentic_system/generation_stage/layout/prompts.py
evo_diagram/agentic_system/generation_stage/layout/viewport_profile.py
evo_diagram/agentic_system/generation_stage/structure/prompts.py
evo_diagram/agentic_system/generation_stage/structure/schemas.py
evo_diagram/agentic_system/generation_stage/structure/structure_agent.py
evo_diagram/agentic_system/generation_stage/styling/prompts.py
evo_diagram/agentic_system/generation_stage/unified/continuation.py
evo_diagram/agentic_system/generation_stage/unified/generator.py
evo_diagram/agentic_system/generation_stage/unified/native_defaults.py
evo_diagram/agentic_system/generation_stage/unified/state.py
evo_diagram/agentic_system/generation_stage/unified/transport_journal.py
evo_diagram/agentic_system/generation_stage/unified/workflow.py
evo_diagram/agentic_system/generation_stage/workflow.py
evo_diagram/agentic_system/iterative_workflow.py
evo_diagram/agentic_system/main.py
evo_diagram/agentic_system/refinement_stage/agent/llm_agent.py
evo_diagram/agentic_system/refinement_stage/agent/prompts.py
evo_diagram/agentic_system/refinement_stage/fixers/apply_edits.py
evo_diagram/agentic_system/refinement_stage/state.py
evo_diagram/agentic_system/render_engine/excalidraw/architecture_style_normalizer.py
evo_diagram/agentic_system/render_engine/excalidraw/arrow_adder.py
evo_diagram/agentic_system/render_engine/excalidraw/converter.py
evo_diagram/agentic_system/render_engine/excalidraw/edge_router.py
evo_diagram/agentic_system/render_engine/excalidraw/layered_layout_compactor.py
evo_diagram/agentic_system/render_engine/excalidraw/radial_concept_compactor.py
evo_diagram/agentic_system/render_engine/shared/edge_crossing_detector.py
evo_diagram/agentic_system/render_engine/shared/edge_routing.py
evo_diagram/agentic_system/render_engine/shared/image_cropper.py
evo_diagram/agentic_system/render_engine/shared/label_geometry.py
evo_diagram/agentic_system/render_engine/workflow.py
evo_diagram/agentic_system/system_prompt/type_patterns/architecture.md
evo_diagram/agentic_system/system_prompt/type_patterns/concept_map.md
evo_diagram/agentic_system/verification_stage/checks/aggregator.py
evo_diagram/agentic_system/verification_stage/checks/collision_detection.py
evo_diagram/agentic_system/verification_stage/checks/containment.py
evo_diagram/agentic_system/verification_stage/checks/label_proximity.py
evo_diagram/agentic_system/verification_stage/critic/comparison.py
evo_diagram/agentic_system/verification_stage/critic/critic_agent.py
evo_diagram/agentic_system/verification_stage/critic/prompts.py
evo_diagram/agentic_system/workflow.py
evo_diagram/canvas_environment/capabilities.py
evo_diagram/core/base_agent.py
evo_diagram/core/llm_factory.py
evo_diagram/tests/config/test_model_loader.py
evo_diagram/tests/core/test_base_agent.py
evo_diagram/tests/generation/test_canvas_prompt_contract.py
evo_diagram/tests/generation/test_layout_agent_contract.py
evo_diagram/tests/generation/test_native_continuation.py
evo_diagram/tests/generation/test_native_continuation_edges.py
evo_diagram/tests/generation/test_native_transport_journal.py
evo_diagram/tests/generation/test_structure_contract.py
evo_diagram/tests/generation/test_unified_generator_contract.py
evo_diagram/tests/generation/test_workflow_refiner_contract.py
evo_diagram/tests/refinement/test_fixers.py
evo_diagram/tests/refinement/test_native_refinement.py
evo_diagram/tests/refinement/test_refiner_workflow.py
evo_diagram/tests/render_engine/test_architecture_render_normalizers.py
evo_diagram/tests/render_engine/test_crossing_detector.py
evo_diagram/tests/render_engine/test_edge_router.py
evo_diagram/tests/render_engine/test_final_ports.py
evo_diagram/tests/render_engine/test_image_cropper.py
evo_diagram/tests/render_engine/test_render_fidelity.py
evo_diagram/tests/verification/test_checks.py
evo_diagram/tests/verification/test_containment_checks.py
evo_diagram/tests/verification/test_label_proximity.py
evo_diagram/tests/verification/test_visual_comparison.py
evo_diagram/tests/verification/test_workflow_inputs.py
scripts/research/inspect_diagram_run.py
scripts/research/render_concept_generalization_matrix.py
scripts/research/render_routing_generalization_matrix.py
scripts/research/reprocess_architecture_manifest.py
scripts/research/reprocess_concept_manifest.py
```

</details>

Of the 82 paths touched by the original eight contributions, the following seven were excluded:

- `.gitignore`
- `CHANGELOG`
- `configs/models.yaml`
- `configs/settings.yaml`
- `docs/next-ai-draw-io-method-analysis.md`
- `docs/quality-iteration-20260908.md`
- `docs/quality-iteration-20260917-overnight.md`

## Validation

- Compared all nine complete imported snapshots against the filtered source snapshots and checked every path, file mode, and blob.
- Verified all eight original author/committer identities and ISO timestamps exactly, with a nonempty diff for every contribution.
- Scanned all 144 unique approved historical blobs and the complete nine-commit filtered history with Gitleaks 8.30.1; no secret findings. Also reviewed URL and credential-like strings and excluded non-text blobs and special file modes.
- Verified that attaching the filtered history leaves the current EvoDesign file tree unchanged. The visible change consists of contributor documentation.
- Ran the repository documentation and release-tool checks: seven tests passed.

## Preserving attribution when merging

**Use a merge commit for the restoration PR.** Squash merging would discard the eight imported commits, and rebasing would rewrite the imported history. The attachment merge intentionally retains the current EvoDesign file tree; it does not replay old implementation changes over the current application.

GitHub contribution statistics can update only after the history reaches the default branch. The README contributor entries remain an explicit record of the credited work.
