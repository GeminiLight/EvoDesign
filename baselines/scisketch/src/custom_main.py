import argparse  # type: ignore
import base64
import json
import logging
import os
import shutil
import subprocess
import sys
from typing import Any, Dict, List, Optional
import zlib

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.abspath(os.path.join(_BASE_DIR, ".."))
# Repository root, used for the dataset/ reference-image fallback. This is the
# variable _write_eval_artifacts already referenced but nobody defined, which
# made every artifact write raise NameError inside a bare `except: pass`.
_PROJECT_ROOT = os.path.abspath(os.path.join(_BASE_DIR, "..", "..", ".."))

logger = logging.getLogger(__name__)

from evo_diagram.core.experiment import get_experiment_id, get_baseline_output_dir

from .utils import concatenate_paper_text, encode_image, get_image_dimensions
from .file_util import write_object_to_file, write_string_to_file
from .configs import DIAGRAM_CONFIGS


def get_parsed_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--save_directory", type=str, default=os.path.join(_ROOT_DIR, "generated_diagram"))
    parser.add_argument("--dataset", type=str, default=None, help="Dataset JSON file path (list of items)")
    parser.add_argument("--start", type=int, default=0, help="Start index (inclusive) when using --dataset")
    parser.add_argument("--end", type=int, default=None, help="End index (exclusive) when using --dataset")
    parser.add_argument("--regeneration", action="store_true", help="Re-generate even if output exists")
    parser.add_argument("--export_png", action="store_true", help="Export drawio output to PNG via docker")
    parser.add_argument(
        "--export_docker_image",
        type=str,
        default="b1f6c1c4/draw.io-export:latest",
        help="Docker image used for export",
    )
    parser.add_argument("--keep_export_xml", action="store_true", help="Keep intermediate wrapped xml file")
    parser.add_argument("--write_eval_artifacts", action="store_true", help="Write outputs in evaluation-compatible format")
    parser.add_argument("--eval_baseline_type", type=str, default="scisketch", help="Baseline type under results/baselines/")
    parser.add_argument("--eval_model_name", type=str, default="", help="Model name under results/baselines/<type>/")
    parser.add_argument(
        "--parsed_paper_directory",
        type=str,
        default=os.path.join(_ROOT_DIR, "samples", "parsed_papers"),
        help="Directory of parsed paper json files (SciSketch original input)",
    )
    parser.add_argument("--sample_id", type=str, help="ID of the sample to process")
    parser.add_argument(
        "--language",
        type=str,
        default="drawio",
        help="code language for generated diagram",
    )
    return parser.parse_args()

def pre_process(args):
    """
    preprocess the args to make sure it is valid and ready for the next stage
    """
    assert args.language in DIAGRAM_CONFIGS, "Language not supported"
    if args.dataset:
        assert os.path.exists(args.dataset), "Dataset file does not exist"
    else:
        assert os.path.exists(args.parsed_paper_directory), "Parsed paper directory does not exist"
    os.makedirs(args.save_directory, exist_ok=True)

def get_test_data(args):
    """
    get test data
    """
    test_data = []
    for file in os.listdir(args.parsed_paper_directory):
        if file.endswith(".json"):
            with open(f"{args.parsed_paper_directory}/{file}", "r") as f:
                data = json.load(f)
            if file.split(".")[0] == "final":
                continue
            assert data.get("caption", ""), "Caption not found in parsed paper file"
            paper_plain_text = concatenate_paper_text(data)
            test_data.append(
                {
                    "paper": paper_plain_text,
                    "caption": data["caption"],
                    "file": file.split(".")[0],
                }
            )

    if args.sample_id:
        test_data = [sample for sample in test_data if sample["file"] == args.sample_id]
    return test_data

def _safe_sample_id(sample_id: str) -> str:
    s = (sample_id or "").strip()
    if not s:
        return "sample"
    s = s.replace(os.sep, "_")
    s = s.replace("/", "_")
    return s

