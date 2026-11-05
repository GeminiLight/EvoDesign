"""Render Python and TS final manifests with the ONE Python renderer, then pixel-diff.

Driven by tools/render.ts (npm run render). Usage:
    PYTHONPATH=<repo> EXCALIDRAW_RENDER_URL=http://127.0.0.1:3001/renderers/excalidraw \
        .venv/bin/python packages/render-engine/tools/render_visual.py <reports/visual> [case ...]

For every <case> dir containing python.json and ts.json it writes python.png,
ts.png, diff.png and appends a record to <reports/visual>/results.json.
Rendering is sequential (one request at a time).
"""
from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

from PIL import Image, ImageChops

from evodesign.agentic_system.render_engine.canvas_render import render_canvas


def render(manifest_path: Path, png_path: Path) -> str | None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    try:
        render_canvas(data=manifest, output_path=str(png_path), canvas_library="excalidraw", capture_output=True)
    except Exception as exc:  # report, keep going
        return f"{type(exc).__name__}: {str(exc)[:300]}"
    return None if png_path.exists() else "renderer produced no file"


def pixel_diff(a_path: Path, b_path: Path, diff_path: Path) -> dict:
    a = Image.open(a_path).convert("RGBA")
    b = Image.open(b_path).convert("RGBA")
    width, height = max(a.width, b.width), max(a.height, b.height)
    canvas_a = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    canvas_b = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    canvas_a.paste(a, (0, 0))
    canvas_b.paste(b, (0, 0))
    delta = ImageChops.difference(canvas_a, canvas_b)
    # A pixel differs when any channel differs; bands are max-combined.
    bands = delta.split()
    any_band = bands[0]
    for band in bands[1:]:
        any_band = ImageChops.lighter(any_band, band)
    mask = any_band.point(lambda v: 255 if v else 0)
    changed = mask.width * mask.height - mask.histogram()[0]
    total = width * height
    overlay = Image.new("RGBA", (width, height), (255, 255, 255, 255))
    overlay.paste(canvas_a.convert("L").point(lambda v: 200 + v // 5).convert("RGBA"), (0, 0))
    overlay.paste(Image.new("RGBA", (width, height), (230, 30, 30, 255)), (0, 0), mask)
    overlay.convert("RGB").save(diff_path)
    return {
        "python_size": [a.width, a.height],
        "ts_size": [b.width, b.height],
        "changed_pixels": changed,
        "total_pixels": total,
        "diff_percent": (100.0 * changed / total) if total else 0.0,
        "identical": changed == 0 and a.size == b.size,
    }


def main() -> None:
    root = Path(sys.argv[1])
    wanted = set(sys.argv[2:])
    results = []
    cases = sorted(p for p in root.iterdir() if p.is_dir() and (p / "ts.json").exists())
    for index, case_dir in enumerate(cases, 1):
        if wanted and case_dir.name not in wanted:
            continue
        record = {"case": case_dir.name}
        try:
            err_py = render(case_dir / "python.json", case_dir / "python.png")
            err_ts = render(case_dir / "ts.json", case_dir / "ts.png")
            record["python_error"], record["ts_error"] = err_py, err_ts
            if not err_py and not err_ts:
                record.update(pixel_diff(case_dir / "python.png", case_dir / "ts.png", case_dir / "diff.png"))
        except Exception:
            record["error"] = traceback.format_exc()[-600:]
        results.append(record)
        print(f"[{index}/{len(cases)}] {case_dir.name}: "
              f"{record.get('diff_percent', 'n/a')} {record.get('python_error') or record.get('ts_error') or record.get('error') or ''}",
              flush=True)
    out = root / "results.json"
    if wanted and out.exists():  # partial run: merge into the previous results
        previous = {r["case"]: r for r in json.loads(out.read_text(encoding="utf-8"))}
        previous.update({r["case"]: r for r in results})
        results = [previous[k] for k in sorted(previous)]
    out.write_text(json.dumps(results, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
