import os
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Tuple
from evo_diagram.canvas_environment import render_png_result
from ..config import KnowledgeEvolutionConfig
from ..schemas import (
    CONTROL_SCORE_KEY,
    DiagramRef,
    Feedback,
    IterationRecord,
    KnowledgeEntry,
    TagSet,
)
from ..maintenance.cycle import compute_confidence
from evo_diagram.utils.io_utils import save_json, copy_file
from evo_diagram.utils.path_manager import safe_path_segment
from evo_diagram.agentic_system.verification_stage.checks.aggregator import run_all_checks
from evo_diagram.agentic_system.iterative_workflow import IterativeRefinerWorkflow
from ..distillation.curators import StrategyExtractorAgent
from evo_diagram.agentic_system.workflow import Text2DiagramWorkflow


logger = logging.getLogger(__name__)

_ALLOWED_STRATEGY_KEYS = {"parse", "styling", "layout"}
_REQUIRED_STRATEGY_FIELDS = ("title", "description")

# Severity weights for objective score computation.
_SEVERITY_WEIGHTS = {
    "critical": 5.0,
    "major": 3.0,
    "minor": 1.0,
    "info": 0.2,
}
_MAX_PENALTY = 50.0


def _iteration_run_dir(output_dir: str, sample_id: str, iteration: int) -> Path:
    """Per-sample iteration workspace; avoids global scratch-file collisions."""
    safe_sample_id = safe_path_segment(sample_id, field_name="dataset sample id")
    return Path(output_dir) / "runs" / safe_sample_id / f"iter_{iteration}"


def _compute_objective_score(findings: List[Dict[str, Any]]) -> float:
    """Compute a 0-10 objective quality score from verification findings.

    Fewer and less severe findings → higher score.
    """
    penalty = sum(_SEVERITY_WEIGHTS.get(f.get("severity", "info"), 0.2) for f in findings)
    normalized = min(penalty, _MAX_PENALTY) / _MAX_PENALTY
    return round(10.0 * (1.0 - normalized), 2)


def _validate_strategy_summary(summary: Any, *, sample_id: str) -> Dict[str, Dict[str, Any]]:
    """Validate StrategyExtractor output before it enters long-lived memory."""
    if not isinstance(summary, dict):
        raise RuntimeError(
            "StrategyExtractor returned invalid output for "
            f"sample={sample_id!r}: expected object, got {type(summary).__name__}"
        )

    validated: Dict[str, Dict[str, Any]] = {}
    for key, value in summary.items():
        if key not in _ALLOWED_STRATEGY_KEYS:
            allowed = ", ".join(sorted(_ALLOWED_STRATEGY_KEYS))
            raise RuntimeError(
                "StrategyExtractor returned unknown strategy category "
                f"{key!r} for sample={sample_id!r}; allowed categories: {allowed}"
            )
        if not isinstance(value, dict):
            raise RuntimeError(
                "StrategyExtractor returned invalid strategy payload for "
                f"sample={sample_id!r}, category={key!r}: expected object, "
                f"got {type(value).__name__}"
            )

        missing = [
            field
            for field in _REQUIRED_STRATEGY_FIELDS
            if not str(value.get(field, "")).strip()
        ]
        if missing:
            raise RuntimeError(
                "StrategyExtractor returned incomplete strategy for "
                f"sample={sample_id!r}, category={key!r}: missing "
                f"{', '.join(missing)}"
            )
        validated[key] = value

    return validated


def _finding_to_dict(f) -> Dict[str, Any]:
    """Extract the relevant fields from a Finding object."""
    d = {"category": f.category, "severity": f.severity.value, "message": f.message}
    if f.element_id:
        d["element_id"] = f.element_id
    return d


