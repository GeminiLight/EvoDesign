# Migration ledger

Generated 2026-11-04T18:11:05.097Z by `npm run ledger`. Do not edit by hand.

| WP | Module | TS file | Ported | Functions | Vectors passed | Failed | Skipped | Tolerated |
|---|---|---|---|---|---|---|---|---|
| WP01 | (runtime helpers) | `src/py/` | yes | | | | | |
| WP01 | `common.semantic_ids` | `src/common/semantic_ids.ts` | yes | 9 | 301/301 | 0 | 0 | 0 |
| WP01 | `common.spec_utils` | `src/common/spec_utils.ts` | yes | 2 | 60/60 | 0 | 0 | 0 |
| WP01 | `common.diagram_types` | `src/common/diagram_types.ts` | yes | 3 | 61/61 | 0 | 0 | 0 |
| WP01 | `common.design_constraints` | `src/common/design_constraints.ts` | yes | 5 | 91/91 | 0 | 0 | 0 |
| WP01 | `common.tldraw_utils` | `src/common/tldraw_utils.ts` | yes | 1 | 25/25 | 0 | 0 | 0 |
| WP01 | `render_engine.shared.order_keys` | `src/render_engine/shared/order_keys.ts` | yes | 1 | 120/120 | 0 | 0 | 0 |
| WP01 | `render_engine.shared.label_geometry` | `src/render_engine/shared/label_geometry.ts` | yes | 1 | 36/36 | 0 | 0 | 0 |
| WP02 | `common.node_icons` | `src/common/node_icons.ts` | yes | 6 | 203/203 | 0 | 0 | 0 |
| WP02 | `common.icon_assets` | `src/common/icon_assets.ts` | yes | 12 | 175/175 | 0 | 0 | 0 |
| WP02 | `common.layout_contract` | `src/common/layout_contract.ts` | yes | 14 | 650/650 | 0 | 0 | 0 |
| WP02 | `generation_stage.layout.element_shape_estimator` | `src/generation_stage/layout/element_shape_estimator.ts` | yes | 10 | 184/184 | 0 | 0 | 0 |
| WP02 | `render_engine.shared.icon_url_adder` | `src/render_engine/shared/icon_url_adder.ts` | yes | 3 | 76/76 | 0 | 0 | 0 |
| WP03 | `render_engine.shared.edge_routing` | `src/render_engine/shared/edge_routing.ts` | yes | 18 | 799/799 | 0 | 0 | 0 |
| WP03 | `render_engine.shared.edge_crossing_detector` | `src/render_engine/shared/edge_crossing_detector.ts` | yes | 17 | 1965/1965 | 0 | 0 | 0 |
| WP03 | `render_engine.shared.normalization` | `src/render_engine/shared/normalization.ts` | yes | 14 | 759/759 | 0 | 0 | 0 |
| WP03 | `render_engine.shared.render_audit` | `src/render_engine/shared/render_audit.ts` | yes | 13 | 445/445 | 0 | 0 | 0 |
| WP04 | `render_engine.excalidraw.converter` | `src/render_engine/excalidraw/converter.ts` | yes | 11 | 769/769 | 0 | 0 | 0 |
| WP04 | `render_engine.excalidraw.normalizer` | `src/render_engine/excalidraw/normalizer.ts` | yes | 3 | 78/78 | 0 | 0 | 0 |
| WP04 | `render_engine.excalidraw.shape_size_fitter` | `src/render_engine/excalidraw/shape_size_fitter.ts` | yes | 18 | 878/878 | 0 | 0 | 0 |
| WP04 | `render_engine.excalidraw.validator` | `src/render_engine/excalidraw/validator.ts` | yes | 4 | 183/183 | 0 | 0 | 0 |
| WP05 | `render_engine.excalidraw.group_fitter` | `src/render_engine/excalidraw/group_fitter.ts` | yes | 6 | 161/161 | 0 | 0 | 0 |
| WP05 | `render_engine.excalidraw.group_alignment_normalizer` | `src/render_engine/excalidraw/group_alignment_normalizer.ts` | yes | 7 | 216/216 | 0 | 0 | 0 |
| WP05 | `render_engine.excalidraw.layered_layout_compactor` | `src/render_engine/excalidraw/layered_layout_compactor.ts` | yes | 15 | 357/357 | 0 | 0 | 0 |
| WP05 | `render_engine.excalidraw.zorder_repair` | `src/render_engine/excalidraw/zorder_repair.ts` | yes | 4 | 136/136 | 0 | 0 | 0 |
| WP06 | `render_engine.excalidraw.radial_concept_compactor` | `src/render_engine/excalidraw/radial_concept_compactor.ts` | yes | 33 | 878/878 | 0 | 0 | 0 |
| WP07 | `render_engine.excalidraw.edge_router` | `src/render_engine/excalidraw/edge_router.ts` | yes | 12 | 1270/1270 | 0 | 0 | 0 |
| WP07 | `render_engine.excalidraw.arrow_routing.context` | `src/render_engine/excalidraw/arrow_routing/context.ts` | yes | 1 | 29/29 | 0 | 0 | 0 |
| WP07 | `render_engine.excalidraw.arrow_routing.geometry` | `src/render_engine/excalidraw/arrow_routing/geometry.ts` | yes | 18 | 1951/1951 | 0 | 0 | 0 |
| WP07 | `render_engine.excalidraw.arrow_routing.grid_router` | `src/render_engine/excalidraw/arrow_routing/grid_router.ts` | yes | 5 | 575/575 | 0 | 0 | 0 |
| WP07 | `render_engine.excalidraw.arrow_routing.detours` | `src/render_engine/excalidraw/arrow_routing/detours.ts` | yes | 8 | 457/457 | 0 | 0 | 0 |
| WP07 | `render_engine.excalidraw.arrow_routing.ports` | `src/render_engine/excalidraw/arrow_routing/ports.ts` | yes | 5 | 221/221 | 0 | 0 | 0 |
| WP07 | `render_engine.excalidraw.arrow_routing.labels` | `src/render_engine/excalidraw/arrow_routing/labels.ts` | yes | 14 | 469/469 | 0 | 0 | 0 |
| WP07 | `render_engine.excalidraw.arrow_routing.passes` | `src/render_engine/excalidraw/arrow_routing/passes.ts` | yes | 7 | 281/281 | 0 | 0 | 0 |
| WP07 | `render_engine.excalidraw.arrow_adder` | `src/render_engine/excalidraw/arrow_adder.ts` | yes | 10 | 314/314 | 0 | 0 | 0 |
| WP07 | `render_engine.excalidraw.sequence_layout` | `src/render_engine/excalidraw/sequence_layout.ts` | yes | 1 | 20/20 | 0 | 0 | 0 |
| WP08 | `render_engine.excalidraw.architecture_style_normalizer` | `src/render_engine/excalidraw/architecture_style_normalizer.ts` | yes | 5 | 198/198 | 0 | 0 | 0 |
| WP08 | `render_engine.excalidraw.architecture_design_system` | `src/render_engine/excalidraw/architecture_design_system.ts` | yes | 18 | 682/682 | 0 | 0 | 0 |
| WP09 | `render_engine.excalidraw.caption_placer` | `src/render_engine/excalidraw/caption_placer.ts` | yes | 8 | 149/149 | 0 | 0 | 0 |
| WP09 | `render_engine.excalidraw.design_theme` | `src/render_engine/excalidraw/design_theme.ts` | yes | 9 | 208/208 | 0 | 0 | 0 |
| WP10 | `render_engine.workflow` | `src/render_engine/workflow.ts` | yes | 0 | 0/0 | 0 | 0 | 0 |
| WP10 | `render_engine.state` | `src/render_engine/state.ts` | yes | 0 | 0/0 | 0 | 0 | 0 |
| WP10 | `render_engine.stages` | `src/render_engine/stages.ts` | yes | 0 | 0/0 | 0 | 0 | 0 |
| WP13 | `evodesign.config.settings` | `src/config/settings.ts` | yes | 2 | 123/123 | 0 | 0 | 0 |
| WP13 | `evodesign.config.model_loader` | `src/config/model_loader.ts` | yes | 2 | 37/37 | 0 | 0 | 0 |
| WP13 | `evodesign.utils.llm_output` | `src/utils/llm_output.ts` | yes | 9 | 467/467 | 0 | 0 | 0 |
| WP13 | `evodesign.utils.path_manager` | `src/utils/path_manager.ts` | yes | 5 | 39/39 | 0 | 0 | 0 |
| WP13 | `evodesign.utils.env_loader` | `src/utils/env_loader.ts` | yes | 3 | 362/362 | 0 | 0 | 0 |
| WP13 | `evodesign.utils.io_utils` | `src/utils/io_utils.ts` | yes | 1 | 48/48 | 0 | 0 | 0 |
| WP13 | `evodesign.core.llm_factory` | `src/core/llm_factory.ts` | yes | 0 | 0/0 | 0 | 0 | 0 |
| WP13 | `evodesign.core.base_agent` | `src/core/base_agent.ts` | yes | 9 | 590/590 | 0 | 0 | 0 |
| WP13 | `evodesign.core.experiment` | `src/core/experiment.ts` | yes | 7 | 34/34 | 0 | 0 | 0 |
| WP13 | `config` | `src/agentic_system/config.ts` | yes | 2 | 48/48 | 0 | 0 | 0 |
| WP13 | `quality_policy` | `src/agentic_system/quality_policy.ts` | yes | 8 | 532/532 | 0 | 0 | 0 |
| WP13 | `evodesign.canvas_runtime` | `src/canvas_runtime.ts` | yes | 1 | 125/125 | 0 | 0 | 0 |
| WP13 | `common.base_workflow` | `src/common/base_workflow.ts` | yes | 0 | 0/0 | 0 | 0 | 0 |
| WP13 | `common.workflow_state_base` | `src/common/workflow_state_base.ts` | yes | 1 | 122/122 | 0 | 0 | 0 |
| WP13 | `common.task_prompts` | `src/common/task_prompts.ts` | yes | 0 | 0/0 | 0 | 0 | 0 |
| WP13 | `common.skill_loader` | `src/common/skill_loader.ts` | yes | 0 | 0/0 | 0 | 0 | 0 |
| WP13 | `common.domain_knowledge_loader` | `src/common/domain_knowledge_loader.ts` | yes | 10 | 837/837 | 0 | 0 | 0 |
| WP13 | `common.self_consistency` | `src/common/self_consistency.ts` | yes | 0 | 0/0 | 0 | 0 | 0 |
| WP14 | `render_engine.canvas_render` | `src/render_engine/canvas_render.ts` | yes | 7 | 390/444 | 0 | 54 | 0 |
| WP14 | `render_engine.service` | `src/render_engine/service.ts` | yes | 3 | 54/108 | 0 | 54 | 0 |
| WP14 | `render_engine.shared.image_cropper` | `src/render_engine/shared/image_cropper.ts` | yes | 0 | 0/0 | 0 | 0 | 0 |
| WP14 | `render_engine.shared.png_validation` | `src/render_engine/shared/png_validation.ts` | yes | 1 | 120/120 | 0 | 0 | 0 |
| WP14 | `evodesign.canvas_environment._render_engine_adapter` | `src/canvas_environment/_render_engine_adapter.ts` | yes | 18 | 563/621 | 0 | 58 | 0 |
| WP14 | `evodesign.canvas_environment.capabilities` | `src/canvas_environment/capabilities.ts` | yes | 5 | 305/305 | 0 | 0 | 0 |
| WP14 | `evodesign.canvas_environment.config` | `src/canvas_environment/config.ts` | yes | 1 | 1/1 | 0 | 0 | 0 |
| WP14 | `evodesign.canvas_environment.constants` | `src/canvas_environment/constants.ts` | yes | 0 | 0/0 | 0 | 0 | 0 |
| WP14 | `evodesign.canvas_environment.editing` | `src/canvas_environment/editing.ts` | yes | 0 | 0/0 | 0 | 0 | 0 |
| WP14 | `evodesign.canvas_environment.environment` | `src/canvas_environment/environment.ts` | yes | 0 | 0/0 | 0 | 0 | 0 |
| WP14 | `evodesign.canvas_environment.geometry` | `src/canvas_environment/geometry.ts` | yes | 3 | 36/36 | 0 | 0 | 0 |
| WP14 | `evodesign.canvas_environment.rendering` | `src/canvas_environment/rendering.ts` | yes | 2 | 0/54 | 0 | 54 | 0 |
| WP14 | `evodesign.canvas_environment.scene` | `src/canvas_environment/scene.ts` | yes | 6 | 111/111 | 0 | 0 | 0 |
| WP14 | `evodesign.canvas_environment.validation` | `src/canvas_environment/validation.ts` | yes | 11 | 772/772 | 0 | 0 | 0 |
| WP15 | `generation_stage.structure.prompts` | `src/generation_stage/structure/prompts.ts` | yes | 0 | 0/0 | 0 | 0 | 0 |
| WP15 | `generation_stage.structure.schemas` | `src/generation_stage/structure/schemas.ts` | yes | 23 | 1079/1079 | 0 | 0 | 0 |
| WP15 | `generation_stage.structure.state` | `src/generation_stage/structure/state.ts` | yes | 1 | 3/3 | 0 | 0 | 0 |
| WP15 | `generation_stage.structure.structure_agent` | `src/generation_stage/structure/structure_agent.ts` | yes | 1 | 1/1 | 0 | 0 | 0 |
| WP15 | `generation_stage.structure.workflow` | `src/generation_stage/structure/workflow.ts` | yes | 0 | 0/0 | 0 | 0 | 0 |
| WP15 | `generation_stage.router.agent` | `src/generation_stage/router/agent.ts` | yes | 0 | 0/0 | 0 | 0 | 0 |
| WP15 | `generation_stage.router.prompts` | `src/generation_stage/router/prompts.ts` | yes | 2 | 10/10 | 0 | 0 | 0 |
| WP15 | `generation_stage.compact_decisions` | `src/generation_stage/compact_decisions.ts` | yes | 5 | 160/160 | 0 | 0 | 0 |
| WP16 | `generation_stage.styling.colorful` | `src/generation_stage/styling/colorful.ts` | yes | 1 | 70/70 | 0 | 0 | 0 |
| WP16 | `generation_stage.styling.contracts` | `src/generation_stage/styling/contracts/__init__.ts` | yes | 1 | 4/4 | 0 | 0 | 0 |
| WP16 | `generation_stage.styling.contracts.base` | `src/generation_stage/styling/contracts/base.ts` | yes | 0 | 0/0 | 0 | 0 | 0 |
| WP16 | `generation_stage.styling.contracts.excalidraw` | `src/generation_stage/styling/contracts/excalidraw.ts` | yes | 0 | 0/0 | 0 | 0 | 0 |
| WP16 | `generation_stage.styling.contracts.tldraw` | `src/generation_stage/styling/contracts/tldraw.ts` | yes | 0 | 0/0 | 0 | 0 | 0 |
| WP16 | `generation_stage.styling.icon_colors` | `src/generation_stage/styling/icon_colors.ts` | yes | 5 | 209/209 | 0 | 0 | 0 |
| WP16 | `generation_stage.styling.prompts` | `src/generation_stage/styling/prompts.ts` | yes | 2 | 121/121 | 0 | 0 | 0 |
| WP16 | `generation_stage.styling.schemas` | `src/generation_stage/styling/schemas.ts` | yes | 20 | 1750/1750 | 0 | 0 | 0 |
| WP16 | `generation_stage.styling.state` | `src/generation_stage/styling/state.ts` | yes | 0 | 0/0 | 0 | 0 | 0 |
| WP16 | `generation_stage.styling.styling_agent` | `src/generation_stage/styling/styling_agent.ts` | yes | 0 | 0/0 | 0 | 0 | 0 |
| WP16 | `generation_stage.styling.workflow` | `src/generation_stage/styling/workflow.ts` | yes | 0 | 0/0 | 0 | 0 | 0 |
| WP17 | `generation_stage.layout.flow_grid` | `src/generation_stage/layout/flow_grid.ts` | yes | 3 | 63/63 | 0 | 0 | 0 |
| WP17 | `generation_stage.layout.layout_agent` | `src/generation_stage/layout/layout_agent.ts` | yes | 1 | 30/30 | 0 | 0 | 0 |
| WP17 | `generation_stage.layout.prompts` | `src/generation_stage/layout/prompts.ts` | yes | 0 | 0/0 | 0 | 0 | 0 |
| WP17 | `generation_stage.layout.sequence_layout` | `src/generation_stage/layout/sequence_layout.ts` | yes | 1 | 1/1 | 0 | 0 | 0 |
| WP17 | `generation_stage.layout.state` | `src/generation_stage/layout/state.ts` | yes | 0 | 0/0 | 0 | 0 | 0 |
| WP17 | `generation_stage.layout.viewport_profile` | `src/generation_stage/layout/viewport_profile.ts` | yes | 3 | 91/91 | 0 | 0 | 0 |
| WP17 | `generation_stage.layout.workflow` | `src/generation_stage/layout/workflow.ts` | yes | 0 | 0/0 | 0 | 0 | 0 |
| WP17 | `generation_stage.workflow` | `src/generation_stage/workflow.ts` | yes | 1 | 93/93 | 0 | 0 | 0 |
| WP18 | `generation_stage.unified.continuation` | `src/generation_stage/unified/continuation.ts` | yes | 1 | 14/14 | 0 | 0 | 0 |
| WP18 | `generation_stage.unified.generator` | `src/generation_stage/unified/generator.ts` | yes | 0 | 0/0 | 0 | 0 | 0 |
| WP18 | `generation_stage.unified.native_defaults` | `src/generation_stage/unified/native_defaults.ts` | yes | 2 | 37/37 | 0 | 0 | 0 |
| WP18 | `generation_stage.unified.sidecar` | `src/generation_stage/unified/sidecar.ts` | yes | 2 | 50/50 | 0 | 0 | 0 |
| WP18 | `generation_stage.unified.state` | `src/generation_stage/unified/state.ts` | yes | 0 | 0/0 | 0 | 0 | 0 |
| WP18 | `generation_stage.unified.transport_journal` | `src/generation_stage/unified/transport_journal.ts` | yes | 1 | 25/25 | 0 | 0 | 0 |
| WP18 | `generation_stage.unified.workflow` | `src/generation_stage/unified/workflow.ts` | yes | 0 | 0/0 | 0 | 0 | 0 |
| WP19 | `verification_stage.checks.aggregator` | `src/verification_stage/checks/aggregator.ts` | yes | 2 | 214/214 | 0 | 0 | 0 |
| WP19 | `verification_stage.checks.binding_consistency` | `src/verification_stage/checks/binding_consistency.ts` | yes | 9 | 1014/1014 | 0 | 0 | 0 |
| WP19 | `verification_stage.checks.collision_detection` | `src/verification_stage/checks/collision_detection.ts` | yes | 14 | 1539/1539 | 0 | 0 | 0 |
| WP19 | `verification_stage.checks.containment` | `src/verification_stage/checks/containment.ts` | yes | 14 | 815/815 | 0 | 0 | 0 |
| WP19 | `verification_stage.checks.finding` | `src/verification_stage/checks/finding.ts` | yes | 2 | 149/149 | 0 | 0 | 0 |
| WP19 | `verification_stage.checks.label_proximity` | `src/verification_stage/checks/label_proximity.ts` | yes | 2 | 105/105 | 0 | 0 | 0 |
| WP19 | `verification_stage.checks.node_icons` | `src/verification_stage/checks/node_icons.ts` | yes | 1 | 84/84 | 0 | 0 | 0 |
| WP19 | `verification_stage.checks.objective_manifest` | `src/verification_stage/checks/objective_manifest.ts` | yes | 10 | 171/171 | 0 | 0 | 0 |
| WP19 | `verification_stage.checks.render_validation` | `src/verification_stage/checks/render_validation.ts` | yes | 3 | 244/244 | 0 | 0 | 0 |
| WP19 | `verification_stage.checks.sequence` | `src/verification_stage/checks/sequence.ts` | yes | 1 | 86/86 | 0 | 0 | 0 |
| WP19 | `verification_stage.reports.report_builder` | `src/verification_stage/reports/report_builder.ts` | yes | 8 | 398/398 | 0 | 0 | 0 |
| WP20 | `verification_stage.critic.comparison` | `src/verification_stage/critic/comparison.ts` | yes | 0 | 0/0 | 0 | 0 | 0 |
| WP20 | `verification_stage.critic.critic_agent` | `src/verification_stage/critic/critic_agent.ts` | yes | 4 | 316/316 | 0 | 0 | 0 |
| WP20 | `verification_stage.critic.prompts` | `src/verification_stage/critic/prompts.ts` | yes | 1 | 39/39 | 0 | 0 | 0 |
| WP20 | `verification_stage.workflow` | `src/verification_stage/workflow.ts` | yes | 6 | 253/293 | 0 | 40 | 0 |
| WP20 | `verification_stage.state` | `src/verification_stage/state.ts` | yes | 2 | 129/129 | 0 | 0 | 0 |
| WP20 | `verification_stage.__main__` | `src/verification_stage/__main__.ts` | yes | 2 | 5/7 | 0 | 2 | 0 |
| WP21 | `refinement_stage.fixers.apply_edits` | `src/refinement_stage/fixers/apply_edits.ts` | yes | 4 | 109/109 | 0 | 0 | 0 |
| WP21 | `refinement_stage.fixers.arrow_reroute` | `src/refinement_stage/fixers/arrow_reroute.ts` | yes | 5 | 53/53 | 0 | 0 | 0 |
| WP21 | `refinement_stage.fixers.deterministic` | `src/refinement_stage/fixers/deterministic.ts` | yes | 18 | 370/370 | 0 | 0 | 0 |
| WP21 | `refinement_stage.fixers.primitives` | `src/refinement_stage/fixers/primitives.ts` | yes | 12 | 303/303 | 0 | 0 | 0 |
| WP22 | `refinement_stage.agent.llm_agent` | `src/refinement_stage/agent/llm_agent.ts` | yes | 2 | 38/38 | 0 | 0 | 0 |
| WP22 | `refinement_stage.agent.prompts` | `src/refinement_stage/agent/prompts.ts` | yes | 1 | 18/18 | 0 | 0 | 0 |
| WP22 | `refinement_stage.reports.refiner_report` | `src/refinement_stage/reports/refiner_report.ts` | yes | 8 | 200/200 | 0 | 0 | 0 |
| WP22 | `refinement_stage.state` | `src/refinement_stage/state.ts` | yes | 4 | 155/155 | 0 | 0 | 0 |
| WP22 | `refinement_stage.__main__` | `src/refinement_stage/__main__.ts` | yes | 2 | 2/5 | 0 | 3 | 0 |
| WP23 | `workflow` | `src/agentic_system/workflow.ts` | yes | 19 | 929/931 | 0 | 2 | 0 |
| WP23 | `iterative_workflow` | `src/agentic_system/iterative_workflow.ts` | yes | 25 | 515/621 | 0 | 106 | 0 |
| WP23 | `main` | `src/agentic_system/main.ts` | yes | 14 | 294/379 | 0 | 85 | 0 |
| WP23 | `__main__` | `src/agentic_system/__main__.ts` | yes | 0 | 0/0 | 0 | 0 | 0 |

