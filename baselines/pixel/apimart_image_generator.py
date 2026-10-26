#!/usr/bin/env python
"""
Simple Apimart Image Generator

Environment variables (.env):
    APIMART_API_KEY=your-api-key
    APIMART_MODEL_NAME=gpt-4o-image
    APIMART_API_BASE=https://api.apimart.ai/v1

Usage:
    generator = ApimartImageGenerator()
    generator.generate_image("Create a flowchart", "output.png")

    # Or override with parameters
    generator = ApimartImageGenerator(
        api_key="your-token",
        model="gpt-4o-image"
    )
    generator.generate_image("Create a flowchart", "output.png")
"""

import os
import sys
import base64
import time
import httpx
from typing import Optional, Dict, Any
from PIL import Image
from io import BytesIO

from dotenv import load_dotenv
from evo_diagram.utils.env_loader import ensure_env_loaded

try:
    from baselines.pixel.prompts import IMAGE_GENERATOR_PROMPT
except ImportError:
    IMAGE_GENERATOR_PROMPT = "Generate a professional diagram: {content}"


# Constants
DEFAULT_TIMEOUT = 60
POLL_TIMEOUT = 30
MAX_RETRIES = 60
POLL_INTERVAL = 10

# Task status constants
STATUS_PENDING = "pending"
STATUS_PROCESSING = "processing"
STATUS_RUNNING = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"


# Model-specific parameter configurations
MODEL_CONFIGS = {
    # Gemini models support resolution parameter
    "gemini-3-pro-image-preview": {
        "optional_params": ["resolution"],
        "default_params": {"resolution": "1K"}
    },
    "gemini-2.5-flash-image-preview": {
        "optional_params": ["image_urls"],
        "default_params": {}
    },
    # Flux models support resolution
    "flux-2-flex": {
        "optional_params": ["resolution"],
        "default_params": {"resolution": "1K"}
    },
    "flux-kontext-pro": {
        "optional_params": ["image_urls"],
        "default_params": {}
    },
    # Doubao models support resolution
    "doubao-seedance-4-5": {
        "optional_params": ["resolution", "image_urls"],
        "default_params": {"resolution": "2K"}
    },
    # GPT models (default)
    "gpt-4o-image": {
        "optional_params": ["image_urls"],
        "default_params": {}
    },
}


