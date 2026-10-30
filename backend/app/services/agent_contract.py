"""Public errors and request shapes for project-scoped Agent collaboration."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.exceptions import AppException


class AgentError(AppException):
    def __init__(self, code: str, message: str, status: int = 409, **extra: Any):
        super().__init__(message, status, public_detail=message)
        self.code, self.extra = code, extra


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class ProposalScope(StrictModel):
    kind: Literal['project', 'elements']
    element_ids: list[str] = Field(default_factory=list, max_length=500)


class ProposalRequest(StrictModel):
    protocol_version: Literal[1] = 1
    operation_id: str = Field(min_length=1, max_length=128)
    base_version: int = Field(ge=1)
    constraints_hash: str = Field(min_length=1, max_length=80)
    scope: ProposalScope
    context_version: int | None = None
    operations: list[dict[str, Any]] = Field(min_length=1, max_length=100)


class RestoreRequest(StrictModel):
    operation_id: str = Field(min_length=1, max_length=128)
    snapshot_id: str
    base_version: int = Field(ge=1)


class ConnectionRequest(StrictModel):
    name: str = Field(default='Agent CLI', min_length=1, max_length=100)


class ApprovalRequest(StrictModel):
    user_code: str
    project_id: str
    can_commit: bool = False


class ClaimRequest(StrictModel):
    device_secret: str = Field(min_length=20, max_length=200)


class ContextRequest(StrictModel):
    version: int = Field(ge=1)
    selected_ids: list[str] = Field(default_factory=list, max_length=500)
    locked_ids: list[str] = Field(default_factory=list, max_length=500)


def envelope(data: Any) -> dict[str, Any]:
    return {'ok': True, 'protocol_version': 1, 'data': data}
