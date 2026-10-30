"""Canvas capability matrix shared by EvoDiagram runtime surfaces."""

from __future__ import annotations

from dataclasses import dataclass

from evo_diagram.canvas_runtime import VALID_CANVAS_LIBRARIES, normalize_canvas_library
from evo_diagram.config.settings import normalize_generation_mode


@dataclass(frozen=True)
class CanvasCapabilities:
    canvas_library: str
    supports_multiagent: bool
    supports_oneshot: bool
    supports_refiner: bool
    supports_knowledge_evolution: bool


_CAPABILITIES: dict[str, CanvasCapabilities] = {
    "excalidraw": CanvasCapabilities(
        canvas_library="excalidraw",
        supports_multiagent=True,
        supports_oneshot=True,
        supports_refiner=True,
        supports_knowledge_evolution=True,
    ),
    "tldraw": CanvasCapabilities(
        canvas_library="tldraw",
        supports_multiagent=True,
        supports_oneshot=False,
        supports_refiner=False,
        supports_knowledge_evolution=False,
    ),
}


def get_canvas_capabilities(canvas_library: str) -> CanvasCapabilities:
    return _CAPABILITIES[normalize_canvas_library(canvas_library)]


def generation_mode_unsupported_reason(
    *,
    canvas_library: str,
    mode: str,
) -> str | None:
    capabilities = get_canvas_capabilities(canvas_library)
    normalized_mode = normalize_generation_mode(mode)
    if normalized_mode == "multiagent" and not capabilities.supports_multiagent:
        return (
            f"multiagent generation is not supported for "
            f"canvas_library={capabilities.canvas_library!r}."
        )
    if normalized_mode == "oneshot" and not capabilities.supports_oneshot:
        return (
            "oneshot generation currently emits Excalidraw scenes only; "
            "use canvas_library='excalidraw' or switch to mode='multiagent'."
        )
    return None


def require_generation_capability(*, canvas_library: str, mode: str) -> None:
    reason = generation_mode_unsupported_reason(
        canvas_library=canvas_library,
        mode=mode,
    )
    if reason:
        raise ValueError(reason)


def refiner_unsupported_reason(*, canvas_library: str, mode: str) -> str | None:
    normalized_mode = normalize_generation_mode(mode)
    if normalized_mode == "oneshot":
        return "iterative refiner is disabled for oneshot generation."
    capabilities = get_canvas_capabilities(canvas_library)
    if not capabilities.supports_refiner:
        return (
            "iterative refiner currently supports Excalidraw manifests only "
            f"(canvas_library={capabilities.canvas_library!r})."
        )
    return None


def require_refiner_capability(*, canvas_library: str, mode: str) -> None:
    reason = refiner_unsupported_reason(canvas_library=canvas_library, mode=mode)
    if reason:
        raise ValueError(reason)


def knowledge_evolution_unsupported_reason(*, canvas_library: str) -> str | None:
    capabilities = get_canvas_capabilities(canvas_library)
    if not capabilities.supports_knowledge_evolution:
        return (
            "knowledge evolution currently requires Excalidraw-compatible "
            "refinement primitives; "
            f"canvas_library={capabilities.canvas_library!r} is generation-only "
            "for this loop."
        )
    return None


def require_knowledge_evolution_capability(*, canvas_library: str) -> None:
    reason = knowledge_evolution_unsupported_reason(canvas_library=canvas_library)
    if reason:
        raise ValueError(reason)


__all__ = [
    "CanvasCapabilities",
    "VALID_CANVAS_LIBRARIES",
    "generation_mode_unsupported_reason",
    "get_canvas_capabilities",
    "knowledge_evolution_unsupported_reason",
    "refiner_unsupported_reason",
    "require_generation_capability",
    "require_knowledge_evolution_capability",
    "require_refiner_capability",
]
