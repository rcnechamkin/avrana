"""Reusable deny-list for operator-internal and secret-shaped content (stdlib only).

Used by the corpus test (nothing operator-internal may be in the member corpus), the egress filter
(nothing operator-internal or secret leaves the host) and the output validator (the model may not emit
it). The patterns are deliberately conservative and will produce false positives; a false positive costs a
re-wording, a false negative costs a disclosure. This complements, and does not replace, human review.

Findings carry the kind and offsets only, never the matched text, so a finding can be logged safely.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Hostnames members are meant to use. Source: services/avrana-portal/portal.py (SERVICES, AUTH_HOST) and
# docs/onboarding/welcome.md. Any other avrana.net host is treated as operator-facing.
MEMBER_HOSTS = frozenset({
    "avrana.net", "auth.avrana.net", "watch.avrana.net", "listen.avrana.net", "read.avrana.net",
    "books.avrana.net", "kindle.avrana.net", "request.avrana.net", "requestabook.avrana.net",
    "requestacomic.avrana.net", "contribute.avrana.net",
})

_INTERNAL_WORDS = (
    "docker", "dockerd", "compose", "container", "containers", "cloudflared", "olivetin", "beszel",
    "tracearr", "recyclarr", "prowlarr", "radarr", "sonarr", "sabnzbd", "mylar", "mylar3", "libation",
    "postgres", "postgresql", "redis", "sqlite", "nginx", "traefik", "systemd", "crontab", "sudo",
    "ssh", "ufw", "lvm", "akadmin", "authentik-worker", "authentik_worker", "authentik-server",
    "authentik_server", "authentik-ldap", "authentik_ldap", "blueprints", "outpost", "kubectl",
    "docker-compose", "bookstack",
)

_PATTERNS: tuple[tuple[str, "re.Pattern[str]"], ...] = (
    ("ip_address", re.compile(r"(?<![\w.])\d{1,3}(?:\.\d{1,3}){3}(?![\w.]*\d)")),
    ("localhost", re.compile(r"\blocalhost\b", re.I)),
    ("port", re.compile(r"(?<=[A-Za-z0-9\])]):\d{3,5}\b|\bports?\s+\d{2,5}\b", re.I)),
    ("filesystem_path", re.compile(r"(?<![\w.])(?:/(?:home|mnt|etc|var|opt|usr|srv|root|proc|dev|tmp)/|~/)")),
    ("internal_name", re.compile(r"(?<![\w-])(?:%s)(?![\w-])" % "|".join(re.escape(w) for w in _INTERNAL_WORDS), re.I)),
    ("identity_header", re.compile(r"\bx-authentik-[a-z-]+", re.I)),
    ("env_var_name", re.compile(r"\b[A-Z][A-Z0-9]*_(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|API)[A-Z0-9_]*\b")),
    ("env_file", re.compile(r"(?<![\w])\.env\b")),
    ("private_key", re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----")),
    ("jwt_shape", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    ("provider_key_shape", re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_-]{20,}\b|\bgh[pousr]_[A-Za-z0-9]{20,}\b|\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("long_hex", re.compile(r"\b[0-9a-fA-F]{32,}\b")),
    ("long_token", re.compile(r"(?<![\w/.:-])[A-Za-z0-9+_-]{40,}={0,2}(?![\w/.:-])")),
    ("credential_assignment", re.compile(r"(?i)\b(?:password|passwd|pwd|api[_ -]?key|secret|token)\s*[:=]\s*(?=\S*[\d!@#$%^&*_])\S{6,}")),
    ("credential_in_url", re.compile(r"https?://[^\s/]+:[^\s/@]+@")),
    ("email_address", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")),
)

_HOST = re.compile(r"(?<![\w.-])((?:[a-z0-9-]+\.)+avrana\.net)\b", re.I)
_ADMIN_GROUP = re.compile(r"authentik\s+admins", re.I)


@dataclass(frozen=True)
class Finding:
    kind: str
    start: int
    end: int


def find_internal_markers(text: str) -> list[Finding]:
    """Return findings for operator-internal or secret-shaped content in `text`."""
    out: list[Finding] = []
    for kind, pat in _PATTERNS:
        for m in pat.finditer(text):
            out.append(Finding(kind, m.start(), m.end()))
    for m in _HOST.finditer(text):
        if m.group(1).lower() not in MEMBER_HOSTS:
            out.append(Finding("admin_hostname", m.start(1), m.end(1)))
    for m in _ADMIN_GROUP.finditer(text):
        out.append(Finding("admin_group", m.start(), m.end()))
    return sorted(out, key=lambda f: (f.start, f.kind))


def has_internal_markers(text: str) -> bool:
    return bool(find_internal_markers(text))


def redact(text: str, replacement: str = "[REDACTED:{kind}]") -> tuple[str, list[Finding]]:
    """Replace every finding with a placeholder naming the kind only. Overlaps are merged."""
    findings = find_internal_markers(text)
    if not findings:
        return text, []
    spans: list[list] = []
    for f in findings:
        if spans and f.start <= spans[-1][1]:
            spans[-1][1] = max(spans[-1][1], f.end)
        else:
            spans.append([f.start, f.end, f.kind])
    out, pos = [], 0
    for s, e, kind in spans:
        out.append(text[pos:s])
        out.append(replacement.format(kind=kind))
        pos = e
    out.append(text[pos:])
    return "".join(out), findings
