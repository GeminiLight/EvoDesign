"""Canvas runtime boundary for EvoDiagram.

The package is intentionally outside ``agentic_system``. It exposes stable
facades for canvas conversion, validation, audit, and rendering.
"""

from evo_diagram.canvas_runtime import normalize_canvas_library

from .config import CanvasEnvironmentConfig
from .constants import (
    CANVAS_DEFAULT_VIEWPORT_HEIGHT,
    CANVAS_DEFAULT_VIEWPORT_WIDTH,
    CANVAS_MARGIN,
    CANVAS_MAX_X,
    CANVAS_MAX_Y,
    VALID_CANVAS_LIBRARIES,
)
from .environment import CanvasEnvironment
from .editing import EditError, apply_operations, assert_preserves_locks
from .geometry import (
    ARROW_SIDES,
    ArrowRouteGeometry,
    route_arrow_between_bboxes,
)
from .scene import (
    color_contrast_ratio,
    compact_architecture_layout,
    disjoint_segment_box_distance,
    excalidraw_element_defaults,
    normalize_architecture_style,
    rebuild_excalidraw_arrows,
)
from .rendering import (
    ANALYSIS_RENDER_SCALE,
    RenderPngResult,
    RenderResult,
    render_canvas,
    render_canvas_file,
    render_manifest,
    render_png_result,
)
from .validation import (
    CanvasAuditIssue,
    CanvasAuditReport,
    audit_layout_instantiation,
    audit_manifest,
    detect_group_frame_ids,
    normalize_manifest,
    repair_manifest_zorder,
    validate_manifest,
    validate_png_file,
)

__all__ = [
    "EditError",
    "apply_operations",
    "assert_preserves_locks",
    "color_contrast_ratio",
    "compact_architecture_layout",
    "disjoint_segment_box_distance",
    "excalidraw_element_defaults",
    "normalize_architecture_style",
    "rebuild_excalidraw_arrows",
    "ARROW_SIDES",
    "ArrowRouteGeometry",
    "CanvasEnvironment",
    "CanvasEnvironmentConfig",
    "CanvasAuditIssue",
    "CanvasAuditReport",
    "CANVAS_MARGIN",
    "CANVAS_MAX_X",
    "CANVAS_MAX_Y",
    "VALID_CANVAS_LIBRARIES",
    "CANVAS_DEFAULT_VIEWPORT_WIDTH",
    "CANVAS_DEFAULT_VIEWPORT_HEIGHT",
    "normalize_canvas_library",
    "ANALYSIS_RENDER_SCALE",
    "RenderPngResult",
    "RenderResult",
    "render_canvas",
    "render_canvas_file",
    "render_manifest",
    "render_png_result",
    "normalize_manifest",
    "validate_manifest",
    "audit_manifest",
    "audit_layout_instantiation",
    "repair_manifest_zorder",
    "route_arrow_between_bboxes",
    "detect_group_frame_ids",
    "validate_png_file",
]
