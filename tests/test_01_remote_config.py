"""
Remote configuration - loading and validating it the way AgentHubNext does at start-up.

The configuration is the one downloaded at the start of this run (or the saved copy when the
download failed, see test_05_config_download).

First the lists are read the way the application reads them (agenthub_health/dotnet.py):
Json.NET into the DTOs of src/AgentHub/RemoteConfiguration/, then json_schema through the
JObject indexer, Value<int?>() and ToObject<List<string>>(). Anything that makes the
application throw at this stage is reported by test_app_can_load_the_lists; the application
would not start, so every other check that needs the configuration fails with the same cause.

The remaining rules are copies of the checks in RemoteConfigurationManager.GetConfigurationAsync.
When any of them fails the application collects the error, prints it, and throws
"Remote configuration error." - so a failure here means AgentHubNext cannot load its agents
in this environment. The error text in each failure is the text the application prints.
"""
from __future__ import annotations

import re
from collections import Counter

import pytest

from agenthub_health import remote
from agenthub_health.probe import ConfigDefect, unused_by_app

pytestmark = [pytest.mark.config, pytest.mark.smoke]

STARTUP = ("GetConfigurationAsync collects this error and throws \"Remote configuration error.\", "
           "so AgentHubNext cannot load its agents, tools and providers in this environment.")
FIX = "Correct the record in Maverick Config Manager for this environment."


def _s(value) -> str:
    """How C# string interpolation prints a value: null as nothing."""
    return "" if value is None else str(value)


def _defect(errors: list[str], rule: str, impact: str = STARTUP, fix: str = FIX) -> None:
    if errors:
        shown = errors[:25]
        more = f"\n... and {len(errors) - 25} more" if len(errors) > 25 else ""
        raise ConfigDefect("\n".join(shown) + more, rule, impact, fix)


def test_app_can_load_the_lists():
    """AgentHubNext can deserialize the agent, tool, MCP and LLM provider lists (Json.NET, typed DTOs)."""
    cfg = remote.load_result()
    _defect(cfg.findings.fatal, remote.LOAD_RULE,
            impact="GetConfigurationAsync throws while reading the lists, before it validates them, so "
                   "AgentHubNext cannot start in this environment.",
            fix="Correct the record named in each line in Maverick Config Manager for this environment.")


def test_values_have_the_types_the_app_expects():
    """Every value has the JSON type of its DTO property, so no silent Json.NET conversion is involved."""
    notes = remote.load_result().findings.notes
    if notes:
        with unused_by_app("Json.NET converts these values without an error, so AgentHubNext loads them; the "
                           "suite uses the converted values in every other check."):
            _defect(notes, "Every value must have the JSON type of its DTO property.",
                    impact="None today. A converted value can differ from what the editor of the record meant "
                           "(for example a number read as text).",
                    fix="Store the value with the expected JSON type in Maverick Config Manager.")


@pytest.mark.parametrize("what", ["agents", "tools", "llm-providers", "mcps"])
def test_list_is_not_empty(cfg, env, what):
    """A configuration list AgentHubNext requires is not empty for this environment."""
    lists = {"agents": cfg.agents, "tools": cfg.tools, "llm-providers": cfg.providers, "mcps": cfg.mcps}
    labels = {"agents": "Agents", "tools": "Tools", "llm-providers": "LLM Providers", "mcps": "MCPs"}
    if not lists[what]:
        extra = f" (after filtering by category == '{env}')" if what in ("agents", "tools") else ""
        _defect([f"{labels[what]} list is empty.{extra}"], f"The {what} list must not be empty.")


def test_agent_keyword_matches_schema_name(cfg):
    """Every agent's keyword equals the Name inside its json_schema."""
    _defect([f"Mismatching agent name '{_s(a.name)}' in schema and agent keyword '{_s(a.keyword)}'."
             for a in cfg.agents if a.keyword != a.name],
            "An agent's keyword must equal json_schema.Name.")


def test_no_duplicate_agent_names(cfg):
    """No two agents in this environment share a name."""
    dup = [_s(n) for n, c in Counter(a.name for a in cfg.agents).items() if c > 1]
    _defect([f"Agents list has duplicate names: {', '.join(dup)}."] if dup else [],
            "Agent names must be unique.")


def test_no_duplicate_tools(cfg):
    """No two tools share the same name and MCP."""
    dup = [f"{_s(n)} (mcp '{m}')" if m else _s(n)
           for (n, m), c in Counter((t.name, t.mcp) for t in cfg.tools).items() if c > 1]
    _defect([f"Tools list has duplicate names: {', '.join(dup)}."] if dup else [],
            "Tool (name, MCP) pairs must be unique.")


def test_no_duplicate_mcp_names(cfg):
    """No two MCP servers share a name."""
    dup = [n for n, c in Counter(m.get("name") for m in cfg.mcps).items() if c > 1]
    _defect([f"MCPs list has duplicate names: {', '.join(map(str, dup))}."] if dup else [],
            "MCP names must be unique.")


def test_agent_llm_provider_exists(cfg):
    """Every agent's llm_provider_id points at an existing provider."""
    _defect([f"Agent '{_s(a.name)}' has invalid LLM Provider Id '{a.llm_provider_id}'."
             for a in cfg.agents if cfg.provider(a.llm_provider_id) is None],
            "llm_provider_id must reference an existing provider.")


