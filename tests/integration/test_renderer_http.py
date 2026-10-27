"""Exercise a built renderer service; run with RENDERER_SMOKE_URL set locally."""

import io
import json
import os
import urllib.request

import pytest
from PIL import Image, ImageChops

from evo_diagram.agentic_system.render_engine.excalidraw.converter import InstantiationToExcalidrawConverter
from evo_diagram.agentic_system.render_engine.tldraw.converter import InstantiationToTldrawConverter

SERVICE = os.getenv("RENDERER_SMOKE_URL", "")
pytestmark = pytest.mark.skipif(not SERVICE, reason="Set RENDERER_SMOKE_URL to a running renderer service")


@pytest.mark.parametrize("engine,converter,field,use_icons", [
    ("excalidraw", InstantiationToExcalidrawConverter, "scene", False),
    ("excalidraw", InstantiationToExcalidrawConverter, "scene", True),
    ("tldraw", InstantiationToTldrawConverter, "snapshot", False),
])
def test_renderer_exports_visible_shapes_and_standalone_text(engine, converter, field, use_icons):
    layout = {
        "title": {"type": "text", "x": 60, "y": 20, "w": 240, "h": 30,
                  "label": {"text": "Renderer smoke test"}},
        "node": {"type": "rectangle", "x": 60, "y": 90, "w": 240, "h": 100,
                 "label": {"text": "Visible node"}, "fillStyle": "solid",
                 "backgroundColor": "#e0e7ff", "strokeColor": "#64748b"},
    }
    if use_icons:
        layout["node:icon"] = {"type": "icon", "props": {"icon": "analytics", "color": "blue"}}
    manifest = converter(layout_instantiation=layout).convert()
    if use_icons:
        assert manifest["files"]
        assert any(element["type"] == "image" for element in manifest["elements"])
    request = urllib.request.Request(
        SERVICE.rstrip("/") + f"/api/v1/renderers/{engine}/snapshot",
        data=json.dumps({field: manifest, "viewport": {"width": 1000, "height": 700}}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=75) as response:
        assert response.headers.get_content_type() == "image/png"
        image = Image.open(io.BytesIO(response.read())).convert("RGB")
    # Check the diagram area rather than accepting a valid but blank PNG or
    # counting a canvas watermark as rendered diagram content.
    area = image.crop((image.width // 5, image.height // 10,
                       image.width * 4 // 5, image.height * 9 // 10))
    background = Image.new("RGB", area.size, image.getpixel((0, 0)))
    ink = ImageChops.difference(area, background).convert("L")
    visible = sum(count for value, count in enumerate(ink.histogram()) if value > 12)
    assert visible / (area.width * area.height) > 0.005, "Renderer returned a blank diagram"
