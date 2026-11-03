"""Import boundary for the local EvoDesign engine package."""

from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
REQUIRED_ENGINE_MODULES = (
    "evodesign.agentic_system.workflow",
    "evodesign.canvas_environment",
    "evodesign.core.llm_factory",
)
RECOVERABLE_IMPORT_ROOTS = frozenset({"evodesign"})


@dataclass(frozen=True)
class _EngineImportAttempt:
    stage: str
    error: ModuleNotFoundError


class EvoDesignImportError(ModuleNotFoundError):
    """Raised when EvoDesign engine package resolution fails."""

    def __init__(self, attempts: list[_EngineImportAttempt]):
        self.attempts = tuple(attempts)
        details = "; ".join(
            f"{attempt.stage}: {attempt.error}" for attempt in attempts
        )
        super().__init__(
            "Failed to import required EvoDesign engine modules after "
            f"{len(attempts)} attempts ({details})"
        )


def ensure_evodesign_importable() -> None:
    """Make the EvoDesign engine importable from an installed package or checkout."""
    attempts: list[_EngineImportAttempt] = []

    if _has_checkout_engine_package():
        _prepend_repo_root()

    try:
        _import_engine_modules()
        return
    except ModuleNotFoundError as exc:
        attempts.append(_EngineImportAttempt("evodesign package", exc))
        _raise_unrecoverable_import(attempts, exc)

    _prepend_repo_root()

    try:
        _import_engine_modules()
    except ModuleNotFoundError as exc:
        attempts.append(_EngineImportAttempt("source checkout package path", exc))
        raise EvoDesignImportError(attempts) from exc


def _raise_unrecoverable_import(
    attempts: list[_EngineImportAttempt],
    exc: ModuleNotFoundError,
) -> None:
    """Stop fallback attempts when the missing module is not an engine alias."""
    if _is_recoverable_import_error(exc):
        return
    raise EvoDesignImportError(attempts) from exc


def _has_checkout_engine_package() -> bool:
    return (REPO_ROOT / "evodesign" / "__init__.py").exists()


def _prepend_repo_root() -> None:
    path_text = str(REPO_ROOT)
    if path_text not in sys.path:
        sys.path.insert(0, path_text)
        importlib.invalidate_caches()


def _is_recoverable_import_error(exc: ModuleNotFoundError) -> bool:
    missing_name = exc.name or ""
    missing_root = missing_name.split(".", 1)[0]
    return missing_root in RECOVERABLE_IMPORT_ROOTS


def _import_engine_modules() -> None:
    """Verify that the backend's required engine package imports resolve."""
    for module_name in REQUIRED_ENGINE_MODULES:
        try:
            importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            raise ModuleNotFoundError(
                f"Failed importing required EvoDesign module {module_name!r}: {exc}",
                name=exc.name,
                path=exc.path,
            ) from exc
