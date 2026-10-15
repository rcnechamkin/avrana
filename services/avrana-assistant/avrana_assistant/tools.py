"""Tool registry stub for A0: denies everything. Authorisation lives here, outside the model.

A future phase adds entries to a policy table and handlers, each with a narrow scope. The model only ever
*proposes* a ToolCall; `ToolRegistry.execute` decides from the Principal and the policy, and member
identity arguments are never taken from the model.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from .datatypes import Principal, ToolCall


@dataclass(frozen=True)
class ToolPolicy:
    """Future per-tool policy. Not populated in A0."""
    allowed_groups: frozenset = frozenset()
    read_only: bool = True
    requires_confirmation: bool = False


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    name: str
    executed: bool
    reason: str


def authorise(principal: Principal, call: ToolCall, policy: Mapping[str, ToolPolicy]) -> Decision:
    """Pure function of (principal, call, policy). Default deny."""
    if not principal.authenticated:
        return Decision(False, "unauthenticated")
    entry = policy.get(call.name)
    if entry is None:
        return Decision(False, "tool_not_in_policy")
    if entry.allowed_groups and not (entry.allowed_groups & principal.groups):
        return Decision(False, "group_not_permitted")
    if not entry.read_only:
        return Decision(False, "write_tools_not_available")
    return Decision(True, "policy_allows")


class ToolRegistry:
    def __init__(self, policy: Mapping[str, ToolPolicy] | None = None,
                 handlers: Mapping[str, Callable] | None = None):
        self._policy = dict(policy or {})
        self._handlers = dict(handlers or {})

    def definitions_for(self, principal: Principal) -> tuple:
        """Tool definitions shown to the model. Empty in A0."""
        return ()

    def execute(self, principal: Principal, call: ToolCall) -> ToolResult:
        d = authorise(principal, call, self._policy)
        if not d.allowed:
            return ToolResult(call.id, call.name, False, d.reason)
        handler = self._handlers.get(call.name)
        if handler is None:
            return ToolResult(call.id, call.name, False, "no_handler_in_a0")
        # Reached only in a later phase. Identity comes from the Principal, never from call.arguments.
        handler(principal, dict(call.arguments))
        return ToolResult(call.id, call.name, True, "executed")
