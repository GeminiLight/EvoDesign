#!/usr/bin/env python3
"""Remove comparison folders that only contain origin.png."""

from __future__ import annotations

import argparse
from pathlib import Path


def is_origin_only(folder: Path) -> bool:
    if not folder.is_dir():
        return False
    files = [p for p in folder.iterdir() if p.is_file()]
    return len(files) == 1 and files[0].name == "origin.png"


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]

    parser = argparse.ArgumentParser(description="Remove comparison folders that only contain origin.png")
    parser.add_argument("--output-dir", type=Path, default=repo_root / "experiments/comparison")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    output_dir = args.output_dir
    if not output_dir.exists():
        return

    for item in output_dir.iterdir():
        if is_origin_only(item):
            if args.dry_run:
                continue
            for file in item.iterdir():
                file.unlink()
            item.rmdir()


if __name__ == "__main__":
    main()
