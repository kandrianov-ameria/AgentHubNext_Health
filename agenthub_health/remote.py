"""
The remote configuration as AgentHubNext sees it.

The five documents are downloaded once, at the start of the run, by bootstrap.run(); when a
download fails the saved copy from an earlier run is used instead. This module reads them
the way the application does (dotnet.py):

  * /api/agents, /api/tools, /api/mcps, /api/llm-providers go through Json.NET into the DTOs,
    including its silent conversions and the cases where it throws;
  * agents and tools are filtered by `category == environment` (ordinal comparison);
  * an agent's definition lives in `json_schema` (Name, AssignedTools, ...); a missing Name is
    null, a JSON null Name is the empty string, exactly like JToken.ToString();
  * a tool's name is `json_schema.name`, rewritten to `[mcp]name` when `json_schema.mcp` is set;
  * provider and MCP `headers` are "Name: value" lines;
  * the AgentHub section of pat-config goes through System.Text.Json (case-insensitive names,
    no type conversion).

When the application could not load the lists at all (Json.NET or GetConfigurationAsync would
throw before validation), config() raises ConfigUnloadable, and every check that needs the
configuration fails with that one root cause - the application would not start either.
"""
from __future__ import annotations

import functools
from dataclasses import dataclass, field
from typing import Any

from . import bootstrap, dotnet, settings
from .probe import ProbeResult, ServiceFailure, Status, SuiteIssue

SERVICE = "aihub-service"
ROOT_AGENT = "PointAndTalkAgent"
LOAD_RULE = "AgentHubNext must be able to deserialize the configuration lists."


def auth_headers() -> dict:
    return {"Authorization": f"Bearer {settings.get('AIHUB_WIN_TOKEN')}"}


def split_arguments(raw: str | None) -> list[str]:
    """Same rule as McpWrapper: comma-separated, trimmed, empty entries dropped."""
    return [a.strip() for a in str(raw or "").split(",") if a.strip()]


parse_headers = dotnet.parse_headers
header_problem = dotnet.header_problem


class ConfigUnloadable(ServiceFailure):
    """The AI-Hub service served configuration lists AgentHubNext cannot load."""


@dataclass
class Fetch:
    download: bootstrap.Download
    data: Any = None

    @property
    def probe(self) -> ProbeResult | None:
        return self.download.probe

    @property
    def source(self) -> str:
        return self.download.source

    def require(self, what: str) -> Any:
        d = self.download
        if d.available:
            return self.data
        if d.suite_input_missing:
            raise SuiteIssue(f"{what} is unavailable: {d.reason}.",
                             "Set the base URL in suite.env; for the token run: "
                             ".venv\\Scripts\\python scripts\\refresh_env.py")
        raise ServiceFailure(d.probe, f"{what} is unavailable: the download of /api/{d.entity} failed "
                                      f"({d.reason}) and no earlier run saved a copy to fall back on.",
                             service=SERVICE)


@functools.lru_cache(maxsize=None)
def fetch(entity: str) -> Fetch:
    """The document for `entity` as this run uses it (fresh, or the saved copy)."""
    d = bootstrap.get(entity)
    data = None
    if d.text is not None:
        try:
            data = (dotnet.parse_system_text_json if entity.startswith("pat-config/")
                    else dotnet.parse_newtonsoft)(d.text)
        except dotnet.JsonError:
            data = None
    return Fetch(d, data)


def pat_config_entity() -> str:
    return bootstrap.pat_entity()


@dataclass
class Agent:
    keyword: str | None
    name: str | None
    llm_provider_id: Any
    secondary_llm_provider_id: Any
    schema: dict
    assigned_tools: list = field(default_factory=list)
    assigned_mcps: list = field(default_factory=list)
    assigned_agents: list = field(default_factory=list)
    instructions: str = ""


@dataclass
class Tool:
    name: str | None    # final name, [mcp]name for MCP tools
    mcp: str | None     # None when json_schema has no "mcp"; "" when it is JSON null or empty


