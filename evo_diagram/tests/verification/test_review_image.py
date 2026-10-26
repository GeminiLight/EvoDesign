import base64
from io import BytesIO

import pytest
from PIL import Image

from evo_diagram.utils.io_utils import image_to_data_url
from evo_diagram.agentic_system.verification_stage.critic.critic_agent import review_image_edge_limit


def test_review_downsamples_only_payload_and_preserves_original(tmp_path):
    path = tmp_path / "export.png"
    Image.new("RGB", (6400, 840), "white").save(path)
    original = path.read_bytes()
    data = image_to_data_url(str(path), max_edge=3072).split(",", 1)[1]
    with Image.open(BytesIO(base64.b64decode(data))) as image:
        assert image.size == (3072, 403)
    assert path.read_bytes() == original
    assert base64.b64decode(image_to_data_url(str(path)).split(",", 1)[1]) == original


def test_small_images_are_not_upscaled(tmp_path):
    path = tmp_path / "small.png"
    Image.new("RGBA", (100, 50)).save(path)
    assert image_to_data_url(str(path), max_edge=3072) == image_to_data_url(str(path))
    with pytest.raises(ValueError):
        image_to_data_url(str(path), max_edge=0)


@pytest.mark.parametrize("font_size, expected", [(32, 3072), (8, 6400), (None, None)])
def test_dense_diagram_keeps_readable_labels(tmp_path, font_size, expected):
    path = tmp_path / "large.png"
    Image.new("RGB", (6400, 1600)).save(path)
    manifest = {"elements": [{"type": "text", "text": "Small label", "fontSize": font_size,
                              "x": 0, "y": 0, "width": 3200, "height": 800}]}
    assert review_image_edge_limit(str(path), manifest) == expected
