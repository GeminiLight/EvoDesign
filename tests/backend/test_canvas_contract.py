from __future__ import annotations

import pytest

from app.core.canvas import (
    SUPPORTED_CANVAS_LIBRARIES,
    SUPPORTED_REFINER_CANVAS_LIBRARIES,
    canvas_library_supports_refiner,
    normalize_canvas_library_value,
)


def test_backend_canvas_library_contract_normalizes_supported_values():
    assert SUPPORTED_CANVAS_LIBRARIES == ("excalidraw", "tldraw")
    assert normalize_canvas_library_value(" Excalidraw ") == "excalidraw"
    assert normalize_canvas_library_value(" TLDraw ") == "tldraw"


def test_backend_canvas_library_contract_rejects_unknown_values():
    with pytest.raises(ValueError, match="Unsupported canvas library"):
        normalize_canvas_library_value("mermaid")


def test_backend_refiner_canvas_capability_is_explicit_and_normalized():
    assert SUPPORTED_REFINER_CANVAS_LIBRARIES == ("excalidraw",)
    assert canvas_library_supports_refiner(" Excalidraw ") is True
    assert canvas_library_supports_refiner("tldraw") is False
    with pytest.raises(ValueError, match="Unsupported canvas library"):
        canvas_library_supports_refiner("bad-canvas")
