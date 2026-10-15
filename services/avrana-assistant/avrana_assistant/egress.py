"""Egress filter: applied to every request before any provider call.

Enforces the data-classification table in docs/assistant/DATA-CLASSIFICATION.md:
  - the member's own text (origin "user") is redacted for secret-shaped, operator-internal and e-mail strings;
  - system text and retrieved passages must be public-help or member-general and must carry no deny-list
    marker, otherwise the whole request is blocked;
  - member-personal, operator-internal and secret classes never leave, except the member's own question
    after redaction.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from .denylist import find_internal_markers, redact
from .datatypes import CompletionRequest, Message

# class -> may be sent to an external provider (as non-user content)
EGRESS_POLICY = {
    "public-help": True,
    "member-general": True,
    "member-personal": False,
    "operator-internal": False,
    "secret": False,
}


class EgressBlocked(Exception):
    def __init__(self, reasons: list[str]):
        super().__init__("egress blocked")
        self.reasons = reasons


@dataclass(frozen=True)
class EgressReport:
    redactions: tuple = ()   # kinds only


def prepare(request: CompletionRequest) -> tuple[CompletionRequest, EgressReport]:
    reasons: list[str] = []
    kinds: list[str] = []
    for f in find_internal_markers(request.system):
        reasons.append(f"system:{f.kind}")
    out: list[Message] = []
    for m in request.messages:
        if m.origin == "user":
            clean, findings = redact(m.content)
            kinds.extend(f.kind for f in findings)
            out.append(replace(m, content=clean))
            continue
        if not EGRESS_POLICY.get(m.data_class, False):
            reasons.append(f"class:{m.data_class}")
            continue
        for f in find_internal_markers(m.content):
            reasons.append(f"{m.origin}:{f.kind}")
        out.append(m)
    if reasons:
        raise EgressBlocked(reasons)
    return replace(request, messages=tuple(out)), EgressReport(tuple(sorted(set(kinds))))