@dataclass
class Config:
    env: str
    agents: list[Agent]
    tools: list[Tool]
    mcps: list[dict]
    providers: list[dict]
    findings: dotnet.Findings = field(default_factory=dotnet.Findings)
    source: str = "download"

    def agent(self, name: str) -> Agent | None:
        return next((a for a in self.agents if a.name == name), None)

    def provider(self, pid: Any) -> dict | None:
        return next((p for p in self.providers if p.get("id") == pid), None)

    def reachable_from_root(self) -> set[str]:
        seen: set[str] = set()
        stack = [ROOT_AGENT]
        while stack:
            n = stack.pop()
            if n in seen:
                continue
            a = self.agent(n)
            if not a:
                continue
            seen.add(n)
            stack.extend(x for x in a.assigned_agents if x is not None)
        return seen


@functools.lru_cache(maxsize=None)
def load_result() -> Config:
    """The configuration and everything the application would convert or reject, without raising
    for load problems (config() raises; the loading checks in test_01 need the details)."""
    env = settings.env_name()
    fetches = {e: fetch(e) for e in bootstrap.LISTS}
    labels = {"agents": "The agent list", "tools": "The tool list", "mcps": "The MCP list",
              "llm-providers": "The LLM provider list"}
    raw = {e: f.require(labels[e]) for e, f in fetches.items()}
    loaded = dotnet.load(raw, env)
    agents = [Agent(keyword=a["keyword"], name=a["name"], llm_provider_id=a["llm_provider_id"],
                    secondary_llm_provider_id=a["secondary_llm_provider_id"], schema=a["schema"],
                    assigned_tools=list(a["AssignedTools"] or []), assigned_mcps=list(a["AssignedMCPs"] or []),
                    assigned_agents=list(a["AssignedAgents"] or []), instructions=a["InnerInstructions"] or "")
              for a in loaded.agents]
    tools = [Tool(name=t["name"], mcp=t["mcp"]) for t in loaded.tools]
    sources = {f.source for f in fetches.values()}
    return Config(env, agents, tools, loaded.mcps, loaded.providers, loaded.findings,
                  source=sources.pop() if len(sources) == 1 else "mixed")


def config() -> Config:
    """Agents, tools, MCPs and LLM providers as the application holds them after loading."""
    cfg = load_result()
    if cfg.findings.fatal:
        probe = fetch("agents").probe
        if probe is not None:
            probe = ProbeResult(probe.service, "configuration lists", probe.method, probe.url,
                                Status.CONTRACT, probe.http_status, probe.latency_ms,
                                body=cfg.findings.fatal[0])
        raise ConfigUnloadable(
            probe, "AgentHubNext cannot load the configuration lists of this environment, so it would not "
                   f"start and this check cannot run. First problem: {cfg.findings.fatal[0]} "
                   "(all of them are listed by test_01_remote_config::test_app_can_load_the_lists).",
            service=SERVICE, cause_key=f"config|{LOAD_RULE}")
    return cfg


@functools.lru_cache(maxsize=None)
def agenthub_section() -> tuple[Fetch, dict | None]:
    """(fetch, the AgentHub settings as AgentHubRemoteSettings holds them, or None when the
    document in use has no usable section)."""
    f = fetch(pat_config_entity())
    section = None
    if f.data is not None:
        section, _why = dotnet.read_agenthub_section(f.data)
    return f, section


def fresh_agenthub_problem() -> str:
    """Why the section downloaded in this run is unusable for the application, or ''."""
    d = bootstrap.get(pat_config_entity())
    if d.fresh_text is None:
        return ""
    try:
        root = dotnet.parse_system_text_json(d.fresh_text)
    except dotnet.JsonError as exc:
        return f"the body is not valid JSON ({exc})"
    _s, why = dotnet.read_agenthub_section(root)
    return why
