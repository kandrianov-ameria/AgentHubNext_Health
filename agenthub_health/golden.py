"""
Golden scenarios (since 1.13.0): the 13 golden scenarios of AgentHubNext_GoldenScenarios_v1.1.xlsx
(sheet Scenarios, Set = Golden) as far as this suite can see them. Kept apart from the health checks:
nothing here changes the verdict, the counts, the history or the exit status; the report shows it in
its own section.

A golden scenario is a whole user journey (voice, pointing, screenshot, answer, tools, devices). The
suite sees only the part that lives in remote services and configuration, so it reports two things:

1. READINESS, worked out at the end of the run, with no request of its own: for each scenario the
   things it needs - the agents and tools in this environment's configuration (reachable from
   PointAndTalkAgent, assigned to the agent that calls them), the MCP servers, the services behind
   them, the LLM provider of PointAndTalkAgent, speech to text - each taken from the checks that ran
   in this run. "Blocked" means a check of the run against something the scenario needs failed.
2. REPLAYS (tests/test_60_golden_replay.py), for the three scenarios that are one model call over a
   screenshot (GS-03.1, GS-10.1, GS-11.1): the screenshot and the spoken request go to the model of
   PointAndTalkAgent with its system prompt, built as AgentLight.BuildSystemMessage and
   BuildUserMessage build them, and the text of the answer is checked against the workbook's pass
   criteria that can be read from text.

What stays manual is named on every scenario (`manual` in golden_scenarios.json). The catalogue is
data: golden_scenarios.json (descriptive columns copied from the workbook; `needs` and `replay` are
this suite's own and grounded in agent-hub-backend / the QAS configuration).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import remote

CATALOGUE_FILE = Path(__file__).resolve().parent / "golden_scenarios.json"
ROOT_AGENT = remote.ROOT_AGENT

# Filled by tests/test_60_golden_replay.py: scenario id -> what was sent and what came back.
REPLAYS: dict[str, dict] = {}


def catalogue() -> list[dict]:
    return json.loads(CATALOGUE_FILE.read_text(encoding="utf-8"))["scenarios"]


# ---- readiness ------------------------------------------------------------------------

OK, WARN, BAD, UNKNOWN = "ok", "warn", "bad", "unknown"


@dataclass
class Need:
    label: str
    state: str
    detail: str


@dataclass
class Readiness:
    scenario: dict
    state: str = "ready"           # ready | degraded | blocked | unknown
    needs: list[Need] = field(default_factory=list)


def _keys(r) -> set[str]:
    keys = {p["service"] for p in r.probes if p.get("service")}
    fp = (r.failure or {}).get("probe")
    if fp and fp.get("service"):
        keys.add(fp["service"])
    return keys


def _tool_assigned(agent, tool: str) -> bool:
    m = re.match(r"^\[(.*?)\](.*)$", tool)
    if m:
        return tool in agent.assigned_mcps
    return tool in agent.assigned_tools


def _verdict_from(records, matcher, what: str) -> Need | None:
    """State of what the matching records say: any failed -> bad, all passed -> ok, none -> None."""
    hits = [r for r in records if matcher(r)]
    bad = [r for r in hits if r.category == "failed"]
    unused = [r for r in hits if r.category == "unused"]
    if bad:
        return Need(what, BAD, "Failed in this run: " + "; ".join(r.objective for r in bad[:3]))
    if unused:
        return Need(what, WARN, "A check failed, but the configuration of this run does not use it: "
                                + "; ".join(r.objective for r in unused[:3]))
    if any(r.category in ("passed", "known_fixed") for r in hits):
        return Need(what, OK, f"{sum(r.category == 'passed' for r in hits)} check(s) passed.")
    return None


def _service_need(records, key: str, why: str = "") -> Need:
    label = f"Service {key}" + (f" ({why})" if why else "")
    return _verdict_from(records, lambda r: key in _keys(r), label) or Need(
        label, UNKNOWN, "No check against it ran in this run (marker filter, or the check was skipped).")


def _mcp_need(cfg, records, name: str) -> Need:
    label = f"MCP server {name}"
    m = next((x for x in cfg.mcps if x.get("name") == name), None)
    if m is None:
        return Need(label, BAD, "There is no MCP server of this name in the configuration.")
    # test_40 / test_41 are parametrised by server name; their ids end in [<name>].
    tag = f"[{name}]"
    got = _verdict_from(records, lambda r: r.module in ("test_40_mcp_servers", "test_41_tavily_image_mcp")
                        and r.nodeid.endswith(tag), label)
    if got is not None:
        return got
    return Need(label, OK if m.get("type") == "stdio" else UNKNOWN,
                "Defined (stdio, runs only on the Maverick machine; the suite checks its definition, not the process)."
                if m.get("type") == "stdio" else "Defined, but no handshake check ran in this run.")


def _llm_need(cfg, records, agent_name: str) -> Need:
    label = f"LLM provider of {agent_name}"
    a = cfg.agent(agent_name)
    if a is None:
        return Need(label, BAD, f"{agent_name} is not defined.")
    states = []
    for role, pid in (("primary", a.llm_provider_id), ("secondary", a.secondary_llm_provider_id)):
        if pid is None:
            continue
        p = cfg.provider(pid)
        if p is None:
            states.append((role, "?", BAD, "no provider with this id"))
            continue
        ident = f"{p.get('name') or p.get('id')}-{p.get('provider_type')}"
        n = _verdict_from(records, lambda r, ident=ident: r.module == "test_20_llm_providers"
                          and f"[{ident}]" in r.objective, "")
        states.append((role, ident, n.state if n else UNKNOWN, n.detail if n else "not probed in this run"))
    if not states:
        return Need(label, BAD, "The agent has no LLM provider.")
    prim = states[0]
    if all(s[2] == BAD for s in states):
        return Need(label, BAD, "; ".join(f"{r} {i}: {d}" for r, i, _s, d in states))
    if prim[2] == BAD:
        return Need(label, WARN, f"The primary provider failed ({prim[3]}); the agent falls back to its "
                                 "secondary provider.")
    if all(s[2] == OK for s in states[:1]):
        return Need(label, OK, f"{prim[1]} answered.")
    return Need(label, UNKNOWN, "; ".join(f"{r} {i}: {d}" for r, i, _s, d in states))


def _speech_need(records) -> Need:
    label = "Speech to text (Deepgram or Whisper)"
    d = _verdict_from(records, lambda r: "deepgram" in _keys(r), "")
    w = _verdict_from(records, lambda r: "whisper" in _keys(r), "")
    st = [x.state if x else UNKNOWN for x in (d, w)]
    if all(s == BAD for s in st):
        return Need(label, BAD, "Both Deepgram and Whisper failed in this run.")
    if BAD in st:
        return Need(label, WARN, "One of Deepgram and Whisper failed in this run; which one the app uses "
                                 "is not known to the suite.")
    if all(s == OK for s in st):
        return Need(label, OK, "Deepgram and Whisper both answered.")
    return Need(label, UNKNOWN, "Not every speech service was checked in this run.")


def _one(need: dict, cfg, records) -> Need:
    kind = need["kind"]
    if kind == "speech":
        return _speech_need(records)
    if kind == "llm":
        return _llm_need(cfg, records, need["agent"])
    if kind == "service":
        return _service_need(records, need["service"], need.get("why", ""))
    if kind == "mcp":
        return _mcp_need(cfg, records, need["name"])
    if kind == "agent":
        label = f"Agent {need['agent']}"
        if cfg.agent(need["agent"]) is None:
            return Need(label, BAD, "Not defined in this environment.")
        if need["agent"] not in cfg.reachable_from_root():
            return Need(label, BAD, f"Defined, but {ROOT_AGENT} has no AssignedAgents path to it.")
        return Need(label, OK, f"Defined and reachable from {ROOT_AGENT}.")
    if kind == "tool":
        label = f"{need['agent']} has {need['tool']}"
        a = cfg.agent(need["agent"])
        if a is None:
            return Need(label, BAD, f"{need['agent']} is not defined in this environment.")
        if need["agent"] != ROOT_AGENT and need["agent"] not in cfg.reachable_from_root():
            return Need(label, BAD, f"{need['agent']} cannot be reached from {ROOT_AGENT}.")
        if not _tool_assigned(a, need["tool"]):
            return Need(label, BAD, "Not in the agent's AssignedMCPs/AssignedTools.")
        return Need(label, OK, "Assigned.")
    if kind == "placeholder":
        label = f"{need['agent']} prompt has {need['text']}"
        a = cfg.agent(need["agent"])
        if a is None:
            return Need(label, BAD, f"{need['agent']} is not defined in this environment.")
        if need["text"] not in a.instructions:
            return Need(label, BAD, "The prompt lacks it, so the agent does not know the stored objects.")
        return Need(label, OK, "Present.")
    return Need(str(need), UNKNOWN, "Unknown kind of need.")


def evaluate(records) -> list[Readiness]:
    """Readiness of every golden scenario. `records` are the health checks of this run (not the
    golden replays). When the configuration cannot be loaded, every scenario is blocked by that."""
    out: list[Readiness] = []
    try:
        cfg = remote.config()
    except Exception as exc:  # noqa: BLE001 - reported in every scenario
        why = getattr(exc, "message", None) or str(exc)
        for s in catalogue():
            out.append(Readiness(s, "blocked", [Need("Remote configuration", BAD, why)]))
        return out
    for s in catalogue():
        needs = [_one(n, cfg, records) for n in s["needs"]]
        states = {n.state for n in needs}
        state = "blocked" if BAD in states else "degraded" if WARN in states else \
            "unknown" if UNKNOWN in states else "ready"
        out.append(Readiness(s, state, needs))
    return out


def summarise(rows: list[Readiness]) -> dict:
    return {k: sum(r.state == k for r in rows) for k in ("ready", "degraded", "blocked", "unknown")}


# ---- replay ---------------------------------------------------------------------------

def strip_tags(text: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", text or "").replace("&nbsp;", " ").split())


def run_checks(answer: str, checks: list[dict]) -> list[tuple[str, bool, str]]:
    """The criteria of a replay, each as (label, passed, detail). Reads the answer as plain text."""
    plain = strip_tags(answer)
    low = plain.lower()
    results = []
    for c in checks:
        t = c["type"]
        if t == "all":
            missing = [x for x in c["terms"] if x.lower() not in low]
            results.append((c["label"], not missing, "missing: " + ", ".join(missing) if missing else "found"))
        elif t == "any":
            hit = [x for x in c["terms"] if x.lower() in low]
            results.append((c["label"], bool(hit), f"found '{hit[0]}'" if hit else "none of: " + ", ".join(c["terms"])))
        elif t == "min_terms":
            hit = [x for x in c["terms"] if x.lower() in low]
            results.append((c["label"], len(hit) >= c["n"], f"found {len(hit)}: {', '.join(hit) or 'none'}"))
        elif t == "none_of":
            hit = [x for x in c["terms"] if x.lower() in low]
            results.append((c["label"], not hit, "found: " + ", ".join(hit) if hit else "none found"))
        elif t == "max_words":
            n = len(plain.split())
            results.append((c["label"], n <= c["n"], f"{n} words"))
        elif t == "no_other_numbers":
            # Only decimal values count (the chart shows 1.2 / 1.5 / 1.9 / 2.6). Integers are labels (Q1, 3D) or
            # derived figures (+117 %), and a number followed by % is a percentage, not a chart value.
            nums = re.findall(r"(?<![A-Za-z\d.,])\d+[.,]\d+(?![\d%])(?!\s*%)", plain)
            base = [float(x) for x in c["allowed"] if "." in x]
            # differences between two chart values (e.g. 2.6 - 1.9 = 0.7) are correct derived figures
            derived = {f"{abs(a - b):.1f}" for a in base for b in base if a != b}
            other = sorted({x.replace(",", ".") for x in nums} - set(c["allowed"]) - derived)
            results.append((c["label"], not other, "other numbers: " + ", ".join(other) if other else "none"))
        else:
            results.append((c["label"], False, f"unknown check type {t}"))
    return results


def system_prompt(cfg, agent) -> str:
    """AgentLight.BuildSystemMessage: the agent's InnerInstructions with %sub-agents% and the date,
    time and path placeholders replaced. (Known facts about the user and the injected prompt
    context of the generation agents are not added: they depend on the device.)"""
    import datetime as _dt
    inject = ("#Sub-Agents and Skills\nYou can delegate instructions to another sub-agent for them to carry out "
              "the assigned task.\r\nIn cases where you need to do something connected with what another agent can "
              "handle, use the handoff_to_agent tool, specify the agent's name and provide detailed instructions for "
              "them.\r\nList of sub-agents::\n")
    for name in agent.assigned_agents:
        sub = cfg.agent(name)
        if sub is not None:
            inject += f" - Agent name: {sub.name}\n   Description: {(sub.schema or {}).get('AgentDescription')}\n"
    now = _dt.datetime.now()
    return (agent.instructions.replace("%sub-agents%", inject)
            .replace("%current_date%", now.strftime("%Y-%m-%d")).replace("%current_time%", now.strftime("%H:%M"))
            .replace("%personal_data_path%", r"C:\Users\<user>\AppData\Local\Maverick\personal"))
