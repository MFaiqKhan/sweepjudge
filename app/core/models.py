from __future__ import annotations

"""Core dataclasses that mirror (a subset of) Google A2A JSON schema.
These models are **internal** to the MVP and are used for both in-process
Redis messages and future HTTP adapters. Keeping them in one place ensures
validation is consistent across orchestrator and agents.
"""

from enum import Enum
from typing import Any, List, Literal, Optional, Union
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, validator


# ---------------------------------------------------------------------------
# Primitive Part types
# ---------------------------------------------------------------------------


class _BasePart(BaseModel):
    """Common base for all Part variants providing metadata hook."""

    metadata: Optional[dict[str, Any]] = None

    class Config:
        extra = "forbid"
        allow_mutation = False


class TextPart(_BasePart):
    type: Literal["text"] = "text"
    text: str


class FileContent(BaseModel):
    name: Optional[str] = None
    mime_type: Optional[str] = Field(None, alias="mimeType")

    # Either raw bytes (base64-encoded str) or URI must be supplied.
    bytes_b64: Optional[str] = Field(None, alias="bytes")
    uri: Optional[str] = None

    @validator("bytes_b64", always=True)
    def _one_of_bytes_or_uri(cls, v, values):
        if (v is None) == (values.get("uri") is None):
            raise ValueError("Either `bytes` or `uri` must be provided, but not both.")
        return v


class FilePart(_BasePart):
    type: Literal["file"] = "file"
    file: FileContent


class DataPart(_BasePart):
    type: Literal["data"] = "data"
    data: Any


Part = Union[TextPart, FilePart, DataPart]


# ---------------------------------------------------------------------------
# Artifact – container of Parts
# ---------------------------------------------------------------------------


class Artifact(BaseModel):
    name: str
    parts: List[Part]
    description: Optional[str] = None
    index: Optional[int] = None  # chunk ordering
    append: bool = False
    last_chunk: bool = Field(False, alias="lastChunk")
    metadata: Optional[dict[str, Any]] = None

    class Config:
        extra = "forbid"
        allow_mutation = False
        allow_population_by_field_name = True


# ---------------------------------------------------------------------------
# Message
# ---------------------------------------------------------------------------


class Role(str, Enum):
    user = "user"
    agent = "agent"


class Message(BaseModel):
    role: Role
    parts: List[Part]
    metadata: Optional[dict[str, Any]] = None

    class Config:
        extra = "forbid"
        allow_mutation = False


# ---------------------------------------------------------------------------
# Task wrapper (our primary envelope)
# ---------------------------------------------------------------------------


class TaskStatus(str, Enum):
    submitted = "submitted"
    working = "working"
    input_required = "input-required"
    completed = "completed"
    canceled = "canceled"
    failed = "failed"


class Task(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    task_type: str = Field(..., alias="task_type")
    payload: dict[str, Any]
    session_id: Optional[str] = Field(None, alias="session_id")
    status: TaskStatus = TaskStatus.submitted
    artifacts: List[Artifact] = []
    karma_delta: Optional[int] = None
    metadata: Optional[dict[str, Any]] = None

    class Config:
        extra = "forbid"
        allow_population_by_field_name = True 