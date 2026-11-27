"""
What a failure touches in the configuration of this run (since 1.14.0).

For every root cause under "Failed checks" the report adds one block, "Affected in this configuration":
which agents, tools, MCP servers, LLM providers and configuration entries depend on the thing that failed,
and how, in plain language. It is worked out from the configuration this run downloaded (or the saved copy
it fell back on), never from the local repository, and it makes no request of its own.

  * Only failures that affect the app get a block. A failure of something the configuration does not use is
    already listed under "Failed, no effect on the app" (plugin._apply_usage, usage.py); it gets none.
  * Which agent uses which service is usage.NEEDS (agent, assigned tools, prompt placeholders), the same table
    that decides "used" and "not used". Only agents reachable from PointAndTalkAgent count.
  * An LLM provider is found by its name in the probe subject ("LLM provider '<name>'", set by test_20); an MCP
    server by "MCP server '<name>'" (test_40); the Tavily key by the stdio record that starts
    mcp-tavily-search-image (test_41). Configuration defects that name an agent, tool, MCP server or provider
    in their message are matched by exact name (a heuristic: the check wrote the name, the suite only reads it).
  * The wording of every effect comes from services.py (each statement there cites the backend source) and from
    the fallback rules the golden readiness already uses (primary provider -> secondary provider).

Nothing here is a verdict: it explains a failure the checks already reported. It never raises; on any problem
the card simply has no block.
"""
from __future__ import annotations

import re
from collections import OrderedDict
from dataclasses import dataclass, field

from . import remote, services, usage
from .runlog import log

ROOT = remote.ROOT_AGENT

KINDS = ("Agents", "Tools", "MCP servers", "LLM providers", "Configuration", "App functions")

# --- wording -----------------------------------------------------------------------------------

# (service, tool) -> what happens to the tool. Taken from services.py (impact) and usage.py (rules).
TOOL_HOW = {
    ("2d-to-3d", "generate_3d_object"): "cannot create new 3D models",
    ("2d-to-video", "generate_video"): "cannot create new videos",
    ("mav-starkit-api", "generate_3d_object"): "cannot store the generated 3D model (GLB)",
    ("mav-starkit-api", "generate_video"): "cannot store the generated video (MP4)",
    ("mav-starkit-api", "send_file_to_srd"): "cannot queue the file for the Sony SRD",
    ("device-mapping", "send_file_to_srd"): "cannot tell which Starkit controllers are paired with this AgentHub",
    ("mavslides-llm", "generate_presentation"): "fails: the LLM calls that plan the deck and write the slide HTML are refused",
    ("mavslides-llm", "edit_slide"): "fails: the coder LLM that rewrites the slide is refused",
    ("mavslides-llm", "insert_slide"): "fails: the LLM that plans the new slide and the coder LLM are refused",
    ("mavslides-openrouter", "edit_slide_image"): "cannot change pictures",
    ("mavslides-openrouter", "generate_presentation"): "pictures the web search did not supply fall back to a local placeholder",
    ("mavslides-websearch", "generate_presentation"): "carries on without web knowledge, so the deck is written from the model's own knowledge",
    ("mavslides-tavily", "generate_presentation"): "pictures are not searched on the web; falls back to OpenRouter generation, then a local placeholder",
}
# These only make a tool worse, they do not stop it.
DEGRADED = {("mavslides-openrouter", "generate_presentation"), ("mavslides-websearch", "generate_presentation"),
            ("mavslides-tavily", "generate_presentation")}

# service -> the entries of the downloaded configuration that hold its address, credential or model, with the role
# each plays (url / key / model), so a failure only names the entries that can be its cause.
def _f(label: str, *roles: str) -> tuple[str, frozenset]:
    return label, frozenset(roles)


