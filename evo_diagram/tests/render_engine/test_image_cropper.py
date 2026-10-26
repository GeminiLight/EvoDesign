"""Native export cropping must preserve faint frames and thin connectors."""

import cv2
import numpy as np
import pytest

from evo_diagram.agentic_system.render_engine.shared.image_cropper import smart_crop


@pytest.mark.parametrize("background", [(255, 255, 255), (248, 250, 252)])
def test_native_crop_preserves_faint_extents_and_requested_padding(tmp_path, background):
    image = np.full((300, 420, 3), background, dtype=np.uint8)
    # A dark title overwhelms the pale outer frame in histogram thresholding.
    cv2.rectangle(image, (100, 50), (350, 95), (32, 33, 36), -1)
    cv2.rectangle(image, (85, 115), (370, 265), (228, 231, 235), 1)
    # The outer dashed rail is intentionally only one pixel wide.
    for y in range(125, 235, 10):
        cv2.line(image, (20, y), (20, y + 4), (209, 212, 214), 1)
    source = tmp_path / "export.png"
    output = tmp_path / "cropped.png"
    cv2.imwrite(str(source), image)

    smart_crop.invoke({
        "image_path": str(source),
        "output_path": str(output),
        "canvas_engine": "excalidraw",
        "padding": 8,
    })

    cropped = cv2.imread(str(output))
    # Every source pixel in the bounds survives, with exact padding on all sides.
    assert np.array_equal(cropped, image[42:274, 12:379])
