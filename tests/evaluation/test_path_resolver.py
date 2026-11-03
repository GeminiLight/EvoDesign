import pytest

from evaluation import path_resolver


def test_wo_refiner_legacy_fallback_uses_wo_refiner_variant(monkeypatch, tmp_path):
    monkeypatch.setattr(path_resolver, "PROJECT_ROOT", tmp_path)

    wo_refiner_image = (
        tmp_path
        / "results"
        / "evodesign_wo_refiner"
        / "sample_a"
        / "rendered_diagram.png"
    )
    wo_refiner_image.parent.mkdir(parents=True)
    wo_refiner_image.write_bytes(b"wo-refiner")

    wo_icon_image = (
        tmp_path
        / "results"
        / "evodesign_wo_icon"
        / "sample_a"
        / "rendered_diagram.png"
    )
    wo_icon_image.parent.mkdir(parents=True)
    wo_icon_image.write_bytes(b"wo-icon")

    resolved, score_dir, reference = path_resolver.parse_method_paths(
        "evodesign_wo_refiner",
        "sample_a",
        exp_id="exp1",
    )

    expected_score_dir = (
        tmp_path
        / "experiments"
        / "exp1"
        / "scores"
        / "evodesign"
        / "evodesign_wo_refiner"
        / "sample_a"
    )

    assert resolved == wo_refiner_image
    assert resolved != wo_icon_image
    assert score_dir == expected_score_dir
    assert reference == tmp_path / "dataset" / "images" / "diagrams" / "sample_a.jpg"


def test_wo_refiner_does_not_use_stale_generic_render_temp(monkeypatch, tmp_path):
    monkeypatch.setattr(path_resolver, "PROJECT_ROOT", tmp_path)

    stale_generic_image = (
        tmp_path
        / "results"
        / "evodesign"
        / "sample_a"
        / "4_render"
        / "diagram_manifest_temp.png"
    )
    stale_generic_image.parent.mkdir(parents=True)
    stale_generic_image.write_bytes(b"stale generic render")

    resolved, _, _ = path_resolver.parse_method_paths(
        "evodesign_wo_refiner/step-3.7-flash",
        "sample_a",
        exp_id="exp1",
    )

    assert resolved == (
        tmp_path
        / "experiments"
        / "exp1"
        / "outputs"
        / "evodesign"
        / "evodesign_wo_refiner"
        / "step-3.7-flash"
        / "sample_a"
        / "rendered_diagram.png"
    )
    assert resolved != stale_generic_image


@pytest.mark.parametrize(
    ("method", "expected_image_parts", "expected_score_parts"),
    [
        (
            "evodesign/model-x",
            ("experiments", "exp1", "outputs", "evodesign", "evodesign", "model-x", "sample_a", "rendered_diagram.png"),
            ("experiments", "exp1", "scores", "evodesign", "evodesign", "model-x", "sample_a"),
        ),
        (
            "evodesign_wo_icon/model-x",
            ("experiments", "exp1", "outputs", "evodesign", "evodesign_wo_icon", "model-x", "sample_a", "rendered_diagram.png"),
            ("experiments", "exp1", "scores", "evodesign", "evodesign_wo_icon", "model-x", "sample_a"),
        ),
        (
            "evodesign-local",
            ("experiments", "exp1", "outputs", "evodesign", "evodesign-local", "sample_a", "rendered_diagram.png"),
            ("experiments", "exp1", "scores", "evodesign", "evodesign-local", "sample_a"),
        ),
    ],
)
def test_parse_method_paths_preserves_evodesign_layouts(
    monkeypatch,
    tmp_path,
    method,
    expected_image_parts,
    expected_score_parts,
):
    monkeypatch.setattr(path_resolver, "PROJECT_ROOT", tmp_path)

    resolved, score_dir, reference = path_resolver.parse_method_paths(
        method,
        "sample_a",
        exp_id="exp1",
    )

    assert resolved == tmp_path.joinpath(*expected_image_parts)
    assert score_dir == tmp_path.joinpath(*expected_score_parts)
    assert reference == tmp_path / "dataset" / "images" / "diagrams" / "sample_a.jpg"


