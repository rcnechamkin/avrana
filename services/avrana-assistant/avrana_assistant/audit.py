"""Audit log without content. Only allow-listed, non-content fields can be recorded."""
from __future__ import annotations

import hashlib

ALLOWED_FIELDS = frozenset({
    "behavior", "reasons", "doc_ids", "input_tokens", "output_tokens", "provider_called",
    "tool_name", "decision", "budget_reason", "egress_kinds", "quarantined_ids",
})


class AuditLog:
    def __init__(self, salt: bytes = b"a0-test-salt"):
        self._salt = salt
        self.records: list[dict] = []

    def subject_hash(self, subject: str) -> str:
        return hashlib.sha256(self._salt + subject.encode("utf-8")).hexdigest()[:12]

    def record(self, event: str, subject: str, **fields) -> None:
        bad = set(fields) - ALLOWED_FIELDS
        if bad:
            raise ValueError(f"fields not allowed in audit records: {sorted(bad)}")
        for v in fields.values():
            if isinstance(v, str) and len(v) > 80:
                raise ValueError("audit values must be short identifiers, not content")
        self.records.append({"event": event, "subject": self.subject_hash(subject), **fields})
