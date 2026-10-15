"""Shared value types. Provider-neutral: nothing here imports a provider SDK."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

# Behaviour classes the pipeline may return (used by the evaluation set).
ANSWER = "answer-with-citation"
REFUSE = "refuse"
ESCALATE = "escalate-to-human"
RECOVERY = "point-to-recovery-flow"
STATUS_UNKNOWN = "say-status-unknown"
BEHAVIOURS = (ANSWER, REFUSE, ESCALATE, RECOVERY, STATUS_UNKNOWN)

ORIGINS = ("system", "user", "retrieved", "assistant", "tool")


@dataclass(frozen=True)
class Principal:
    """Who is asking, as established at the Authentik edge and passed out-of-band.

    Built by the caller from verified headers. The pipeline never builds or modifies one from text.
    """
    subject: str
    groups: frozenset = frozenset()
    authenticated: bool = True

    def __post_init__(self):
        object.__setattr__(self, "groups", frozenset(self.groups))

    @classmethod
    def anonymous(cls) -> "Principal":
        return cls(subject="anonymous", groups=frozenset(), authenticated=False)


@dataclass(frozen=True)
class Message:
    role: str                       # "user" | "assistant" | "tool"
    content: str
    origin: str = "user"            # where the text came from; drives egress handling
    data_class: str = "member-personal"
    tool_call_id: str | None = None  # set on role == "tool" results

    def __post_init__(self):
        if self.origin not in ORIGINS:
            raise ValueError(f"bad origin {self.origin!r}")


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CompletionRequest:
    system: str
    messages: tuple
    max_output_tokens: int
    tools: tuple = ()
    model_label: str = "default"     # opaque key into the configured price table; not a real model id
    timeout_s: float = 20.0


@dataclass(frozen=True)
class CompletionResponse:
    text: str
    tool_calls: tuple = ()
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str = "end"


@dataclass(frozen=True)
class Passage:
    doc_id: str
    title: str
    text: str
    score: float
    data_class: str
    index: int = 0


@dataclass(frozen=True)
class PipelineResult:
    behavior: str
    text: str
    citations: tuple = ()
    confidence: float = 0.0
    retrieved_ids: tuple = ()
    quarantined_ids: tuple = ()
    reasons: tuple = ()              # guard / policy reasons (kinds only, never content)
    tool_calls_denied: tuple = ()
    provider_called: bool = False
    input_tokens: int = 0
    output_tokens: int = 0