@pytest.mark.parametrize(
    ("method", "expected_image_parts", "expected_score_parts"),
    [
        (
            "baselines/mermaid/model-x",
            ("experiments", "exp1", "outputs", "baseline", "code_mermaid", "model-x", "sample_a", "render.png"),
            ("experiments", "exp1", "scores", "baseline", "code_mermaid", "model-x", "sample_a"),
        ),
        (
            "baselines_mermaid_model-x",
            ("experiments", "exp1", "outputs", "baseline", "code_mermaid", "model-x", "sample_a", "render.png"),
            ("experiments", "exp1", "scores", "baseline", "code_mermaid", "model-x", "sample_a"),
        ),
    ],
)
def test_parse_method_paths_preserves_baseline_layouts(
    monkeypatch,
    tmp_path,
    method,
    expected_image_parts,
    expected_score_parts,
):
    monkeypatch.setattr(path_resolver, "PROJECT_ROOT", tmp_path)

    resolved, score_dir, reference = path_resolver.parse_method_paths(
        method,
        "sample_a",
        exp_id="exp1",
    )

    assert resolved == tmp_path.joinpath(*expected_image_parts)
    assert score_dir == tmp_path.joinpath(*expected_score_parts)
    assert reference == tmp_path / "dataset" / "images" / "diagrams" / "sample_a.jpg"


@pytest.mark.parametrize(
    ("method", "data_id", "error_fragment"),
    [
        ("evodesign", "../sample_a", "data_id"),
        ("evodesign\\..\\model", "sample_a", "method"),
        ("evodesign/../model", "sample_a", "model segment"),
        ("evodesign_wo_icon/..", "sample_a", "model segment"),
        ("evodesign_bad name", "sample_a", "variant segment"),
        ("baselines/../model-x", "sample_a", "baseline segment"),
        ("baselines/code_mermaid/../model-x", "sample_a", "model segment"),
        ("baselines//model-x", "sample_a", "baseline segment"),
        ("baselines/code_mermaid/", "sample_a", "model segment"),
    ],
)
def test_parse_method_paths_rejects_unsafe_segments(
    monkeypatch,
    tmp_path,
    method,
    data_id,
    error_fragment,
):
    monkeypatch.setattr(path_resolver, "PROJECT_ROOT", tmp_path)

    with pytest.raises(ValueError, match=error_fragment):
        path_resolver.parse_method_paths(method, data_id, exp_id="exp1")


def test_parse_method_paths_rejects_unsafe_experiment_id(monkeypatch, tmp_path):
    monkeypatch.setattr(path_resolver, "PROJECT_ROOT", tmp_path)

    with pytest.raises(ValueError, match="experiment id"):
        path_resolver.parse_method_paths("evodesign", "sample_a", exp_id="../exp1")


def test_missing_submodel_raises_instead_of_picking_another_model(monkeypatch, tmp_path):
    """Auto-detection used to return the first sub-model directory containing the
    sample, so a run over several backbones silently mixed their outputs into one
    aggregated row."""
    monkeypatch.setattr(path_resolver, "PROJECT_ROOT", tmp_path)

    base = (
        tmp_path / "experiments" / "exp1" / "outputs" / "evodesign" / "evodesign"
    )
    for model in ("model-a", "model-b"):
        image = base / model / "sample_a" / "rendered_diagram.png"
        image.parent.mkdir(parents=True)
        image.write_bytes(model.encode())

    with pytest.raises(path_resolver.AmbiguousSubmodelError) as exc:
        path_resolver.parse_method_paths("evodesign", "sample_a", exp_id="exp1")

    message = str(exc.value)
    assert "model-a" in message and "model-b" in message
    assert "sub-model" in message


def test_single_submodel_directory_still_requires_an_explicit_model(monkeypatch, tmp_path):
    """One backbone today, two tomorrow: the same command must not change meaning."""
    monkeypatch.setattr(path_resolver, "PROJECT_ROOT", tmp_path)

    image = (
        tmp_path
        / "experiments"
        / "exp1"
        / "outputs"
        / "evodesign"
        / "evodesign"
        / "model-a"
        / "sample_a"
        / "rendered_diagram.png"
    )
    image.parent.mkdir(parents=True)
    image.write_bytes(b"png")

    with pytest.raises(path_resolver.AmbiguousSubmodelError):
        path_resolver.parse_method_paths("evodesign", "sample_a", exp_id="exp1")


