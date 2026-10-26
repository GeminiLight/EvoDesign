"""Path manager contract tests."""

from __future__ import annotations


def test_path_manager_separates_package_and_repo_roots():
    from evo_diagram.utils import path_manager

    assert path_manager.PACKAGE_ROOT.name == "evo_diagram"
    assert path_manager.REPO_ROOT == path_manager.PACKAGE_ROOT.parent
    assert "PROJECT_ROOT" not in path_manager.__all__
    assert not hasattr(path_manager, "PROJECT_ROOT")
    assert path_manager.CONFIG_DIR == path_manager.REPO_ROOT / "configs"
    assert path_manager.ENV_FILE == path_manager.REPO_ROOT / ".env"
    assert path_manager.DATASET_DIR == path_manager.REPO_ROOT / "dataset"
    assert path_manager.DEFAULT_TEST_DATASET == (
        path_manager.REPO_ROOT / "dataset" / "test" / "data.json"
    )
    # Datasets are a separate release; the conventional path stays stable.
    assert path_manager.DEFAULT_TEST_DATASET.is_absolute()


def test_path_manager_default_path_base_is_package_root():
    from evo_diagram.utils import path_manager

    assert path_manager.get_path("resources") == path_manager.RESOURCES_DIR
    assert path_manager.get_repo_root() == path_manager.REPO_ROOT
    assert path_manager.get_package_root() == path_manager.PACKAGE_ROOT


def test_safe_path_segment_accepts_normal_filename_segment():
    from evo_diagram.utils.path_manager import safe_path_segment

    assert safe_path_segment("sample-1_2.3") == "sample-1_2.3"


def test_safe_path_segment_rejects_unsafe_or_ambiguous_values():
    import pytest

    from evo_diagram.utils.path_manager import safe_path_segment

    for value in (
        "",
        ".",
        "..",
        "../secret",
        "nested/path",
        "nested\\path",
        "bad name",
        " sample",
        "sample ",
        1,
    ):
        with pytest.raises(ValueError):
            safe_path_segment(value, field_name="dataset item id")


def test_safe_join_under_returns_path_below_root(tmp_path):
    from evo_diagram.utils.path_manager import safe_join_under

    assert safe_join_under(tmp_path, "sample", "iter_1") == tmp_path / "sample" / "iter_1"