def get_dataset_data(dataset_path: str, start: int = 0, end: Optional[int] = None) -> List[Dict[str, str]]:
    with open(dataset_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("dataset_json_must_be_list")

    start_idx = max(0, min(int(start), len(data)))
    end_idx = len(data) if end is None else max(start_idx, min(int(end), len(data)))
    sliced = data[start_idx:end_idx]

    test_data: List[Dict[str, str]] = []
    for i, item in enumerate(sliced, start=start_idx):
        if not isinstance(item, dict):
            continue
        item_id = _safe_sample_id(item.get("id") or f"sample_{i}")
        paper_plain_text = (item.get("content") or item.get("text") or "").strip()
        caption = (item.get("query") or item.get("query_v1") or "").strip()
        if not paper_plain_text:
            paper_plain_text = caption
        ref_img = item.get("image_url") or item.get("image") or ""
        test_data.append({"paper": paper_plain_text, "caption": caption, "file": item_id, "ref_image": ref_img})
    return test_data

def get_candidate_image_list(file_name: str) -> list[dict]:
    """
    get candidate image list based on the file name
    Args:
        file_name (str): file name
    Returns:
        list[dict]: candidate image list with the following keys:
            name (str): name of the image
            mime_type (str): mime type of the image
            base64 (str): base64 encoded image
            width (float): width of the image
            height (float): height of the image
    """
    candidate_list = []
    candidate_dir = os.path.join(_ROOT_DIR, "input_images", file_name)
    if os.path.exists(candidate_dir):
        for image in os.listdir(candidate_dir):
            if image.endswith(".png") or image.endswith(".jpg"):
                width, height = get_image_dimensions(os.path.join(candidate_dir, image))
                candidate_list.append(
                    {
                        "name": image.split(".")[0],
                        "mime_type": f"image/{image.split('.')[-1]}",
                        "base64": encode_image(os.path.join(candidate_dir, image)),
                        "width": width,
                        "height": height,
                    }
                )

    return candidate_list

def _wrap_mxgraphmodel_to_mxfile(mxgraphmodel_xml: str) -> str:
    s = (mxgraphmodel_xml or "").strip()
    if not s:
        return ""
    if s.startswith("<mxfile"):
        return s
    if not s.startswith("<mxGraphModel"):
        return s
    co = zlib.compressobj(level=9, wbits=-15)
    enc = base64.b64encode(co.compress(s.encode("utf-8")) + co.flush()).decode("ascii")
    return f'<mxfile host="app.diagrams.net" version="24.7.0"><diagram id="page1" name="Page-1">{enc}</diagram></mxfile>'


def _export_drawio_to_png(
    final_diagram_path: str,
    export_docker_image: str,
    keep_export_xml: bool,
    regeneration: bool,
) -> Optional[str]:
    if not shutil.which("docker"):
        raise RuntimeError("docker_not_found")

    if not os.path.exists(final_diagram_path):
        raise FileNotFoundError(final_diagram_path)

    out_dir = os.path.dirname(os.path.abspath(final_diagram_path))
    stem, _ = os.path.splitext(os.path.basename(final_diagram_path))
    out_png = os.path.join(out_dir, f"{stem}.png")
    if (not regeneration) and os.path.exists(out_png):
        return out_png

    raw = open(final_diagram_path, "r", encoding="utf-8").read()
    wrapped = _wrap_mxgraphmodel_to_mxfile(raw)
    if not wrapped:
        raise RuntimeError("empty_drawio_xml")

    export_xml = os.path.join(out_dir, f"{stem}_export.xml")
    with open(export_xml, "w", encoding="utf-8") as f:
        f.write(wrapped)

    subprocess.run(
        ["docker", "run", "--rm", "-v", f"{out_dir}:/files", export_docker_image, "png"],
        check=True,
    )

    generated = export_xml + ".png"
    if not os.path.exists(generated):
        generated = export_xml + ".xml.png"
    if not os.path.exists(generated):
        raise RuntimeError("export_png_not_found")

    os.replace(generated, out_png)
    if not keep_export_xml:
        try:
            os.remove(export_xml)
        except Exception:
            pass
    return out_png


def _atomic_write_json(path: str, obj: Any) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _infer_eval_model_name(arg_value: str) -> str:
    v = (arg_value or "").strip()
    if v:
        return v
    for k in ("ELYSIVER_MODEL", "OPENAI_MODEL"):
        vv = (os.getenv(k) or "").strip()
        if vv:
            return vv
    return "unknown_model"


def _write_eval_artifacts(
    data_id: str,
    query: str,
    content: str,
    generated_png_path: str,
    final_diagram_path: str,
    baseline_type: str,
    model_name: str,
    dataset_ref_image_hint: str,
) -> None:
    out_dir = get_baseline_output_dir(baseline_type, model_name, get_experiment_id())
    os.makedirs(out_dir, exist_ok=True)
    sample_dir = os.path.join(out_dir, data_id)
    os.makedirs(sample_dir, exist_ok=True)

    out_png = os.path.join(sample_dir, "render.png")
    if os.path.exists(generated_png_path):
        shutil.copy2(generated_png_path, out_png)

    ref_src = ""
    if isinstance(dataset_ref_image_hint, str) and dataset_ref_image_hint.strip() and os.path.exists(dataset_ref_image_hint.strip()):
        ref_src = dataset_ref_image_hint.strip()
    else:
        candidate = os.path.join(_PROJECT_ROOT, "dataset", "images", "diagrams", f"{data_id}.jpg")
        if os.path.exists(candidate):
            ref_src = candidate

    ref_dst = os.path.join(sample_dir, "reference.jpg")
    if ref_src:
        shutil.copy2(ref_src, ref_dst)

    text_path = os.path.join(sample_dir, "input.json")
    _atomic_write_json(
        text_path,
        {
            "id": data_id,
            "query": query,
            "content": content,
        },
    )

    map_path = os.path.join(out_dir, "mapping.json")
    mapping = []
    if os.path.exists(map_path):
        try:
            with open(map_path, "r", encoding="utf-8") as f:
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
            "reference_image_path": ref_dst if os.path.exists(ref_dst) else (ref_src or ""),
            "generated_image_path": out_png,
            "final_diagram_path": final_diagram_path,
        }
    )
    _atomic_write_json(map_path, mapping)


