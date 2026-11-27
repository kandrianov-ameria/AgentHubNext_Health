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
  mavslides-llm    MAV Slides engine (src/Windows/MavSlides/Engine/SlidesEngine.cs): the main and
                   coder LLM are called by generate_presentation (structure, slide HTML) and
                   edit_slide (_coder.CompleteAsync) and, since 4.0.74, insert_slide (_llm plans the
                   slide, _coder writes its HTML), agent "MavSlidesAgent" (SlidesService.IsAgent).
  mavslides-openrouter
                   OpenRouterImageClient: edit_slide_image (SlidesEngine.EditImageAsync) and, as the
                   fallback for pictures, generate_presentation (SlideImageService.ProduceAsync).
  mavslides-websearch, mavslides-tavily
                   WebSearchClient and the image-search MCP: generate_presentation only
                   (SlidesEngine web knowledge, SlideImageService.SearchAsync).
  mavslides-vision ImageCorrection runs only when "remove watermarks" or "expand web images" is on in
                   the AgentHub settings (EngineSettings.Images, both off by default). That setting
                   lives on each PC (agenthub.settings.json), which the suite cannot see, so the
                   service is always reported as unused.
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
MAV_SLIDES = "MavSlidesAgent"

VISION_OPTIONS_OFF = ("MAV Slides calls its vision model only when 'remove watermarks from web images' or "
                      "'expand web images' is switched on in the AgentHub settings window. Both are off by "
                      "default (MavSlidesOptions) and the setting lives on each PC, where this suite cannot "
                      "see it, so a failure here is reported as having no effect.")


@dataclass(frozen=True)
class Usage:
    service: str
    used: bool
    why: str          # which part of the configuration uses it, or why nothing does


def _agent_facts(cfg) -> dict[str, dict]:
    reach = cfg.reachable_from_root()
    out = {}
    for name in (IMAGE_TO_3D, IMAGE_TO_VIDEO, MAV_SLIDES):
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


_PLACEHOLDERS_3D = {"%existing_3d_objects%", "%online_srd_devices%"}
_PLACEHOLDERS_VIDEO = {"%existing_videos%", "%online_srd_devices%"}

# service key -> {agent: (local tools it must have assigned, prompt placeholders it must contain)}.
# One table for two readers: all_services() below (is the service used?) and impact.py (which agents
# and tools does a failure of it touch?). Rules and their source are described in the docstring above.
NEEDS: dict[str, dict[str, tuple[set, set]]] = {
    "2d-to-3d": {IMAGE_TO_3D: ({"generate_3d_object"}, set())},
    "2d-to-video": {IMAGE_TO_VIDEO: ({"generate_video"}, set())},
    "mav-starkit-api": {
        IMAGE_TO_3D: ({"generate_3d_object", "send_file_to_srd"}, _PLACEHOLDERS_3D),
        IMAGE_TO_VIDEO: ({"generate_video", "send_file_to_srd"}, _PLACEHOLDERS_VIDEO)},
    "device-mapping": {
        IMAGE_TO_3D: ({"send_file_to_srd"}, {"%online_srd_devices%"}),
        IMAGE_TO_VIDEO: ({"send_file_to_srd"}, {"%online_srd_devices%"})},
    "mavslides-llm": {MAV_SLIDES: ({"generate_presentation", "edit_slide", "insert_slide"}, set())},
    "mavslides-openrouter": {MAV_SLIDES: ({"edit_slide_image", "generate_presentation"}, set())},
    "mavslides-websearch": {MAV_SLIDES: ({"generate_presentation"}, set())},
    "mavslides-tavily": {MAV_SLIDES: ({"generate_presentation"}, set())},
}


@functools.lru_cache(maxsize=None)
def all_services() -> dict[str, Usage]:
    out: dict[str, Usage] = {}
    try:
        cfg = remote.config()
    except Exception:  # noqa: BLE001 - unloadable or unavailable: reported elsewhere
        cfg = None
    if cfg is not None:
        facts = _agent_facts(cfg)
        for service, needs in NEEDS.items():
            out[service] = _from_agents(service, facts, needs)
    out["mavslides-vision"] = Usage("mavslides-vision", False, VISION_OPTIONS_OFF)
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
