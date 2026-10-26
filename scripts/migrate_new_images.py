#!/usr/bin/env python3
"""Copy migrated training images into ``dataset/images/diagrams`` safely."""

from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import dataclass
from pathlib import Path


DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SIDECAR = Path("temp/migration/new_ids.json")


@dataclass(frozen=True)
class ImageMigrationResult:
    requested: int
    copied: int
    missing: list[str]
    existing: list[str]
    target_dir: Path
    dry_run: bool


def _resolve_repo_path(repo_root: Path, path: Path) -> Path:
    return path if path.is_absolute() else repo_root / path


def _load_ids(path: Path) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Expected a JSON array of IDs in {path}")
    return [str(item) for item in payload]


def copy_images(
    *,
    repo_root: Path = DEFAULT_REPO_ROOT,
    id_list_json: Path = DEFAULT_SIDECAR,
    new_pack_images: Path,
    target_dir: Path | None = None,
    dry_run: bool = False,
    overwrite: bool = False,
    allow_missing: bool = False,
) -> ImageMigrationResult:
    repo_root = repo_root.resolve()
    id_list_json = _resolve_repo_path(repo_root, id_list_json)
    target_dir = target_dir or repo_root / "dataset" / "images" / "diagrams"
    target_dir = _resolve_repo_path(repo_root, target_dir)
    new_pack_images = new_pack_images.expanduser().resolve()

    new_ids = _load_ids(id_list_json)
    missing: list[str] = []
    existing: list[str] = []
    copy_pairs: list[tuple[Path, Path]] = []

    for image_id in new_ids:
        src = new_pack_images / f"{image_id}.jpg"
        dst = target_dir / f"{image_id}.jpg"
        if not src.exists():
            missing.append(image_id)
            continue
        if dst.exists() and not overwrite:
            existing.append(image_id)
            continue
        copy_pairs.append((src, dst))

    if missing and not allow_missing:
        raise FileNotFoundError(
            "Missing source images: " + ", ".join(missing[:20])
            + (" ..." if len(missing) > 20 else "")
        )
    if existing:
        raise FileExistsError(
            "Target images already exist; pass --overwrite to replace them: "
            + ", ".join(existing[:20])
            + (" ..." if len(existing) > 20 else "")
        )

    copied = 0
    if not dry_run:
        for src, dst in copy_pairs:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copied += 1
    else:
        copied = len(copy_pairs)

    return ImageMigrationResult(
        requested=len(new_ids),
        copied=copied,
        missing=missing,
        existing=existing,
        target_dir=target_dir,
        dry_run=dry_run,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=DEFAULT_REPO_ROOT)
    parser.add_argument("--id-list-json", type=Path, default=DEFAULT_SIDECAR)
    parser.add_argument("--new-pack-images", type=Path, required=True)
    parser.add_argument("--target-dir", type=Path, default=None)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--allow-missing",
        action="store_true",
        help="Return success even when some listed source images are absent.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.write and args.dry_run:
        raise SystemExit("--write and --dry-run are mutually exclusive")
    result = copy_images(
        repo_root=args.repo_root,
        id_list_json=args.id_list_json,
        new_pack_images=args.new_pack_images,
        target_dir=args.target_dir,
        dry_run=args.dry_run or not args.write,
        overwrite=args.overwrite,
        allow_missing=args.allow_missing,
    )

    print(f"[INFO] Requested: {result.requested}")
    print(f"[INFO] Copied:    {result.copied}")
    print(f"[INFO] Missing:   {len(result.missing)}")
    print(f"[INFO] Target:    {result.target_dir}")
    if result.dry_run:
        print("[DRY-RUN] No files were copied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
