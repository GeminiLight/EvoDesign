from __future__ import annotations

import pytest

from evo_diagram.user_memory.extractors.diff_extractor import EnhancedDiffExtractor
from evo_diagram.user_memory.extractors.manifest_validator import (
    ManifestFormat,
    ManifestValidator,
)
from evo_diagram.user_memory.schemas.observation_schemas import (
    CategoryObservation,
    VisualObservation,
)


def _observation() -> VisualObservation:
    category = CategoryObservation(
        description="User changed the diagram",
        magnitude="moderate",
        affected_properties=["text"],
    )
    return VisualObservation(
        structural_changes=category,
        styling_changes=category,
        layout_changes=category,
        semantic_changes=category,
        overall_intent="Clarify the design",
    )


def _shape(shape_id: str, text: str) -> dict:
    return {
        "id": shape_id,
        "type": "geo",
        "x": 0,
        "y": 0,
        "props": {"text": text, "w": 120, "h": 40},
    }


def test_diff_extractor_treats_empty_model_manifest_as_additions():
    diff = EnhancedDiffExtractor().extract_diff(
        model_manifest={"shapes": []},
        user_manifest={"shapes": [_shape("shape:added", "Added")]},
        visual_observation=_observation(),
    )

    assert [addition.shape_id for addition in diff.additions] == ["shape:added"]
    assert diff.deletions == []
    assert "VLM-only" not in " ".join(diff.warnings)


def test_diff_extractor_treats_empty_user_manifest_as_deletions():
    diff = EnhancedDiffExtractor().extract_diff(
        model_manifest={"shapes": [_shape("shape:deleted", "Deleted")]},
        user_manifest={"shapes": []},
        visual_observation=_observation(),
    )

    assert diff.additions == []
    assert [deletion.shape_id for deletion in diff.deletions] == ["shape:deleted"]
    assert "VLM-only" not in " ".join(diff.warnings)


def test_diff_extractor_rejects_unknown_manifest_formats():
    with pytest.raises(ValueError, match="manifest format is unknown"):
        EnhancedDiffExtractor().extract_diff(
            model_manifest={"not_a_manifest": True},
            user_manifest={"still_not_a_manifest": True},
            visual_observation=_observation(),
        )

    with pytest.raises(ValueError, match="model=unknown, user=legacy_array"):
        EnhancedDiffExtractor().extract_diff(
            model_manifest={"not_a_manifest": True},
            user_manifest={"shapes": [_shape("shape:added", "Added")]},
            visual_observation=_observation(),
        )

    with pytest.raises(ValueError, match="model=legacy_array, user=unknown"):
        EnhancedDiffExtractor().extract_diff(
            model_manifest={"shapes": [_shape("shape:deleted", "Deleted")]},
            user_manifest={"still_not_a_manifest": True},
            visual_observation=_observation(),
        )


def test_manifest_validator_treats_known_empty_manifest_as_valid():
    result = ManifestValidator().validate({"shapes": []})

    assert result.format == ManifestFormat.LEGACY_ARRAY
    assert result.is_valid is True
    assert result.shape_count == 0


def test_manifest_validator_reports_malformed_document_store_without_throwing():
    result = ManifestValidator().validate({"document": {"store": []}})

    assert result.format == ManifestFormat.UNKNOWN
    assert result.is_valid is False
    assert result.shape_count == 0
    assert "document.store is missing or not an object" in result.warnings


def test_manifest_validator_handles_non_dict_and_malformed_assets():
    validator = ManifestValidator()

    unknown = validator.validate(None)
    assert unknown.format == ManifestFormat.UNKNOWN
    assert unknown.is_valid is False
    result = validator.validate({"assets": object()})

    assert result.format == ManifestFormat.UNKNOWN
    assert result.is_valid is False
    assert result.has_assets is False


def test_user_memory_lazy_export_points_to_active_diff_extractor_module():
    from evo_diagram.user_memory import extractors

    assert extractors.EnhancedDiffExtractor is EnhancedDiffExtractor
    assert extractors.EnhancedDiffExtractor.__module__.endswith(".diff_extractor")
