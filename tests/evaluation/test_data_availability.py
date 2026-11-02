import json
from pathlib import Path

import pytest

from evaluation.analysis.test_data_availability import check_data_availability


@pytest.mark.parametrize(
    "relative_path",
    [
        "sample/rendered_diagram.png",
        "sample/render.png",
        "sample/image.png",
        "sample/4_render/preview.png",
        "sample.png",
    ],
)
def test_available_image_layouts(tmp_path, relative_path):
    dataset = tmp_path / "data.json"
    dataset.write_text(json.dumps([{"id": "sample"}, {"id": "missing"}]))
    image = tmp_path / relative_path
    image.parent.mkdir(parents=True, exist_ok=True)
    image.touch()

    available, missing = check_data_availability(str(dataset), str(tmp_path))

    assert available == [{"id": "sample", "found_image_path": str(image)}]
    assert missing == [{"id": "missing"}]


def test_baseline_prefers_render_then_image_then_flat(tmp_path):
    dataset = tmp_path / "data.json"
    dataset.write_text('[{"id": "sample"}]')
    sample = tmp_path / "sample"
    sample.mkdir()
    render = sample / "render.png"
    fallback = sample / "image.png"
    for path in (render, fallback, tmp_path / "sample.png"):
        path.touch()

    available, _ = check_data_availability(str(dataset), str(tmp_path))
    assert Path(available[0]["found_image_path"]) == render

    render.unlink()
    render.mkdir()
    available, _ = check_data_availability(str(dataset), str(tmp_path))
    assert Path(available[0]["found_image_path"]) == fallback


def test_non_image_layouts_stay_missing(tmp_path):
    dataset = tmp_path / "data.json"
    dataset.write_text('[{"id": "file"}, {"id": "directory"}]')
    (tmp_path / "file").mkdir()
    (tmp_path / "file" / "4_render").touch()
    (tmp_path / "directory" / "4_render" / "preview.png").mkdir(parents=True)

    available, missing = check_data_availability(str(dataset), str(tmp_path))

    assert available == []
    assert missing == [{"id": "file"}, {"id": "directory"}]