_PC = "pat-config › AgentHub › "
_MS = "pat-config › AgentHub › MavSlides › "
CONFIG_FIELDS = {
    "deepgram": [_f(_PC + "DefaultDeepgramApiKey", "key")],
    "whisper": [_f(_PC + "WhisperUrl", "url"), _f(_PC + "WhisperModel", "model"), _f(_PC + "ProxyAuthHeader", "key")],
    "vision": [_f(_PC + "VisionUrl", "url"), _f(_PC + "VisionModel", "model"), _f(_PC + "ProxyAuthHeader", "key")],
    "sam3": [_f(_PC + "SamPredictTextUrl", "url"), _f(_PC + "SamPredictUrl", "url"),
             _f(_PC + "ProxyAuthHeader", "key")],
    "mav-starkit-api": [_f(_PC + "MavStarkitApiKey", "key")],
    "device-mapping": [_f(_PC + "DeviceMappingBearerToken", "key")],
    "log-upload": [_f(_PC + "DeviceMappingBearerToken", "key")],
    "mavslides-llm": [_f(_MS + "LlmUrl / CoderUrl", "url"), _f(_MS + "LlmApiKey / CoderApiKey", "key"),
                      _f(_MS + "LlmModel / CoderModel", "model")],
    "mavslides-vision": [_f(_MS + "VisionUrl", "url"), _f(_MS + "VisionApiKey", "key"),
                         _f(_MS + "VisionModel", "model")],
    "mavslides-openrouter": [_f(_MS + "OpenRouterUrl", "url"), _f(_MS + "OpenRouterApiKey", "key")],
    "mavslides-websearch": [_f(_MS + "WebSearchMcpUrl", "url"), _f(_MS + "WebSearchMcpToken", "key")],
    "mavslides-tavily": [_f(_MS + "TavilyApiKey", "key")],
}
ALL_ROLES = frozenset({"url", "key", "model"})

LIST_DOCS = {"agents": "agent list (/api/agents)", "tools": "tool list (/api/tools)",
             "mcps": "MCP list (/api/mcps)", "llm-providers": "LLM provider list (/api/llm-providers)",
             "pat-config": "pat-config (/api/pat-config)"}

_STATUS_WORDS = {
    "auth_failed": "rejects the key or token",
    "not_found": "answers 404 (wrong address or model name)",
    "client_error": "refuses the request",
    "server_error": "answers with a server error",
    "unavailable": "is unavailable",
    "timeout": "does not answer in time",
    "dns_failed": "cannot be found (DNS)",
    "tls_failed": "fails the TLS handshake",
    "connection_failed": "cannot be reached",
    "contract": "answers, but not in the shape the app reads",
    "unexpected_access": "accepts a request it should refuse",
}


def _status_phrase(probe: dict | None) -> str:
    if not probe:
        return "has a defect in its configuration record"
    word = _STATUS_WORDS.get(probe.get("status", ""), "failed its check")
    code = probe.get("http_status")
    return f"{word} (HTTP {code})" if code else word


_ADDRESS_STATUSES = {"timeout", "dns_failed", "tls_failed", "connection_failed", "unavailable", "server_error"}


def _relevant(entries, probe: dict | None):
    """The entries that can be the cause of this probe's status; all of them when none can be told apart."""
    if not probe:
        return list(entries)
    st = probe.get("status", "")
    want = ({"key"} if st == "auth_failed" else {"url"} if st in _ADDRESS_STATUSES or st == "contract"
            else {"url", "model"} if st in ("not_found", "client_error") else set())
    hit = [x for x in entries if x[1] & want]
    return hit or list(entries)


def _config_how(probe: dict | None, roles: frozenset = ALL_ROLES) -> str:
    """What may be wrong with the value stored in a configuration entry, from the probe that used it."""
    if not probe:
        return "holds a value that is missing or wrong (see What happened)"
    st = probe.get("status", "")
    if st == "auth_failed":
        return "the key or token stored here is rejected" if "key" in roles else "is sent with the rejected credential"
    if st in _ADDRESS_STATUSES:
        return "the address stored here does not answer" if "url" in roles else "is sent to a service that does not answer"
    if st == "not_found":
        return ("the address or model name stored here is not known to the service" if roles & {"url", "model"}
                else "is sent to a service that answers 404")
    if st == "contract":
        return "the service behind it answers in a shape the app does not read"
    if st == "unexpected_access":
        return "is not enforced by the service"
    return "is sent to a service that refuses the request"


def _first_sentence(text: str, n: int = 200) -> str:
    text = " ".join((text or "").split())
    text = re.sub(r"\s*\((?:docs|README|src)[^)]*\)", "", text)     # source citations are for the maintainer
    cut = text.find(". ")
    if 0 < cut < n:
        text = text[: cut + 1]
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


# --- result ------------------------------------------------------------------------------------

@dataclass
class Entry:
    name: str
    how: str
    note: str = ""      # shown in italics: where it is held, or that it only degrades


