"""
Which external services AgentHubNext uses with the configuration of this run.

Worked out again on every run, from the configuration the run downloaded (or the saved copy
it fell back on). A failure of a service the configuration does not use is reported under
"Failed, no effect on the app" with the reason given here (plugin._failure applies it).

Services and the rule for each, from agent-hub-backend:

  2d-to-3d         TwoDToThreeDClient is called only by ImageTo3DAgentTools.generate_3d_object,
                   and AgentLight uses ImageTo3DAgentTools only for the agent named
                   "ImageTo3DAgent" (AgentLight.cs, tool container selection).
  2d-to-video      TwoDToVideoClient: only ImageToVideoAgentTools.generate_video, agent
                   "ImageToVideoAgent".
  mav-starkit-api  MavStarkitApiClient: generate_3d_object and generate_video (storage),
                   send_file_to_srd (ImageGenerationAgentToolsBase), and the prompt
                   placeholders %existing_3d_objects% / %existing_videos% /
                   %online_srd_devices% of those two agents (BuildRunInnerInstructionsAsync).
  device-mapping   DeviceMappingClient (/starkit-device-mapping): only through
                   GetSrdRoutingStateAsync, i.e. send_file_to_srd and %online_srd_devices%
                   of those two agents.
  deepgram, whisper, vision, sam3
                   configured in the AgentHub section of pat-config; a service whose fields
                   are empty there is switched off by the app (AgentHubRemoteSettings).

An agent counts only when it is in this environment's category and can be reached from
PointAndTalkAgent through AssignedAgents - every session starts with PointAndTalkAgent
(AgentHubSessionManager.GetOrCreateSessionAsync).

Services not listed here are used regardless of the configuration: the AI-Hub service itself,
log upload, Seq. LLM providers and MCP servers are already tested only when, or reported as no
effect unless, an agent uses them (test_20, test_40, test_41).

When the configuration could not be loaded, nothing is marked unused: without it the suite
cannot tell, and the application would not start anyway.
"""
from __future__ import annotations

import functools
from dataclasses import dataclass

from . import remote

IMAGE_TO_3D = "ImageTo3DAgent"
IMAGE_TO_VIDEO = "ImageToVideoAgent"


@dataclass(frozen=True)
class Usage:
    service: str
    used: bool
    why: str          # which part of the configuration uses it, or why nothing does


def _agent_facts(cfg) -> dict[str, dict]:
    reach = cfg.reachable_from_root()
    out = {}
    for name in (IMAGE_TO_3D, IMAGE_TO_VIDEO):
        a = cfg.agent(name)
        out[name] = {
            "defined": a is not None,
            "reachable": a is not None and name in reach,
            "tools": set(t for t in (a.assigned_tools if a else []) if t),
            "prompt": (a.instructions if a else "") or "",
        }
    return out


def _agent_state(name: str, f: dict) -> str:
    if not f["defined"]:
        return f"there is no {name} in this environment"
    if not f["reachable"]:
        return f"{name} cannot be reached from PointAndTalkAgent through AssignedAgents"
    return ""


def _uses(facts: dict, needs: dict[str, tuple[set, set]]) -> tuple[bool, list[str], list[str]]:
    """needs: agent -> (tool names, prompt placeholders). Returns (used, users, reasons not)."""
    users, nots = [], []
    for name, (tools, placeholders) in needs.items():
        f = facts[name]
        state = _agent_state(name, f)
        if state:
            nots.append(state)
            continue
        hits = sorted(f["tools"] & tools) + sorted(p for p in placeholders if p in f["prompt"])
        if hits:
            users.append(f"{name} ({', '.join(hits)})")
        else:
            nots.append(f"{name} is assigned none of {', '.join(sorted(tools))}"
                        + (f" and its prompt has none of {', '.join(sorted(placeholders))}" if placeholders else ""))
    return bool(users), users, nots


def _from_agents(service: str, facts: dict, needs: dict) -> Usage:
    used, users, nots = _uses(facts, needs)
    if used:
        return Usage(service, True, "used by " + "; ".join(users))
    return Usage(service, False, "The configuration of this run does not use it: " + "; ".join(nots) + ".")


def _from_pat(service: str, section: dict | None, fields: list[str]) -> Usage:
    if section is None:
        return Usage(service, True, "pat-config unavailable; assumed used")
    empty = [k for k in fields if not str(section.get(k) or "").strip()]
    if empty:
        return Usage(service, False, f"The AgentHub section of pat-config leaves {', '.join(empty)} empty, so "
                                     "AgentHubNext does not call this service in this environment.")
    return Usage(service, True, f"configured by {', '.join(fields)} in pat-config")


@functools.lru_cache(maxsize=None)
def all_services() -> dict[str, Usage]:
    out: dict[str, Usage] = {}
    try:
        cfg = remote.config()
    except Exception:  # noqa: BLE001 - unloadable or unavailable: reported elsewhere
        cfg = None
    if cfg is not None:
        facts = _agent_facts(cfg)
        placeholders_3d = {"%existing_3d_objects%", "%online_srd_devices%"}
        placeholders_video = {"%existing_videos%", "%online_srd_devices%"}
        out["2d-to-3d"] = _from_agents("2d-to-3d", facts, {IMAGE_TO_3D: ({"generate_3d_object"}, set())})
        out["2d-to-video"] = _from_agents("2d-to-video", facts, {IMAGE_TO_VIDEO: ({"generate_video"}, set())})
        out["mav-starkit-api"] = _from_agents("mav-starkit-api", facts, {
            IMAGE_TO_3D: ({"generate_3d_object", "send_file_to_srd"}, placeholders_3d),
            IMAGE_TO_VIDEO: ({"generate_video", "send_file_to_srd"}, placeholders_video)})
        out["device-mapping"] = _from_agents("device-mapping", facts, {
            IMAGE_TO_3D: ({"send_file_to_srd"}, {"%online_srd_devices%"}),
            IMAGE_TO_VIDEO: ({"send_file_to_srd"}, {"%online_srd_devices%"})})
    try:
        _f, section = remote.agenthub_section()
    except Exception:  # noqa: BLE001
        section = None
    out["deepgram"] = _from_pat("deepgram", section, ["DefaultDeepgramApiKey"])
    out["whisper"] = _from_pat("whisper", section, ["WhisperUrl", "WhisperModel"])
    out["vision"] = _from_pat("vision", section, ["VisionUrl", "VisionModel"])
    out["sam3"] = _from_pat("sam3", section, ["SamPredictTextUrl"])
    return out


def of(service: str) -> Usage | None:
    """The usage of a config-dependent service, or None when the service does not depend on
    the configuration (or the configuration could not be read)."""
    return all_services().get(service)


def unused_reason(service: str) -> str:
    u = of(service)
    return u.why if u is not None and not u.used else ""
