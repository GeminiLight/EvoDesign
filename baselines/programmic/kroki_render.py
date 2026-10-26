"""
Kroki Render - Render Mermaid diagrams using Kroki service.

This module provides functionality to render Mermaid diagrams to various
output formats (PNG, SVG, PDF) using the Kroki API.
"""

import os
import base64
import random
import time
import requests
from typing import Optional
from pathlib import Path

# Statuses the public kroki.io instance returns under load or on hiccups.
# Counting these as sample failures penalises the baseline for the renderer's
# rate limit rather than for the diagram it produced.
_TRANSIENT_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})


class KrokiRender:
    """Render Mermaid diagrams using Kroki service."""

    def __init__(
        self,
        kroki_url: str = "https://kroki.io",
        diagram_type: str = "mermaid",
        output_format: str = "jpg",
        max_retries: int = 6,
        timeout: int = 30,
        backoff_base: float = 1.0,
        max_backoff: float = 30.0
    ):
        """Initialize KrokiRender.

        Args:
            kroki_url: Kroki server URL (default: https://kroki.io)
            diagram_type: Diagram type (default: mermaid)
            output_format: Output format: svg, png, pdf, jpeg, jpg (default: jpg)
            max_retries: Retries for transient HTTP failures such as 429
            timeout: Per-request timeout in seconds
            backoff_base: First backoff delay in seconds; doubles per attempt
            max_backoff: Upper bound for a single backoff delay
        """
        self.kroki_url = kroki_url.rstrip("/")
        self.diagram_type = diagram_type
        self.output_format = output_format.lower()
        self.max_retries = max(0, int(max_retries))
        self.timeout = timeout
        self.backoff_base = backoff_base
        self.max_backoff = max_backoff

        # Validate output format
        valid_formats = ["svg", "png", "pdf", "jpeg", "jpg"]
        if self.output_format not in valid_formats:
            raise ValueError(f"Invalid output format: {output_format}. Must be one of {valid_formats}")

    def _encode_diagram(self, diagram_code: str) -> str:
        """Encode diagram code using Deflate compression + Base64.

        This is Kroki's GET/URL encoding. ``render`` no longer uses it: a large
        diagram still exceeds the server URL length limit after compression and
        comes back as HTTP 414, so the source is sent in a POST body instead.
        Kept for callers that need to build a shareable Kroki URL.

        Args:
            diagram_code: Mermaid diagram code

        Returns:
            Base64 encoded diagram string
        """
        import zlib

        # Compress with zlib
        compressed = zlib.compress(diagram_code.encode("utf-8"), level=9)

        # Encode to base64
        encoded = base64.urlsafe_b64encode(compressed).decode("ascii")

        # Remove padding
        return encoded.rstrip("=")

    def _retry_delay(self, attempt: int, response: Optional[requests.Response]) -> float:
        """Backoff for *attempt* (0-based), honouring Retry-After when present."""
        if response is not None:
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                try:
                    return min(float(retry_after), self.max_backoff)
                except ValueError:
                    pass
        delay = min(self.backoff_base * (2 ** attempt), self.max_backoff)
        # Jitter keeps concurrent workers from retrying in lockstep.
        return delay * (0.5 + random.random() / 2)

    def _post_with_retry(self, url: str, diagram_code: str) -> bytes:
        """POST the diagram source, retrying transient failures with backoff."""
        last_error: Optional[Exception] = None

        for attempt in range(self.max_retries + 1):
            response = None
            try:
                response = requests.post(
                    url,
                    data=diagram_code.encode("utf-8"),
                    headers={"Content-Type": "text/plain; charset=utf-8"},
                    timeout=self.timeout,
                )
            except requests.exceptions.RequestException as e:
                last_error = e
            else:
                if response.status_code < 400:
                    return response.content
                detail = (response.text or "").strip()[:200]
                error = RuntimeError(
                    f"Failed to render diagram: HTTP {response.status_code}: {detail}"
                )
                if response.status_code not in _TRANSIENT_STATUS:
                    raise error
                last_error = error

            if attempt < self.max_retries:
                time.sleep(self._retry_delay(attempt, response))

        raise RuntimeError(f"Failed to render diagram after {self.max_retries + 1} attempts: {last_error}")

    def render(
        self,
        diagram_code: str,
        output_path: Optional[str] = None
    ) -> Optional[bytes]:
        """Render Mermaid diagram to specified format.

        The source is sent in a POST body rather than compressed into the URL:
        the GET form hits the server URL length limit (HTTP 414) on long
        diagrams, which turned large samples into failures.

        Args:
            diagram_code: Mermaid diagram code
            output_path: Optional path to save the rendered output

        Returns:
            Rendered output as bytes, or None if output_path is provided
        """
        url = f"{self.kroki_url}/{self.diagram_type}/{self.output_format}"

        output_bytes = self._post_with_retry(url, diagram_code)

        # Save to file if output_path is provided
        if output_path:
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(output_bytes)
            return None

        return output_bytes

    def render_svg(
        self,
        diagram_code: str,
        output_path: Optional[str] = None
    ) -> Optional[bytes]:
        """Render Mermaid diagram to SVG format.

        Args:
            diagram_code: Mermaid diagram code
            output_path: Optional path to save the SVG file

        Returns:
            SVG content as bytes, or None if output_path is provided
        """
        self.output_format = "svg"
        return self.render(diagram_code, output_path)

    def render_png(
        self,
        diagram_code: str,
        output_path: Optional[str] = None
    ) -> Optional[bytes]:
        """Render Mermaid diagram to PNG format.

        Args:
            diagram_code: Mermaid diagram code
            output_path: Optional path to save the PNG file

        Returns:
            PNG content as bytes, or None if output_path is provided
        """
        self.output_format = "png"
        return self.render(diagram_code, output_path)

    def render_pdf(
        self,
        diagram_code: str,
        output_path: Optional[str] = None
    ) -> Optional[bytes]:
        """Render Mermaid diagram to PDF format.

        Args:
            diagram_code: Mermaid diagram code
            output_path: Optional path to save the PDF file

        Returns:
            PDF content as bytes, or None if output_path is provided
        """
        self.output_format = "pdf"
        return self.render(diagram_code, output_path)

    def render_from_file(
        self,
        input_path: str,
        output_path: Optional[str] = None,
        output_format: Optional[str] = None
    ) -> Optional[bytes]:
        """Render Mermaid diagram from file.

        Args:
            input_path: Path to file containing Mermaid diagram code
            output_path: Optional path to save the rendered output
            output_format: Optional output format override

        Returns:
            Rendered output as bytes, or None if output_path is provided
        """
        # Read diagram code from file
        with open(input_path, "r", encoding="utf-8") as f:
            diagram_code = f.read()

        # Override output format if specified
        if output_format:
            self.output_format = output_format.lower()

        return self.render(diagram_code, output_path)

    def render_batch(
        self,
        diagram_codes: list[str],
        output_dir: str,
        prefix: str = "diagram",
        file_format: Optional[str] = None
    ) -> list[str]:
        """Render multiple Mermaid diagrams.

        Args:
            diagram_codes: List of Mermaid diagram codes
            output_dir: Directory to save rendered outputs
            prefix: Filename prefix (default: diagram)
            file_format: File extension for output files (default: uses current output_format)

        Returns:
            List of output file paths
        """
        if file_format:
            file_format = file_format.lstrip(".")
        else:
            file_format = self.output_format

        os.makedirs(output_dir, exist_ok=True)

        output_paths = []
        for idx, diagram_code in enumerate(diagram_codes, start=1):
            output_path = os.path.join(output_dir, f"{prefix}_{idx:04d}.{file_format}")
            self.render(diagram_code, output_path)
            output_paths.append(output_path)

        return output_paths


if __name__ == "__main__":
    # Test the KrokiRender class
    print("Testing KrokiRender...")

    # Sample Mermaid diagram
    sample_diagram = """
    graph TD
        A[Start] --> B{Is it working?}
        B -->|Yes| C[Great!]
        B -->|No| D[Fix it]
        D --> B
        C --> E[End]
    """

    # Create renderer
    renderer = KrokiRender(output_format="svg")

    # Test render to file
    output_path = "test_diagram.svg"
    print(f"Rendering to {output_path}...")
    renderer.render(sample_diagram, output_path)
    print(f"✓ Successfully rendered to {output_path}")

    # Test render to bytes
    print("Rendering to bytes...")
    svg_bytes = renderer.render(sample_diagram)
    print(f"✓ Successfully rendered, size: {len(svg_bytes)} bytes")

    # Test PNG format
    print("\nRendering to PNG...")
    renderer_png = KrokiRender(output_format="png")
    png_bytes = renderer_png.render(sample_diagram)
    print(f"✓ Successfully rendered PNG, size: {len(png_bytes)} bytes")

    print("\nAll tests passed!")