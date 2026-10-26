"""Promoter agents for guideline extraction and principle promotion."""

import json
import logging
from typing import Any, Dict, List

from langchain_core.language_models import BaseChatModel
from evo_diagram.core.base_agent import BaseAgent

logger = logging.getLogger(__name__)

# ── Guideline Extractor prompts ──────────────────────────────────────────────

_GUIDELINE_EXTRACTOR_SYSTEM = """
# Role: [Knowledge Base Manager & Consolidator]

## Role Context
You are a Lead Technical Editor and Strategy Manager within the Knowledge Search & Distillation framework. Your core purpose is "Guideline Evolution." You manage a dynamic Knowledge Base of design guidelines. You receive NEW strategy items (fragmented observations) and must integrate them into the EXISTING guidelines.

## Layer Alignment
To ensure the evolution is precise and contextually relevant:
1.  **Scope Lens**: You must interpret and filter all input rules strictly through the current **Agent Focus**:
    -   `parse`: Logic extraction, entity identification, content fidelity.
    -   `styling`: Visual design, colors, fonts, shapes, stroke styles.
    -   `layout`: Spatial arrangement, direction (TB/LR), grouping, alignment.
2.  **Semantic Clustering**: Group rules based on *functional similarity*.
3.  **Incremental Evolution**: You do not rebuild from scratch. You ADD new guidelines or UPDATE existing ones with new insights. You never delete guidelines.

## Logic Paradigm
You must follow this reasoning paradigm:
1.  **Analyze New Items**: Read `new_strategy_items`. Filter for current `{{agent}}` focus.
2.  **Compare with Existing**: Check `existing_guidelines`.
    -   Does a new item fit into an existing guideline's scope? -> **UPDATE**.
    -   Is the new item a completely new concept? -> **ADD**.
    -   Does the new item contradict or supersede an existing one? -> **UPDATE** with a narrower `when_to_use`; do not delete.
3.  **Synthesize Updates**:
    -   For **UPDATE**: Merge the new rules into the existing `content`. Refine the `when_to_use` condition to be a union of old and new.
    -   For **ADD**: Create a new guideline entry.
4.  **Format**: Output a JSON object containing a list of `operations`.

## Global Constraints
1.  **JSON Only**: Output must be a strictly valid JSON dictionary.
2.  **Atomic Operations**: Each change must be a distinct operation in the list.
3.  **Preserve IDs**: When updating, you MUST use the correct `item_id` from the existing guidelines.
"""

_GUIDELINE_EXTRACTOR_TASK = """
# Task: [Guideline Knowledge Base Evolution]

## Task Objective
Process a list of NEW strategy items and update the EXISTING guidelines knowledge base. You must determine whether to ADD new guidelines or UPDATE existing ones by merging new content and narrowing stale scopes.

## Input Context
1.  **Domain**: {{domain}}
2.  **Diagram Type**: {{diagram_type}}
3.  **Agent Focus**: {{agent}}
4.  **Existing Guidelines**: The current state of the knowledge base.
5.  **New Strategy Items**: New observations to be integrated.

## Execution Pipeline
1.  **Match**: Iterate through NEW items. Try to find a semantically matching EXISTING guideline.
2.  **Decide Operation**:
    -   **ADD**: If no match found.
    -   **UPDATE**: If match found. Merge content.
    -   Do **not** delete existing guidelines. If an existing item looks stale,
        narrow it through UPDATE and explain the tighter scope in `when_to_use`.
3.  **Format**: Construct the JSON output.

## Output Format
Output a single valid JSON object with the following structure:
```json
{{
    "operations": [
        {{
            "operation_type": "add",
            "title": "String (Synthesized Title)",
            "description": "String (Summary)",
            "when_to_use": "String (Combined specific conditions)",
            "content": "String (Consolidated rules: '- Rule 1\\n- Rule 2...')"
        }},
        {{
            "operation_type": "update",
            "item_id": "String (ID of the existing guideline being updated)",
            "title": "String (New Synthesized Title, usually same as old)",
            "description": "String (New Summary)",
            "when_to_use": "String (New Combined specific conditions)",
            "content": "String (New Consolidated rules)"
        }}
    ]
}}
```

## Input Data
Context - Domain: {{domain}}
Context - Diagram Type: {{diagram_type}}
Context - Agent Focus: {{agent}}

**Existing Guidelines:**
{{existing_guidelines}}

**New Strategy Items:**
{{new_strategy_items}}
"""

# ── Principle Promoter prompts ───────────────────────────────────────────────

_PRINCIPLE_PROMOTER_SYSTEM = """
# Role: [Design Principle Synthesizer]

## Role Context
You evaluate whether a group of Guidelines that apply across different diagram types share a common underlying Principle. If they do, you synthesize a higher-level Principle that captures their shared design wisdom.

## Key Distinction
- A **Guideline** captures a pattern that has been validated within one diagram type (e.g., flowchart) but across multiple business domains.
- A **Principle** captures the abstract design tenet that makes multiple guidelines work even when the diagram type itself changes (flowchart vs. sequence vs. class diagram, etc.).

## Example
Guidelines:
1. "Use color to distinguish process roles" (diagram_type: flowchart)
2. "Use color to distinguish actor lanes" (diagram_type: sequence_diagram)
3. "Use color to distinguish class categories" (diagram_type: class_diagram)

→ Principle: "Visual differentiation through color carries semantic role information regardless of diagram structure. Whenever the diagram contains multiple categories of nodes, assign each category a distinct, consistent color."

## Constraints
1. **JSON Only**: Output must be strictly valid JSON.
2. **Be conservative**: Only promote if there is a genuine shared design tenet, not just surface similarity in wording.
"""

