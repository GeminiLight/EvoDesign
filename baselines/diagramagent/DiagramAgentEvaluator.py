# evaluator_adapter.py
import argparse
import json
import os
import shutil
import sys
from typing import Any, Dict, List, Optional

from PIL import Image

_DIAG_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
from evo_diagram.core.experiment import get_experiment_id, get_baseline_output_dir

class DiagramAgentEvaluator:
    def __init__(self, use_gpt4o: bool = True, output_dir: Optional[str] = None):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        from baselines.diagramagent.DiagramAgent import DiagramAgent

        self.agent = DiagramAgent(use_gpt4o=use_gpt4o)
        self.output_dir = output_dir or os.path.join(base_dir, "results", "dataset_test")
        os.makedirs(self.output_dir, exist_ok=True)

    def evaluate_on_canvasbench(self, canvasbench_data: list) -> dict:
        """
        canvasbench_data: list of {"query": str, "content": str, "image": str, "type": str}
        返回与 EvoDiagram 相同的 9 维评估指标
        """
        results = []

        for idx, item in enumerate(canvasbench_data):
            print(f"Processing {idx+1}/{len(canvasbench_data)}: {item['type']}")

            # 根据任务类型选择 pipeline
            if item.get("task") == "coding":
                result = self.agent.code_from_image(item["image"], item["type"])
            elif item.get("task") == "editing":
                # 需要先有原始代码
                original = self.agent.generate(item["content"])
                result = self.agent.edit(original["code"], item["query"])
            else:  # generation
                result = self.agent.generate(
                    _compose_generation_input(item.get("query", ""), item.get("content", ""))
                )

            # 保存输出
            if result["success"] and result.get("image_path"):
                output_path = os.path.join(self.output_dir, f"{idx}_{item['type']}.png")
                Image.open(result["image_path"]).save(output_path)
                results.append({
                    "index": idx,
                    "success": True,
                    "output_image": output_path,
                    "code": result["code"]
                })
            else:
                results.append({
                    "index": idx,
                    "success": False,
                    "errors": result.get("errors", [])
                })

        return results


def _compose_generation_input(query: str, content: str) -> str:
    """Feed the model both the intent and the source text.

    ``query or content`` short-circuited on the query, and every dataset item
    has a non-empty query, so the source content never reached the model while
    the judge still scored content fidelity against it. Other baselines
    (baselines/scisketch/src/custom_main.py, evo_diagram/agentic_system/main.py)
    consume both fields.
    """
    q = (query or "").strip()
    c = (content or "").strip()
    if q and c:
        return f"Intent: {q}\n\nSource content:\n{c}"
    return q or c


def _atomic_write_json(path: str, obj: Any) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _safe_sample_id(sample_id: str) -> str:
    s = (sample_id or "").strip()
    if not s:
        return "sample"
    s = s.replace(os.sep, "_")
    s = s.replace("/", "_")
    return s


def _resolve_reference_image(project_root: str, dataset_path: str, item: Dict[str, Any], data_id: str) -> str:
    ref_candidate = os.path.join(project_root, "dataset", "images", "diagrams", f"{data_id}.jpg")
    if os.path.exists(ref_candidate):
        return ref_candidate

    hint = item.get("image_url") or item.get("image") or ""
    if isinstance(hint, str) and hint.strip():
        hint_path = hint.strip()
        if os.path.isabs(hint_path) and os.path.exists(hint_path):
            return hint_path
        base = os.path.dirname(os.path.abspath(dataset_path))
        rel = os.path.normpath(os.path.join(base, hint_path))
        if os.path.exists(rel):
            return rel
    return ""


def _write_eval_artifacts(
    eval_output_root: str,
    baseline_type: str,
    model_name: str,
    data_id: str,
    query: str,
    content: str,
    generated_png_path: str,
    reference_image_path: str,
    code_path: str,
) -> None:
    out_dir = get_baseline_output_dir(baseline_type, model_name, get_experiment_id())
    os.makedirs(out_dir, exist_ok=True)
    sample_dir = os.path.join(out_dir, data_id)
    os.makedirs(sample_dir, exist_ok=True)

    out_png = os.path.join(sample_dir, "render.png")
    # The runner passes the same directory this function resolves to, so source
    # and destination can be the identical file; shutil.copy2 raises
    # SameFileError there and (uncaught) aborts the whole `set -e` sweep.
    if os.path.exists(generated_png_path) and not (
        os.path.exists(out_png) and os.path.samefile(generated_png_path, out_png)
    ):
        shutil.copy2(generated_png_path, out_png)

    ref_dst = os.path.join(sample_dir, "reference.jpg")
    if reference_image_path and os.path.exists(reference_image_path):
        shutil.copy2(reference_image_path, ref_dst)

    text_path = os.path.join(sample_dir, "input.json")
    _atomic_write_json(text_path, {"id": data_id, "query": query, "content": content})

    mapping_path = os.path.join(out_dir, "mapping.json")
    mapping: Any = []
    if os.path.exists(mapping_path):
        try:
            with open(mapping_path, "r", encoding="utf-8") as f:
                mapping = json.load(f)
        except Exception:
            mapping = []
    if not isinstance(mapping, list):
        mapping = []
    mapping = [m for m in mapping if not (isinstance(m, dict) and m.get("id") == data_id)]
    mapping.append(
        {
            "id": data_id,
            "query": query,
            "content_path": text_path,
            "reference_image_path": ref_dst if os.path.exists(ref_dst) else (reference_image_path or ""),
            "generated_image_path": out_png,
            "code_path": code_path,
        }
    )
    _atomic_write_json(mapping_path, mapping)


