"""Judge agents: DemotionJudgerAgent + MergeJudgerAgent."""

import logging
from typing import Any, Dict, List

from langchain_core.language_models import BaseChatModel
from evo_diagram.core.base_agent import BaseAgent

logger = logging.getLogger(__name__)

# ── Demotion Judger prompts ──────────────────────────────────────────────────

_DEMOTION_JUDGER_SYSTEM = """
# Role: [Knowledge Quality Auditor]

## Role Context
You audit knowledge items (Guidelines or Principles) that have been underperforming in recent usage. Your job is to decide whether they should be demoted to a lower tier, or if they are still valid despite recent poor performance.

## Demotion Rules
- A **Guideline** can be demoted to a **Strategy** (it was promoted too eagerly, or conditions changed)
- A **Principle** can be demoted to a **Guideline** (the abstraction was too broad)
- Demotion does NOT mean deletion — the knowledge is still useful, just at a more specific tier

## When to Demote
- The knowledge has been consistently ineffective in recent samples
- The failure conditions it was supposed to address have changed
- It was promoted based on insufficient evidence

## When NOT to Demote
- Recent failures are due to external factors (bad input, rendering issues), not the knowledge itself
- The knowledge is still valid but was applied in wrong contexts
- Small sample size — a few failures don't invalidate established knowledge

## Constraints
1. **JSON Only**: Output must be strictly valid JSON.
2. **Be conservative**: Only demote when there is clear evidence of ineffectiveness.
"""

_DEMOTION_JUDGER_TASK = """
# Task: [Knowledge Item Demotion Evaluation]

## Task Objective
Evaluate whether a knowledge item ({{tier}}) should be demoted based on its recent usage performance.

## Knowledge Item Under Review
- **ID**: {{item_id}}
- **Title**: {{title}}
- **Tier**: {{tier}}
- **Content**: {{content}}
- **When to use**: {{when_to_use}}
- **Original confidence**: {{confidence}}
- **Total usage count**: {{usage_count}}
- **Success count**: {{success_count}}
- **Recent success rate**: {{recent_success_rate}}
- **Validated domains**: {{validated_domains}}

## Recent Failure Context
{{failure_context}}

## Decision Criteria
1. Is the recent failure rate genuinely caused by the knowledge being wrong/inadequate?
2. Or is it caused by misapplication, bad input, or rendering issues?
3. Is the sample size sufficient to make a judgment?

## Output Format
Output a single valid JSON object:
```json
{
    "should_demote": true,
    "new_tier": "strategy",
    "reason": "String — why demotion is warranted",
    "updated_when_to_use": "String — narrowed scope after demotion"
}
```

Or if NOT demoting:
```json
{
    "should_demote": false,
    "reason": "String — why this knowledge should stay at current tier"
}
```
"""

# ── Merge Judger prompts ─────────────────────────────────────────────────────

_MERGE_JUDGER_SYSTEM = """
# Role: [Knowledge Consolidation Auditor]

## Role Context
You audit groups of same-tier knowledge items (Strategies, Guidelines, or
Principles) that share similar titles or topics. Your job is to decide whether
they describe the SAME underlying piece of design knowledge (and should be
merged into one consolidated entry) or whether they capture genuinely different
nuances that should remain separate.

## When to Merge
- The items express the same actionable rule, just paraphrased differently
- The items target the same trigger/condition but have minor wording variations
- Merging them removes redundancy without losing information

## When NOT to Merge
- The items target different triggers, conditions, or scopes (even if the title is similar)
- One item is a strict generalization that would lose precision when merged
- The items contradict each other (this is a signal of conflict, not redundancy)

## Constraints
1. **JSON Only**: Output must be strictly valid JSON.
2. **Be conservative**: Only merge when there is clear semantic overlap.
3. **Preserve evidence**: When merging, the consolidated entry MUST keep the
   strongest signal from each source (highest delta_score, broadest validated_domains).
"""

