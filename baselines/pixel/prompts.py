"""
Prompts for Pixel Baseline.
"""

IMAGE_GENERATOR_PROMPT = """
Given the following content: {content}

Generate a professional diagram to meet the user intent "{query}".

The output should follow the visual aesthetic of a "digital whiteboard" (e.g., tldraw or Excalidraw). Use a clean white background and minimalist flat vector shapes.
""".strip()