class ApimartImageGenerator:
    """Simple image generator for Apimart API."""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None, api_base: Optional[str] = None):
        """Initialize with API key and model name."""
        self.api_key = api_key
        self.model = model or "gpt-4o-image"
        self.api_base = api_base or "https://api.apimart.ai/v1"
        self.model_config = MODEL_CONFIGS.get(self.model, MODEL_CONFIGS["gpt-4o-image"])

    def _get_model_defaults(self) -> Dict[str, Any]:
        """Get default parameters for the current model."""
        return self.model_config.get("default_params", {})

    def _get_headers(self) -> Dict[str, str]:
        """Get common request headers."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    def _save_from_url(self, url: str, output_path: str) -> bool:
        """Download and save image from URL."""
        try:
            with httpx.Client(timeout=POLL_TIMEOUT) as client:
                response = client.get(url)
                response.raise_for_status()
                img = Image.open(BytesIO(response.content))
                img.save(output_path)
                print(f"Image saved to {output_path}")
                return True
        except Exception as e:
            print(f"Error downloading image from URL: {e}")
            return False

    def _save_from_base64(self, b64_data: str, output_path: str) -> bool:
        """Decode and save image from base64."""
        try:
            img_bytes = base64.b64decode(b64_data)
            img = Image.open(BytesIO(img_bytes))
            img.save(output_path)
            print(f"Image saved to {output_path}")
            return True
        except Exception as e:
            print(f"Error decoding base64 image: {e}")
            return False

    def save_image(self, image_data: Dict[str, Any], output_path: str) -> bool:
        """Save image from URL or base64."""
        # Create output directory if needed
        output_dir = os.path.dirname(output_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

        if "url" in image_data:
            return self._save_from_url(image_data["url"], output_path)
        elif "b64_json" in image_data:
            return self._save_from_base64(image_data["b64_json"], output_path)

        print("Error: No valid image data found (url or b64_json)")
        return False

    def _poll_task_status(self, task_id: str, max_retries: int = MAX_RETRIES, poll_interval: int = POLL_INTERVAL) -> Optional[Dict[str, Any]]:
        """Poll task status until completion or failure."""
        headers = self._get_headers()
        processing_statuses = {STATUS_PENDING, STATUS_PROCESSING, STATUS_RUNNING}

        for attempt in range(max_retries):
            try:
                with httpx.Client(timeout=POLL_TIMEOUT) as client:
                    response = client.get(
                        f"{self.api_base}/tasks/{task_id}",
                        headers=headers
                    )
                    response.raise_for_status()
                    task_data = response.json().get("data", {})
                    status = task_data.get("status", "unknown")
                    print(f"Task {task_id} status: {status} (attempt {attempt + 1}/{max_retries})")

                    if status in (STATUS_SUCCEEDED, STATUS_COMPLETED):
                        return task_data
                    elif status == STATUS_FAILED:
                        error_msg = task_data.get("error", "Unknown error")
                        print(f"Task failed: {error_msg}")
                        return None
                    elif status in processing_statuses:
                        time.sleep(poll_interval)
                    else:
                        print(f"Warning: Unknown status '{status}', continuing to poll...")
                        time.sleep(poll_interval)

            except httpx.HTTPStatusError as e:
                print(f"HTTP error polling task status: {e.response.status_code} - {e}")
                time.sleep(poll_interval)
            except Exception as e:
                print(f"Error polling task status: {e}")
                time.sleep(poll_interval)

        print(f"Task timed out after {max_retries * poll_interval} seconds")
        return None

    def generate_image(self, content: str, output_path: str = "output.png", **kwargs) -> bool:
        """Generate and save an image using asynchronous task processing."""
        if not self.api_key:
            print("Error: API key not provided")
            return False

        # Build request payload
        prompt = IMAGE_GENERATOR_PROMPT.format(content=content, query=kwargs.get("query", content))

        # Start with base parameters
        payload = {
            "model": self.model,
            "prompt": prompt,
        }

        # Add model-specific defaults
        model_defaults = self._get_model_defaults()
        for key, value in model_defaults.items():
            if key not in kwargs:  # Only add if not overridden by user
                payload[key] = value

        # Add optional parameters
        # Common parameters
        if "size" in kwargs:
            payload["size"] = kwargs["size"]
        elif "size" not in model_defaults:
            payload["size"] = "1:1"  # Default size if not specified

        # n parameter (number of images)
        if "n" in kwargs:
            payload["n"] = kwargs["n"]
        elif "n" not in model_defaults:
            payload["n"] = 1  # Default to 1 image

        # Resolution parameter (for Gemini, Flux, Doubao models)
        if "resolution" in kwargs:
            payload["resolution"] = kwargs["resolution"]

        # Reference images (for models that support them)
        if kwargs.get("image_urls"):
            payload["image_urls"] = kwargs["image_urls"]

        headers = self._get_headers()

        try:
            # Submit image generation request
            with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
                response = client.post(
                    f"{self.api_base}/images/generations",
                    json=payload,
                    headers=headers
                )
                response.raise_for_status()
                data = response.json()

            # Handle response: check for task_id (async) or image data (sync)
            # The API may return task_id directly in response or nested in data array
            task_id = None

            if "task_id" in data:
                task_id = data["task_id"]
            elif data.get("data") and isinstance(data["data"], list) and len(data["data"]) > 0:
                first_item = data["data"][0]
                if isinstance(first_item, dict):
                    if "task_id" in first_item:
                        task_id = first_item["task_id"]
                    elif first_item.get("status") == "submitted" and "task_id" in first_item:
                        task_id = first_item["task_id"]

            if task_id:
                # Async processing - poll for results
                print(f"Task submitted: {task_id}, polling for results (every {POLL_INTERVAL}s, max {MAX_RETRIES} attempts)...")

                task_data = self._poll_task_status(task_id)

                if task_data:
                    # Try different response formats
                    # Format 1: data[0] contains url or b64_json
                    if task_data.get("data") and isinstance(task_data["data"], list) and len(task_data["data"]) > 0:
                        image_data = task_data["data"][0]
                        if isinstance(image_data, dict) and ("url" in image_data or "b64_json" in image_data):
                            return self.save_image(image_data, output_path)

                    # Format 2: result.images[0].url[0] (Apimart format)
                    result = task_data.get("result", {})
                    images = result.get("images", [])
                    if images and len(images) > 0:
                        first_image = images[0]
                        urls = first_image.get("url", [])
                        if urls and len(urls) > 0:
                            return self.save_image({"url": urls[0]}, output_path)

                    print("Error: Task completed but no image data found")
                    print(f"Task data: {task_data}")
                    return False
                else:
                    print("Error: Task polling returned no data")
                    return False

            elif data.get("data") and isinstance(data["data"], list) and len(data["data"]) > 0:
                # Check if this is actually image data (sync processing)
                first_item = data["data"][0]
                if isinstance(first_item, dict) and ("url" in first_item or "b64_json" in first_item):
                    # Sync processing - save immediately
                    return self.save_image(first_item, output_path)
                else:
                    print("Error: No task_id or valid image data in response")
                    print(f"Response: {data}")
                    return False
            else:
                print("Error: No task_id or image data in response")
                print(f"Response: {data}")
                return False

        except httpx.HTTPStatusError as e:
            print(f"HTTP error: {e.response.status_code} - {e}")
            return False
        except Exception as e:
            print(f"Error generating image: {e}")
            return False


def main():
    # Load .env file
    ensure_env_loaded()
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=True)

    import argparse
    parser = argparse.ArgumentParser(description="Generate diagrams using Apimart API")
    parser.add_argument("--text", "-t", required=True, help="Text description for the diagram")
    parser.add_argument("--output", "-o", default="output.png", help="Output file path")
    parser.add_argument("--model", help="Model name (overrides .env)")
    parser.add_argument("--size", default="1:1", help="Image size ratio (e.g., 1:1, 16:9)")
    parser.add_argument("--resolution", help="Image resolution (e.g., 1K, 2K, 4K) for supported models")
    parser.add_argument("--image-urls", nargs="+", help="Reference image URLs")
    args = parser.parse_args()

    generator = ApimartImageGenerator(
        api_key=os.getenv("APIMART_API_KEY") or os.getenv("API_KEY"),
        model=args.model or os.getenv("APIMART_MODEL_NAME"),
        api_base=os.getenv("APIMART_API_BASE")
    )

    success = generator.generate_image(
        args.text,
        args.output,
        size=args.size,
        resolution=args.resolution,
        image_urls=args.image_urls
    )

    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
