#!/usr/bin/env python3
"""
One-step icon setup script for EvoDiagram.
Downloads Material Icons from npm and generates colored variants automatically.
"""
import argparse
import io
import json
import os
import re
import sys
import tarfile
import urllib.request
import xml.etree.ElementTree as ET
from typing import Dict, Iterable, Optional, Tuple


class IconConfig:
    """Configuration constants for icon setup."""

    def __init__(self, project_root: str):
        self.project_root = project_root
        self.icons_base_dir = os.path.join(project_root, "resources", "icons", "material-design-icons")
        self.filled_dir = os.path.join(self.icons_base_dir, "filled")
        self.npm_registry_url = "https://registry.npmjs.org/@material-design-icons/svg"

        # Tool services public directory for localhost access
        self.tool_services_dir = os.path.join(project_root, "agentic_system", "tool_services")
        self.tool_services_public_dir = os.path.join(self.tool_services_dir, "public")
        self.tool_services_icons_dir = os.path.join(self.tool_services_public_dir, "icons", "material-design-icons")
        self.manifest_file = os.path.join(self.tool_services_icons_dir, "manifest.json")

    @property
    def color_map(self) -> Tuple[Tuple[str, str], ...]:
        """Return color mapping for icon variants."""
        return (
            ("black", "#1d1d1d"),
            ("grey", "#737373"),
            ("light_violet", "#9e86c8"),
            ("violet", "#5b2245"),
            ("blue", "#2f80ed"),
            ("light_blue", "#56ccf2"),
            ("yellow", "#ffc114"),
            ("orange", "#f2994a"),
            ("green", "#27ae60"),
            ("light_green", "#6fcf97"),
            ("light_red", "#ff8f8f"),
            ("red", "#eb5757"),
        )


class HTTPClient:
    """HTTP client for fetching data from URLs."""

    @staticmethod
    def fetch_json(url: str) -> dict:
        """Fetch JSON data from URL."""
        with urllib.request.urlopen(url) as resp:
            if resp.status != 200:
                raise RuntimeError(f"HTTP {resp.status} for {url}")
            return json.loads(resp.read().decode("utf-8"))

    @staticmethod
    def download(url: str) -> bytes:
        """Download binary data from URL."""
        with urllib.request.urlopen(url) as resp:
            if resp.status != 200:
                raise RuntimeError(f"HTTP {resp.status} for {url}")
            return resp.read()


class NPMDownloader:
    """Handles downloading Material Icons from npm registry."""

    def __init__(self, config: IconConfig):
        self.config = config

    def get_tarball_url(self, version: Optional[str] = None) -> str:
        """Get npm tarball URL for specific version or latest."""
        if version:
            meta = HTTPClient.fetch_json(self.config.npm_registry_url)
            ver_info = meta.get("versions", {}).get(version)
            if not ver_info:
                raise ValueError(f"Version {version} not found in npm registry")
            return ver_info["dist"]["tarball"]
        latest = HTTPClient.fetch_json(f"{self.config.npm_registry_url}/latest")
        return latest["dist"]["tarball"]

    def download_and_extract(self, version: Optional[str] = None) -> int:
        """Download tarball and extract filled icons."""
        tarball_url = self.get_tarball_url(version)
        data = HTTPClient.download(tarball_url)
        return self._extract_filled_icons(data)

    def _extract_filled_icons(self, tarball_bytes: bytes) -> int:
        """Extract filled icons from npm tarball."""
        os.makedirs(self.config.filled_dir, exist_ok=True)
        count = 0

        with tarfile.open(fileobj=io.BytesIO(tarball_bytes), mode="r:gz") as tar:
            for member in tar.getmembers():
                if not self._is_valid_icon_member(member):
                    continue

                filename = os.path.basename(member.name)
                target_path = os.path.join(self.config.filled_dir, filename)
                extracted = tar.extractfile(member)
                if extracted is None:
                    continue

                with open(target_path, "wb") as f:
                    f.write(extracted.read())
                count += 1

        return count

    @staticmethod
    def _is_valid_icon_member(member) -> bool:
        """Check if tarball member is a valid filled icon file."""
        if not member.isfile():
            return False
        if not member.name.startswith("package/filled/"):
            return False
        if not member.name.endswith(".svg"):
            return False
        return True