def test_agent_secondary_provider_is_valid(cfg):
    """A secondary provider, when set, exists and differs from the primary one."""
    errors = []
    for a in cfg.agents:
        s = a.secondary_llm_provider_id
        if s is None:
            continue
        if s == a.llm_provider_id:
            errors.append(f"Agent '{_s(a.name)}' has SecondaryLlmProviderId equal to primary LlmProviderId "
                          f"'{a.llm_provider_id}'.")
        if cfg.provider(s) is None:
            errors.append(f"Agent '{_s(a.name)}' has invalid Secondary LLM Provider Id '{s}'.")
    _defect(errors, "secondary_llm_provider_id must exist and differ from the primary provider.")


def test_assigned_agents_exist(cfg):
    """Every agent named in AssignedAgents exists."""
    names = {a.name for a in cfg.agents}
    _defect([f"Agent '{_s(a.name)}' has invalid assigned agent '{_s(s)}'."
             for a in cfg.agents for s in a.assigned_agents if s not in names],
            "Every AssignedAgents entry must be an existing agent.")


def test_assigned_local_tools_exist(cfg):
    """Every entry in AssignedTools is a defined local (non-MCP) tool."""
    local = {t.name for t in cfg.tools if not t.mcp}
    _defect([f"Agent '{_s(a.name)}' has invalid assigned tool '{_s(t)}'."
             for a in cfg.agents for t in a.assigned_tools if t not in local],
            "Every AssignedTools entry must be a defined local tool.")


def test_assigned_mcp_tools_exist(cfg):
    """Every entry in AssignedMCPs is a defined tool of that MCP server."""
    errors = []
    for a in cfg.agents:
        for ref in a.assigned_mcps:
            if ref is None:
                continue  # Regex.Match(null) throws - reported by test_app_can_load_the_lists
            m = re.match(r"^\[(.*?)\](.*)$", ref)
            mcp = m.group(1) if m else None
            # x.MCP == mcpName: a tool without "mcp" in its schema has MCP null, so an entry
            # without brackets can match it - the same comparison the application makes.
            if not any(t.mcp == mcp and t.name == ref for t in cfg.tools):
                errors.append(f"Agent '{_s(a.name)}' has invalid assigned MCP tool '{ref}'.")
    _defect(errors, "Every AssignedMCPs entry must be '[mcpName]toolName' of a defined MCP tool.")


def test_embedding_provider_configured(cfg):
    """A primary 'open_ai_embedding' provider exists for the embedding client."""
    ok = any(p.get("primary") and p.get("provider_type") == "open_ai_embedding" for p in cfg.providers)
    _defect([] if ok else ["Embedding Provider configuration not found. Embedding Client will not be available."],
            "A provider with primary=true and provider_type='open_ai_embedding' must exist.",
            impact="AgentHubNext starts, but prints this warning and runs without the Embedding Client.")


REQUIRED_HEADERS = {
    "open_ai": [("Authorization",)],
    "anthropic": [("x-api-key",), ("anthropic-version",)],
    "gemini": [("x-goog-api-key", "Authorization")],
    "open_ai_embedding": [("Authorization",)],
}


def test_embedding_provider_has_authorization(cfg):
    """The primary embedding provider's headers can be read and include Authorization (Program.cs)."""
    p = next((p for p in cfg.providers if p.get("primary") and p.get("provider_type") == "open_ai_embedding"), None)
    if p is None:
        pytest.skip("No primary open_ai_embedding provider - reported by test_embedding_provider_configured.")
    problem = remote.header_problem(p.get("headers"))
    if not problem and "Authorization" not in remote.parse_headers(p.get("headers")):
        problem = ("its headers have no 'Authorization' line; the application throws \"Authorization header not "
                   "found in embedding provider configuration\"")
    _defect([f"Embedding provider '{_s(p.get('name'))}' (id {p.get('id')}): {problem}"] if problem else [],
            "The embedding provider needs a readable Authorization header.",
            impact="\"Initialize Embedding Client... Failed\": AgentHubNext starts, but runs without the "
                   "Embedding Client.")


def test_agent_providers_are_usable(cfg):
    """Each provider an agent uses has a supported type and the headers AgentLight requires."""
    from agenthub_health.remote import header_problem, parse_headers
    errors = []
    used = {}
    for a in cfg.agents:
        for pid in (a.llm_provider_id, a.secondary_llm_provider_id):
            if pid is not None:
                used.setdefault(pid, []).append(_s(a.name))
    for pid, agents in sorted(used.items(), key=lambda x: str(x[0])):
        p = cfg.provider(pid)
        if p is None:
            continue  # reported by test_agent_llm_provider_exists
        ptype = p.get("provider_type")
        name = p.get("name") or pid
        if ptype not in ("open_ai", "anthropic", "gemini"):
            errors.append(f"Provider '{name}' (id {pid}) has type '{ptype}', which AgentLight does not support "
                          f"(\"Provider type '{ptype}' is not supported for AgentLight.\"). Used by: {', '.join(agents)}.")
            continue
        problem = header_problem(p.get("headers"))
        if problem:
            errors.append(f"Provider '{name}' (id {pid}, {ptype}): {problem} Used by: {', '.join(map(_s, agents))}.")
            continue
        headers = parse_headers(p.get("headers"))
        for alternatives in REQUIRED_HEADERS[ptype]:
            if not any(h in headers for h in alternatives):
                errors.append(f"Provider '{name}' (id {pid}, {ptype}) has no '{' or '.join(alternatives)}' header. "
                              f"Used by: {', '.join(agents)}.")
    _defect(errors, "AgentLight.CreateProviderFromId throws for an unsupported provider type or a missing header.",
            impact="The agent cannot be created when a session starts, so it cannot answer.")
