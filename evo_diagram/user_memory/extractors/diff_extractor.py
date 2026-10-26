"""VLM-Guided JSON Diff Extractor - Layer 2 of the preference learning system.

Extracts precise JSON differences between model-generated and user-adjusted
diagrams, guided by VLM observations to prioritize relevant properties.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Set, Union

from .manifest_normalizer import (
    ManifestNormalizer,
    NormalizedShape,
)
from .manifest_validator import ManifestFormat
from ..schemas.diff_schemas import (
    GuidedDiff,
    PropertyChange,
    ShapeAddition,
    ShapeDeletion,
    ShapeModification,
)
from ..schemas.observation_schemas import VisualObservation

logger = logging.getLogger(__name__)


class EnhancedDiffExtractor:
    """Extract ALL property changes with robust format handling."""

    # Default property category sets
    DEFAULT_STRUCTURE_PROPS = {
        "chart_type",
        "node_type",
        "edge_type",
        "parent_id",
        "source",
        "target",
        "label",
        "description",
        "type",
    }

    DEFAULT_STYLING_PROPS = {
        "geo",
        "color",
        "fill",
        "dash",
        "size",
        "font",
        "align",
        "verticalAlign",
        "opacity",
        "text",
        "growY",
        "icon",
        "arrowheadStart",
        "arrowheadEnd",
        "labelPosition",
        "labelColor",
        "url",
    }

    DEFAULT_LAYOUT_PROPS = {
        "x",
        "y",
        "w",
        "h",
        "rotation",
        "scale",
        "nodesep",
        "ranksep",
        "linkDistance",
        "nodeSpacing",
        "bend",
    }

    DEFAULT_COMPUTED_PROPS = {
        "computed_width",
        "computed_height",
        "text_width",
        "text_height",
        "typeName",
        "index",
        "id",
        "parentId",
        "meta",
    }

    def __init__(
        self,
        epsilon: float = 0.01,
        structure_props: Optional[Set[str]] = None,
        styling_props: Optional[Set[str]] = None,
        layout_props: Optional[Set[str]] = None,
        computed_props: Optional[Set[str]] = None,
    ):
        """Initialize diff extractor.

        Args:
            epsilon: Tolerance for floating-point comparison.
            structure_props: Property names classified as structure. Uses defaults if None.
            styling_props: Property names classified as styling. Uses defaults if None.
            layout_props: Property names classified as layout. Uses defaults if None.
            computed_props: Property names to skip during comparison. Uses defaults if None.
        """
        self.epsilon = epsilon
        self.structure_props = structure_props if structure_props is not None else self.DEFAULT_STRUCTURE_PROPS
        self.styling_props = styling_props if styling_props is not None else self.DEFAULT_STYLING_PROPS
        self.layout_props = layout_props if layout_props is not None else self.DEFAULT_LAYOUT_PROPS
        self.computed_props = computed_props if computed_props is not None else self.DEFAULT_COMPUTED_PROPS
        self.normalizer = ManifestNormalizer()

    def extract_diff(
        self,
        model_manifest: Union[Dict, str, Path],
        user_manifest: Union[Dict, str, Path],
        visual_observation: VisualObservation,
    ) -> GuidedDiff:
        """Extract all changes with robust format handling."""
        logger.info("Starting VLM-guided JSON diff extraction with robust format handling")

        # Load manifests if paths provided
        if isinstance(model_manifest, (str, Path)):
            with open(model_manifest) as f:
                model_manifest = json.load(f)

        if isinstance(user_manifest, (str, Path)):
            with open(user_manifest) as f:
                user_manifest = json.load(f)

        diff = GuidedDiff(visual_observation=visual_observation)

        # Step 1: Normalize both manifests
        model_norm = self.normalizer.normalize(model_manifest)
        user_norm = self.normalizer.normalize(user_manifest)

        logger.info(
            f"Format detected: model={model_norm.format.value}, user={user_norm.format.value}"
        )
        logger.info(
            f"Shapes extracted: model={len(model_norm.shapes)}, user={len(user_norm.shapes)}"
        )

        # Collect warnings
        all_warnings = model_norm.warnings + user_norm.warnings

        # Step 2: Reject untrusted manifests. A valid empty diagram on one side
        # is still an actionable add/delete diff, but UNKNOWN means format
        # detection failed and all add/delete semantics would be fabricated.
        if (
            model_norm.format == ManifestFormat.UNKNOWN
            or user_norm.format == ManifestFormat.UNKNOWN
        ):
            warning_msg = (
                "JSON diff extraction failed: manifest format is unknown "
                f"(model={model_norm.format.value}, user={user_norm.format.value})"
            )
            all_warnings.append(warning_msg)
            logger.error("%s; warnings=%s", warning_msg, all_warnings)
            raise ValueError(warning_msg)

        # Step 3: Get priority properties from VLM
        priority_properties = self._get_priority_properties(visual_observation)

        # Step 4: Detect additions/deletions
        added_ids = set(user_norm.shapes.keys()) - set(model_norm.shapes.keys())
        deleted_ids = set(model_norm.shapes.keys()) - set(user_norm.shapes.keys())

        for shape_id in added_ids:
            diff.additions.append(
                ShapeAddition(
                    shape_id=shape_id,
                    shape_type=user_norm.shapes[shape_id].type,
                    properties=self._shape_to_dict(user_norm.shapes[shape_id]),
                    related_observation="structural",
                )
            )

        for shape_id in deleted_ids:
            diff.deletions.append(
                ShapeDeletion(
                    shape_id=shape_id,
                    shape_type=model_norm.shapes[shape_id].type,
                    properties=self._shape_to_dict(model_norm.shapes[shape_id]),
                    related_observation="structural",
                )
            )

        # Step 5: Detect modifications (with numeric tolerance)
        common_ids = set(model_norm.shapes.keys()) & set(user_norm.shapes.keys())
        for shape_id in common_ids:
            model_shape = model_norm.shapes[shape_id]
            user_shape = user_norm.shapes[shape_id]

            changes = self._compare_normalized_shapes(
                model_shape, user_shape, priority_properties
            )

            if changes:
                diff.modifications.append(
                    ShapeModification(shape_id=shape_id, changes=changes)
                )

        logger.info(
            f"Diff extraction complete: {len(diff.additions)} additions, "
            f"{len(diff.deletions)} deletions, {len(diff.modifications)} modifications"
        )

        diff.warnings = all_warnings
        return diff

    def _compare_normalized_shapes(
        self,
        model_shape: NormalizedShape,
        user_shape: NormalizedShape,
        priority_properties: Dict[str, Set[str]],
    ) -> List[PropertyChange]:
        """Compare normalized shapes with numeric tolerance."""
        changes = []

        # Top-level properties
        for key in ["x", "y", "rotation", "is_locked", "opacity"]:
            if key in self.computed_props:
                continue

            model_val = getattr(model_shape, key)
            user_val = getattr(user_shape, key)

            if not self._values_equal(model_val, user_val):
                changes.append(
                    PropertyChange(
                        property_path=key,
                        from_value=model_val,
                        to_value=user_val,
                        category=self._categorize_property(key),
                        is_priority=self._is_priority(key, priority_properties),
                        vlm_hint=self._get_vlm_hint(key, priority_properties),
                    )
                )

        # Props (dynamic property discovery)
        all_prop_keys = set(model_shape.props.keys()) | set(user_shape.props.keys())
        for prop_key in all_prop_keys:
            if prop_key in self.computed_props:
                continue

            model_val = model_shape.props.get(prop_key)
            user_val = user_shape.props.get(prop_key)

            if not self._values_equal(model_val, user_val):
                changes.append(
                    PropertyChange(
                        property_path=f"props.{prop_key}",
                        from_value=model_val,
                        to_value=user_val,
                        category=self._categorize_property(prop_key),
                        is_priority=self._is_priority(prop_key, priority_properties),
                        vlm_hint=self._get_vlm_hint(prop_key, priority_properties),
                    )
                )

        return changes

    def _values_equal(self, val1, val2) -> bool:
        """Compare values with numeric tolerance."""
        # Handle None
        if val1 is None and val2 is None:
            return True
        if val1 is None or val2 is None:
            return False

        # Numeric comparison with epsilon
        if isinstance(val1, (int, float)) and isinstance(val2, (int, float)):
            return abs(float(val1) - float(val2)) < self.epsilon

        # Deep object comparison for dicts
        if isinstance(val1, dict) and isinstance(val2, dict):
            if set(val1.keys()) != set(val2.keys()):
                return False
            return all(self._values_equal(val1[k], val2[k]) for k in val1.keys())

        # Deep list comparison
        if isinstance(val1, list) and isinstance(val2, list):
            if len(val1) != len(val2):
                return False
            return all(self._values_equal(v1, v2) for v1, v2 in zip(val1, val2))

        # Default equality
        return val1 == val2

    def _shape_to_dict(self, shape: NormalizedShape) -> dict:
        """Convert NormalizedShape to dict."""
        return {
            "id": shape.id,
            "type": shape.type,
            "x": shape.x,
            "y": shape.y,
            "rotation": shape.rotation,
            "isLocked": shape.is_locked,
            "opacity": shape.opacity,
            "props": shape.props,
            "meta": shape.meta,
            "parentId": shape.parent_id,
            "index": shape.index,
        }

    def _get_priority_properties(
        self, obs: VisualObservation
    ) -> Dict[str, Set[str]]:
        """Extract priority properties from VLM observation."""
        return {
            "structural": set(obs.structural_changes.affected_properties),
            "styling": set(obs.styling_changes.affected_properties),
            "layout": set(obs.layout_changes.affected_properties),
            "semantic": set(obs.semantic_changes.affected_properties),
        }

    def _is_priority(self, prop_name: str, priority_props: Dict[str, Set[str]]) -> bool:
        """Check if property is flagged as priority by VLM."""
        return any(prop_name in props for props in priority_props.values())

    def _categorize_property(self, prop_name: str) -> str:
        """Categorize property by Agent workflow."""
        if prop_name in self.structure_props:
            return "structure"
        elif prop_name in self.styling_props:
            return "styling"
        elif prop_name in self.layout_props:
            return "layout"
        return "other"

    def _get_vlm_hint(
        self, prop_name: str, priority_props: Dict[str, Set[str]]
    ) -> Optional[str]:
        """Get VLM observation hint for this property."""
        for category, props in priority_props.items():
            if prop_name in props:
                return category
        return None
