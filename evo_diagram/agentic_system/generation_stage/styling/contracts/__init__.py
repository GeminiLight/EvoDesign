"""Canvas-specific styling contracts for the Styling Agent."""

from evo_diagram.canvas_runtime import normalize_canvas_library

from .excalidraw import EXCALIDRAW_STYLING_CONTRACT
from .tldraw import TLDRAW_STYLING_CONTRACT

# Map canvas library name to contract
_CANVAS_CONTRACTS = {
    "excalidraw": EXCALIDRAW_STYLING_CONTRACT,
    "tldraw": TLDRAW_STYLING_CONTRACT,
}


def get_styling_contract(canvas: str) -> str:
    """Return the full styling contract for the given canvas.

    Each contract includes:
    - Canvas-specific rules, do/donts, and reminder

    Args:
        canvas: Canvas library name ("excalidraw" or "tldraw").
    """
    return _CANVAS_CONTRACTS[normalize_canvas_library(canvas)]


def get_excalidraw_contract() -> str:
    """Return Excalidraw-only styling contract."""
    return EXCALIDRAW_STYLING_CONTRACT


def get_tldraw_contract() -> str:
    """Return TLDraw-only styling contract."""
    return TLDRAW_STYLING_CONTRACT
