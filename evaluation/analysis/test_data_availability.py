#!/usr/bin/env python3
"""
Test Data Availability Checker

Check which data items from the input JSON have corresponding generated images.
"""

import json
import argparse
from pathlib import Path
from typing import List, Tuple


def check_data_availability(
    input_json: str,
    diagram_dir: str
) -> Tuple[List[dict], List[dict]]:
    """
    Check which data items have available images.

    Returns:
        Tuple of (available_items, missing_items)
    """
    with open(input_json) as f:
        data = json.load(f)

    diagram_path = Path(diagram_dir)
    available = []
    missing = []

    for item in data:
        data_id = item['id']
        found_path = None

        # Check multiple possible locations
        locations = [
            diagram_path / data_id / "rendered_diagram.png",
            diagram_path / data_id / "4_render",
            diagram_path / f"{data_id}.png",
        ]

        for loc in locations:
            if loc.exists():
                if loc.is_dir():
                    # Check for PNG files in directory
                    pngs = list(loc.glob("*.png"))
                    if pngs:
                        found_path = str(pngs[0])
                        break
                else:
                    found_path = str(loc)
                    break

        if found_path:
            item_copy = item.copy()
            item_copy['found_image_path'] = found_path
            available.append(item_copy)
        else:
            missing.append(item)

    return available, missing


def main():
    parser = argparse.ArgumentParser(
        description="Check data availability for evaluation"
    )
    parser.add_argument(
        "--input-json",
        default="../dataset/test/data.json",
        help="Input JSON file"
    )
    parser.add_argument(
        "--diagram-dir",
        default="../examples",
        help="Base directory for generated images"
    )

    args = parser.parse_args()

    print("=" * 80)
    print("DATA AVAILABILITY CHECK")
    print("=" * 80)
    print(f"\nInput JSON: {args.input_json}")
    print(f"Diagram directory: {args.diagram_dir}")

    available, missing = check_data_availability(args.input_json, args.diagram_dir)

    print(f"\n{'=' * 80}")
    print(f"RESULTS")
    print(f"{'=' * 80}")
    print(f"Total data items: {len(available) + len(missing)}")
    print(f"✓ Available: {len(available)}")
    print(f"✗ Missing: {len(missing)}")

    if available:
        print(f"\n{'=' * 80}")
        print(f"AVAILABLE DATA (ready for evaluation)")
        print(f"{'=' * 80}")
        for item in available:
            print(f"  ✓ {item['id']}")
            print(f"    Image: {item['found_image_path']}")
            print(f"    Type: {item['diagram_type']}")

    if missing:
        print(f"\n{'=' * 80}")
        print(f"MISSING DATA (no images found)")
        print(f"{'=' * 80}")
        if len(missing) <= 10:
            for item in missing:
                print(f"  ✗ {item['id']} ({item['diagram_type']})")
        else:
            for item in missing[:5]:
                print(f"  ✗ {item['id']} ({item['diagram_type']})")
            print(f"  ... and {len(missing) - 5} more")

    print(f"\n{'=' * 80}")
    print(f"NEXT STEPS")
    print(f"{'=' * 80}")

    if len(available) > 0:
        print(f"\n✓ You can evaluate {len(available)} data items:")
        print(f"\npython3 -m evaluation.run_evaluation \\")
        print(f"    --input-json {args.input_json} \\")
        print(f"    --method evodiagram \\")
        print(f"    --exp-id <experiment_id>")

        if len(available) <= 10:
            print(f"\nOr evaluate specific IDs:")
            for item in available[:3]:
                print(f"python3 -m evaluation.run_evaluation --input-json {args.input_json} --method evodiagram --exp-id <experiment_id> --data-id {item['id']}")

    if len(missing) > 0:
        print(f"\n✗ {len(missing)} data items need images generated first.")
        print(f"   Run your diagram generation pipeline to create images for these IDs.")

    print()


if __name__ == "__main__":
    main()
