"""Structure agent — Stage 1 of the EvoDiagram pipeline.

Uses the shared ``EVODIAGRAM_SKILL_SYSTEM_PROMPT`` as its system message and
the minimal ``STRUCTURE_TASK_PROMPT`` as its task message. After a successful
run it stores a conversation thread on the workflow state so downstream agents
can inherit the Structure task and output without serialising prompt blocks.

Self-consistency (optional)
---------------------------
When the env var ``STRUCTURE_SELF_CONSISTENCY_N`` is set to an integer >= 2,
this agent draws that many independent samples concurrently and majority-votes
on the ``chart_type`` field via ``common.self_consistency.sample_and_vote``.
Non-voted fields come from a single winning sample so ids/coords stay
internally consistent. When the env var is unset or <= 1, behaviour is
identical to single-shot (the default).
"""

import logging
from typing import Any, List, Optional

from langchain_core.language_models import BaseChatModel

from evo_diagram.agentic_system.common.skill_loader import EVODIAGRAM_SKILL_SYSTEM_PROMPT
from evo_diagram.agentic_system.common.spec_utils import (
    build_assistant_content,
    parse_stage_output,
)
from evo_diagram.agentic_system.generation_stage.structure.prompts import STRUCTURE_TASK_PROMPT
from evo_diagram.agentic_system.generation_stage.structure.schemas import (
    StructureValidationError,
    validate_structure_instantiation,
)
from evo_diagram.agentic_system.generation_stage.structure.state import WorkflowState
from evo_diagram.core.base_agent import BaseAgent, _render_template

logger = logging.getLogger(__name__)

from evo_diagram.config.settings import AppSettings


def _unwrap_and_validate_structure_sample(raw_output: Any) -> tuple[Optional[dict[str, Any]], dict[str, Any]]:
    """Unwrap and canonicalize one Structure sample before self-consistency voting."""
    parsed = parse_stage_output(
        raw_output,
        stage_name="StructureAgent",
        require_instantiation_dict=True,
    )
    return parsed.specification, validate_structure_instantiation(parsed.instantiation)


class StructureAgent(BaseAgent):
    """Generate the semantic topology directly from text.

    Input: text_content, user_query, design_expertise, runtime_directives.
    Output: structure_specification (Phase-1 diagnosis) + structure_instantiation (concrete graph).
    """

    def __init__(
        self,
        model: BaseChatModel,
        tools: Optional[List[Any]] = None,
        **kwargs: Any,
    ) -> None:
        kwargs.setdefault("strict_json_output", True)
        super().__init__(
            model=model,
            tools=tools,
            system_prompt=EVODIAGRAM_SKILL_SYSTEM_PROMPT,
            task_prompt=STRUCTURE_TASK_PROMPT,
            **kwargs,
        )

    def _read_self_consistency_n(self) -> int:
        """Read self-consistency sample count from settings; default 1 (single-shot)."""
        return AppSettings.get_default().structure_self_consistency_n

    def run(self, state: WorkflowState) -> WorkflowState:
        input_dict = {
            "text_content": state.text_content or "",
            "user_query": state.user_query or "",
            "content_area": state.content_area or "N/A",
            "stage_knowledge": state.stage_knowledge or "N/A",
            "design_expertise": state.design_expertise or "N/A",
            "runtime_directives": state.runtime_directives or "N/A",
        }

        # Render task prompt
        rendered_task = _render_template(STRUCTURE_TASK_PROMPT, input_dict)

        # Build conversation: system + user task
        # Use type-specific system prompt when diagram_type is available
        system_prompt = self._system_prompt
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": rendered_task},
        ]

        n_samples = self._read_self_consistency_n()
        if n_samples >= 2:
            from evo_diagram.agentic_system.common.self_consistency import sample_and_vote

            logger.info(
                f"[StructureAgent] Invoking LLM (self-consistency N={n_samples}, "
                f"vote_key='chart_type')..."
            )

            def _invoke_sc(_input_dict):
                return self.invoke_with_history(messages)

            specification, instantiation = sample_and_vote(
                _invoke_sc,
                input_dict,
                n_samples=n_samples,
                vote_key="chart_type",
                unwrap_fn=_unwrap_and_validate_structure_sample,
            )
        else:
            logger.info("[StructureAgent] Invoking LLM...")
            raw_output = self.invoke_with_history(messages)
            parsed = parse_stage_output(
                raw_output,
                stage_name="StructureAgent",
                require_instantiation_dict=True,
            )
            specification = parsed.specification
            instantiation = parsed.instantiation

        try:
            instantiation = validate_structure_instantiation(instantiation)
        except StructureValidationError as exc:
            state.add_error(str(exc))
            raise

        if specification:
            state.update_stage("structure_specification", specification)
        state.update_stage("structure_instantiation", instantiation)

        # Save conversation history for downstream agents
        assistant_content = build_assistant_content(
            "Structure Design Specification",
            specification,
            instantiation,
        )
        messages.append({"role": "assistant", "content": assistant_content})
        state.conversation_history = messages

        return state
