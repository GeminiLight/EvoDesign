
from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import END, StateGraph

from evo_diagram.canvas_runtime import normalize_canvas_library

from .state import WorkflowState
from .shared.icon_url_adder import icon_url_adder
from .shared.render_audit import audit_layout_instantiation, audit_tldraw_manifest
from .stages import (
	ALIGN_GROUPS,
	ARROW,
	CONVERT,
	FIT_GROUPS,
	SIZE_FIT,
	VALIDATE,
	ZORDER_REPAIR,
)

logger = logging.getLogger(__name__)


def _raise_on_blocking_render_audit(report: Any, *, canvas_library: str) -> None:
	"""Fail the render workflow on semantic losses that later validators miss."""
	issues = getattr(report, "issues", None)
	if not isinstance(issues, list):
		return
	blocking = [
		issue
		for issue in issues
		if getattr(issue, "category", None) == "arrow_coverage"
	]
	if not blocking:
		return
	details = "\n".join(getattr(issue, "message", str(issue)) for issue in blocking)
	raise RuntimeError(
		f"{canvas_library} render audit failed: structure edges were not "
		f"faithfully rendered.\n{details}"
	)


class RenderWorkflow:
	"""Sequential workflow that converts styling data, adds arrows, validates, and renders."""

	def __init__(self, canvas_library: str = None) -> None:
		if canvas_library is None:
			canvas_library = WorkflowState.model_fields["canvas_library"].default
		self.canvas_library = normalize_canvas_library(canvas_library)

		self._graph_builder = StateGraph(WorkflowState)
		if self.canvas_library == "excalidraw":
			self.graph = self._build_excalidraw_workflow()
		else:
			self.graph = self._build_tldraw_workflow()

	# ==================================================================
	# TLDraw workflow
	# ==================================================================
	def _build_tldraw_workflow(self):
		workflow = self._graph_builder
		workflow.add_node("add_icon_urls", self._run_icon_url_adder)
		workflow.add_node("convert_snapshot", self._run_converter)
		workflow.add_node("add_arrows", self._run_arrow_tool)
		workflow.add_node("fit_groups", self._run_group_fitter)
		workflow.add_node("validate_snapshot", self._run_validator)
		workflow.set_entry_point("add_icon_urls")
		workflow.add_edge("add_icon_urls", "convert_snapshot")
		workflow.add_edge("convert_snapshot", "add_arrows")
		workflow.add_edge("add_arrows", "fit_groups")
		workflow.add_edge("fit_groups", "validate_snapshot")
		workflow.add_edge("validate_snapshot", END)
		return workflow.compile()

	def _run_icon_url_adder(self, state: WorkflowState) -> WorkflowState:
		"""Add icon URLs to styling_instantiation before conversion."""
		updated_layout = icon_url_adder.invoke({
			"styling_json": state.layout_instantiation
		})
		state.layout_instantiation = updated_layout
		logger.info("[RenderWorkflow] Icon URLs added to layout_instantiation")
		return state

	def _run_converter(self, state: WorkflowState) -> WorkflowState:
		"""Convert positioned styling JSON into a TLDraw manifest."""
		from .tldraw.converter import InstantiationToTldrawConverter
		audit_layout_instantiation(
			state.layout_instantiation,
			state.structure_instantiation,
		)
		converter = InstantiationToTldrawConverter(
			layout_instantiation=state.layout_instantiation,
			structure_instantiation=state.structure_instantiation,
		)
		manifest = converter.convert()
		state.update_stage(CONVERT, {"manifest": manifest})
		logger.info("[RenderWorkflow] Manifest (no arrows) generated in memory")
		return state

	def _run_arrow_tool(self, state: WorkflowState) -> WorkflowState:
		"""Enrich manifest with arrows using concept hierarchy relations."""
		from .tldraw.arrow_adder import make_arrow_adder_tool
		arrow_tool = make_arrow_adder_tool()
		base_manifest = state.diagram_manifest or state.manifest_without_arrows
		enriched_manifest = arrow_tool.invoke(
			{
				"manifest_json": base_manifest,
				"concept_json": state.structure_instantiation,
				"output_path": "",
			}
		)
		state.update_stage(ARROW, {"manifest": enriched_manifest})
		report = audit_tldraw_manifest(enriched_manifest, state.structure_instantiation)
		_raise_on_blocking_render_audit(report, canvas_library="TLDraw")
		logger.info("[RenderWorkflow] Manifest enriched with arrows in memory")
		return state

	def _run_group_fitter(self, state: WorkflowState) -> WorkflowState:
		"""Fit group frames to contain their child nodes."""
		from .tldraw.group_fitter import fit_groups_to_children
		logger.info("[RenderWorkflow] Fitting group frames to children")
		fitted_manifest = fit_groups_to_children(
			manifest=state.diagram_manifest,
			structure_instantiation=state.structure_instantiation,
			padding=20
		)
		state.update_stage(FIT_GROUPS, {"manifest": fitted_manifest})
		logger.info("[RenderWorkflow] Group frames fitted successfully")
		return state

	def _run_validator(self, state: WorkflowState) -> WorkflowState:
		"""Validate manifest structure before rendering."""
		from .tldraw.validator import validate_tldraw_manifest
		logger.info("[RenderWorkflow] Validating manifest structure")
		report = validate_tldraw_manifest(manifest_data=state.diagram_manifest)
		state.update_stage(VALIDATE, report)
		if not report.get("is_valid", False):
			errors = "\n".join(report.get("errors", []))
			raise ValueError(f"Snapshot validation failed:\n{errors}")
		return state

	# ==================================================================
	# Excalidraw workflow
	# ==================================================================
	def _build_excalidraw_workflow(self):
		workflow = self._graph_builder
		workflow.add_node("excalidraw_add_icon_urls", self._run_excalidraw_icon_url_adder)
		workflow.add_node("excalidraw_convert", self._run_excalidraw_converter)
		workflow.add_node("excalidraw_size_fit", self._run_excalidraw_size_fit)
		workflow.add_node("excalidraw_fit_groups", self._run_excalidraw_group_fitter)
		workflow.add_node("excalidraw_align_groups", self._run_excalidraw_group_alignment)
		workflow.add_node("excalidraw_arrows", self._run_excalidraw_arrow_adder)
		workflow.add_node("excalidraw_zorder_repair", self._run_excalidraw_zorder_repair)
		workflow.add_node("excalidraw_validate", self._run_excalidraw_validator)
		workflow.set_entry_point("excalidraw_add_icon_urls")
		workflow.add_edge("excalidraw_add_icon_urls", "excalidraw_convert")
		workflow.add_edge("excalidraw_convert", "excalidraw_size_fit")
		workflow.add_edge("excalidraw_size_fit", "excalidraw_fit_groups")
		workflow.add_edge("excalidraw_fit_groups", "excalidraw_align_groups")
		workflow.add_edge("excalidraw_align_groups", "excalidraw_arrows")
		workflow.add_edge("excalidraw_arrows", "excalidraw_zorder_repair")
		workflow.add_edge("excalidraw_zorder_repair", "excalidraw_validate")
		workflow.add_edge("excalidraw_validate", END)
		return workflow.compile()

	def _run_excalidraw_icon_url_adder(self, state: WorkflowState) -> WorkflowState:
		"""Add icon URLs to styling_instantiation before Excalidraw conversion."""
		updated_layout = icon_url_adder.invoke({
			"styling_json": state.layout_instantiation
		})
		state.layout_instantiation = updated_layout
		logger.info("[RenderWorkflow/Excalidraw] Icon URLs added to layout_instantiation")
		return state

	def _run_excalidraw_converter(self, state: WorkflowState) -> WorkflowState:
		"""Convert positioned styling JSON into an Excalidraw manifest."""
		from .excalidraw.converter import InstantiationToExcalidrawConverter
		audit_layout_instantiation(
			state.layout_instantiation,
			state.structure_instantiation,
		)
		converter = InstantiationToExcalidrawConverter(
			layout_instantiation=state.layout_instantiation,
			structure_instantiation=state.structure_instantiation,
		)
		manifest = converter.convert()
		state.update_stage(CONVERT, {"manifest": manifest})
		logger.info("[RenderWorkflow/Excalidraw] Manifest (no arrows) generated in memory")
		return state

	def _run_excalidraw_size_fit(self, state: WorkflowState) -> WorkflowState:
		"""Enforce shape.width/height ≥ bound-text bbox (plus shape-type padding).

			Runs AFTER convert (manifest is populated) and BEFORE fit_groups
			(group frames wrap the enlarged children) and arrows (waypoints need
			final shape bboxes after all geometry passes). Only expands, keeps
			shape center, syncs bound-text geometry.
		"""
		from .excalidraw.shape_size_fitter import fit_shape_sizes_to_text
		fitted_manifest = fit_shape_sizes_to_text(state.diagram_manifest)
		state.update_stage(SIZE_FIT, {"manifest": fitted_manifest})
		logger.info("[RenderWorkflow/Excalidraw] Shape sizes fitted to bound text")
		return state

	def _run_excalidraw_arrow_adder(self, state: WorkflowState) -> WorkflowState:
		"""Enrich Excalidraw manifest with arrows from structure_instantiation."""
		from .excalidraw.arrow_adder import add_excalidraw_arrows_to_manifest
		from .excalidraw.architecture_style_normalizer import normalize_architecture_style
		from .shared.render_audit import audit_excalidraw_manifest
		base_manifest = state.diagram_manifest or state.manifest_without_arrows
		enriched_manifest = add_excalidraw_arrows_to_manifest(
			manifest=base_manifest,
			structure_instantiation=state.structure_instantiation,
		)
		enriched_manifest = normalize_architecture_style(
			manifest=enriched_manifest,
			structure_instantiation=state.structure_instantiation,
			layout_instantiation=state.layout_instantiation,
		)
		state.update_stage(ARROW, {"manifest": enriched_manifest})
		report = audit_excalidraw_manifest(enriched_manifest, state.structure_instantiation)
		_raise_on_blocking_render_audit(report, canvas_library="Excalidraw")
		logger.info("[RenderWorkflow/Excalidraw] Manifest enriched with arrows in memory")
		return state

	def _run_excalidraw_group_fitter(self, state: WorkflowState) -> WorkflowState:
		"""Fit group backgrounds in Excalidraw manifest to wrap children."""
		from .excalidraw.group_fitter import fit_excalidraw_groups_to_children
		logger.info("[RenderWorkflow/Excalidraw] Fitting group frames to children")
		fitted_manifest = fit_excalidraw_groups_to_children(
			manifest=state.diagram_manifest,
			structure_instantiation=state.structure_instantiation,
			padding=20,
		)
		state.update_stage(FIT_GROUPS, {"manifest": fitted_manifest})
		logger.info("[RenderWorkflow/Excalidraw] Group frames fitted successfully")
		return state

	def _run_excalidraw_group_alignment(self, state: WorkflowState) -> WorkflowState:
		"""Preserve equal-width/equal-height group intent from layout output."""
		from .excalidraw.group_alignment_normalizer import preserve_group_alignment_intent
		from .excalidraw.layered_layout_compactor import compact_architecture_layout
		from .excalidraw.radial_concept_compactor import compact_concept_map_layout
		aligned_manifest = preserve_group_alignment_intent(
			manifest=state.diagram_manifest,
			layout_instantiation=state.layout_instantiation,
		)
		aligned_manifest = compact_architecture_layout(
			manifest=aligned_manifest,
			structure_instantiation=state.structure_instantiation,
		)
		aligned_manifest = compact_concept_map_layout(
			manifest=aligned_manifest,
			structure_instantiation=state.structure_instantiation,
		)
		state.update_stage(ALIGN_GROUPS, {"manifest": aligned_manifest})
		logger.info("[RenderWorkflow/Excalidraw] Group alignment intent preserved")
		return state

	def _run_excalidraw_zorder_repair(self, state: WorkflowState) -> WorkflowState:
		"""Reassign fractional indices by layer band so group frames never occlude their children."""
		from .excalidraw.zorder_repair import is_enabled as _zorder_repair_enabled, repair_zorder
		if not _zorder_repair_enabled():
			logger.info(
				"[RenderWorkflow/Excalidraw] zorder_repair disabled via "
				"EVODIAGRAM_RENDER_FIX_ZORDER; skipping."
			)
			return state
		repaired_manifest = repair_zorder(state.diagram_manifest)
		state.update_stage(ZORDER_REPAIR, {"manifest": repaired_manifest})
		return state

	def _run_excalidraw_validator(self, state: WorkflowState) -> WorkflowState:
		"""Validate Excalidraw manifest structure."""
		from .excalidraw.validator import validate_excalidraw_manifest
		logger.info("[RenderWorkflow/Excalidraw] Validating manifest structure")
		report = validate_excalidraw_manifest(manifest_data=state.diagram_manifest)
		state.update_stage(VALIDATE, report)
		if not report.get("is_valid", False):
			errors = "\n".join(report.get("errors", []))
			raise ValueError(f"Excalidraw manifest validation failed:\n{errors}")
		return state

	def run(self, state: WorkflowState) -> WorkflowState:
		"""Run all stages and return the completed state."""
		logger.info(f"Starting render workflow (canvas_library={self.canvas_library})...")
		result_dict = self.graph.invoke(state)
		result = WorkflowState(**result_dict) if isinstance(result_dict, dict) else result_dict
		logger.info("Render workflow finished.")
		return result
