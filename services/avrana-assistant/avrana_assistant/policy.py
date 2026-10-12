"""Pre-model input policy: deterministic routing for requests the model must not decide.

These rules run before retrieval and before any provider call. Because they are lexical they are
incomplete by nature; the output validator and the tool gateway are the second and third layers.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .denylist import find_internal_markers
from .guards import detect_injection
from .datatypes import ANSWER, ESCALATE, RECOVERY, REFUSE, STATUS_UNKNOWN

MAX_QUESTION_CHARS = 1200


@dataclass(frozen=True)
class Decision:
    behavior: str | None      # None: continue to retrieval
    reason: str = ""
    doc_id: str = ""          # corpus document that supplies the member-facing text


_I = re.I
_OTHER_MEMBER = re.compile(
    r"\b(?:another|other|someone else'?s?|somebody else'?s?|his|her|their)\s+(?:member|user|account|password|watch|history|viewing|library|email|e-mail)"
    r"|\bwhat\s+(?:is|are|was|were)\s+\w+\s+(?:watching|listening|reading|requesting)\b"
    r"|\b(?:list|show|give me|tell me)\b[^.\n]{0,25}\b(?:all\s+)?(?:members|users|accounts|usernames)\b"
    r"|\bwho\s+(?:else\s+)?(?:has|have)\s+access\b|\bwho\s+(?:is|are)\s+(?:watching|using|signed in)\b"
    r"|\b(?:watch|viewing|playback|listening|reading)\s+history\s+of\b|\bdoes\s+\w+\s+have\s+(?:access|the)\b", _I)
_ADMIN_CLAIM = re.compile(
    r"\bi\s*(?:am|'m)\s+(?:the\s+|an?\s+|your\s+)?(?:admin|administrator|owner|operator|developer|root|staff|cody)\b"
    r"|\bas\s+(?:the\s+|an?\s+)?(?:admin|administrator|owner)\b|\b(?:admin|administrator|owner)\s+(?:here|speaking|override|mode)\b"
    r"|\bthis\s+is\s+(?:the\s+)?(?:admin|owner|administrator|cody)\b|\bmaintenance\s+mode\b|\bauthori[sz]ed\s+by\b", _I)
_OPERATOR = re.compile(
    r"\b(?:docker|container|server\s+ip|ip\s+address|ssh|sudo|root\s+access|admin\s+panel|admin\s+page|ops\s+(?:page|site|dashboard)|"
    r"api\s+keys?|environment\s+variables?|\.env|config(?:uration)?\s+files?|database|backups?|firewall|tunnel|cloudflare|"
    r"which\s+(?:host|server|machine)|what\s+(?:host|server|machine)|port\s+number|open\s+ports?|credentials?|secrets?|"
    r"client\s+secret|oidc|ldap|internal\s+(?:hostname|network|docs?|documentation)|runbook|logs?\s+of\s+the|server\s+logs?)\b", _I)
_DIRECT_PASSWORD = re.compile(
    r"\b(?:reset|change|set|update|send)\b[^.\n]{0,25}\bpassword\b|\bpassword\b[^.\n]{0,25}\b(?:reset|changed|for me)\b|"
    r"\bforgot(?:ten)?\b[^.\n]{0,25}\b(?:password|login|username)\b|\blocked\s+out\b|\bcan'?t\s+(?:log|sign)\s*in\b"
    r"|\bpassword\b[^.\n]{0,30}\b(?:not\s+working|doesn'?t\s+work|wrong|rejected)\b|\b(?:lost|forgot)\s+my\s+login\b", _I)
_GRANT = re.compile(
    r"\b(?:give|grant|add|enable|unlock|upgrade|activate)\b[^.\n]{0,30}\b(?:me|my\s+account|access|permission|group)\b"
    r"|\bmake\s+me\s+(?:an?\s+)?(?:admin|member|contributor)\b|\bput\s+me\s+in\b|\bmove\s+me\s+to\b", _I)
_STATUS = re.compile(
    r"\b(?:is|are)\s+(?:the\s+)?[\w.\- ]{0,30}?\b(?:down|up|offline|online|broken|working|running|available)\b"
    r"|\b(?:outage|status\s+page|any\s+(?:issues|problems)|service\s+status|maintenance)\b"
    r"|\bnot\s+(?:loading|connecting|responding)\s+(?:right\s+now|today)\b|\bright\s+now\b[^.\n]{0,40}\b(?:down|working|up)\b", _I)
_MISSING_LIBRARY = re.compile(
    r"\b(?:can'?t|cannot|can\s+not|don'?t|do\s+not|doesn'?t|not\s+able\s+to|unable\s+to)\s+(?:i\s+)?(?:see|find|view|get\s+to|open)\b[^.\n]{0,40}\b(?:librar(?:y|ies)|section|tile|service|collection)\b"
    r"|\b(?:librar(?:y|ies)|section|tile|service)\b[^.\n]{0,30}\b(?:missing|not\s+(?:showing|there|visible|listed)|isn'?t\s+(?:there|showing|visible))\b"
    r"|\b(?:no|without)\s+access\s+to\b|\bwhy\s+(?:don'?t|can'?t|do\s+i\s+not)\s+i\s+have\b", _I)
_CONTACT = re.compile(
    r"\b(?:contact|reach|email|e-mail|message|talk\s+to|speak\s+(?:to|with)|ask)\b[^.\n]{0,30}\b(?:support|admin|administrator|human|person|someone|owner|help\s*desk|you)\b"
    r"|\bsupport\s+(?:email|address|number|ticket|form)\b|\bhuman\b|\bopen\s+a\s+ticket\b|\bfile\s+a\s+(?:ticket|complaint)\b|\bwho\s+do\s+i\s+(?:ask|contact|talk)\b", _I)


def classify(question: str) -> Decision:
    q = question.strip()
    if not q:
        return Decision(REFUSE, "empty_input")
    if len(q) > MAX_QUESTION_CHARS:
        return Decision(REFUSE, "input_too_long")
    if detect_injection(q):
        return Decision(REFUSE, "prompt_injection")
    if _ADMIN_CLAIM.search(q):
        return Decision(REFUSE, "identity_claim_in_text")
    if _OTHER_MEMBER.search(q):
        return Decision(REFUSE, "other_member_data")
    if _OPERATOR.search(q) or find_internal_markers(q):
        return Decision(REFUSE, "operator_internal_request")
    if _DIRECT_PASSWORD.search(q):
        return Decision(RECOVERY, "password", "password-reset")
    if _GRANT.search(q):
        return Decision(ESCALATE, "access_change_request", "contact-support")
    if _MISSING_LIBRARY.search(q):
        return Decision(ANSWER, "missing_library", "missing-library")
    if _STATUS.search(q):
        return Decision(STATUS_UNKNOWN, "status_request", "service-down")
    if _CONTACT.search(q):
        return Decision(ESCALATE, "contact_request", "contact-support")
    return Decision(None)
