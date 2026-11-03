#!/usr/bin/env python3
import argparse
import io
import json
import os
import sys
import tarfile
import urllib.request
from typing import Optional

NPM_REGISTRY_URL = "https://registry.npmjs.org/@material-design-icons/svg"

# Determine project root relative to this script
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUTPUT_DIR = os.path.join(PROJECT_ROOT, "resources", "icons", "material-design-icons", "filled")


def _fetch_json(url: str) -> dict:
    with urllib.request.urlopen(url) as resp:
        if resp.status != 200:
            raise RuntimeError(f"HTTP {resp.status} for {url}")
        return json.loads(resp.read().decode("utf-8"))


def _download(url: str) -> bytes:
    with urllib.request.urlopen(url) as resp:
        if resp.status != 200:
            raise RuntimeError(f"HTTP {resp.status} for {url}")
        return resp.read()


def _get_tarball_url(version: Optional[str]) -> str:
    if version:
        meta = _fetch_json(NPM_REGISTRY_URL)
        ver_info = meta.get("versions", {}).get(version)
        if not ver_info:
            raise ValueError(f"Version {version} not found in npm registry")
        return ver_info["dist"]["tarball"]
    latest = _fetch_json(f"{NPM_REGISTRY_URL}/latest")
    return latest["dist"]["tarball"]


def _extract_filled_icons(tarball_bytes: bytes, output_dir: str) -> int:
    os.makedirs(output_dir, exist_ok=True)
    count = 0
    with tarfile.open(fileobj=io.BytesIO(tarball_bytes), mode="r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            # npm package content is under "package/"
            name = member.name
            if not name.startswith("package/filled/"):
                continue
            if not name.endswith(".svg"):
                continue
            filename = os.path.basename(name)
            target_path = os.path.join(output_dir, filename)
            extracted = tar.extractfile(member)
            if extracted is None:
                continue
            with open(target_path, "wb") as f:
                f.write(extracted.read())
            count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download Google Material Icons (filled) from npm and save locally.")
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--version",
        default=None,
        help="Optional npm version, e.g. 1.2.1 (default: latest)",
    )

    args = parser.parse_args()

    tarball_url = _get_tarball_url(args.version)
    data = _download(tarball_url)
    count = _extract_filled_icons(data, args.output_dir)

    print(f"✓ Downloaded {count} icons to {args.output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