@dataclass
class Impact:
    groups: "OrderedDict[str, list[Entry]]" = field(default_factory=OrderedDict)
    direct_agents: set = field(default_factory=set)
    summary: str = ""

    def add(self, kind: str, name: str, how: str, note: str = "") -> None:
        lst = self.groups.setdefault(kind, [])
        for x in lst:
            if x.name == name:
                if how and how not in x.how:
                    x.how = f"{x.how}; {how}" if x.how else how
                if note and note not in x.note:
                    if x.note.startswith("assigned to ") and note.startswith("assigned to "):
                        x.note = f"{x.note}, {note[len('assigned to '):]}"      # one tool, several agents
                    else:
                        x.note = f"{x.note}; {note}" if x.note else note
                return
        lst.append(Entry(name, how, note))

    def ordered(self) -> "OrderedDict[str, list[Entry]]":
        return OrderedDict((k, self.groups[k]) for k in KINDS if self.groups.get(k))


# --- building blocks ---------------------------------------------------------------------------

def _agent_note(name: str) -> str:
    return "" if name == ROOT else f"handed off to by {ROOT}"


def _agents_and_tools(imp: Impact, cfg, reach, service: str) -> None:
    """Agents and tools that need `service` (usage.NEEDS), as this configuration has them."""
    for agent_name, (tools, placeholders) in usage.NEEDS.get(service, {}).items():
        a = cfg.agent(agent_name)
        if a is None or agent_name not in reach:
            continue
        have = sorted(set(a.assigned_tools) & tools)
        ph = sorted(p for p in placeholders if p in (a.instructions or ""))
        if not have and not ph:
            continue
        bits = []
        if have:
            bits.append(f"its tool{'s' if len(have) > 1 else ''} {', '.join(have)} "
                        f"{'are' if len(have) > 1 else 'is'} affected")
        if ph:
            bits.append(f"its prompt placeholder{'s' if len(ph) > 1 else ''} {', '.join(ph)} cannot be filled")
        imp.add("Agents", agent_name, "; ".join(bits), _agent_note(agent_name))
        imp.direct_agents.add(agent_name)
        for t in have:
            how = TOOL_HOW.get((service, t), "is affected")
            degraded = (service, t) in DEGRADED
            imp.add("Tools", t, how, f"assigned to {agent_name}" + ("; degrades, does not stop it" if degraded else ""))


def _config_entries(imp: Impact, service: str, probe: dict | None) -> None:
    for label, roles in _relevant(CONFIG_FIELDS.get(service, []), probe):
        imp.add("Configuration", label, _config_how(probe, roles))


def _app_function(imp: Impact, service: str) -> None:
    svc = services.SERVICES.get(service)
    if svc is not None and service != "suite":
        imp.add("App functions", svc.title, _first_sentence(svc.impact))


def _provider_state(records, p: dict) -> str:
    """failed | ok | unknown for one LLM provider, from this run's checks (test_20)."""
    name = p.get("name") or p.get("id")
    ident = f"{name}-{p.get('provider_type')}"
    mine = [r for r in records if r.module == "test_20_llm_providers" and r.nodeid.endswith(f"[{ident}]")]
    if any(r.category == "failed" for r in mine):
        return "failed"
    if any(r.category in ("passed", "known_fixed") for r in mine):
        return "ok"
    return "unknown"