def test_explicit_submodel_resolves_without_error(monkeypatch, tmp_path):
    monkeypatch.setattr(path_resolver, "PROJECT_ROOT", tmp_path)

    base = (
        tmp_path / "experiments" / "exp1" / "outputs" / "evodesign" / "evodesign"
    )
    for model in ("model-a", "model-b"):
        image = base / model / "sample_a" / "rendered_diagram.png"
        image.parent.mkdir(parents=True)
        image.write_bytes(model.encode())

    resolved, _, _ = path_resolver.parse_method_paths(
        "evodesign/model-b", "sample_a", exp_id="exp1"
    )

    assert resolved == base / "model-b" / "sample_a" / "rendered_diagram.png"


def test_missing_sample_is_still_a_plain_miss(monkeypatch, tmp_path):
    monkeypatch.setattr(path_resolver, "PROJECT_ROOT", tmp_path)

    base = (
        tmp_path / "experiments" / "exp1" / "outputs" / "evodesign" / "evodesign"
    )
    other = base / "model-a" / "other_sample" / "rendered_diagram.png"
    other.parent.mkdir(parents=True)
    other.write_bytes(b"png")

    resolved, _, _ = path_resolver.parse_method_paths(
        "evodesign", "sample_a", exp_id="exp1"
    )

    assert not resolved.exists()


def test_reference_lookup_does_not_depend_on_evodesign_outputs(monkeypatch, tmp_path):
    """Resolving a reference image while evaluating a baseline must not trip over
    evodesign sub-model ambiguity."""
    monkeypatch.setattr(path_resolver, "PROJECT_ROOT", tmp_path)

    image = (
        tmp_path
        / "experiments"
        / "exp1"
        / "outputs"
        / "evodesign"
        / "evodesign"
        / "model-a"
        / "sample_a"
        / "rendered_diagram.png"
    )
    image.parent.mkdir(parents=True)
    image.write_bytes(b"png")

    assert path_resolver.get_reference_image_path("sample_a") == (
        tmp_path / "dataset" / "images" / "diagrams" / "sample_a.jpg"
    )

    # Evaluating a baseline is unaffected by the evodesign layout.
    resolved, _, reference = path_resolver.parse_method_paths(
        "baselines/mermaid/model-x", "sample_a", exp_id="exp1"
    )
    assert reference == tmp_path / "dataset" / "images" / "diagrams" / "sample_a.jpg"
    assert "code_mermaid" in str(resolved)


@pytest.mark.parametrize('method', ['evodesign/model', 'evodiagram/model'])
def test_package_rename_reads_historical_experiments_without_moving_them(monkeypatch, tmp_path, method):
    monkeypatch.setattr(path_resolver, 'PROJECT_ROOT', tmp_path)
    old = tmp_path / 'experiments' / 'past' / 'outputs' / 'evodiagram' / 'evodiagram' / 'model' / 'sample' / 'rendered_diagram.png'
    old.parent.mkdir(parents=True)
    old.write_bytes(b'original run')
    # A new namespace can exist for other samples without hiding old runs.
    current = tmp_path / 'experiments' / 'past' / 'outputs' / 'evodesign' / 'evodesign'
    current.mkdir(parents=True)
    image, scores, _ = path_resolver.parse_method_paths(method, 'sample', exp_id='past')
    assert image == old
    assert old.read_bytes() == b'original run'
    assert scores == tmp_path / 'experiments' / 'past' / 'scores' / 'evodesign' / 'evodesign' / 'model' / 'sample'
    new = current / 'model' / 'sample' / 'rendered_diagram.png'
    new.parent.mkdir(parents=True)
    new.write_bytes(b'new run')
    assert path_resolver.parse_method_paths(method, 'sample', exp_id='past')[0] == new


def test_package_rename_reads_historical_variant_results(monkeypatch, tmp_path):
    monkeypatch.setattr(path_resolver, 'PROJECT_ROOT', tmp_path)
    old = tmp_path / 'results' / 'evodiagram_wo_refiner' / 'sample' / 'rendered_diagram.png'
    old.parent.mkdir(parents=True)
    old.touch()
    assert path_resolver.parse_method_paths('evodesign_wo_refiner', 'sample', exp_id='past')[0] == old
    assert path_resolver.parse_method_paths('evodiagram_wo_refiner', 'sample', exp_id='past')[0] == old