_PRINCIPLE_PROMOTER_TASK = """
# Task: [Guideline → Principle Promotion Evaluation]

## Task Objective
Evaluate whether a group of Guidelines that apply across DIFFERENT diagram types share a common underlying Principle. If yes, synthesize the Principle.

## Input Context
The following Guidelines have been validated across multiple domains and apply to different diagram types:

{{guidelines_block}}

## Execution Pipeline
1. **Analyze**: Read all guidelines carefully. Identify what action or insight they share.
2. **Judge**: Do these guidelines genuinely reflect the same underlying design principle that holds regardless of diagram type? Or are they superficially similar but fundamentally different?
3. **Decide**:
   - If YES (genuine shared design tenet) → output SHOULD_PROMOTE=true and synthesize a Principle
   - If NO (no real commonality) → output SHOULD_PROMOTE=false and explain why

## Output Format
Output a single valid JSON object:
```json
{
    "should_promote": true,
    "principle_title": "String — concise, philosophical title",
    "principle_content": "String — the abstract principle, 2-3 sentences",
    "principle_when_to_use": "String — when this principle applies",
    "principle_description": "String — one-line summary",
    "reasoning": "String — why these guidelines share (or don't share) a common principle"
}
```

Or if NOT promoting:
```json
{
    "should_promote": false,
    "reasoning": "String — why these guidelines do NOT share a common principle"
}
```
"""


# ── Agent classes ────────────────────────────────────────────────────────────

class GuidelineExtractorAgent(BaseAgent):
    """Agent responsible for merging multiple strategy entries with the same tags
    into a single consolidated entry."""

    def __init__(self, model: BaseChatModel, **kwargs):
        super().__init__(
            model,
            system_prompt=_GUIDELINE_EXTRACTOR_SYSTEM,
            task_prompt=_GUIDELINE_EXTRACTOR_TASK,
            **kwargs
        )

    def run(self, domain: str, diagram_type: str, agent: str, new_items: List[Dict], existing_guidelines: List[Dict]) -> Dict[str, Any]:
        simplified_new_items = []
        for item in new_items:
            simplified_new_items.append({
                "title": item.get("title", ""),
                "description": item.get("description", ""),
                "content": item.get("content", ""),
                "when_to_use": item.get("when_to_use", "")
            })
        new_items_str = json.dumps(simplified_new_items, indent=2, ensure_ascii=False)

        simplified_existing = []
        for item in existing_guidelines:
             simplified_existing.append({
                "id": item.get("id"),
                "title": item.get("title", ""),
                "description": item.get("description", ""),
                "content": item.get("content", ""),
                "when_to_use": item.get("when_to_use", "")
            })
        existing_str = json.dumps(simplified_existing, indent=2, ensure_ascii=False)

        input_dict = {
            "domain": domain,
            "diagram_type": diagram_type,
            "agent": agent,
            "new_strategy_items": new_items_str,
            "existing_guidelines": existing_str
        }
        return self.invoke(input_dict)


class PrinciplePromoterAgent(BaseAgent):
    """Agent that evaluates whether guidelines across different diagram types
    share a common principle, and synthesizes the principle if they do."""

    def __init__(self, model: BaseChatModel, **kwargs):
        super().__init__(
            model,
            system_prompt=_PRINCIPLE_PROMOTER_SYSTEM,
            task_prompt=_PRINCIPLE_PROMOTER_TASK,
            **kwargs,
        )

    def _format_guideline_block(self, guidelines: List[Dict[str, Any]]) -> str:
        blocks = []
        for i, g in enumerate(guidelines, 1):
            tags = g.get("tags", {}) or {}
            domains = ", ".join(tags.get("domain", ["unknown"]))
            diagram_types = ", ".join(tags.get("diagram_type", ["unknown"]))
            agents = ", ".join(tags.get("agent", ["unknown"]))
            blocks.append(
                f"### Guideline {i}\n"
                f"- **Title**: {g.get('title', 'N/A')}\n"
                f"- **Diagram type(s)**: {diagram_types}\n"
                f"- **Domains**: {domains}\n"
                f"- **Agent(s)**: {agents}\n"
                f"- **Content**: {g.get('content', 'N/A')}\n"
                f"- **When to use**: {g.get('when_to_use', 'N/A')}\n"
                f"- **Confidence**: {g.get('confidence', 0)}\n"
                f"- **Support count**: {g.get('support_count', 1)}"
            )
        return "\n\n".join(blocks)

    def run(self, guidelines: List[Dict[str, Any]]) -> Dict[str, Any]:
        guidelines_block = self._format_guideline_block(guidelines)
        input_dict = {"guidelines_block": guidelines_block}
        return self.invoke(input_dict)
