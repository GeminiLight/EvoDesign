"""Shared render utilities used by both TLDraw and Excalidraw pipelines.

The langchain tool wrapper lives in ``shared.icon_url_adder`` and is built on
first use, so rendering itself needs no langchain (the browser build).
"""

from .icon_url_adder import make_icon_url_adder_tool

__all__ = ["make_icon_url_adder_tool"]