class SVGColorizer:
    """Handles colorization of SVG files."""

    FILL_TAGS = {"path", "rect", "circle", "ellipse", "polygon"}
    STROKE_TAGS = {"line", "polyline"}
    EXCLUDED_COLORS = {"none", "transparent"}

    def __init__(self, config: IconConfig):
        self.config = config

    def generate_colored_variants(self) -> Dict[str, int]:
        """Generate all colored variants of icons."""
        results: Dict[str, int] = {}
        svg_files = list(self._iter_svg_files(self.config.filled_dir))

        for color_key, hex_color in self.config.color_map:
            count = self._colorize_batch(svg_files, color_key, hex_color)
            results[color_key] = count

        return results

    def copy_to_tool_services(self) -> int:
        """Copy all icons to tool_services public directory for localhost access."""
        print("📂 Copying icons to tool_services public directory...")

        if not os.path.exists(self.config.icons_base_dir):
            print(f"⚠ Source icons directory not found: {self.config.icons_base_dir}")
            return 0

        # Create target directory structure
        os.makedirs(self.config.tool_services_icons_dir, exist_ok=True)

        total_count = 0
        for item in os.listdir(self.config.icons_base_dir):
            src_item = os.path.join(self.config.icons_base_dir, item)
            dst_item = os.path.join(self.config.tool_services_icons_dir, item)

            if os.path.isdir(src_item):
                # Copy entire color directory
                if os.path.exists(dst_item):
                    # Skip if already exists to save time
                    continue
                self._copy_tree(src_item, dst_item)
                count = len(list(self._iter_svg_files(dst_item)))
                total_count += count
                print(f"  ✓ Copied {count} icons from {item}/")

        print(f"✓ Total icons copied to tool_services: {total_count}")
        return total_count

    def generate_manifest(self) -> None:
        """Generate a manifest file listing all available icons for easy HTTP access."""
        print("📋 Generating icon manifest...")

        manifest = {
            "version": "1.0",
            "colors": {},
            "total_icons": 0
        }

        total_count = 0
        for color_key, hex_color in self.config.color_map:
            color_dir = os.path.join(self.config.tool_services_icons_dir, color_key)
            if not os.path.exists(color_dir):
                continue

            icons = []
            for svg_file in self._iter_svg_files(color_dir):
                icon_name = os.path.basename(svg_file)
                # Get relative path for HTTP access
                http_path = f"/icons/material-design-icons/{color_key}/{icon_name}"
                icons.append({
                    "name": icon_name.replace(".svg", ""),
                    "file": icon_name,
                    "url": http_path
                })

            if icons:
                manifest["colors"][color_key] = {
                    "hex": hex_color,
                    "count": len(icons),
                    "icons": icons
                }
                total_count += len(icons)

        manifest["total_icons"] = total_count

        # Write manifest file
        os.makedirs(os.path.dirname(self.config.manifest_file), exist_ok=True)
        with open(self.config.manifest_file, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)

        print(f"✓ Generated manifest with {total_count} icons")
        print(f"📍 Manifest location: {self.config.manifest_file}")

    @staticmethod
    def _copy_tree(src: str, dst: str) -> None:
        """Recursively copy directory tree."""
        os.makedirs(dst, exist_ok=True)
        for item in os.listdir(src):
            src_item = os.path.join(src, item)
            dst_item = os.path.join(dst, item)
            if os.path.isdir(src_item):
                SVGColorizer._copy_tree(src_item, dst_item)
            else:
                import shutil
                shutil.copy2(src_item, dst_item)

    def _colorize_batch(self, svg_files: Iterable[str], color_key: str, hex_color: str) -> int:
        """Colorize a batch of SVG files with a specific color."""
        out_dir = os.path.join(self.config.icons_base_dir, color_key)
        os.makedirs(out_dir, exist_ok=True)
        count = 0

        for svg_file in svg_files:
            rel_path = os.path.relpath(svg_file, self.config.filled_dir)
            out_path = os.path.join(out_dir, rel_path)
            self._apply_color(svg_file, out_path, hex_color)
            count += 1

        return count

    def _apply_color(self, svg_path: str, out_path: str, color: str) -> None:
        """Apply color to a single SVG file."""
        try:
            tree = ET.parse(svg_path)
        except ET.ParseError:
            self._copy_fallback(svg_path, out_path)
            return

        self._process_svg_tree(tree, color)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        tree.write(out_path, encoding="utf-8", xml_declaration=False)

    def _process_svg_tree(self, tree: ET.ElementTree, color: str) -> None:
        """Process all elements in SVG tree and apply color."""
        root = tree.getroot()
        for elem in root.iter():
            self._colorize_element(elem, color)

    def _colorize_element(self, elem: ET.Element, color: str) -> None:
        """Apply color to a single SVG element."""
        tag = elem.tag.split("}")[-1]

        self._apply_fill_color(elem, tag, color)
        self._apply_stroke_color(elem, tag, color)
        self._apply_style_color(elem, color)

    def _apply_fill_color(self, elem: ET.Element, tag: str, color: str) -> None:
        """Apply fill color to element."""
        fill = elem.get("fill")
        if fill is not None:
            if self._should_replace(fill):
                elem.set("fill", color)
        elif tag in self.FILL_TAGS:
            elem.set("fill", color)

    def _apply_stroke_color(self, elem: ET.Element, tag: str, color: str) -> None:
        """Apply stroke color to element."""
        stroke = elem.get("stroke")
        if stroke is not None:
            if self._should_replace(stroke):
                elem.set("stroke", color)
        elif tag in self.STROKE_TAGS:
            elem.set("stroke", color)

    def _apply_style_color(self, elem: ET.Element, color: str) -> None:
        """Apply color via style attribute."""
        style = elem.get("style")
        if style:
            elem.set("style", self._replace_style_colors(style, color))

    @staticmethod
    def _replace_style_colors(style: str, color: str) -> str:
        """Replace fill/stroke colors in CSS style string."""
        fill_re = re.compile(r"(^|;)\s*fill\s*:\s*([^;]+)", re.IGNORECASE)
        stroke_re = re.compile(r"(^|;)\s*stroke\s*:\s*([^;]+)", re.IGNORECASE)

        def replace_fill(match: re.Match) -> str:
            prefix, val = match.group(1), match.group(2)
            return f"{prefix}fill:{color}" if SVGColorizer._should_replace(val) else match.group(0)

        def replace_stroke(match: re.Match) -> str:
            prefix, val = match.group(1), match.group(2)
            return f"{prefix}stroke:{color}" if SVGColorizer._should_replace(val) else match.group(0)

        style = fill_re.sub(replace_fill, style)
        style = stroke_re.sub(replace_stroke, style)
        return style

    @staticmethod
    def _should_replace(value: str) -> bool:
        """Check if color value should be replaced."""
        return value.strip().lower() not in SVGColorizer.EXCLUDED_COLORS

    @staticmethod
    def _copy_fallback(src_path: str, dst_path: str) -> None:
        """Copy file as fallback if SVG parsing fails."""
        with open(src_path, "rb") as f_in, open(dst_path, "wb") as f_out:
            f_out.write(f_in.read())

    @staticmethod
    def _iter_svg_files(src_dir: str) -> Iterable[str]:
        """Iterate over all SVG files in directory."""
        for root, _, files in os.walk(src_dir):
            for name in files:
                if name.lower().endswith(".svg"):
                    yield os.path.join(root, name)


