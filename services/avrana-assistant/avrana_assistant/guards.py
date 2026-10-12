"""Content guards: injection detection on text going in, validation of model output coming out.

All checks are deterministic and lexical. They are a safety net around an untrusted model, not a
proof of correctness; the grounding check in particular is a weak heuristic.
"""
from __future__ import annotations

import re

from .denylist import find_internal_markers
from .textutil import tokens
from .datatypes import CompletionResponse

_INJECTION = [
    ("override_instructions", re.compile(r"\b(?:ignore|disregard|forget|override|bypass)\b[^.\n]{0,40}\b(?:instructions?|rules?|prompts?|guidelines?|polic(?:y|ies)|restrictions?)\b", re.I)),
    ("reveal_prompt", re.compile(r"\b(?:reveal|show|print|repeat|display|output|leak|tell me)\b[^.\n]{0,30}\b(?:system|hidden|initial|original|your)\s+(?:prompt|instructions?|rules)\b", re.I)),
    ("system_prompt_mention", re.compile(r"\bsystem\s+prompt\b", re.I)),
    ("role_marker", re.compile(r"(?im)^\s*(?:system|assistant|developer|admin(?:istrator)?)\s*:")),
    ("role_reassignment", re.compile(r"\byou\s+are\s+now\b|\bact\s+as\b|\bpretend\s+(?:to\s+be|you\s+are)\b|\bfrom\s+now\s+on\b", re.I)),
    ("jailbreak_phrase", re.compile(r"\bjailbreak\b|\bdeveloper\s+mode\b|\bdo\s+anything\s+now\b|\bDAN\b")),
    ("note_to_model", re.compile(r"\b(?:note|message|instruction)s?\s+(?:to|for)\s+(?:the\s+)?(?:ai|assistant|model|llm|bot)\b", re.I)),
    ("directive_to_assistant", re.compile(r"\b(?:assistant|ai|chatbot)\b[^.\n]{0,20}\b(?:must|should|always|never)\b", re.I)),
    ("markup_injection", re.compile(r"</?\s*(?:system|assistant|instructions?|passage|untrusted[a-z_]*|tool)\b", re.I)),
    ("tell_user_directive", re.compile(r"\b(?:tell|inform|instruct)\s+(?:the\s+)?(?:user|member|them)s?\s+(?:that|to)\b", re.I)),
]


def detect_injection(text: str) -> list[str]:
    """Names of injection shapes found in `text` (kinds only)."""
    return [name for name, pat in _INJECTION if pat.search(text)]


_CITE = re.compile(r"\[doc:([a-z0-9][a-z0-9-]*)\]")
_NEGATION = re.compile(r"\b(?:cannot|can't|can not|won't|will not|do not|don't|never|not|unable|no)\b", re.I)
_STATUS = re.compile(
    r"\b(?:is|are|was|were|has been|have been)\s+(?:(?:currently|now|still|fully|always|really|just|completely|\w+ly)\s+)?"
    r"(?:up|down|online|offline|working|operational|running|unavailable|fixed|restored|healthy)\b"
    r"|\ball systems (?:are )?(?:operational|normal|up)\b|\bno (?:known )?(?:issues|outages|incidents)\b"
    r"|\b(?:outage|maintenance window)\b", re.I)
_ACTION_CLAIM = re.compile(
    r"\b(?:i|we)(?:'ve| have)?\s+(?:just\s+|already\s+)?(?:reset|created|sent|granted|added|enabled|opened|notified|emailed|restarted|updated|changed|unlocked|escalated|filed)\b"
    r"|\b(?:i|we)(?:'ll| will)\s+(?:reset|create|send|grant|add|enable|notify|email|restart|file|open)\b", re.I)
_ASK_SECRET = re.compile(
    r"\b(?:send|tell|give|share|type|enter|paste|provide|confirm|reply with|text)\b[^.\n]{0,20}\b(?:password|passcode|token|api key|secret|recovery (?:link|code))\b", re.I)


def citations(text: str) -> list[str]:
    return _CITE.findall(text)


def _sentences(text: str) -> list[str]:
    text = _CITE.sub("", text)
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


def validate_output(response: CompletionResponse, allowed_ids: set[str], passage_text: str,
                    *, min_grounding: float = 0.6) -> list[str]:
    """Return guard reasons (kinds only). An empty list means the output may be shown."""
    reasons: list[str] = []
    if response.tool_calls:
        reasons.append("tool_call_in_a0")
    text = response.text or ""
    if not text.strip():
        reasons.append("empty_output")
    for f in find_internal_markers(text):
        reasons.append(f"operator_or_secret:{f.kind}")
    cites = citations(text)
    if not cites:
        reasons.append("no_citation")
    elif any(c not in allowed_ids for c in cites):
        reasons.append("citation_not_in_retrieved_set")
    if detect_injection(text):
        reasons.append("injection_shape_in_output")
    ground = set(tokens(passage_text))
    for sent in _sentences(text):
        # A negation counts only if it comes BEFORE the claim ("I cannot tell you it is up"), not after.
        for m in _STATUS.finditer(sent):
            if not _NEGATION.search(sent[:m.start()]):
                reasons.append("status_claim")
                break
        for m in _ACTION_CLAIM.finditer(sent):
            if not re.search(r"\b(?:cannot|can't|unable|not)\b", sent[:m.start()], re.I):
                reasons.append("invented_action")
                break
        for m in _ASK_SECRET.finditer(sent):
            if not _NEGATION.search(sent[:m.start()]):
                reasons.append("solicits_secret")
                break
        terms = tokens(sent)
        if len(terms) >= 4:
            hit = sum(1 for t in terms if t in ground) / len(terms)
            if hit < min_grounding:
                reasons.append("ungrounded_sentence")
    # de-duplicate, keep order
    seen, out = set(), []
    for r in reasons:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out
