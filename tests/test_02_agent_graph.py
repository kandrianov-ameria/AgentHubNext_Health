"""
Agent graph - checks that go beyond what AgentHubNext validates at startup.
The app starts with these problems present; they show up as agents that can
never be reached or tools the prompt asks for but cannot call.
"""
from __future__ import annotations

import pytest

from agenthub_health.probe import ConfigDefect
from agenthub_health.remote import ROOT_AGENT

pytestmark = [pytest.mark.config, pytest.mark.smoke]

# Agents that are invoked from code rather than by handoff (README.md, remote_prompts/README.md).
INVOKED_FROM_CODE = {"MemoryConsolidationAgent"}


def test_root_agent_exists(cfg, env):
    """PointAndTalkAgent - the agent every session starts with - is defined."""
    if cfg.agent(ROOT_AGENT) is None:
        raise ConfigDefect(f"No agent named '{ROOT_AGENT}' in category '{env}'.",
                           "The Point & Talk session always starts with PointAndTalkAgent.",
                           "No Point & Talk session can start.",
                           "Add or restore PointAndTalkAgent for this environment in Maverick Config Manager.")


def test_handoff_tool_not_assigned_explicitly(cfg):
    """No agent lists handoff_to_agent in AssignedTools (AgentLight injects it automatically)."""
    offenders = [a.name for a in cfg.agents if "handoff_to_agent" in a.assigned_tools]
    if offenders:
        raise ConfigDefect(f"handoff_to_agent is assigned explicitly to: {', '.join(offenders)}.",
                           "AgentLight auto-injects handoff_to_agent when AssignedAgents is non-empty (CLAUDE.md, Tool execution).",
                           "The agent is offered the handoff tool twice.",
                           "Remove handoff_to_agent from AssignedTools.")


@pytest.mark.xfail(reason="Known: the PointAndTalkAgent prompt names NanoBananaImageEditorAgent as a handoff "
                          "target, but it is not in its AssignedAgents (found during the repository review).",
                   raises=ConfigDefect, strict=False)
def test_agents_named_in_root_prompt_are_reachable(cfg):
    """Every agent the PointAndTalkAgent prompt mentions can actually be handed off to."""
    root = cfg.agent(ROOT_AGENT)
    if root is None:
        pytest.skip("PointAndTalkAgent is not defined - reported by test_root_agent_exists.")
    reach = cfg.reachable_from_root()
    named = [a.name for a in cfg.agents if a.name and a.name != ROOT_AGENT and a.name in root.instructions]
    orphans = [n for n in named if n not in reach]
    if orphans:
        raise ConfigDefect(f"The PointAndTalkAgent prompt names {', '.join(orphans)}, but no AssignedAgents path "
                           "from PointAndTalkAgent leads there.",
                           "Handoff is only possible to agents listed in AssignedAgents.",
                           "The model is told to hand off to an agent it has no handoff route to.",
                           "Add the agent to PointAndTalkAgent's AssignedAgents, or remove it from the prompt.")


@pytest.mark.xfail(reason="Known: the PointAndTalkAgent prompt refers to a memory tool that is not in its "
                          "AssignedTools (memory_save at the repository review; save_user_memory on QAS on "
                          "2026-09-30).",
                   raises=ConfigDefect, strict=False)
def test_root_agent_has_the_memory_tools_its_prompt_uses(cfg):
    """Every memory tool the PointAndTalkAgent prompt refers to is assigned to it."""
    root = cfg.agent(ROOT_AGENT)
    if root is None:
        pytest.skip("PointAndTalkAgent is not defined - reported by test_root_agent_exists.")
    mentioned = [t for t in ("memory_save", "memory_search", "memory_delete", "save_user_memory",
                             "get_saved_user_memories") if t in root.instructions]
    missing = [t for t in mentioned if t not in root.assigned_tools]
    if missing:
        raise ConfigDefect(f"The prompt refers to {', '.join(missing)}, which PointAndTalkAgent cannot call.",
                           "An agent can only call tools listed in its AssignedTools.",
                           "Requests to remember something permanently cannot be carried out.",
                           "Assign the tool to PointAndTalkAgent, or change the prompt.")


def test_no_unreachable_agents(cfg):
    """Lists agents that nothing hands off to (informational - may be intentional)."""
    if cfg.agent(ROOT_AGENT) is None:
        pytest.skip("PointAndTalkAgent is not defined.")
    orphan = sorted({a.name for a in cfg.agents if a.name} - cfg.reachable_from_root() - INVOKED_FROM_CODE)
    if orphan:
        pytest.skip(f"Defined but unreachable from PointAndTalkAgent: {', '.join(orphan)}. "
                    "Confirm this is intentional.")
