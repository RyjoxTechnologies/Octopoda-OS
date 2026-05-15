"""
Synrix Cloud API - Pydantic Models
====================================
Request and response models for the FastAPI cloud API.
"""

import json
from pydantic import BaseModel, Field, field_validator
from typing import Optional, Any, List, Dict


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class RegisterAgentRequest(BaseModel):
    agent_id: str = Field(..., min_length=1, max_length=128)
    agent_type: str = Field(default="generic", max_length=64)
    metadata: Optional[Dict[str, Any]] = None


class RememberRequest(BaseModel):
    key: str = Field(..., min_length=1, max_length=512)
    value: Any
    tags: Optional[List[str]] = Field(default=None, max_length=50)

    @field_validator("key")
    @classmethod
    def key_not_blank(cls, v):
        if not v.strip():
            raise ValueError("key must not be blank")
        return v

    @field_validator("value")
    @classmethod
    def value_size_limit(cls, v):
        serialized = json.dumps(v, default=str)
        if len(serialized.encode("utf-8")) > 1_048_576:
            raise ValueError("value must not exceed 1 MB when serialized")
        return v


class BatchRememberRequest(BaseModel):
    items: List[RememberRequest] = Field(..., min_length=1, max_length=1000)


class SnapshotRequest(BaseModel):
    label: Optional[str] = Field(default=None, max_length=128)


class RestoreRequest(BaseModel):
    label: Optional[str] = Field(default=None, max_length=128)


class SharedWriteRequest(BaseModel):
    key: str = Field(..., min_length=1, max_length=512)
    value: Any
    # Default to "shared" so direct REST users can POST without specifying
    # an author. SDK clients that track per-agent attribution still pass
    # an explicit value; the field is preserved for that case.
    author_agent_id: str = Field(default="shared", min_length=1, max_length=128)

    @field_validator("value")
    @classmethod
    def value_size_limit(cls, v):
        serialized = json.dumps(v, default=str)
        if len(serialized.encode("utf-8")) > 1_048_576:
            raise ValueError("value must not exceed 1 MB when serialized")
        return v


class TaskCreateRequest(BaseModel):
    task_id: str = Field(..., min_length=1, max_length=128)
    from_agent: str = Field(..., min_length=1, max_length=128)
    to_agent: str = Field(..., min_length=1, max_length=128)
    payload: Dict[str, Any]


class TaskActionRequest(BaseModel):
    agent_id: str = Field(..., min_length=1, max_length=128)
    result: Optional[Dict[str, Any]] = None


class DecisionLogRequest(BaseModel):
    decision: str = Field(..., min_length=1, max_length=2048)
    reasoning: str = Field(..., min_length=1, max_length=4096)
    context: Optional[Dict[str, Any]] = None


class RawWriteRequest(BaseModel):
    key: str = Field(..., min_length=1, max_length=512)
    value: Any
    metadata: Optional[Dict[str, Any]] = None

    @field_validator("value")
    @classmethod
    def value_size_limit(cls, v):
        serialized = json.dumps(v, default=str)
        if len(serialized.encode("utf-8")) > 1_048_576:
            raise ValueError("value must not exceed 1 MB when serialized")
        return v


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    status: str
    version: str
    backend: str
    uptime_seconds: float


class MemoryResponse(BaseModel):
    node_id: Optional[int] = None
    key: str
    latency_us: float
    timestamp: float
    success: bool = True
    loop_warning: Optional[dict] = None
    warning: Optional[str] = None


class RecallResponse(BaseModel):
    value: Any = None
    key: str
    latency_us: float
    found: bool


class SearchResponse(BaseModel):
    items: List[Dict[str, Any]]
    count: int
    latency_us: float


class SnapshotResponse(BaseModel):
    label: str
    keys_captured: int
    latency_us: float


class RestoreResponse(BaseModel):
    label: str
    keys_restored: int
    recovery_time_us: float


class AgentResponse(BaseModel):
    agent_id: str
    agent_type: str = "generic"
    status: str = "running"
    metrics: Optional[Dict[str, Any]] = None


class BatchMemoryResponse(BaseModel):
    agent_id: str
    results: List[Dict[str, Any]]
    count: int


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None


# ---------------------------------------------------------------------------
# Conversation processing models
# ---------------------------------------------------------------------------

class ProcessConversationRequest(BaseModel):
    messages: List[Dict[str, str]] = Field(..., min_length=1, max_length=100,
        description="List of {role, content} message dicts")
    extract_preferences: bool = Field(default=True,
        description="Extract user preferences from the conversation")
    extract_facts: bool = Field(default=True,
        description="Extract factual statements from the conversation")
    extract_decisions: bool = Field(default=True,
        description="Extract decisions and action items")
    namespace: str = Field(default="conversations",
        description="Key namespace prefix for stored memories")


class GetContextRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2048,
        description="The current user message or topic to find context for")
    limit: int = Field(default=10, ge=1, le=50,
        description="Max memories to return")
    format: str = Field(default="text",
        description="'text' for a formatted string, 'raw' for list of dicts")
