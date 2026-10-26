"""Base workflow state class with shared fields and validation logic."""

from logging import getLogger
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator

from evo_diagram.canvas_runtime import normalize_canvas_library

logger = getLogger(__name__)


class WorkflowStateBase(BaseModel):
    """Base class for all workflow state classes.

    Common fields shared across all workflows:
    - current_stage: Current workflow stage
    - canvas_library: Canvas library selection (validated)
    - text_content: Original input text
    - user_query: User query for guidance
    - design_expertise: Cross-session knowledge retrieved from ChromaDB
      (design memory, user preferences). Reference-quality, not authoritative.
    - runtime_directives: Per-request override context the caller injects
      with HIGHEST priority. Two callers populate it today: (1) the backend's
      incremental-edit path passes a JSON snapshot of locked node ids + the
      current canvas schema; (2) the refiner passes prior-iteration feedback
      for retries. Distinct from ``design_expertise`` — that is reference
      knowledge, this is must-honour directives for THIS request.
    - conversation_history: Multi-turn message thread used by the generation
      pipeline so downstream agents inherit upstream tasks and outputs without
      serialising nested prompt blocks.
    - content_area: Optional domain / subject-area hint from the dataset or API
      request. It is prompt context, not a schema field emitted by the stages.
    """

    # Stage tracking
    current_stage: str = "init"

    # Canvas library selection (validated)
    canvas_library: str = Field(
        default="excalidraw",
        description="The canvas library for which the workflow is being executed: 'tldraw' or 'excalidraw'."
    )

    # Input fields
    text_content: str = ""
    user_query: Optional[str] = None

    # Knowledge/context fields
    stage_knowledge: str = ""  # System-built per-type knowledge from system_prompt/type_patterns/*.md
    design_expertise: str = ""  # External knowledge (ChromaDB, user preferences)
    runtime_directives: str = ""
    diagram_type: Optional[str] = None  # Current diagram type for dynamic system prompt
    content_area: Optional[str] = None

    # Conversation thread for multi-turn pipeline mode.
    # List of dicts: [{"role": "system", "content": ...}, {"role": "user", "content": ...},
    #                  {"role": "assistant", "content": ...}, ...]
    conversation_history: List[Dict[str, str]] = Field(default_factory=list)

    @field_validator('canvas_library', mode='before')
    @classmethod
    def validate_canvas_library(cls, v: str) -> str:
        """Validate and normalize canvas_library value."""
        return normalize_canvas_library(v)

    def update_stage(self, stage: str, data: Any = None) -> None:
        """Update workflow stage and assign data to the matching field.

        If ``stage`` matches a field name on this model, ``data`` is assigned
        to that field.  Subclasses can still override for custom logic, but
        the common case (set current_stage + assign to field) works out of
        the box.
        """
        self.current_stage = stage
        if stage in type(self).model_fields:
            setattr(self, stage, data)