**Total** vectors passed 34504/34962, failed 0, skipped 458.

## Stage parity

112/112 example cases reproduce every workflow snapshot.


## End-to-end runs (phase 2)

Recorded: 36 runs (36 recorded twice identically), 158 LLM calls in cassettes.

Replay (2026-11-04T17:54:05.101Z): **36/36** runs identical.

| Run | OK | LLM calls matched | Snapshots matched | First divergence |
|---|---|---|---|---|
| big_en_aes__refine | yes | 5/5 | 27/27 |  |
| concept_ml__multi | yes | 4/4 | 24/24 |  |
| cy_flywheel_ty2__multi | yes | 4/4 | 24/24 |  |
| dg_pkgs_ty1__noverify | yes | 3/3 | 20/20 |  |
| dp_k8s_ty1__multi | yes | 4/4 | 24/24 |  |
| ecommerce_aes__unified | yes | 2/2 | 12/12 |  |
| flow_h1__router | yes | 5/5 | 24/24 |  |
| flow_leave_aes__compact | yes | 4/4 | 24/24 |  |
| flow_x1__multi | yes | 4/4 | 24/24 |  |
| flow_x2__unified_router | yes | 3/3 | 12/12 |  |
| hcai_demo__refine | yes | 5/5 | 27/27 |  |
| iot_aes__unified_refine | yes | 3/3 | 15/15 |  |
| kb_sprint_ty1__multi | yes | 4/4 | 24/24 |  |
| ls_web_ty2__multi | yes | 4/4 | 24/24 |  |
| ne_saas_ty1__refine | yes | 6/6 | 32/32 |  |
| paper_full_f2__multi | yes | 4/4 | 24/24 |  |
| paper_method_x2__refine | yes | 6/6 | 32/32 |  |
| plain_ecommerce__icons | yes | 4/4 | 24/24 |  |
| quickstart_service__router | yes | 5/5 | 24/24 |  |
| rag_aes__unified_stream | yes | 3/3 | 12/12 |  |
| sm_course_ty1__nocritic | yes | 3/3 | 24/24 |  |
| t_class_tz__refine_forced | yes | 6/6 | 32/32 |  |
| t_er_ty__multi | yes | 4/4 | 24/24 |  |
| t_er_tz__refine_regress | yes | 6/6 | 32/32 |  |
| t_fishbone_ty__multi | yes | 4/4 | 24/24 |  |
| t_funnel_ty__repair | yes | 9/9 | 24/24 |  |
| t_matrix_ty__multi | yes | 4/4 | 24/24 |  |
| t_mindmap_ty__router | yes | 5/5 | 24/24 |  |
| t_orgchart_ty__multi | yes | 4/4 | 24/24 |  |
| t_orgchart_ty__unified_repair | yes | 3/3 | 13/13 |  |
| t_sequence_tz__multi | yes | 3/3 | 24/24 |  |
| t_state_tz__multi | yes | 4/4 | 24/24 |  |
| t_state_tz__refine_multi | yes | 5/5 | 27/27 |  |
| t_swimlane_ty__multi | yes | 4/4 | 24/24 |  |
| t_swot_ty__refine | yes | 7/7 | 32/32 |  |
| t_timeline_ty__repair | yes | 5/5 | 24/24 |  |