def _provider(imp: Impact, cfg, reach, records, p: dict, probe: dict | None) -> None:
    pid, name = p.get("id"), p.get("name") or p.get("id")
    model = f", model {p.get('model')}" if p.get("model") else ""
    imp.add("LLM providers", f"{name}", f"{_status_phrase(probe)}", f"{p.get('provider_type')}{model}")
    imp.add("Configuration", f"llm-providers › '{name}'", _config_how(probe))
    users = 0
    for a in cfg.agents:
        if a.name not in reach:
            continue
        roles = [r for r, v in (("primary", a.llm_provider_id), ("secondary", a.secondary_llm_provider_id),
                                ("low tier", a.low_tier_llm_provider_id)) if v is not None and v == pid]
        if not roles:
            continue
        users += 1
        hows = []
        for role in roles:
            if role == "primary":
                sec = cfg.provider(a.secondary_llm_provider_id) if a.secondary_llm_provider_id is not None else None
                if sec is None or sec.get("id") == pid:
                    hows.append(f"uses '{name}' as its primary provider with nothing to fall back to, so it cannot answer")
                else:
                    state = _provider_state(records, sec)
                    sname = sec.get("name") or sec.get("id")
                    hows.append({
                        "failed": f"uses '{name}' as its primary provider; its secondary provider '{sname}' also failed in this run, so it cannot answer",
                        "ok": f"uses '{name}' as its primary provider and falls back to its secondary provider '{sname}', which answered",
                        "unknown": f"uses '{name}' as its primary provider and falls back to its secondary provider '{sname}' (not checked in this run)",
                    }[state])
            elif role == "secondary":
                hows.append(f"uses '{name}' as its secondary provider, needed only when the primary one fails")
            else:
                hows.append(f"uses '{name}' as its low-tier provider (first choice for thinking status, memory consolidation "
                            "and the suggested question); it falls back to its primary and secondary provider")
        imp.add("Agents", a.name, "; ".join(hows), _agent_note(a.name))
        imp.direct_agents.add(a.name)
    emb = p.get("provider_type") == "open_ai_embedding"
    if emb:
        imp.add("App functions", "Embedding Client", "uses this provider for embeddings; without it the client is not "
                "created and the app continues without it")
    elif users == 0:
        imp.add("LLM providers", f"{name}", "", f"assigned only to agents that {ROOT} cannot reach")


def _mcp(imp: Impact, cfg, reach, m: dict, probe: dict | None) -> None:
    name = m.get("name")
    imp.add("MCP servers", f"{name}", _status_phrase(probe), str(m.get("type") or ""))
    imp.add("Configuration", f"mcps › record '{name}'", _config_how(probe))
    pat = re.compile(r"^\[(.*?)\](.*)$")
    users = 0
    for a in cfg.agents:
        if a.name not in reach:
            continue
        refs = [r for r in a.assigned_mcps if r and pat.match(r) and pat.match(r).group(1) == name]
        if not refs:
            continue
        users += 1
        tool_names = [pat.match(r).group(2) for r in refs]
        imp.add("Agents", a.name, "loses " + ", ".join(tool_names), _agent_note(a.name))
        imp.direct_agents.add(a.name)
        for r in refs:
            imp.add("Tools", r, "cannot be used while the server fails", f"assigned to {a.name}")
    if users == 0:
        imp.add("MCP servers", f"{name}", "", "no agent that the app can reach assigns it")


def _tavily_server(cfg) -> dict | None:
    for m in cfg.mcps:
        text = f"{m.get('name') or ''} {m.get('command') or ''} {m.get('arguments') or ''}"
        if m.get("type") == "stdio" and "mcp-tavily-search-image" in text:
            return m
    return None


def _config_docs(imp: Impact, probe: dict | None) -> None:
    """A request to the AI-Hub service failed: name the document that could not be downloaded."""
    url = (probe or {}).get("url", "")
    hit = next((k for k in ("pat-config", "llm-providers", "mcps", "agents", "tools") if f"/api/{k}" in url), None)
    docs = [hit] if hit else list(LIST_DOCS)
    for d in docs:
        how = ("the app falls back to its encrypted cache; with none it shuts down" if d == "pat-config"
               else "cannot be downloaded, so the app cannot load its agents, tools, MCP servers and LLM providers")
        imp.add("Configuration", LIST_DOCS[d], how)


def _named(imp: Impact, cfg, reach, records, message: str, probe: dict | None) -> None:
    """Configuration defects: the check names what is wrong; match those names against this configuration."""
    def found(name) -> bool:
        n = str(name or "")
        return len(n) >= 4 and re.search(r"(?<![\w-])" + re.escape(n) + r"(?![\w-])", message) is not None
    for a in cfg.agents:
        if found(a.name):
            imp.add("Agents", a.name, "named by the check as the problem (see What happened)",
                    "reachable from " + ROOT if a.name in reach else f"{ROOT} cannot reach it")
            imp.direct_agents.add(a.name)
            imp.add("Configuration", "agent list (/api/agents)", "contains the defect named in What happened")
    for t in cfg.tools:
        if found(t.name):
            imp.add("Tools", str(t.name), "named by the check as the problem (see What happened)")
            imp.add("Configuration", "tool list (/api/tools)", "contains the defect named in What happened")
    for m in cfg.mcps:
        if found(m.get("name")):
            _mcp(imp, cfg, reach, m, probe)
    for p in cfg.providers:
        if found(p.get("name")):
            _provider(imp, cfg, reach, records, p, probe)