def _build_rich_feedback(
    before_findings,
    after_findings,
    refiner_state,
    delta_score: float,
) -> Dict[str, Any]:
    """Build rich feedback from refinement iteration.

    Combines:
    - before/after findings (full Finding objects with category, severity, message, element_id)
    - applied edits (with rationale from EditOp)
    - delta_score
    """
    # Findings before refinement
    findings_before = [_finding_to_dict(f) for f in before_findings]

    # Findings after refinement
    findings_after = [_finding_to_dict(f) for f in after_findings]

    # Applied edits with rationale
    edits: List[Dict[str, Any]] = []
    for log in refiner_state.iteration_logs:
        for outcome in log.deterministic_edits + log.llm_edits:
            if outcome.applied:
                edit_info = {
                    "op": outcome.edit.op,
                    "element_id": outcome.edit.id,
                    "args": outcome.edit.payload,
                    "source": outcome.edit.source,
                }
                if outcome.edit.rationale:
                    edit_info["rationale"] = outcome.edit.rationale
                edits.append(edit_info)

    # Compute what was fixed vs what remains
    before_cats = {f["category"] for f in findings_before}
    after_cats = {f["category"] for f in findings_after}
    resolved_categories = sorted(before_cats - after_cats)
    remaining_categories = sorted(after_cats)

    return {
        "findings_before": findings_before,
        "findings_after": findings_after,
        "edits": edits,
        "delta_score": delta_score,
        "resolved_categories": resolved_categories,
        "remaining_categories": remaining_categories,
    }