## Work package notes

- WP01 基础运行时与公共工具: [notes](notes/WP01.md)
- WP02 图标资源与尺寸估算: [notes](notes/WP02.md)
- WP03 共享几何、路由工具与审计: [notes](notes/WP03.md)
- WP04 转换器与尺寸适配: [notes](notes/WP04.md)
- WP05 分组框、对齐、层级压缩、图层顺序: [notes](notes/WP05.md)
- WP06 概念图放射压缩: [notes](notes/WP06.md)
- WP07 连线路由与时序图: [notes](notes/WP07.md)
- WP08 架构图设计系统: [notes](notes/WP08.md)
- WP09 统一主题与说明文字: [notes](notes/WP09.md)
- WP10 流水线编排、端到端对照与出图: [notes](notes/WP10.md)
- WP11 独立验收: no notes yet
- WP12 第二期对照基础设施（录制回放、端到端录制、函数向量、回放工具）: [notes](notes/WP12.md)
- WP13 基础层：配置、工具、LLM 工厂与 BaseAgent、公共流程件: [notes](notes/WP13.md)
- WP14 出图与画布环境: [notes](notes/WP14.md)
- WP15 生成·结构与路由: [notes](notes/WP15.md)
- WP16 生成·样式: [notes](notes/WP16.md)
- WP17 生成·布局与多智能体编排: [notes](notes/WP17.md)
- WP18 生成·一体化（unified/native）: [notes](notes/WP18.md)
- WP19 校验·确定性检查与报告: [notes](notes/WP19.md)
- WP20 校验·评审与流程: [notes](notes/WP20.md)
- WP21 修复·确定性修复器: [notes](notes/WP21.md)
- WP22 修复·大模型修复与流程: [notes](notes/WP22.md)
- WP23 总编排: [notes](notes/WP23.md)
- WP24 集成：端到端回放对照全部通过: [notes](notes/WP24.md)
- WP25 第二期独立验收: no notes yet