def process_dataset(
    dataset_path: str,
    output_dir: Optional[str] = None,
    start: int = 0,
    end: Optional[int] = None,
    task: str = "generation",
    use_gpt4o: bool = False,
    write_eval_artifacts: bool = False,
    eval_baseline_type: str = "diagramagent",
    eval_model_name: str = "",
) -> List[Dict[str, Any]]:
    if not os.path.exists(dataset_path):
        raise FileNotFoundError(dataset_path)

    evaluator = DiagramAgentEvaluator(use_gpt4o=use_gpt4o, output_dir=output_dir)
    baseline_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.abspath(os.path.join(baseline_dir, "../.."))
    model_name = (eval_model_name or os.getenv("ELYSIVER_MODEL") or os.getenv("OPENAI_MODEL") or "unknown_model").strip()
    with open(dataset_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("dataset_json_must_be_list")

    end_idx = len(data) if end is None else min(len(data), max(start, end))
    start_idx = max(0, min(start, len(data)))
    sliced = data[start_idx:end_idx]

    try:
        from tqdm import tqdm

        it = tqdm(sliced)
    except Exception:
        it = sliced

    results: List[Dict[str, Any]] = []
    for i, item in enumerate(it, start=start_idx):
        if not isinstance(item, dict):
            continue

        item_id = _safe_sample_id(item.get("id", f"sample_{i}"))
        diagram_type = item.get("diagram_type") or item.get("type") or ""
        query = item.get("query") or item.get("query_v1") or ""
        content = item.get("content") or ""
        image_url = item.get("image_url") or item.get("image") or ""

        if task == "coding":
            if not isinstance(image_url, str) or not image_url:
                results.append({"id": item_id, "success": False, "error": "missing_image_url"})
                continue
            result = evaluator.agent.code_from_image(image_url, diagram_type or "flowchart")
        elif task == "editing":
            original = evaluator.agent.generate(content or query)
            original_code = original.get("code") if isinstance(original, dict) else None
            if not isinstance(original_code, str) or not original_code.strip():
                results.append({"id": item_id, "success": False, "error": "missing_original_code"})
                continue
            result = evaluator.agent.edit(original_code, query or content)
        else:
            result = evaluator.agent.generate(_compose_generation_input(query, content))

        rec: Dict[str, Any] = {"id": item_id, "diagram_type": diagram_type, "success": bool(result.get("success"))}
        sample_dir = os.path.join(evaluator.output_dir, item_id)
        os.makedirs(sample_dir, exist_ok=True)
        if result.get("success"):
            code = result.get("code")
            code_path = ""
            if isinstance(code, str) and code.strip():
                code_path = os.path.join(sample_dir, "code.txt")
                with open(code_path, "w", encoding="utf-8") as f:
                    f.write(code)
                rec["code_path"] = code_path

            image_path = result.get("image_path")
            if isinstance(image_path, str) and os.path.exists(image_path):
                out_img = os.path.join(sample_dir, "render.png")
                try:
                    Image.open(image_path).save(out_img)
                    rec["output_image"] = out_img
                except Exception as e:
                    rec["image_error"] = str(e)
                if write_eval_artifacts and os.path.exists(out_img):
                    ref_img = _resolve_reference_image(repo_root, dataset_path, item, item_id)
                    _write_eval_artifacts(
                        eval_output_root=repo_root,
                        baseline_type=eval_baseline_type,
                        model_name=model_name,
                        data_id=item_id,
                        query=query,
                        content=content,
                        generated_png_path=out_img,
                        reference_image_path=ref_img,
                        code_path=code_path,
                    )
        else:
            rec["errors"] = result.get("errors", [])
        results.append(rec)

    out_path = os.path.join(evaluator.output_dir, "results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="DiagramAgent dataset test runner")
    parser.add_argument("--dataset", "-d", type=str, required=True, help="Dataset JSON path")
    parser.add_argument("--output", "-o", type=str, default=None, help="Output directory")
    parser.add_argument("--start", "-s", type=int, default=0, help="Start index (inclusive)")
    parser.add_argument("--end", "-e", type=int, default=None, help="End index (exclusive)")
    parser.add_argument(
        "--task",
        "-t",
        type=str,
        default="generation",
        choices=["generation", "editing", "coding"],
        help="Task type",
    )
    parser.add_argument("--use-gpt4o", action="store_true", help="Enable GPT-4o in CheckAgent")
    parser.add_argument("--write-eval-artifacts", action="store_true", help="Write outputs in evaluation-compatible format")
    parser.add_argument("--eval-baseline-type", type=str, default="diagramagent", help="Baseline type under results/baselines/")
    parser.add_argument("--eval-model-name", type=str, default="", help="Model name under results/baselines/<type>/")
    args = parser.parse_args()

    process_dataset(
        dataset_path=args.dataset,
        output_dir=args.output,
        start=args.start,
        end=args.end,
        task=args.task,
        use_gpt4o=args.use_gpt4o,
        write_eval_artifacts=args.write_eval_artifacts,
        eval_baseline_type=args.eval_baseline_type,
        eval_model_name=args.eval_model_name,
    )


if __name__ == "__main__":
    main()
