#!/usr/bin/env python
import os
import sys
import json
import logging
import argparse
from typing import Optional

from dotenv import load_dotenv
from evo_diagram.utils.env_loader import ensure_env_loaded

from baselines.pixel.prompts import IMAGE_GENERATOR_PROMPT

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class GeminiImageGenerator:
    """
    Class to handle text-to-image diagram generation using the Google GenAI SDK.
    """

    def __init__(self, env_path: Optional[str] = None):
        """
        Initialize the generator. Loads environment variables and sets up the GenAI client.
        """
        # Load environment variables
        if env_path is None:
            env_path = os.path.join(os.path.dirname(__file__), ".env")

        ensure_env_loaded()
        load_dotenv(env_path, override=True)

        # Prefer specific Gemini keys, fallback to generic or Google key
        self.api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        # Default model from user requirement, or environment variable
        self.model_name = os.getenv("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")

        if not self.api_key:
            logger.warning("GEMINI_API_KEY or GOOGLE_API_KEY not found in environment variables.")

        try:
            from google import genai

            # Initialize the client as per user provided example
            self.client = genai.Client(api_key=self.api_key)
            logger.info(f"Initialized Google GenAI Client with model: {self.model_name}")
        except ImportError:
            logger.error(
                "google-genai is required for Gemini image generation. "
                "Install the baseline extras with `pip install 'evo-diagram[baselines]'`."
            )
            raise
        except Exception as e:
            logger.error(f"Failed to initialize GenAI Client: {e}")
            raise

    def generate_image(
        self,
        content: str,
        query: Optional[str] = None,
        output_path: str = None
    ) -> bool:
        """
        Generates an image from text content.

        Args:
            content: The text description or prompt for the image.
            query: The user intent/query for the diagram. If not provided, generates from content.
            output_path: The path where the generated image should be saved.

        Returns:
            bool: True if image generation and saving was successful, False otherwise.
        """
        # Use IMAGE_GENERATOR_PROMPT from prompts module
        if query is None:
            query = f"Generate a diagram for: {content}"

        prompt_text = IMAGE_GENERATOR_PROMPT.format(content=content, query=query)

        logger.info(f"Generating image for content length: {len(prompt_text)}")

        try:
            # Call the API
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=[prompt_text],
            )

            image_saved = False

            # Check response parts
            if hasattr(response, 'parts'):
                for part in response.parts:
                    if part.text is not None and not part.inline_data:
                        logger.info(f"Received text response part: {part.text[:50]}...")

                    if part.inline_data is not None:
                        try:
                            # Use method from user example
                            image = part.as_image()

                            # Ensure directory exists
                            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

                            image.save(output_path)
                            logger.info(f"Saved generated image to {output_path}")
                            image_saved = True
                            # If we only want one image, we can break here
                            break
                        except Exception as e:
                            logger.error(f"Failed to save image from part: {e}")

            if not image_saved:
                logger.warning("No image data found in response parts.")

            return image_saved

        except Exception as e:
            logger.error(f"Generation failed: {e}")
            return False

    def process_file(self, input_path: str, output_path: str = None):
        """Process a single text file or JSON file."""
        if not os.path.exists(input_path):
            logger.error(f"Input file not found: {input_path}")
            return

        with open(input_path, "r", encoding="utf-8") as f:
            file_content = f.read()

        # Try to parse as JSON
        content = None
        query = None
        requirements = None

        try:
            import json
            data = json.loads(file_content)
            if isinstance(data, dict):
                content = data.get("content") or data.get("text")
                query = data.get("query")
                requirements = data.get("requirements")
            else:
                # If it's a list or other JSON structure, treat as text
                content = file_content
        except json.JSONDecodeError:
            # Not JSON, treat as plain text
            content = file_content

        if not content:
            logger.error(f"No content found in file: {input_path}")
            return

        if output_path is None:
            # Generate output path from input filename
            base_name = os.path.splitext(os.path.basename(input_path))[0]
            output_dir = os.path.join(os.path.dirname(__file__), "experiments", "gemini")
            output_path = os.path.join(output_dir, f"{base_name}.png")

        self.generate_image(content, query=query, output_path=output_path)

def process_dataset(
    dataset_path: str,
    output_dir: str = None,
    env_path: Optional[str] = None,
    model: Optional[str] = None
):
    """
    Process a dataset JSON file using GeminiImageGenerator.

    Args:
        dataset_path: Path to the dataset JSON file.
        output_dir: Directory to save generated images. If None, derived from model name.
        env_path: Path to .env file for configuration.
        model: Model name override. Without it every run falls back to
            GEMINI_IMAGE_MODEL, so a per-model output directory would still be
            filled by one and the same underlying model.
    """
    import json
    from tqdm import tqdm

    if not os.path.exists(dataset_path):
        logger.error(f"Dataset not found: {dataset_path}")
        return

    try:
        generator = GeminiImageGenerator(env_path=env_path)
    except Exception as e:
        logger.error(f"Failed to initialize generator: {e}")
        return
    if model:
        generator.model_name = model
    logger.info(f"Using model: {generator.model_name}")

    with open(dataset_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if output_dir is None:
        # Replicate the logic to determine default output dir based on model name
        safe_model = generator.model_name.replace("/", "_").replace(":", "_")
        base_dir = os.path.dirname(os.path.abspath(__file__))
        output_dir = os.path.join(base_dir, "experiments", safe_model)

    logger.info(f"Processing {len(data)} items from dataset...")
    logger.info(f"Output directory: {output_dir}")

    for i, item in enumerate(tqdm(data)):
        content = item.get("content") or item.get("text")
        if not content:
            continue

        item_id = item.get("id", f"sample_{i}")
        query = item.get("query")

        # diagram_type could be added to query
        if item.get("diagram_type"):
            diagram_type = item.get("diagram_type")
            query = f"{query}. Type: {diagram_type}" if query else f"Generate a {diagram_type} diagram"

        safe_item_id = str(item_id).replace(os.sep, "_").replace("/", "_")
        sample_dir = os.path.join(output_dir, safe_item_id)
        out_path = os.path.join(sample_dir, "image.png")

        # Skip if exists? (Optional feature, currently commented out)
        # if os.path.exists(out_path): continue

        generator.generate_image(content, query=query, output_path=out_path)


def main():
    parser = argparse.ArgumentParser(description="Gemini Image Generator")
    parser.add_argument("--input", "-i", type=str, help="Input text file path")
    parser.add_argument("--dataset", "-d", type=str, help="Input dataset JSON path")
    parser.add_argument("--text", "-t", type=str, help="Direct text input")
    parser.add_argument("--output", "-o", type=str, help="Output path (file or dir)")
    parser.add_argument("--model", "-m", type=str, help="Override model name")

    args = parser.parse_args()

    try:
        generator = GeminiImageGenerator()
        if args.model:
            generator.model_name = args.model
    except Exception:
        sys.exit(1)

    if args.dataset:
        process_dataset(args.dataset, args.output, model=args.model)
        return

    if args.text:
        out_path = args.output if args.output else "output.png"
        generator.generate_image(args.text, output_path=out_path)

    elif args.input:
        generator.process_file(args.input, args.output)

    else:
        parser.print_help()

if __name__ == "__main__":
    main()