def process_test_data(
    test_data: list[dict],
    configs: dict,
    save_directory: str,
    regeneration: bool = False,
    export_png: bool = False,
    export_docker_image: str = "b1f6c1c4/draw.io-export:latest",
    keep_export_xml: bool = False,
    write_eval_artifacts: bool = False,
    eval_baseline_type: str = "scisketch",
    eval_model_name: str = "",
):
    """
    the main function for processing the test data to generate diagrams
    """
    from tqdm import tqdm
    from .diagram_handler import (
        generate_based_on_description,
        replace_components_with_images,
    )

    eval_artifact_failures: List[str] = []

    for sample in tqdm(test_data, desc="Generating Diagram Plans"):
        sample_key = _safe_sample_id(sample.get("file") or "")
        candidate_list = get_candidate_image_list(sample["file"])
        output_file = f"{save_directory}/{sample_key}/{sample_key}.json"
        final_diagram_file = f"{save_directory}/{sample_key}/{sample_key}_final{configs['file_extension']}"
        out_png_path = os.path.splitext(final_diagram_file)[0] + ".png"
        if (not regeneration) and os.path.exists(final_diagram_file) and os.path.exists(output_file):
            if export_png and (not os.path.exists(out_png_path)) and configs.get("file_extension") == ".drawio":
                try:
                    _export_drawio_to_png(
                        final_diagram_path=final_diagram_file,
                        export_docker_image=export_docker_image,
                        keep_export_xml=keep_export_xml,
                        regeneration=regeneration,
                    )
                except Exception:
                    logger.warning("drawio PNG export failed for sample %s", sample_key, exc_info=True)
            if write_eval_artifacts:
                if not os.path.exists(out_png_path) and os.path.exists(final_diagram_file) and configs.get("file_extension") == ".drawio":
                    try:
                        _export_drawio_to_png(
                            final_diagram_path=final_diagram_file,
                            export_docker_image=export_docker_image,
                            keep_export_xml=keep_export_xml,
                            regeneration=regeneration,
                        )
                    except Exception:
                        logger.warning("drawio PNG export failed for sample %s", sample_key, exc_info=True)
                try:
                    _write_eval_artifacts(
                        data_id=sample_key,
                        query=(sample.get("caption") or ""),
                        content=(sample.get("paper") or ""),
                        generated_png_path=out_png_path,
                        final_diagram_path=final_diagram_file,
                        baseline_type=(eval_baseline_type or "scisketch"),
                        model_name=_infer_eval_model_name(eval_model_name),
                        dataset_ref_image_hint=(sample.get("ref_image") or ""),
                    )
                except Exception:
                    eval_artifact_failures.append(sample_key)
                    logger.exception("eval artifact write failed for sample %s", sample_key)
            continue

        initial_layout, final_layout, description, refinements, verifications = (
            generate_based_on_description(
                sample["paper"],
                sample["caption"],
                language=configs["language"],
                format=configs["parse_format"],
                candidate_list=candidate_list
            )
        )
        out = {}
        out[sample_key] = {
            "caption": sample["caption"],
            "description": description,
            "initial_layout": initial_layout,
            "final_layout": final_layout,
            "refinements": refinements,
            "verifications": verifications,
        }
        final_diagram, replacement_plan, images = replace_components_with_images(
            description, final_layout, candidate_list
        )
        out[sample_key]["replacement_plan"] = replacement_plan
        out[sample_key]["final_diagram"] = final_diagram

        os.makedirs(f"{save_directory}/{sample_key}", exist_ok=True)
        write_object_to_file(out, output_file)
        write_string_to_file(final_diagram, final_diagram_file)
        if export_png and configs.get("file_extension") == ".drawio":
            try:
                _export_drawio_to_png(
                    final_diagram_path=final_diagram_file,
                    export_docker_image=export_docker_image,
                    keep_export_xml=keep_export_xml,
                    regeneration=True,
                )
            except Exception:
                logger.warning("drawio PNG export failed for sample %s", sample_key, exc_info=True)
        if write_eval_artifacts:
            if not os.path.exists(out_png_path) and os.path.exists(final_diagram_file) and configs.get("file_extension") == ".drawio":
                try:
                    _export_drawio_to_png(
                        final_diagram_path=final_diagram_file,
                        export_docker_image=export_docker_image,
                        keep_export_xml=keep_export_xml,
                        regeneration=True,
                    )
                except Exception:
                    logger.warning("drawio PNG export failed for sample %s", sample_key, exc_info=True)
            try:
                _write_eval_artifacts(
                    data_id=sample_key,
                    query=(sample.get("caption") or ""),
                    content=(sample.get("paper") or ""),
                    generated_png_path=out_png_path,
                    final_diagram_path=final_diagram_file,
                    baseline_type=(eval_baseline_type or "scisketch"),
                    model_name=_infer_eval_model_name(eval_model_name),
                    dataset_ref_image_hint=(sample.get("ref_image") or ""),
                )
            except Exception:
                eval_artifact_failures.append(sample_key)
                logger.exception("eval artifact write failed for sample %s", sample_key)

    if eval_artifact_failures:
        logger.error(
            "eval artifact write failed for %d/%d samples: %s",
            len(eval_artifact_failures),
            len(test_data),
            ", ".join(eval_artifact_failures),
        )
    return {
        "total": len(test_data),
        "eval_artifact_failures": list(eval_artifact_failures),
    }


def main():
    """
    main function
    """
    args = get_parsed_args()
    pre_process(args)
    configs = DIAGRAM_CONFIGS.get(args.language, {})
    save_directory = args.save_directory
    if args.dataset:
        test_data = get_dataset_data(args.dataset, start=args.start, end=args.end)
        process_test_data(
            test_data,
            configs,
            save_directory,
            regeneration=args.regeneration,
            export_png=args.export_png,
            export_docker_image=args.export_docker_image,
            keep_export_xml=args.keep_export_xml,
            write_eval_artifacts=args.write_eval_artifacts,
            eval_baseline_type=args.eval_baseline_type,
            eval_model_name=args.eval_model_name,
        )
        return

    test_data = get_test_data(args)
    process_test_data(
        test_data,
        configs,
        save_directory,
        regeneration=args.regeneration,
        export_png=args.export_png,
        export_docker_image=args.export_docker_image,
        keep_export_xml=args.keep_export_xml,
        write_eval_artifacts=args.write_eval_artifacts,
        eval_baseline_type=args.eval_baseline_type,
        eval_model_name=args.eval_model_name,
    )

if __name__ == "__main__":
    main()
