"""
LLM-based Preference Extraction Agent

Replaces rule-based inference with LLM reasoning to extract semantic,
context-rich preferences from diagram modifications.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from langchain_core.language_models import BaseChatModel

from evo_diagram.core.base_agent import BaseAgent
from ..schemas.diff_schemas import GuidedDiff
from ..schemas.observation_schemas import VisualObservation
from ..schemas.semantic_preference_schemas import (
    PreferenceExtractionResult,
    SemanticPreference,
)

logger = logging.getLogger(__name__)


# ============================================================================
# System Prompt
# ============================================================================

SYSTEM_PROMPT = """You are an expert diagram design analyst specializing in extracting user preferences from diagram modifications.

Your task: Analyze changes a user made to an auto-generated diagram and extract high-level, generalizable design preferences.

## Analysis Framework

When analyzing changes, consider:

1. **Intent**: Why did the user make these changes?
   - Visual emphasis/hierarchy?
   - Improving readability?
   - Following conventions?
   - Personal aesthetic preferences?

2. **Pattern**: What design principle do these changes reveal?
   - Consistent across multiple elements?
   - Specific to element type/role?
   - Context-dependent?

3. **Generalization**: How can this preference apply to future diagrams?
   - Same diagram type?
   - Same content domain?
   - Broader applicability?

4. **Agent Alignment**: Which workflow does this preference affect?
   - **Structure**: Semantic organization (node types, edge relations, grouping, hierarchy)
   - **Styling**: Visual appearance (colors, shapes, fills, borders, arrows, fonts)
   - **Layout**: Spatial arrangement (positions, spacing, alignment, sizing)

## Agent Category Rules

Use these rules to determine agent_category:

**Structure** - Semantic/organizational properties:
- chart_type, diagram_type
- node.type (semantic type, not visual shape)
- edge.relation, edge.source, edge.target
- group.members, group.group_member_relation, group.parent_group_id

**Styling** - Visual/aesthetic properties:
- type (geo/arrow/text), props.geo (rectangle/ellipse/etc)
- props.color, props.labelColor, props.fill
- props.dash, props.size, props.font
- props.arrowheadStart, props.arrowheadEnd
- props.text, props.align, props.verticalAlign
- opacity, rotation

**Layout** - Spatial/positioning properties:
- x, y (positions)
- w, h (dimensions)
- nodesep, ranksep, linkDistance, nodeSpacing
- scale, bend

## Output Format

Return a JSON array of preference objects:

```json
[
  {
    "preference_text": "Clear, context-rich description of the preference",
    "agent_category": "Structure|Styling|Layout",
    "applies_to": {
      "diagram_type": "class|dataflow|sequence|...",
      "content_area": "Software Engineering|Business Process|...",
      "element_type": "node|edge|group|arrow",
      "element_role": "entity|service|flow|..."
    },
    "confidence": 0.0-1.0,
    "design_rationale": "Why this preference improves the diagram",
    "evidence_summary": "Brief summary of supporting changes"
  }
]
```

## Guidelines

