"""Object-oriented facade for canvas conversion, rendering, and checks."""

from __future__ import annotations

from typing import Any, Dict, Optional

from .config import CanvasEnvironmentConfig
from .rendering import (
    RenderPngResult,
    RenderResult,
    render_canvas_file,
    render_manifest,
    render_png_result,
)
from .validation import (
    CanvasAuditReport,
    audit_layout_instantiation,
    audit_manifest,
    normalize_manifest,
    repair_manifest_zorder,
    validate_manifest,
)


class CanvasEnvironment:
    """Stable boundary around the canvas runtime.

    Agentic workflows should use this class or the module-level facade
    functions instead of reaching into ``agentic_system.render_engine``
    internals.
    """

    def __init__(self, config: Optional[CanvasEnvironmentConfig] = None) -> None:
        self.config = config or CanvasEnvironmentConfig()

    @property
    def canvas_library(self) -> str:
        return self.config.normalized_canvas_library()

    def render_manifest(
        self,
        layout_instantiation: Dict[str, Any],
        structure_instantiation: Dict[str, Any],
        *,
        output_dir: Optional[str] = None,
    ) -> RenderResult:
        return render_manifest(
            layout_instantiation=layout_instantiation,
            structure_instantiation=structure_instantiation,
            canvas_library=self.canvas_library,
            output_dir=output_dir,
            viewport_width=self.config.viewport_width,
            viewport_height=self.config.viewport_height,
        )

    def render_png(
        self,
        manifest: Dict[str, Any],
        output_path: str,
    ) -> bool:
        return render_png_result(
            manifest=manifest,
            output_path=output_path,
            canvas_library=self.canvas_library,
            viewport_width=self.config.viewport_width,
            viewport_height=self.config.viewport_height,
        ).ok

    def render_png_result(
        self,
        manifest: Dict[str, Any],
        output_path: str,
    ) -> RenderPngResult:
        return render_png_result(
            manifest=manifest,
            output_path=output_path,
            canvas_library=self.canvas_library,
            viewport_width=self.config.viewport_width,
            viewport_height=self.config.viewport_height,
        )

    def render_file(
        self,
        input_path: str,
        output_path: str,
    ) -> Dict[str, str]:
        return render_canvas_file(
            input_path=input_path,
            output_path=output_path,
            canvas_library=self.canvas_library,
            viewport_width=self.config.viewport_width,
            viewport_height=self.config.viewport_height,
        )

    def normalize_manifest(self, manifest: Dict[str, Any]) -> Dict[str, Any]:
        return normalize_manifest(manifest, canvas_library=self.canvas_library)

    def validate_manifest(self, manifest: Dict[str, Any]) -> Dict[str, Any]:
        return validate_manifest(manifest, canvas_library=self.canvas_library)

    def audit_manifest(
        self,
        manifest: Dict[str, Any],
        structure_instantiation: Optional[Dict[str, Any]] = None,
    ) -> CanvasAuditReport:
        return audit_manifest(
            manifest,
            structure_instantiation=structure_instantiation,
            canvas_library=self.canvas_library,
        )

    def audit_layout_instantiation(
        self,
        layout_instantiation: Dict[str, Any],
        structure_instantiation: Optional[Dict[str, Any]] = None,
    ) -> list[str]:
        return audit_layout_instantiation(
            layout_instantiation,
            structure_instantiation=structure_instantiation,
        )

    def repair_zorder(self, manifest: Dict[str, Any]) -> Dict[str, Any]:
        return repair_manifest_zorder(
            manifest,
            canvas_library=self.canvas_library,
        )


__all__ = ["CanvasEnvironment"]