def _callers(imp: Impact, cfg, reach) -> None:
    """Agents that hand off to an affected agent are affected too, indirectly."""
    callers: dict[str, list[str]] = {}
    for target in sorted(imp.direct_agents):
        if target == ROOT:
            continue
        for a in cfg.agents:
            if a.name in reach and target in a.assigned_agents and a.name not in imp.direct_agents:
                callers.setdefault(a.name, []).append(target)
    for caller, targets in callers.items():
        names = targets[0] if len(targets) == 1 else ", ".join(targets[:-1]) + " and " + targets[-1]
        imp.add("Agents", caller, f"hands requests over to {names}, which {'is' if len(targets) == 1 else 'are'} "
                                  "affected", "indirect")


def _summary(imp: Impact) -> str:
    g = imp.ordered()

    def n(kind, one, many):
        c = len(g.get(kind, []))
        return f"{c} {one if c == 1 else many}" if c else ""
    parts = [x for x in (n("Agents", "agent", "agents"), n("Tools", "tool", "tools"),
                         n("MCP servers", "MCP server", "MCP servers"),
                         n("LLM providers", "LLM provider", "LLM providers"),
                         n("Configuration", "configuration entry", "configuration entries"),
                         n("App functions", "app function", "app functions")) if x]
    if not parts:
        return "No agent or tool depends on it; the effect is on a function of the app itself."
    text = ", ".join(parts[:-1]) + (" and " if len(parts) > 1 else "") + parts[-1]
    return f"Affected in this environment's configuration: {text}."


# --- entry point -------------------------------------------------------------------------------

_LLM_SUBJECT = re.compile(r"^LLM provider '(.*)'$")
_MCP_SUBJECT = re.compile(r"^MCP server '(.*)'$")


def analyse(group, records) -> Impact | None:
    """The impact of one root cause (a group of records with the same cause), or None.

    `records` are all health checks of the run (used to see whether a fallback provider also failed).
    Call it only for failures that affect the app."""
    try:
        return _analyse(group, records)
    except Exception:  # noqa: BLE001 - an extra on the card; it must never break the report
        log.exception("Could not work out what a failure affects")
        return None


def _analyse(group, records) -> Impact | None:
    try:
        cfg = remote.config()
    except Exception:  # noqa: BLE001 - nothing to read the configuration from
        return None
    reach = cfg.reachable_from_root()
    imp = Impact()
    explained = False
    for r in group:
        f = r.failure or {}
        probe = f.get("probe")
        subject = (probe or {}).get("subject", "")
        keys = [k for k in (f.get("service_keys") or []) if k and k != "suite"]
        if probe and probe.get("status") == "unexpected_access" and "aihub-service" in keys:
            continue   # a security check, not a download failure: no agent or tool is touched
        m_llm, m_mcp = _LLM_SUBJECT.match(subject), _MCP_SUBJECT.match(subject)
        if m_llm:
            p = next((x for x in cfg.providers if (x.get("name") or x.get("id")) == m_llm.group(1)), None)
            if p is not None:
                _provider(imp, cfg, reach, records, p, probe)
                explained = True
        if m_mcp:
            m = next((x for x in cfg.mcps if x.get("name") == m_mcp.group(1)), None)
            if m is not None:
                _mcp(imp, cfg, reach, m, probe)
                explained = True
        for key in keys:
            if key in usage.NEEDS:
                _agents_and_tools(imp, cfg, reach, key)
                _config_entries(imp, key, probe)
                explained = True
            elif key in CONFIG_FIELDS:
                _config_entries(imp, key, probe)
                explained = True
            elif key == "tavily":
                m = _tavily_server(cfg)
                if m is not None:
                    _mcp(imp, cfg, reach, m, probe)
                    explained = True
            elif key == "aihub-service" and probe:
                # A failed request. Without a probe it is a configuration defect (test_01, 02, 20): the
                # default service key says nothing about what it concerns, so the names in its message do.
                _config_docs(imp, probe)
                explained = True
        if not explained:
            _named(imp, cfg, reach, records, f.get("message", ""), probe)
        if "Agents" not in imp.groups and "Tools" not in imp.groups:
            for key in keys:
                if key != "aihub-service":
                    _app_function(imp, key)
    if not imp.groups:
        return None
    _callers(imp, cfg, reach)
    imp.summary = _summary(imp)
    return imp
