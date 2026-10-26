#!/usr/bin/env python3
"""Migrate an external training-data pack into ``dataset/train/data.json``.

The external pack path is intentionally explicit. This script is often run on
local research machines, so it must not depend on a developer-specific
absolute checkout path or write into the dataset without a visible command-line
contract.
"""

from __future__ import annotations

import argparse
import copy
import json
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SIDECAR = Path("temp/migration/new_ids.json")


@dataclass(frozen=True)
class TrainingMigrationResult:
    old_train_size: int
    new_pack_size: int
    test_size: int
    removed_test_overlap: int
    merged_size: int
    new_records: list[dict[str, Any]]
    merged_records: list[dict[str, Any]]
    output_path: Path
    sidecar_path: Path
    dry_run: bool


def _resolve_repo_path(repo_root: Path, path: Path) -> Path:
    return path if path.is_absolute() else repo_root / path


def _load_json_list(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Expected a JSON array in {path}")
    if not all(isinstance(item, dict) for item in payload):
        raise ValueError(f"Expected every item in {path} to be a JSON object")
    return payload


def _normalize_id(raw_id: Any) -> str:
    value = str(raw_id)
    return value[:-4] if value.lower().endswith(".jpg") else value


def _normalize_new_record(record: dict[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(record)
    new_id = _normalize_id(normalized["id"])
    normalized["id"] = new_id
    normalized["image_url"] = f"./dataset/images/diagrams/{new_id}.jpg"
    return normalized


def _normalize_existing_train_record(record: dict[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(record)
    normalized.setdefault("vertical_domain", "general")
    expected_url = f"./dataset/images/diagrams/{normalized['id']}.jpg"
    image_url = str(normalized.get("image_url", ""))
    if image_url != expected_url and not image_url.endswith("react.png"):
        normalized["image_url"] = expected_url
    return normalized


def _write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
    ) as tmp:
        json.dump(payload, tmp, indent=4, ensure_ascii=False)
        tmp.write("\n")
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def run_migration(
    *,
    repo_root: Path = DEFAULT_REPO_ROOT,
    new_pack_json: Path,
    test_json: Path | None = None,
    old_train_json: Path | None = None,
    output_path: Path | None = None,
    sidecar_path: Path | None = None,
    dry_run: bool = False,
) -> TrainingMigrationResult:
    repo_root = repo_root.resolve()
    dataset_dir = repo_root / "dataset"
    test_json = test_json or dataset_dir / "test" / "data.json"
    old_train_json = old_train_json or dataset_dir / "dataset_with_other_queries.json"
    output_path = output_path or dataset_dir / "train" / "data.json"
    sidecar_path = sidecar_path or DEFAULT_SIDECAR

    test_json = _resolve_repo_path(repo_root, test_json)
    old_train_json = _resolve_repo_path(repo_root, old_train_json)
    output_path = _resolve_repo_path(repo_root, output_path)
    sidecar_path = _resolve_repo_path(repo_root, sidecar_path)
    new_pack_json = new_pack_json.expanduser().resolve()

    test_data = _load_json_list(test_json)
    old_train = _load_json_list(old_train_json)
    new_data = _load_json_list(new_pack_json)

    test_ids = {_normalize_id(record["id"]) for record in test_data}
    old_train_normalized = [
        _normalize_existing_train_record(record) for record in old_train
    ]
    old_train_ids = {_normalize_id(record["id"]) for record in old_train_normalized}

    new_records: list[dict[str, Any]] = []
    removed = 0
    for record in new_data:
        normalized = _normalize_new_record(record)
        if normalized["id"] in test_ids:
            removed += 1
            continue
        new_records.append(normalized)

    new_ids = {record["id"] for record in new_records}
    collision = old_train_ids & new_ids
    if collision:
        raise ValueError(f"ID collision with old train: {sorted(collision)}")

    merged = old_train_normalized + new_records
    merged_ids = [record["id"] for record in merged]
    if len(merged_ids) != len(set(merged_ids)):
        dupes = [item for item, count in Counter(merged_ids).items() if count > 1]
        raise ValueError(f"Duplicate IDs in merged dataset: {dupes}")

    if not dry_run:
        _write_json_atomic(output_path, merged)
        _write_json_atomic(sidecar_path, [record["id"] for record in new_records])

    return TrainingMigrationResult(
        old_train_size=len(old_train),
        new_pack_size=len(new_data),
        test_size=len(test_data),
        removed_test_overlap=removed,
        merged_size=len(merged),
        new_records=new_records,
        merged_records=merged,
        output_path=output_path,
        sidecar_path=sidecar_path,
        dry_run=dry_run,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=DEFAULT_REPO_ROOT)
    parser.add_argument("--new-pack-json", type=Path, required=True)
    parser.add_argument("--test-json", type=Path, default=None)
    parser.add_argument("--old-train-json", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--sidecar", type=Path, default=None)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.write and args.dry_run:
        raise SystemExit("--write and --dry-run are mutually exclusive")
    result = run_migration(
        repo_root=args.repo_root,
        new_pack_json=args.new_pack_json,
        test_json=args.test_json,
        old_train_json=args.old_train_json,
        output_path=args.output,
        sidecar_path=args.sidecar,
        dry_run=args.dry_run or not args.write,
    )

    print(f"[INFO] Old train size: {result.old_train_size}")
    print(f"[INFO] New pack size:  {result.new_pack_size}")
    print(f"[INFO] Test set size:  {result.test_size}")
    print(f"[INFO] Removed {result.removed_test_overlap} test-overlap items")
    print(f"[INFO] New items after dedup: {len(result.new_records)}")
    print(f"[INFO] Merged train size: {result.merged_size}")
    if result.dry_run:
        print(f"[DRY-RUN] Would write merged dataset to {result.output_path}")
        print(f"[DRY-RUN] Would write new ID sidecar to {result.sidecar_path}")
    else:
        print(f"[INFO] Written merged dataset to {result.output_path}")
        print(f"[INFO] Saved new ID list to {result.sidecar_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