- **Be specific**: "User prefers red for entity nodes in class diagrams" NOT "User likes red"
- **Be contextual**: Include diagram_type and content_area when applicable
- **Be actionable**: Preferences should be clear enough for agents to apply
- **Confidence**: Higher if pattern is consistent across multiple elements
- **Agent category**: Choose the PRIMARY agent this preference affects
- **Evidence**: Summarize the changes concisely (don't list every single change)
"""


# ============================================================================
# Few-Shot Examples
# ============================================================================

FEW_SHOT_EXAMPLES = """
## Example 1: Styling - Entity Color Preference

**Input:**
- Diagram Type: class
- Content Area: Software Engineering
- VLM Intent: "User wants to emphasize core domain entities"
- Changes:
  * node:Account: props.color blue → red (priority: high)
  * node:Contact: props.color blue → red (priority: high)
  * node:AddressBook: props.color blue → red (priority: high)
  * node:ContactGroup: props.color blue → red (priority: high)

**Reasoning:**
Step 1 - Intent: User changed all 4 entity node colors from blue to red. This suggests they want to visually emphasize these core domain objects.

Step 2 - Pattern: Consistent pattern across ALL entity nodes (4/4). This is a strong, deliberate pattern, not random adjustments.

Step 3 - Agent Category: This affects **Styling Agent** because props.color is a visual appearance property.

Step 4 - Generalization: Applies to class diagrams in Software Engineering domain, specifically for entity nodes representing domain objects.

**Output:**
```json
[
  {
    "preference_text": "User prefers red color for entity nodes in class diagrams to emphasize core domain objects and create visual hierarchy",
    "agent_category": "Styling",
    "applies_to": {
      "diagram_type": "class",
      "content_area": "Software Engineering",
      "element_type": "node",
      "element_role": "entity"
    },
    "confidence": 0.95,
    "design_rationale": "Red color creates strong visual emphasis, helping readers quickly identify primary domain entities in complex class diagrams",
    "evidence_summary": "Changed all 4 entity nodes (Account, Contact, AddressBook, ContactGroup) from blue to red"
  }
]
```

---

## Example 2: Styling - Arrow Style Preference

**Input:**
- Diagram Type: dataflow
- Content Area: Software Architecture
- VLM Intent: "User wants to distinguish between different relationship types"
- Changes:
  * arrow:auth_flow: props.dash draw → dashed (priority: high)
  * arrow:data_flow: props.dash draw → dashed (priority: high)
  * arrow:control_flow: props.dash draw → dashed (priority: high)

**Reasoning:**
Step 1 - Intent: User changed arrow line styles from solid to dashed for multiple flows. This suggests they want to visually distinguish these flows from other relationships (likely solid lines represent different semantics).

Step 2 - Pattern: Consistent across 3 arrows, all representing similar flow types. Pattern indicates categorical distinction (dashed for data/control flows vs solid for other relationships).

Step 3 - Agent Category: This affects **Styling Agent** because props.dash is a visual line style property.

Step 4 - Generalization: Applies to dataflow diagrams where different arrow styles indicate different relationship semantics.

**Output:**
```json
[
  {
    "preference_text": "User prefers dashed arrows for data and control flows in dataflow diagrams to visually distinguish them from structural relationships",
    "agent_category": "Styling",
    "applies_to": {
      "diagram_type": "dataflow",
      "content_area": "Software Architecture",
      "element_type": "arrow",
      "element_role": "flow"
    },
    "confidence": 0.85,
    "design_rationale": "Dashed lines visually separate transient flows (data/control) from permanent structural relationships, improving diagram clarity",
    "evidence_summary": "Changed 3 flow arrows (auth_flow, data_flow, control_flow) from solid to dashed lines"
  }
]
```

---

## Example 3: Layout - Position Adjustment

**Input:**
- Diagram Type: class
- Content Area: Software Engineering
- VLM Intent: "User wants to improve spacing and prevent overlap"
- Changes:
  * node:Contact: x 150.0 → 27.29 (Δ=-122.7, priority: high)
  * node:Contact: y 260.0 → 262.37 (Δ=+2.4, priority: high)
  * node:ContactGroup: x 450.0 → 406.46 (Δ=-43.5, priority: high)

**Reasoning:**
Step 1 - Intent: User moved two nodes leftward and slightly adjusted vertical position. The VLM observed this was to prevent overlap and improve spacing.

Step 2 - Pattern: Both movements are leftward adjustments. The larger movement (Contact: -122.7px) suggests resolving a significant overlap, while the smaller one (ContactGroup: -43.5px) is a minor adjustment.

Step 3 - Agent Category: This affects **Layout Agent** because x, y are spatial positioning properties.

Step 4 - Generalization: Hard to generalize specific pixel movements, but reveals user prefers non-overlapping layout with clear spacing. This is more about collision avoidance than a specific spacing preference.

**Output:**
```json
[
  {
    "preference_text": "User prefers non-overlapping node layouts with clear spacing in class diagrams, adjusting positions to prevent visual collisions",
    "agent_category": "Layout",
    "applies_to": {
      "diagram_type": "class",
      "content_area": "Software Engineering",
      "element_type": "node"
    },
    "confidence": 0.70,
    "design_rationale": "Clear spacing prevents visual clutter and ensures all nodes are fully readable without overlap",
    "evidence_summary": "Moved 2 nodes leftward to prevent overlap (Contact: -122.7px, ContactGroup: -43.5px)"
  }
]
```

---

## Example 4: Structure - Grouping Preference

**Input:**
- Diagram Type: class
- Content Area: Software Engineering
- VLM Intent: "User wants to organize related entities into logical modules"
- Changes:
  * group:auth_module: group.members [] → ["node:Account", "node:Auth"] (priority: high)
  * group:auth_module: group.group_member_relation "parallel" → "hierarchical" (priority: high)

**Reasoning:**
Step 1 - Intent: User created a new group for authentication-related entities and changed the member relationship to hierarchical. This shows they want to organize related concepts into logical modules.

Step 2 - Pattern: Creating semantic grouping with hierarchical organization. This is an organizational/structural decision, not visual.

Step 3 - Agent Category: This affects **Structure Agent** because group.members and group.group_member_relation are semantic organization properties.

Step 4 - Generalization: Applies to class diagrams where related entities should be grouped into logical modules with clear hierarchical relationships.

**Output:**
```json
[
  {
    "preference_text": "User prefers grouping authentication-related entities into logical modules with hierarchical organization in class diagrams",
    "agent_category": "Structure",
    "applies_to": {
      "diagram_type": "class",
      "content_area": "Software Engineering",
      "element_type": "group",
      "element_role": "module"
    },
    "confidence": 0.80,
    "design_rationale": "Logical grouping with hierarchical relationships improves diagram comprehension by showing clear module boundaries and internal structure",
    "evidence_summary": "Created auth_module group with 2 members (Account, Auth) and hierarchical member relationship"
  }
]
```
"""


# ============================================================================
# Task Prompt Template
# ============================================================================

TASK_PROMPT = """## Task Context

**Diagram Type**: {{diagram_type}}
**Content Area**: {{content_area}}
**Vertical Domain**: {{vertical_domain}}
**User Query**: {{user_query}}

---

## Reference Examples

{{few_shot_examples}}

---

## User's Overall Intent (from VLM Analysis)

{{overall_intent}}

VLM observed these high-level changes:
- **Structure changes**: {{structural_changes_desc}} (magnitude: {{structural_magnitude}})
- **Styling changes**: {{styling_changes_desc}} (magnitude: {{styling_magnitude}})
- **Layout changes**: {{layout_changes_desc}} (magnitude: {{layout_magnitude}})

---

## Precise Changes (from JSON Diff)

{{changes_formatted}}

---

## Your Task

Analyze these changes step by step following the framework:

### Step 1: Understand Intent
Based on the VLM observation and precise changes, what is the user trying to achieve?

### Step 2: Identify Patterns
Are there consistent patterns across multiple elements? What design principles emerge?

### Step 3: Categorize by Agent
Which agent workflow does each preference primarily affect?
- Structure: Semantic/organizational changes (node types, grouping, relations)
- Styling: Visual/aesthetic changes (colors, shapes, fonts, arrows)
- Layout: Spatial/positioning changes (x, y, w, h, spacing)

### Step 4: Generalize Preferences
How can these preferences be applied to future similar diagrams?

---

## Output

Provide your step-by-step reasoning above, then output the extracted preferences in JSON format.

**IMPORTANT**: Extract ALL identified preferences with their confidence scores. Low-confidence preferences will be filtered programmatically.
"""


# ============================================================================
# Agent Implementation
# ============================================================================


class LLMPreferenceExtractionAgent(BaseAgent):
    """
    LLM-based agent that extracts semantic preferences from diagram modifications.

    Replaces rule-based inference with LLM reasoning to produce context-rich,
    actionable preferences.
    """

    def __init__(
        self,
        model: BaseChatModel,
        min_confidence: float = 0.7,
        **kwargs
    ):
        """
        Initialize the LLM preference extraction agent.

        Args:
            model: LLM model to use for extraction
            min_confidence: Minimum confidence threshold (default: 0.7)
        """
        super().__init__(
            model=model,
            system_prompt=SYSTEM_PROMPT,
            task_prompt=TASK_PROMPT,
            tools=None,
            exclude_think=True,
            jsonalize_output=True,
            **kwargs
        )
        self.min_confidence = min_confidence
        logger.info(f"Initialized LLMPreferenceExtractionAgent with min_confidence={min_confidence}")

    def extract_preferences(
        self,
        visual_observation: VisualObservation,
        guided_diff: GuidedDiff,
        task_context: Dict[str, Any],
    ) -> PreferenceExtractionResult:
        """
        Extract semantic preferences from diagram modifications.

        Args:
            visual_observation: VLM's high-level understanding
            guided_diff: JSON diff with precise changes
            task_context: Task metadata (diagram_type, content_area, etc.)

        Returns:
            PreferenceExtractionResult with extracted preferences
        """
        logger.info("Starting LLM-based preference extraction")

        has_changes = any(
            (
                guided_diff.additions,
                guided_diff.deletions,
                guided_diff.modifications,
            )
        )
        if not has_changes:
            logger.info("No JSON diff changes detected, skipping preference extraction")
            return PreferenceExtractionResult(
                status="no_preferences",
                preferences=[],
                filtered_count=0,
                task_context=task_context,
                warnings=["No JSON diff changes detected"],
            )

        # Format input for LLM
        input_dict = self._format_input(visual_observation, guided_diff, task_context)

        try:
            input_dict["few_shot_examples"] = FEW_SHOT_EXAMPLES

            # Invoke LLM
            logger.info("Invoking LLM for preference extraction...")
            logger.info(
                "Input contains %d additions, %d deletions, %d modifications",
                len(guided_diff.additions),
                len(guided_diff.deletions),
                len(guided_diff.modifications),
            )

            raw_result = self.invoke(input_dict)

            # Log raw result for debugging
            logger.info("LLM invocation completed")
            logger.debug(f"Raw result type: {type(raw_result).__name__}")
            if isinstance(raw_result, str):
                logger.debug(f"Raw result preview (first 1000 chars): {raw_result[:1000]}")
            else:
                logger.debug(f"Raw result: {raw_result}")

            # Parse result
            preferences, filtered_count, reasoning = self._parse_result(raw_result)

            logger.info(
                f"Extracted {len(preferences)} preferences "
                f"(filtered {filtered_count} low-confidence preferences)"
            )

            return PreferenceExtractionResult(
                status="succeeded" if preferences else "no_preferences",
                preferences=preferences,
                filtered_count=filtered_count,
                task_context=task_context,
                reasoning=reasoning
            )

        except Exception as e:
            logger.error(f"Preference extraction failed: {e}", exc_info=True)
            return PreferenceExtractionResult(
                status="failed",
                preferences=[],
                filtered_count=0,
                task_context=task_context,
                errors=[f"{type(e).__name__}: {e}"],
            )

    def _format_input(
        self,
        visual_observation: VisualObservation,
        guided_diff: GuidedDiff,
        task_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Format input data for LLM prompt."""
        # Extract task context
        diagram_type = task_context.get("diagram_type", "unknown")
        content_area = task_context.get("content_area", "unknown")
        vertical_domain = task_context.get("vertical_domain", "unknown")
        user_query = task_context.get("query", "N/A")

        # Format VLM observations
        overall_intent = visual_observation.overall_intent
        structural_changes_desc = visual_observation.structural_changes.description
        structural_magnitude = visual_observation.structural_changes.magnitude
        styling_changes_desc = visual_observation.styling_changes.description
        styling_magnitude = visual_observation.styling_changes.magnitude
        layout_changes_desc = visual_observation.layout_changes.description
        layout_magnitude = visual_observation.layout_changes.magnitude

        # Format JSON diff changes
        changes_formatted = self._format_changes(guided_diff)

        return {
            "diagram_type": diagram_type,
            "content_area": content_area,
            "vertical_domain": vertical_domain,
            "user_query": user_query,
            "overall_intent": overall_intent,
            "structural_changes_desc": structural_changes_desc,
            "structural_magnitude": structural_magnitude,
            "styling_changes_desc": styling_changes_desc,
            "styling_magnitude": styling_magnitude,
            "layout_changes_desc": layout_changes_desc,
            "layout_magnitude": layout_magnitude,
            "changes_formatted": changes_formatted,
        }

    def _format_changes(self, guided_diff: GuidedDiff) -> str:
        """Format guided diff changes for LLM prompt."""
        lines = []

        for addition in guided_diff.additions:
            lines.append(f"\n**Added {addition.shape_id}:**")
            lines.append(
                f"  * shape_type: {addition.shape_type} "
                f"[{addition.related_observation}] [structure]"
            )
            if addition.properties:
                lines.append(
                    "  * properties: "
                    + json.dumps(addition.properties, ensure_ascii=False, sort_keys=True)
                )

        for deletion in guided_diff.deletions:
            lines.append(f"\n**Deleted {deletion.shape_id}:**")
            lines.append(
                f"  * shape_type: {deletion.shape_type} "
                f"[{deletion.related_observation}] [structure]"
            )
            if deletion.properties:
                lines.append(
                    "  * removed_properties: "
                    + json.dumps(deletion.properties, ensure_ascii=False, sort_keys=True)
                )

        for mod in guided_diff.modifications:
            shape_id = mod.shape_id
            lines.append(f"\n**{shape_id}:**")

            for change in mod.changes:
                priority_flag = "(priority: high)" if change.is_priority else ""
                vlm_hint = f"[{change.vlm_hint}]" if change.vlm_hint else ""

                # Format delta for numeric changes
                if isinstance(change.from_value, (int, float)) and isinstance(change.to_value, (int, float)):
                    delta = change.to_value - change.from_value
                    delta_str = f" (Δ={delta:+.1f})"
                else:
                    delta_str = ""

                lines.append(
                    f"  * {change.property_path}: {change.from_value} → {change.to_value}{delta_str} "
                    f"{priority_flag} {vlm_hint} [{change.category}]"
                )

        return "\n".join(lines) if lines else "No JSON-level changes detected."

    def _parse_result(self, raw_result: Any) -> tuple[List[SemanticPreference], int, Optional[str]]:
        """
        Parse LLM output into SemanticPreference objects.

        Returns:
            (preferences, filtered_count, reasoning)
        """
        # Log raw result for debugging
        logger.debug(f"Parsing LLM result (type: {type(raw_result).__name__})")
        if isinstance(raw_result, str):
            logger.debug(f"Raw LLM output (first 500 chars): {raw_result[:500]}")

        # Extract reasoning if present (text before JSON)
        reasoning = None
        preferences_data = []

        if isinstance(raw_result, str):
            # Try to extract JSON from text
            try:
                json_start = raw_result.find("[")
                json_end = raw_result.rfind("]") + 1
                if json_start >= 0 and json_end > json_start:
                    reasoning = raw_result[:json_start].strip()
                    json_str = raw_result[json_start:json_end]
                    logger.debug(f"Extracted JSON array (length: {len(json_str)})")
                    preferences_data = json.loads(json_str)
                    logger.debug(f"Parsed {len(preferences_data)} preference objects from JSON")
                else:
                    logger.warning(f"No JSON array found in LLM output (length: {len(raw_result)})")
                    logger.debug(f"Full output: {raw_result}")
                    raise ValueError("LLM output did not contain a JSON preference array")
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse JSON from LLM output: {e}")
                logger.debug(f"JSON string: {json_str}")
                raise ValueError(f"Failed to parse preference JSON: {e}") from e

        elif isinstance(raw_result, list):
            preferences_data = raw_result
            logger.debug(f"LLM returned list with {len(preferences_data)} items")

        elif isinstance(raw_result, dict):
            if "preferences" in raw_result:
                preferences_data = raw_result["preferences"]
                reasoning = raw_result.get("reasoning")
                if not isinstance(preferences_data, list):
                    raise ValueError("LLM preferences payload must be a list")
                logger.debug(f"LLM returned dict with {len(preferences_data)} preferences")
            else:
                logger.warning(f"Unexpected dict format: {list(raw_result.keys())}")
                logger.debug(f"Full dict: {raw_result}")
                raise ValueError(
                    "LLM output dict must contain a 'preferences' field"
                )
        else:
            raise ValueError(
                f"Unsupported LLM preference output type: {type(raw_result).__name__}"
            )

        # Convert to SemanticPreference objects and filter by confidence
        preferences = []
        filtered_count = 0
        parse_errors = []

        for index, item in enumerate(preferences_data):
            try:
                pref = SemanticPreference(**item)

                if pref.confidence >= self.min_confidence:
                    preferences.append(pref)
                    logger.debug(
                        f"Accepted preference (confidence={pref.confidence:.2f}): "
                        f"{pref.preference_text[:80]}"
                    )
                else:
                    filtered_count += 1
                    logger.debug(
                        f"Filtered low-confidence preference (confidence={pref.confidence:.2f}): "
                        f"{pref.preference_text[:80]}"
                    )


            except Exception as e:
                logger.warning(f"Failed to parse preference item %d: %s", index, e)
                parse_errors.append(f"item {index}: {e}")
                continue

        if preferences_data and not preferences and filtered_count == 0 and parse_errors:
            raise ValueError(
                "LLM returned preference objects, but none matched the schema: "
                + "; ".join(parse_errors[:3])
            )

        return preferences, filtered_count, reasoning

    def run(self, state: Any) -> Any:
        """
        Not used - use extract_preferences() instead.
        """
        raise NotImplementedError(
            "LLMPreferenceExtractionAgent does not use run() method. "
            "Use extract_preferences() instead."
        )
