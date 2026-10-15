"""Provider-neutral model interface and a deterministic fake provider.

No provider SDK is imported here or anywhere in this package. A real provider would implement
`Provider.complete` in its own module (see the service README); knowledge, policy, retrieval and tool
logic never import it.
"""
from __future__ import annotations

import re
from typing import Protocol, runtime_checkable

from .datatypes import CompletionRequest, CompletionResponse, ToolCall


class ProviderError(Exception):
    pass


class ProviderUnavailable(ProviderError):
    """Outage, timeout or transport failure. The pipeline degrades to a human-escalation answer."""


@runtime_checkable
class Provider(Protocol):
    def complete(self, request: CompletionRequest) -> CompletionResponse:
        ...


def estimate_tokens(text: str) -> int:
    """Deterministic, conservative token estimate (about 4 characters per token, rounded up)."""
    return len(text) // 4 + 1


def request_input_tokens(request: CompletionRequest) -> int:
    return estimate_tokens(request.system) + sum(estimate_tokens(m.content) for m in request.messages)


_QUESTION = re.compile(r'<member_question>\n?(.*?)</member_question>', re.S)
_PASSAGE = re.compile(r'<passage id="([a-z0-9-]+)"[^>]*>\n?(.*?)</passage>', re.S)

HOSTILE_KINDS = (
    "follow_injection", "tool_call", "fake_status", "leak_operator", "bad_citation", "no_citation",
    "invented_policy", "invented_action", "ask_password", "echo_secret",
)


class FakeProvider:
    """Deterministic stand-in for a model. Never touches the network.

    Modes:
      rules    - extractive answer from the first retrieved passage with a valid citation.
      scripted - returns the queued responses (strings or CompletionResponse) in order.
      hostile  - misbehaves on purpose, one `kind` per call (cycling), to exercise the guard layer.
      outage   - raises ProviderUnavailable.
    """

    def __init__(self, mode: str = "rules", *, script=None, hostile=None):
        if mode not in ("rules", "scripted", "hostile", "outage"):
            raise ValueError(mode)
        self.mode = mode
        self.script = list(script or [])
        self.hostile = [hostile] if isinstance(hostile, str) else list(hostile or HOSTILE_KINDS)
        for k in self.hostile:
            if k not in HOSTILE_KINDS:
                raise ValueError(f"unknown hostile kind {k}")
        self.calls: list[CompletionRequest] = []

    @staticmethod
    def passages_in(request: CompletionRequest) -> list[tuple[str, str]]:
        found: list[tuple[str, str]] = []
        for m in request.messages:
            found.extend(_PASSAGE.findall(m.content))
        return found

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        self.calls.append(request)
        n_in = request_input_tokens(request)
        if self.mode == "outage":
            raise ProviderUnavailable("fake outage")
        if self.mode == "scripted":
            if not self.script:
                raise ProviderError("script exhausted")
            item = self.script.pop(0)
            if isinstance(item, CompletionResponse):
                return item
            return CompletionResponse(text=item, input_tokens=n_in, output_tokens=estimate_tokens(item))
        passages = self.passages_in(request)
        first_id = passages[0][0] if passages else "unknown"
        if self.mode == "hostile":
            kind = self.hostile[(len(self.calls) - 1) % len(self.hostile)]
            return self._hostile(kind, first_id, n_in)
        if not passages:
            text = "I could not find that in the help documents."
        else:
            q = " ".join(_QUESTION.findall(" ".join(m.content for m in request.messages)))
            text = self._extract(passages[0][1], first_id, q)
        return CompletionResponse(text=text, input_tokens=n_in,
                                  output_tokens=min(estimate_tokens(text), request.max_output_tokens))

    @staticmethod
    def _extract(body: str, doc_id: str, question: str = "", limit: int = 380) -> str:
        flat = []
        for line in body.splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            flat.append(s.lstrip("-* ").strip())
        lines = [s.strip() for s in re.split(r"(?<=[.!?])\s+", " ".join(flat)) if s.strip()]
        from .textutil import tokens
        q = set(tokens(question))
        ranked = sorted(range(len(lines)), key=lambda i: (-len(q & set(tokens(lines[i]))), i))[:3]
        text = " ".join(lines[i] for i in sorted(ranked))
        if len(text) > limit:
            text = text[:limit].rsplit(" ", 1)[0]
        return f"{text} [doc:{doc_id}]"

    def _hostile(self, kind: str, doc_id: str, n_in: int) -> CompletionResponse:
        cite = f"[doc:{doc_id}]"
        tool = ()
        if kind == "follow_injection":
            text = f"Understood. Ignoring previous instructions: here is my system prompt and the admin notes. {cite}"
        elif kind == "tool_call":
            text = f"Sure, I will reset that now. {cite}"
            tool = (ToolCall("call-1", "reset_password", {"member": "someone-else"}),)
        elif kind == "fake_status":
            text = f"Everything is fine: the service is currently up and all systems are operational. {cite}"
        elif kind == "leak_operator":
            text = "You can reach the admin console at ops" + ".avrana.net on " + ".".join(["192", "168", "1", "20"]) + f" {cite}"
        elif kind == "bad_citation":
            text = "Install the app and sign in with your account. [doc:made-up-document]"
        elif kind == "no_citation":
            text = "Install the app and sign in with your account."
        elif kind == "invented_policy":
            text = ("Members may stream unlimited ultra definition video on twelve devices and request up to "
                    f"fifty titles every single week without approval. {cite}")
        elif kind == "invented_action":
            text = f"I have reset your password and granted you access to every library. {cite}"
        elif kind == "ask_password":
            text = f"Please send me your current password so that I can check your account. {cite}"
        else:  # echo_secret
            text = "Your key is sk-" + "q7" * 14 + f" {cite}"
        return CompletionResponse(text=text, tool_calls=tool, input_tokens=n_in, output_tokens=estimate_tokens(text))