_MERGE_JUDGER_TASK = """
# Task: [Knowledge Consolidation Decision]

## Task Objective
Evaluate whether the following group of same-tier knowledge items should be
merged into a single consolidated entry, or whether they should remain separate.

## Tier Under Review
{{tier}}

## Candidate Group
{{items_block}}

## Decision Criteria
1. Do the items describe the same underlying rule, just phrased differently?
2. Do they share the same trigger condition (`when_to_use`) or do they target distinct scenarios?
3. Would merging them lose any precision or nuance that would harm future retrieval?

## Output Format
Output a single valid JSON object.

If MERGING:
```json
{
    "should_merge": true,
    "merged_title": "String — the consolidated title",
    "merged_description": "String — one-line summary of the merged rule",
    "merged_content": "String — the consolidated rule body, capturing the strongest wording",
    "merged_when_to_use": "String — the union of triggers, with overlap removed",
    "reasoning": "String — why these items describe the same knowledge"
}
```

If NOT MERGING:
```json
{
    "should_merge": false,
    "reasoning": "String — why these items are genuinely distinct and should remain separate"
}
```
"""


# ── Agent classes ────────────────────────────────────────────────────────────

class DemotionJudgerAgent(BaseAgent):
    """Agent that evaluates whether a knowledge item (guideline/principle)
    should be demoted based on recent usage performance."""

    def __init__(self, model: BaseChatModel, **kwargs):
        super().__init__(
            model,
            system_prompt=_DEMOTION_JUDGER_SYSTEM,
            task_prompt=_DEMOTION_JUDGER_TASK,
            **kwargs,
        )

    def _format_failure_context(self, failed_samples: List[Dict[str, Any]]) -> str:
        if not failed_samples:
            return "No specific failure context available."
        blocks = []
        for s in failed_samples[:5]:
            blocks.append(
                f"- Sample {s.get('sample_id', '?')}: "
                f"Δscore={s.get('delta_score', 'N/A')}, "
                f"domain={s.get('domain', 'N/A')}, "
                f"issue={s.get('issue', 'N/A')}"
            )
        return "\n".join(blocks)

    def run(
        self,
        item: Dict[str, Any],
        failed_samples: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        tags = item.get("tags", {})
        recent_usage = item.get("usage_count", 0)
        success_count = item.get("success_count", 0)
        recent_success_rate = round(success_count / max(recent_usage, 1), 2)

        input_dict = {
            "item_id": item.get("id", "unknown"),
            "title": item.get("title", "N/A"),
            "tier": item.get("tier", "unknown"),
            "content": item.get("content", "N/A"),
            "when_to_use": item.get("when_to_use", "N/A"),
            "confidence": item.get("confidence", 0),
            "usage_count": recent_usage,
            "success_count": success_count,
            "recent_success_rate": str(recent_success_rate),
            "validated_domains": ", ".join(item.get("validated_domains", [])),
            "failure_context": self._format_failure_context(failed_samples),
        }
        return self.invoke(input_dict)


class MergeJudgerAgent(BaseAgent):
    """Agent that evaluates whether a group of same-tier knowledge items should
    be merged into a single consolidated entry."""

    def __init__(self, model: BaseChatModel, **kwargs):
        super().__init__(
            model,
            system_prompt=_MERGE_JUDGER_SYSTEM,
            task_prompt=_MERGE_JUDGER_TASK,
            **kwargs,
        )

    def _format_items(self, items: List[Dict[str, Any]]) -> str:
        blocks = []
        for idx, item in enumerate(items, 1):
            tags = item.get("tags", {}) or {}
            domains = ", ".join(tags.get("domain", [])) or "unknown"
            diagram_types = ", ".join(tags.get("diagram_type", [])) or "unknown"
            agents = ", ".join(tags.get("agent", [])) or "unknown"
            blocks.append(
                f"### Item {idx}\n"
                f"- ID: {item.get('id', 'unknown')}\n"
                f"- Title: {item.get('title', 'N/A')}\n"
                f"- Description: {item.get('description', 'N/A')}\n"
                f"- Content: {item.get('content', 'N/A')}\n"
                f"- When to use: {item.get('when_to_use', 'N/A')}\n"
                f"- Domains: {domains}\n"
                f"- Diagram types: {diagram_types}\n"
                f"- Agents: {agents}\n"
                f"- Δscore: {item.get('delta_score', 0)} | "
                f"usage={item.get('usage_count', 0)} | "
                f"success={item.get('success_count', 0)} | "
                f"support={item.get('support_count', 1)}"
            )
        return "\n\n".join(blocks)

    def run(self, tier: str, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        input_dict = {
            "tier": tier,
            "items_block": self._format_items(items),
        }
        return self.invoke(input_dict)