class IconSetup:
    """Main orchestrator for icon setup process."""

    def __init__(self, project_root: str):
        self.config = IconConfig(project_root)
        self.downloader = NPMDownloader(self.config)
        self.colorizer = SVGColorizer(self.config)

    def run(self, skip_download: bool = False, skip_colorize: bool = False,
            skip_tool_services: bool = False, version: Optional[str] = None) -> None:
        """Execute the icon setup process."""
        icon_count = self._download_or_skip(skip_download, version)
        self._colorize_or_skip(skip_colorize, icon_count)

        # Copy to tool_services for localhost access
        if not skip_tool_services:
            self._setup_tool_services_icons()

        self._print_summary()

    def _download_or_skip(self, skip_download: bool, version: Optional[str]) -> int:
        """Download icons or skip if requested."""
        if not skip_download:
            print("📦 Downloading Material Icons from npm...")
            count = self.downloader.download_and_extract(version)
            print(f"✓ Downloaded {count} icons to {self.config.filled_dir}")
            return count
        else:
            print("⏭ Skipping download")
            count = len(list(SVGColorizer._iter_svg_files(self.config.filled_dir)))
            if os.path.exists(self.config.filled_dir):
                print(f"✓ Using existing {count} icons from {self.config.filled_dir}")
            return count

    def _colorize_or_skip(self, skip_colorize: bool, icon_count: int) -> None:
        """Colorize icons or skip if requested."""
        if not skip_colorize and icon_count > 0:
            print("\n🎨 Generating colored variants...")
            results = self.colorizer.generate_colored_variants()
            total_colored = sum(results.values())
            print(f"✓ Generated {total_colored} colored icons")
            for key, num in results.items():
                print(f"  - {key}: {num} icons")
        else:
            if skip_colorize:
                print("\n⏭ Skipping colorization")
            elif icon_count == 0:
                print("\n⚠ No icons to colorize")

    def _setup_tool_services_icons(self) -> None:
        """Setup icons in tool_services for localhost access."""
        print("\n🌐 Setting up icons for localhost access...")
        self.colorizer.copy_to_tool_services()
        self.colorizer.generate_manifest()

    def _print_summary(self) -> None:
        """Print completion summary."""
        print(f"\n✅ Icon setup complete!")
        print(f"📁 Icons directory: {self.config.icons_base_dir}")
        print(f"🌐 Tool Services icons: {self.config.tool_services_icons_dir}")
        print(f"📋 Manifest file: {self.config.manifest_file}")
        print(f"\n📖 Access icons via HTTP at: http://localhost:3000/icons/material-design-icons/<color>/<icon>.svg")
        print(f"📖 Or view manifest at: http://localhost:3000/icons/material-design-icons/manifest.json")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="One-step setup: Download and colorize Material Icons for EvoDiagram"
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Skip download, only colorize existing icons"
    )
    parser.add_argument(
        "--skip-colorize",
        action="store_true",
        help="Skip colorization, only download icons"
    )
    parser.add_argument(
        "--skip-tool-services",
        action="store_true",
        help="Skip copying icons to tool_services for localhost access"
    )
    parser.add_argument(
        "--version",
        default=None,
        help="Optional npm version, e.g. 1.2.1 (default: latest)"
    )

    args = parser.parse_args()

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    setup = IconSetup(project_root)
    setup.run(
        skip_download=args.skip_download,
        skip_colorize=args.skip_colorize,
        skip_tool_services=args.skip_tool_services,
        version=args.version
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
