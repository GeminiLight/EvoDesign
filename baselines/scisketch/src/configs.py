import os

DIAGRAM_CONFIGS = {
    "mermaid": {
        "language": "mermaid",
        "file_extension": ".mmd",
        "parse_format": "mermaid",
        # "output_directory": "generated_diagram_mermaid",
    },
    "tikz": {
        "language": "tikz/LaTeX",
        "file_extension": ".tex",
        "parse_format": "latex",
        # "output_directory": "generated_diagram_latex",
    },
    "drawio": {
        "language": "drwaio mxGraph/xml",
        "file_extension": ".drawio",
        "parse_format": "xml",
        # "output_directory": "generated_diagram_drawio_with_image",
    },
    "svg": {
        "language": "svg",
        "file_extension": ".svg",
        "parse_format": "svg",
        # "output_directory": "generated_diagram_svg",
    },
}

_DEFAULT_ENGINE = os.getenv("ELYSIVER_MODEL") or os.getenv("OPENAI_MODEL") or ""

ENGINE_CONFIGS = {
    "text_analysis": _DEFAULT_ENGINE or "gpt-4.1",
    "layout_generation": _DEFAULT_ENGINE or "gpt-4.1",
    "layout_refinement": _DEFAULT_ENGINE or "gpt-4.1",
    "graphic_code_verification": _DEFAULT_ENGINE or "gpt-4.1",
    "element_discriminator": _DEFAULT_ENGINE or "gpt-4.1",
    "image_retrieval": _DEFAULT_ENGINE or "gpt-4.1",
    "svg_generation": _DEFAULT_ENGINE or "gpt-4.1",
}
