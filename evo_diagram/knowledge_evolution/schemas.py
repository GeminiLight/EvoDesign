import json
from typing import List, Dict, Any, Optional, Literal
from pydantic import BaseModel, Field, StrictFloat, StrictInt


# Key under ``IterationRecord.evaluation`` holding the objective score of a
# knowledge-free control generation of the same sample. Written by
# ``iteration.loop.RefineLoop`` when ``config.first_pass_control_run`` is on and
# read by ``engine.evaluate_knowledge_outcome``.
CONTROL_SCORE_KEY = "control_score_before"


def load_dataset(path: str) -> List["DatasetItem"]:
    """Load dataset from JSON file."""
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        items = data.get("dataset", data) if isinstance(data, dict) else data
        return [DatasetItem(**item) for item in items]

class TagSet(BaseModel):
    domain: List[str] = Field(default_factory=list)
    diagram_type: List[str] = Field(default_factory=list)
    agent: List[str] = Field(default_factory=list)

class KnowledgeEntry(BaseModel):
    id: str
    tags: TagSet
    title: str
    description: str
    content: str  # The actual rule content
    when_to_use: str

    # Tier: strategy (local) → guideline (cross-domain) → principle (cross-diagram-type)
    tier: Literal["strategy", "guideline", "principle"] = "strategy"
    polarity: Literal["positive", "neutral", "negative"] = "positive"  # positive enters active memory; neutral/negative are audit-only strategy records

    # Quality tracking
    delta_score: StrictFloat = 0.0     # Quality delta from verification
    confidence: StrictFloat = 0.0      # Aggregate confidence
    usage_count: StrictInt = 0         # Times retrieved
    success_count: StrictInt = 0       # Times used successfully
    support_count: StrictInt = 1       # Evidence count

    # Promotion tracking
    generalization_status: Literal[
        "local",
        "validated",
        "promoted",
        "demoted",
        "merged",
        "pruned",
        "retired",
    ] = "local"
    validated_domains: List[str] = Field(default_factory=list)  # Domains where verified
    validation_success_rate: StrictFloat = 0.0
    active: bool = True
    archive_reason: Optional[str] = None
    archived_at: Optional[str] = None

    # Provenance (guideline/principle only)
    evidence_ids: List[str] = Field(default_factory=list)  # Source strategy/guideline IDs

class EvaluationScore(BaseModel):
    structure: int = 0
    fidelity: int = 0
    aesthetics: int = 0

class Feedback(BaseModel):
    LLM_comments: List[str]
    human_comments: List[str] = Field(default_factory=list)

class DiagramRef(BaseModel):
    representation: str  # Path to JSON manifest
    manifest_ref: str    # Path to PNG image

class IterationRecord(BaseModel):
    id: str
    iteration: int
    tags: TagSet
    text_content: str
    user_query: str
    diagram: DiagramRef
    evaluation: Dict[str, Any]  # structure, fidelity, quality, etc.
    feedback: Feedback
    delta_score: float = 0.0

class DatasetItem(BaseModel):
    """Dataset item for the active knowledge-evolution dataset format."""

    id: str
    content: str
    content_area: str
    query: str
    diagram_type: str = "General"
    other_queries: List[Dict[str, Any]] = Field(default_factory=list)
    image_url: Optional[str] = None

class SynthesisResult(BaseModel):
    guideline: List[KnowledgeEntry] = Field(default_factory=list)
    principles: List[KnowledgeEntry] = Field(default_factory=list)
