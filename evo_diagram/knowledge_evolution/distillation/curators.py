"""Strategy extraction agent.

Extracts generalizable strategies from iteration history (issues, applied edits,
Δscore) — no intermediate playbook representation needed.
"""

import json
import logging
from typing import Any, Dict

from langchain_core.language_models import BaseChatModel
from evo_diagram.core.base_agent import BaseAgent

logger = logging.getLogger(__name__)

_STRATEGY_EXTRACTOR_SYSTEM = """
# Role: Diagram Strategy Extractor

You analyze iteration feedback from a diagram generation pipeline and extract generalizable design strategies.

## Input
You receive iteration history: for each iteration, the issues found, the edits applied, and the quality change (Δscore). Positive Δscore means the edit improved the diagram.

## Task
From the iteration feedback, extract reusable strategies grouped into three categories:
- **parse**: Text understanding, entity extraction, content fidelity
- **styling**: Visual design, colors, shapes, fonts, fills
- **layout**: Position, spacing, direction, grouping, alignment

## Rules
1. **Generalize**: Convert specific fixes (e.g., "moved node A right") into universal rules (e.g., "increase horizontal spacing between sibling nodes").
2. **Evidence-based**: Only extract strategies supported by actual iteration feedback. Do not invent rules.
3. **Deduplicate**: If multiple iterations point to the same insight, consolidate into one strategy.
4. **Actionable**: Each strategy must be a concrete instruction a code-generation model can follow.
5. **when_to_use**: Bind to the specific domain + diagram type context, not generic.

## Output
Return a single valid JSON object. Only include categories that have strategies:
{
  "parse": {
    "title": "short title",
    "description": "what this strategy covers",
    "when_to_use": "when to apply this",
    "content": "the concrete rules, one per line"
  },
  "styling": { ... },
  "layout": { ... }
}
"""

_STRATEGY_EXTRACTOR_TASK = """
## Context
Domain: {{domain}}
Diagram Type: {{diagram_type}}
User Instruction: {{text}}

## Iteration History (JSON)
{{iteration_history}}

Extract generalizable strategies from the above feedback. Return valid JSON only.
"""


class StrategyExtractorAgent(BaseAgent):

    def __init__(self, model: BaseChatModel, **kwargs):
        super().__init__(
            model,
            system_prompt=_STRATEGY_EXTRACTOR_SYSTEM,
            task_prompt=_STRATEGY_EXTRACTOR_TASK,
            **kwargs
        )

    def run(
        self,
        text_content: str,
        domain: str,
        diagram_type: str,
        iteration_history: str,
    ) -> Dict[str, Any]:
        input_dict = {
            "text": text_content,
            "domain": domain,
            "diagram_type": diagram_type,
            "iteration_history": iteration_history,
        }
        return self.invoke(input_dict)
