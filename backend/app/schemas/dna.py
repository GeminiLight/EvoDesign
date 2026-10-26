from pydantic import BaseModel, ConfigDict, Field


class DnaRuleSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str
    cabin_id: str
    title: str
    preview: str
    source: str
    enabled: bool
    pinned: bool
    usage_count: int
    updated_at: str  # ISO 8601 string


class DnaRulesPayload(BaseModel):
    """Full rule library - used for both GET response and PUT request body."""

    model_config = ConfigDict(extra="forbid")

    structure: list[DnaRuleSchema] = Field(default_factory=list)
    style: list[DnaRuleSchema] = Field(default_factory=list)
    layout: list[DnaRuleSchema] = Field(default_factory=list)
    project_id: str | None = None


class DnaCandidateOut(BaseModel):
    temp_id: int
    cabin_id: str
    title: str
    preview: str


class DnaAnalyzeResponse(BaseModel):
    candidates: list[DnaCandidateOut]
