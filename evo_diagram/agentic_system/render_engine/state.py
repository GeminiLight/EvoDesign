
from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import Field

from ..common.workflow_state_base import WorkflowStateBase
from .stages import CONVERT, MANIFEST_STAGES, RENDER, VALIDATE


def _require_manifest(stage: str, payload: Dict[str, Any]) -> Dict[str, Any]:
	manifest = payload.get("manifest")
	if not isinstance(manifest, dict):
		raise ValueError(
			f"RenderWorkflow stage {stage!r} must return a manifest dict; "
			f"got {type(manifest).__name__}."
		)
	if not isinstance(manifest.get("elements"), list) and not isinstance(manifest.get("document"), dict):
		raise ValueError(
			f"RenderWorkflow stage {stage!r} returned an invalid manifest. "
			"Expected a top-level 'elements' list or 'document' object."
		)
	return manifest


class WorkflowState(WorkflowStateBase):
	"""State container for the render workflow pipeline."""

	structure_instantiation: Dict[str, Any] = Field(description="Semantic Topology used for arrow generation.")
	layout_instantiation: Dict[str, Any] = Field(description="Positioned styling JSON emitted by the layout workflow.")

	validation_report: Optional[Dict[str, Any]] = None

	diagram_manifest: Optional[Dict[str, Any]] = None
	# Intermediate snapshot without arrows, kept for debug or further processing
	manifest_without_arrows: Optional[Dict[str, Any]] = None

	render_stdout: Optional[str] = None
	render_stderr: Optional[str] = None

	def update_stage(self, stage: str, payload: Optional[Dict[str, Any]] = None) -> None:
		"""Update workflow bookkeeping after each stage finishes."""

		payload = payload or {}
		self.current_stage = stage

		if stage in MANIFEST_STAGES:
			manifest = _require_manifest(stage, payload)
			if stage == CONVERT:
				self.manifest_without_arrows = manifest
			self.diagram_manifest = manifest
		elif stage == VALIDATE:
			self.validation_report = payload
		elif stage == RENDER:
			self.render_stdout = payload.get("stdout")
			self.render_stderr = payload.get("stderr")
		else:
			raise ValueError(f"Unknown stage name: {stage}")
