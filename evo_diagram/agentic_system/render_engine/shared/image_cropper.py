import logging
import os

# Use headless version to avoid GL dependencies
import cv2
import numpy as np
from langchain_core.tools import tool

logger = logging.getLogger(__name__)


@tool
def smart_crop(image_path: str, output_path: str, padding: int = 0, bottom_offset: int = None, top_left_margin: int = None, canvas_engine: str = "tldraw") -> str:
    """
    Removes bottom watermarks and automatically crops white/light-gray margins.

    Args:
        image_path (str): Path to the source image.
        output_path (str): Path to save the processed image (forced to .png).
        padding (int): Extra margin to leave around the content (default: 0px for very tight crop).
        bottom_offset (int): Pixels to cut from the bottom to remove watermarks (default: auto based on canvas_engine).
        top_left_margin (int): Pixels to cut from top-left to remove menu icons (default: auto based on canvas_engine).
        canvas_engine (str): Canvas rendering engine - "excalidraw" or "tldraw" (affects which UI elements to remove).
    Returns:
        str: A message indicating the result of the operation.
    """
    # Auto-determine margins based on canvas engine if not specified
    if bottom_offset is None:
        if canvas_engine.lower() == "tldraw":
            bottom_offset = 120  # Tldraw has bottom watermark
        elif canvas_engine.lower() == "excalidraw":
            bottom_offset = 0    # Excalidraw exportToBlob output is chrome-free
        else:
            bottom_offset = 100   # Default

    if top_left_margin is None:
        if canvas_engine.lower() == "excalidraw":
            top_left_margin = 0  # exportToBlob output has no top-left icon
        elif canvas_engine.lower() == "tldraw":
            top_left_margin = 0    # Tldraw doesn't have top-left icon
        else:
            top_left_margin = 0     # Default
    # 1. Load image
    img = cv2.imread(image_path)
    if img is None:
        return f"Error: Could not read image at {image_path}"

    h, w = img.shape[:2]

    # 2. Step 1: Remove UI elements from top-left and bottom (canvas-engine-dependent)
    img_working = img[top_left_margin:h, top_left_margin:w]

    # Cut off the bottom area to eliminate fixed UI elements (e.g., watermarks)
    safe_h = max(0, img_working.shape[0] - bottom_offset)
    img_working = img_working[0:safe_h, 0:]

    # Native Excalidraw exports have clean, uniform padding, with no UI to
    # remove. A dark title can dominate Otsu's threshold and erase pale frame
    # borders or dashed relations from the bounds. Morphological opening also
    # erases thin strokes. Preserve every visible deviation from the exported
    # canvas color, including single-pixel lines and tinted backgrounds.
    if canvas_engine.lower() == "excalidraw":
        background = img_working[0, 0].astype(np.int16)
        difference = np.max(
            np.abs(img_working.astype(np.int16) - background), axis=2
        )
        thresh = (difference > 2).astype(np.uint8) * 255
    else:
        gray = cv2.cvtColor(img_working, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(
            gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
        )
        kernel = np.ones((5, 5), np.uint8)
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel, iterations=2)
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel, iterations=1)

    # 6. Bounding Box Calculation
    # Find all non-zero (white) pixels which represent the actual diagram content
    coords = cv2.findNonZero(thresh)

    if coords is None:
        return "Warning: No valid content detected after watermark removal."

    # Calculate the minimal upright bounding rectangle
    x, y, cw, ch = cv2.boundingRect(coords)

    # 7. Apply Padding and Boundary Constraints
    h_work, w_work = img_working.shape[:2]
    final_x1 = max(0, x - padding)
    final_y1 = max(0, y - padding)
    final_x2 = min(w_work, x + cw + padding)
    final_y2 = min(h_work, y + ch + padding)

    # 8. Final Crop and Export
    # Slice the image using calculated coordinates
    final_img = img_working[final_y1:final_y2, final_x1:final_x2]

    # Ensure output is PNG for lossless quality in papers/reports
    final_output_path = os.path.splitext(output_path)[0] + ".png"
    cv2.imwrite(final_output_path, final_img)

    result_msg = (f"Resized: {w}x{h} -> {final_img.shape[1]}x{final_img.shape[0]}\n"
                  f"Saved to: {final_output_path}")
    logger.info("%s", result_msg)
    return result_msg

if __name__ == "__main__":
    # Example usage for your ReAct framework diagram
    input_img = "./examples/react_paper/rendered_diagram.png"
    output_img = "./examples/react_paper/cropped_rendered_diagram.png"

    # When invoking directly as a tool object for testing
    try:
        smart_crop.invoke({
            "image_path": input_img,
            "output_path": output_img,
            "bottom_offset": 120,
            "padding": 20
        })
    except Exception as e:
        print(f"Tool invocation failed: {e}")
