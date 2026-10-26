"""
Icon URL Adder Tool

Adds HTTP URLs to icon entries in styling JSON for rendering via tool_services.
"""

import argparse
import json
import logging
from copy import deepcopy
from typing import Any, Dict, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from evo_diagram.agentic_system.common.icon_assets import (
    format_icon_url,
    is_local_material_icon_url,
    require_icon_svg_path,
)
from evo_diagram.agentic_system.common.semantic_ids import ICON_SUFFIX
from evo_diagram.agentic_system.common.node_icons import bundled_icons
from evo_diagram.config.settings import AppSettings

logger = logging.getLogger(__name__)

# Icons are served from tool_services at: http://localhost:3000/icons/material-design-icons/
# Pattern: http://localhost:3000/icons/material-design-icons/{color}/{icon}.svg


def _is_icon_entry(key: str) -> bool:
    """Check if an entry is an icon entry."""
    if not isinstance(key, str):
        return False
    return key.endswith(ICON_SUFFIX)


def add_icon_urls(
    styling_json: Dict[str, Any],
    base_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Add bundled Material icon URLs to icon entries in styling JSON.

    Args:
        styling_json: The styling JSON dictionary with icon entries
        base_url: Optional Material icon route template (defaults to
            render.icon_base_url in settings.yaml)

    Returns:
        Updated styling JSON with URLs added to icon entries
    """
    if base_url is None:
        base_url = AppSettings.get_default().icon_base_url

    updated = deepcopy(styling_json)
    added_count = 0

    for key, value in updated.items():
        if not _is_icon_entry(key):
            continue

        if not isinstance(value, dict):
            continue

        props = value.get("props", {})
        if not isinstance(props, dict):
            continue

        # Get icon name and color
        icon_name = props.get("icon")
        icon_color = props.get("color", "black")

        if not icon_name:
            continue

        # Add or update URL
        url = format_icon_url(icon_name, icon_color, base_url)
        if not is_local_material_icon_url(url):
            raise ValueError(
                "Icon URL template must target the bundled Material icon route "
                f"({url!r}). Use a template containing "
                "'/icons/material-design-icons/{color}/{icon}.svg'."
            )
        if icon_name not in bundled_icons():
            require_icon_svg_path(
                str(icon_name), icon_color=str(icon_color), icon_url=url, element_id=key,
            )
        props["url"] = url
        added_count += 1

    logger.info("[IconUrlAdder] Added URLs to %d icon entries", added_count)
    return updated


class IconUrlAdderInput(BaseModel):
    styling_json: Dict[str, Any] = Field(..., description="Styling JSON with icon entries")
    base_url: Optional[str] = Field(None, description="Optional Material icon route template")


def _icon_url_adder_impl(
    styling_json: Dict[str, Any],
    base_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Add icon URLs to styling JSON entries."""
    return add_icon_urls(styling_json, base_url=base_url)


def make_icon_url_adder_tool() -> StructuredTool:
    """Create an instance of the icon URL adder tool."""
    return StructuredTool.from_function(
        func=_icon_url_adder_impl,
        name="icon_url_adder",
        description="Add HTTP URLs to icon entries in styling JSON for rendering via tool_services",
        args_schema=IconUrlAdderInput,
    )


# Export the tool instance for direct use
icon_url_adder = make_icon_url_adder_tool()


def main():
    """CLI entry point for testing the tool."""
    parser = argparse.ArgumentParser(
        description="Add icon URLs to styling JSON entries"
    )
    parser.add_argument(
        "--input",
        type=str,
        required=True,
        help="Path to styling JSON file",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="styling_with_urls.json",
        help="Output path for updated JSON",
    )
    parser.add_argument(
        "--base-url",
        type=str,
        default=None,
        help="Material icon route template (e.g., http://localhost:3000/icons/material-design-icons/{color}/{icon}.svg)",
    )

    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        styling_json = json.load(f)

    result = icon_url_adder.invoke(
        {
            "styling_json": styling_json,
            "base_url": args.base_url,
        }
    )

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"Updated styling JSON saved to: {args.output}")


if __name__ == "__main__":
    main()