class RefineLoop:
    def __init__(
        self,
        config: KnowledgeEvolutionConfig,
        generator_workflow: Text2DiagramWorkflow,
        refiner_workflow: IterativeRefinerWorkflow,
        extractor_agent: StrategyExtractorAgent,
    ):
        self.config = config
        self.generator = generator_workflow
        self.refiner = refiner_workflow
        self.extractor = extractor_agent

    def _control_score(
        self,
        *,
        sample_id: str,
        text_content: str,
        user_prompt: str,
        diagram_type: str,
        content_domain: str,
    ) -> float | None:
        """Objective score of the same sample generated *without* knowledge.

        Enabled by ``config.first_pass_control_run``. It gives
        ``engine.evaluate_knowledge_outcome`` a paired causal baseline: the same
        prompt, the same generator, the only difference being the injected
        ``design_expertise``. Costs one extra generator call per sample; no
        render is needed because ``run_all_checks`` works on the manifest.
        """
        if not getattr(self.config, "first_pass_control_run", False):
            return None

        logger.info("   [Control] Generating knowledge-free baseline...")
        control_state = self.generator.run(
            text_content,
            user_prompt,
            design_expertise="",
            diagram_type=diagram_type,
            content_area=content_domain,
        )
        control_manifest = getattr(control_state, "diagram_manifest", None)
        if not isinstance(control_manifest, dict):
            raise RuntimeError(
                "Control generation produced no diagram manifest for "
                f"sample={sample_id!r}."
            )
        control_findings = run_all_checks(
            control_manifest,
            structure=getattr(control_state, "structure_instantiation", None),
            layout_instantiation=getattr(control_state, "layout_instantiation", None),
            canvas_library=self.config.canvas_library,
        )
        score = _compute_objective_score([f.to_dict() for f in control_findings])
        logger.info("   [Control] Knowledge-free objective score: %s", score)
        return score

    def run_loop(
        self,
        sample_id: str,
        sample_info,
        retrieved_knowledge: str,
    ) -> Tuple[List[KnowledgeEntry], List[IterationRecord]]:

        content_domain = sample_info.content_area
        diagram_type = sample_info.diagram_type
        text_content = sample_info.content
        user_prompt = sample_info.query
        safe_sample_id = safe_path_segment(sample_id, field_name="dataset sample id")

        history: List[IterationRecord] = []
        iteration_feedback: List[Dict[str, Any]] = []

        state = self.generator.run(
            text_content,
            user_prompt,
            design_expertise=retrieved_knowledge,
            diagram_type=diagram_type,
            content_area=content_domain,
        )
        structure_instantiation = getattr(state, "structure_instantiation", None)
        layout_instantiation = getattr(state, "layout_instantiation", None)

        # diagram_manifest is mutated each outer iteration (refined_manifest
        # → next iteration's input). Without this, all iterations would
        # re-refine the same baseline manifest.
        diagram_manifest = getattr(state, "diagram_manifest", None)
        if not isinstance(diagram_manifest, dict):
            raise RuntimeError(
                f"Generator produced no diagram manifest for sample={sample_id!r}."
            )

        control_score = self._control_score(
            sample_id=sample_id,
            text_content=text_content,
            user_prompt=user_prompt,
            diagram_type=diagram_type,
            content_domain=content_domain,
        )

        for i in range(self.config.max_iterations):
            logger.info("   [Iter %d] Generating...", i)

            run_dir = _iteration_run_dir(self.config.output_dir, sample_id, i)
            run_dir.mkdir(parents=True, exist_ok=True)
            manifest_path = str(run_dir / self.config.manifest_document_fname)
            rendered_path = str(run_dir / self.config.rendered_diagram_fname)

            with open(manifest_path, "w", encoding='utf-8') as f:
                json.dump(diagram_manifest, f, indent=2, ensure_ascii=False)
            logger.info("Saved output diagram manifest into %s", manifest_path)

            render_result = render_png_result(
                manifest=diagram_manifest,
                output_path=rendered_path,
                canvas_library=self.config.canvas_library,
            )
            if not render_result.ok:
                detail = f": {render_result.error}" if render_result.error else ""
                raise RuntimeError(
                    f"Render failed for sample={sample_id!r}, iteration={i}, "
                    f"canvas_library={self.config.canvas_library!r}: {rendered_path}{detail}"
                )
            logger.info("Saved rendered diagram image into %s", rendered_path)

            saved_manifest_path = save_json(
                diagram_manifest,
                os.path.join(self.config.code_dir, f"{safe_sample_id}_iter_{i}.json"),
            )
            saved_img_path = copy_file(
                rendered_path,
                os.path.join(self.config.images_dir, f"{safe_sample_id}_iter_{i}.png"),
            )
            before_artifacts = {
                "manifest": saved_manifest_path,
                "image": saved_img_path,
            }

            logger.info("   [Iter %d] Reflecting...", i)

            # Compute objective score BEFORE refinement
            before_findings = run_all_checks(
                diagram_manifest,
                structure=structure_instantiation,
                layout_instantiation=layout_instantiation,
                canvas_library=self.config.canvas_library,
            )
            score_before = _compute_objective_score([f.to_dict() for f in before_findings])

            refiner_output_dir = os.path.join(
                self.config.output_dir,
                f"{safe_sample_id}_iter_{i}_refiner",
            )
            os.makedirs(refiner_output_dir, exist_ok=True)

            # Write generation-stage context to files for refinement_stage.
            structure_path = None
            if structure_instantiation is not None:
                structure_path = os.path.join(refiner_output_dir, "structure.json")
                with open(structure_path, "w", encoding="utf-8") as f:
                    json.dump(structure_instantiation, f, ensure_ascii=False)
            layout_path = None
            if layout_instantiation is not None:
                layout_path = os.path.join(refiner_output_dir, "layout.json")
                with open(layout_path, "w", encoding="utf-8") as f:
                    json.dump(layout_instantiation, f, ensure_ascii=False)

            final_state = self.refiner.run(
                manifest_path=saved_manifest_path,
                image_path=saved_img_path,
                structure_path=structure_path,
                layout_path=layout_path,
                output_dir=refiner_output_dir,
                canvas_library=self.config.canvas_library,
                max_iterations=1,
                skip_rerender_between_iterations=True,
            )
            if getattr(final_state, "status", None) == "failed":
                errors = getattr(final_state, "errors", None) or ["unknown refiner error"]
                raise RuntimeError(
                    f"Refiner failed for sample={sample_id!r}, iteration={i}: "
                    + "; ".join(str(error) for error in errors)
                )

            # Compute objective score AFTER refinement
            refined_manifest_path = final_state.refined_manifest_path
            if refined_manifest_path and os.path.exists(refined_manifest_path):
                with open(refined_manifest_path, "r", encoding="utf-8") as f:
                    refined_manifest = json.load(f)
            else:
                refined_manifest = diagram_manifest
            if not isinstance(refined_manifest, dict):
                raise RuntimeError(
                    f"Refiner produced an invalid manifest for sample={sample_id!r}, "
                    f"iteration={i}."
                )

            refined_rendered_path = str(run_dir / "refined_diagram.png")
            refined_render_result = render_png_result(
                manifest=refined_manifest,
                output_path=refined_rendered_path,
                canvas_library=self.config.canvas_library,
            )
            if not refined_render_result.ok:
                detail = (
                    f": {refined_render_result.error}"
                    if refined_render_result.error
                    else ""
                )
                raise RuntimeError(
                    f"Refined render failed for sample={sample_id!r}, iteration={i}, "
                    f"canvas_library={self.config.canvas_library!r}: {refined_rendered_path}{detail}"
                )
            saved_refined_manifest_path = save_json(
                refined_manifest,
                os.path.join(self.config.code_dir, f"{safe_sample_id}_iter_{i}_refined.json"),
            )
            saved_refined_img_path = copy_file(
                refined_rendered_path,
                os.path.join(self.config.images_dir, f"{safe_sample_id}_iter_{i}_refined.png"),
            )
            after_artifacts = {
                "manifest": saved_refined_manifest_path,
                "image": saved_refined_img_path,
                "source_manifest": refined_manifest_path,
            }

            after_findings = run_all_checks(
                refined_manifest,
                structure=structure_instantiation,
                layout_instantiation=layout_instantiation,
                canvas_library=self.config.canvas_library,
            )
            score_after = _compute_objective_score([f.to_dict() for f in after_findings])
            delta_score = round(score_after - score_before, 2)

            # Build rich feedback with full findings + edit rationales
            feedback = _build_rich_feedback(
                before_findings, after_findings, final_state, delta_score
            )
            feedback["artifacts"] = {
                "before": before_artifacts,
                "after": after_artifacts,
            }
            iteration_feedback.append({
                "iteration": i,
                **feedback,
            })

            evaluation = {
                "quality": score_after,
                "score_before": score_before,
                "score_after": score_after,
                "artifacts": {
                    "before": before_artifacts,
                    "after": after_artifacts,
                },
            }
            if control_score is not None:
                # Per-sample constant; recorded on every iteration so any single
                # record is self-contained for the success criterion and audits.
                evaluation[CONTROL_SCORE_KEY] = control_score

            record = IterationRecord(
                id=f"{sample_id}_iter_{i}",
                iteration=i,
                tags=TagSet(domain=[content_domain], diagram_type=[diagram_type]),
                text_content=text_content,
                user_query=user_prompt,
                diagram=DiagramRef(
                    representation=saved_refined_manifest_path,
                    manifest_ref=saved_refined_img_path,
                ),
                evaluation=evaluation,
                feedback=Feedback(LLM_comments=[json.dumps(feedback, indent=2, ensure_ascii=False)]),
                delta_score=delta_score,
            )
            history.append(record)

            logger.info(
                "   [Iter %d] Δscore: %s | Before: %d findings | After: %d findings | Edits: %d",
                i, delta_score, len(before_findings), len(after_findings),
                len(feedback["edits"]),
            )

            # Carry the refined manifest into the next outer iteration so
            # successive refiner calls compose, instead of all re-refining
            # the same baseline.
            diagram_manifest = refined_manifest

        # Extract strategies from iteration history (single LLM call)
        logger.info("Extracting strategies for %s...", sample_id)
        history_json = json.dumps(iteration_feedback, indent=2, ensure_ascii=False)
        summary = self.extractor.run(text_content, content_domain, diagram_type, history_json)
        summary = _validate_strategy_summary(summary, sample_id=sample_id)

        # Average delta_score across iterations
        avg_delta = round(
            sum(r.delta_score for r in history) / max(len(history), 1), 2
        ) if history else 0.0

        strategies: List[KnowledgeEntry] = []
        for key, value in summary.items():
            entry = KnowledgeEntry(
                id=f"{sample_id}_{key}",
                tags=TagSet(
                    domain=[content_domain],
                    diagram_type=[diagram_type],
                    agent=[key]
                ),
                title=value["title"],
                description=value["description"],
                content=value.get("content", ""),
                when_to_use=value.get("when_to_use", ""),
                delta_score=avg_delta,
            )
            # Confidence uses the same formula as MaintenanceCycle so the
            # value stays comparable across creation-time and re-score time.
            entry.confidence = compute_confidence(entry)
            strategies.append(entry)

        return strategies, history
