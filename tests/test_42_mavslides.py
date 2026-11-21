"""
MAV Slides (AgentHubNext 4.0.70, configuration source changed in 4.0.71) - the services MavSlidesAgent's
engine calls.

Since 4.0.71 the addresses, keys and model names come from the remote configuration, the `MavSlides` object
inside the AgentHub section of pat-config (AgentHubRemoteSettings.MavSlides -> SlidesService.Configure ->
MavSlidesServiceConfig -> EngineSettings.Create); before they were build secrets. The suite reads the same
object from the pat-config it downloaded (remote.mavslides()), so no MAVSLIDES_* value lives in .env or
suite.env any more. An empty value is "not configured" (EngineSettings.Normalize).

  main / coder LLM   POST {url}/chat/completions   LlmClient.cs (coder and vision fall back to the main
                                                   endpoint when their url and model are both empty)
  vision LLM         same request with one image   LlmClient.CompleteWithImageAsync
  OpenRouter         POST {url}/images             OpenRouterImageClient.cs
  web-search MCP     streamable HTTP, initialize   McpClients.cs, WebSearchClient
  Tavily key         POST api.tavily.com/search    the --api-key of the image-search MCP (McpClients.cs,
                                                   ImageSearchClient) and the api-key header of the web-search MCP

Whether the app uses each service is decided per run in usage.py (MavSlidesAgent assigned which tools).
An empty value is a skipped check when the service is unused and a configuration defect (the app logs
"not configured" and the feature degrades or fails) when it is used.
"""
from __future__ import annotations

import base64

import pytest

from agenthub_health import remote, settings, usage
from agenthub_health.probe import (ConfigDefect, ServiceFailure, Status, call, contract, expect_ok,
                                   expect_refused)

pytestmark = pytest.mark.smoke

ROLES = ["main", "coder", "vision"]
PROMPT = "Reply with the single word PONG."
# OpenRouterOptions.DefaultImageModels, first entry (src/Windows/MavSlides/Engine/EngineSettings.cs).
OPENROUTER_MODEL = "google/gemini-3.1-flash-lite-image"
# The service keys of usage.py, per role.
LLM_SERVICE = {"main": "mavslides-llm", "coder": "mavslides-llm", "vision": "mavslides-vision"}


# --- settings, as EngineSettings builds them -------------------------------------------

IMPACT = {
    "mavslides-llm": "MavSlidesAgent cannot generate or edit presentations: the engine reports the LLM as not configured.",
    "mavslides-openrouter": "Pictures cannot be generated or edited; generation falls back to local placeholders "
                            "(SlidesEngine.CheckConfiguration).",
    "mavslides-websearch": "generate_presentation continues without web knowledge (WebSearchClient.ConfigurationProblem).",
    "mavslides-tavily": "Image search is unavailable (ImageSearchClient.ConfigurationProblem); pictures fall back to "
                        "OpenRouter generation, then to a local placeholder.",
}
# What EngineSettings does when OpenRouterUrl is empty (EngineSettings.OpenRouterUrl default).
OPENROUTER_DEFAULT_URL = "https://openrouter.ai/api/v1"


def _require(service: str, *names: str) -> dict:
    """The named members of AgentHub.MavSlides (pat-config). An empty one skips the check when the app does not
    use the service in this environment, and is a configuration defect otherwise."""
    values = {n: remote.mavslides(n) for n in names}
    missing = [n for n, v in values.items() if not v]
    if missing:
        unused = usage.unused_reason(service)
        if unused:
            pytest.skip(f"MavSlides.{', MavSlides.'.join(missing)} empty. {unused}")
        remote.mavslides(missing[0], service=service, impact=IMPACT.get(service, ""))   # raises ConfigDefect
    return values


def _endpoint(role: str) -> tuple[str, str, str]:
    """(url, key, model) of an LLM role as EngineSettings.Create builds it. Coder / vision with no url and no model
    use the main endpoint; otherwise a missing url or model comes from main, and the key follows the url."""
    p = role.capitalize()
    main = (remote.mavslides("LlmUrl"), remote.mavslides("LlmApiKey"), remote.mavslides("LlmModel"))
    if role == "main":
        return main
    url, model = remote.mavslides(p + "Url"), remote.mavslides(p + "Model")
    if not url and not model:
        return main
    return (url or main[0], main[1] if not url else remote.mavslides(p + "ApiKey"), model or main[2])


def _authorization(key: str) -> dict:
    """LlmClient.SetAuthorization: a key containing a space is sent as it is, anything else as a Bearer token."""
    if not key:
        return {}
    return {"Authorization": key if " " in key else f"Bearer {key}"}


def _suffix(base: str, suffix: str) -> str:
    base = base.rstrip("/")
    return base if base.lower().endswith(suffix) else base + suffix


# --- LLMs --------------------------------------------------------------------------------

def _content(body) -> str | None:
    """LlmClient.ReadContent: choices[0].message.content as a string or an array of text parts."""
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(str(p.get("text") or "") for p in content if isinstance(p, dict))
    return None


@pytest.mark.parametrize("role", ROLES)
def test_llm_answers(role, asset):
    """The MAV Slides LLM (main, coder or vision) answers the request LlmClient sends, with a non-empty message."""
    service = LLM_SERVICE[role]
    url, key, model = _endpoint(role)
    # The effective url / model of coder and vision come from the main endpoint when they set none of
    # their own, so a missing effective value always means the main LLM value is missing.
    missing = [n for n, v in (("LlmUrl", url), ("LlmModel", model)) if not v]
    if missing:
        _require(service, *missing)
    # An empty key is sent as no Authorization header (LlmClient.SetAuthorization): the endpoint decides.
    body = {"model": model, "stream": False}
    if role == "vision":
        image = "data:image/jpeg;base64," + base64.b64encode(asset("probe.jpg").read_bytes()).decode()
        body["messages"] = [{"role": "system", "content": "Describe the image in one short sentence."},
                            {"role": "user", "content": [{"type": "image_url", "image_url": {"url": image}}]}]
    else:
        body["messages"] = [{"role": "system", "content": "You answer with one word."},
                            {"role": "user", "content": PROMPT}]
    res = call(service, f"{role} LLM chat/completions", "POST", _suffix(url, "/chat/completions"),
               headers=_authorization(key), json=body, timeout=settings.TIMEOUT_LLM,
               subject=f"MAV Slides {role} LLM")
    hint = f"Model '{model}'. LlmClient retries transient failures 3 times, this check once."
    expect_ok(res, f"MAV Slides {role} LLM", hint)
    text = _content(res.json)
    contract(res, text is not None and text.strip() != "",
             f"MAV Slides {role} LLM answered 200 but choices[0].message.content is "
             f"{'missing' if text is None else 'empty'}; LlmClient treats that as 'Empty LLM answer'.", hint)


# --- OpenRouter ------------------------------------------------------------------------------

def _openrouter_url() -> str:
    """{OpenRouterUrl}/images; an empty OpenRouterUrl means the public API (EngineSettings.Create)."""
    return (remote.mavslides("OpenRouterUrl") or OPENROUTER_DEFAULT_URL).rstrip("/") + "/images"


def _image_body(prompt: str | None, size: str = "256x256") -> dict:
    """OpenRouterImageClient.CreateBody (without the model list loop); prompt None leaves the field out."""
    body = {"model": OPENROUTER_MODEL, "n": 1, "stream": False, "output_format": "png", "size": size}
    if prompt is not None:
        body["prompt"] = prompt
    return body


def test_openrouter_refuses_without_key():
    """POST {OpenRouter}/images is refused without an Authorization header."""
    res = call("mavslides-openrouter", "images (no key)", "POST", _openrouter_url(), json=_image_body("a red circle"),
               subject="MAV Slides OpenRouter key")
    expect_refused(res, "POST /images without Authorization")


def test_openrouter_key_accepted():
    """POST {OpenRouter}/images accepts the key. The request has no prompt, so it is rejected as invalid (and
    nothing is generated or billed) rather than as unauthorized."""
    v = _require("mavslides-openrouter", "OpenRouterApiKey")
    res = call("mavslides-openrouter", "images (no prompt)", "POST", _openrouter_url(),
               headers=_authorization(v["OpenRouterApiKey"]), json=_image_body(None),
               subject="MAV Slides OpenRouter key")
    hint = ("The key is accepted when the answer is 400 or 422 (invalid request). OpenRouterImageClient also reads "
            "an 'error' object in a 2xx body.")
    if res.http_status == 402:
        raise ServiceFailure(res, "POST /images answered 402: the OpenRouter account has no credit, so image "
                                  "generation and editing fail.", hint)
    if res.status is Status.AUTH_FAILED:
        raise ServiceFailure(res, "POST /images refused the OpenRouter key.", hint)
    if res.http_status in (400, 422):
        return
    err = res.json.get("error") if isinstance(res.json, dict) else None
    if res.ok and isinstance(err, dict):
        if str(err.get("code")) in ("401", "402", "403"):
            raise ServiceFailure(res, f"POST /images answered 2xx with error code {err.get('code')}.", hint)
        return
    if res.ok:
        res.status = Status.UNEXPECTED_ACCESS
        raise ServiceFailure(res, "POST /images accepted a request without a prompt and answered 2xx; an image may "
                                  "have been generated and billed.", hint)
    expect_ok(res, "POST /images with the OpenRouter key", hint)


@pytest.mark.live
def test_openrouter_generates_image():
    """OpenRouter generates a real image for the request OpenRouterImageClient sends. Billable: only with --live."""
    v = _require("mavslides-openrouter", "OpenRouterApiKey")
    res = call("mavslides-openrouter", "images (generate)", "POST", _openrouter_url(),
               headers=_authorization(v["OpenRouterApiKey"]), json=_image_body("a plain red circle on white"),
               timeout=settings.TIMEOUT_GENERATION, subject="MAV Slides OpenRouter key")
    expect_ok(res, "OpenRouter image generation", f"Model '{OPENROUTER_MODEL}', the first of the app's default list.")
    b64 = ""
    try:
        b64 = (res.json["data"][0]["b64_json"] or "")
    except (KeyError, IndexError, TypeError):
        pass
    try:
        raw = base64.b64decode(b64, validate=True) if b64 else b""
    except ValueError:
        raw = b""
    magic = (raw[:8] == b"\x89PNG\r\n\x1a\n" or raw[:3] == b"\xff\xd8\xff" or raw[:4] == b"RIFF")
    contract(res, magic, "OpenRouter answered 200 but data[0].b64_json is not a PNG, JPEG or WebP image; "
                         "OpenRouterImageClient.Decode throws 'does not contain an image'.")


# --- web-search MCP and Tavily ----------------------------------------------------------------

def test_websearch_mcp_completes_handshake():
    """The MAV Slides web-search MCP (streamable HTTP) answers 'initialize' with the headers WebSearchClient sends."""
    v = _require("mavslides-websearch", "WebSearchMcpUrl")
    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    token = remote.mavslides("WebSearchMcpToken")
    if token:
        headers["Authorization"] = token if " " in token else f"Bearer {token}"
    if remote.mavslides("TavilyApiKey"):
        headers["api-key"] = remote.mavslides("TavilyApiKey")
    body = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                       "clientInfo": {"name": "agenthub-health", "version": "1.0"}}}
    res = call("mavslides-websearch", "initialize", "POST", v["WebSearchMcpUrl"], headers=headers,
               json=body, subject="MAV Slides web-search MCP")
    hint = "WebSearchClient connects lazily; when it fails the engine continues without web knowledge."
    expect_ok(res, "MAV Slides web-search MCP initialize", hint)
    contract(res, '"result"' in res.body or (isinstance(res.json, dict) and "result" in res.json),
             "The web-search MCP answered 200 but without a JSON-RPC result.", hint)


def test_tavily_key_returns_images():
    """The Tavily key MAV Slides ships with is accepted by Tavily Search and returns images (one search per run)."""
    v = _require("mavslides-tavily", "TavilyApiKey")
    key = v["TavilyApiKey"]
    body = {"query": "wooden chair", "max_results": 5, "include_images": True, "include_image_descriptions": True}
    headers = {"Authorization": f"Bearer {key}", "accept": "application/json",
               "content-type": "application/json", "X-Client-Source": "MCP"}
    res = call("mavslides-tavily", "search", "POST", settings.TAVILY_SEARCH_URL, headers=headers, json=body,
               timeout=60, subject="MAV Slides Tavily key")
    hint = "Same request as the image-search MCP's tavilySearch (src/Windows/MavSlides/Engine/McpClients.cs)."
    expect_ok(res, "Tavily search with the MAV Slides key", hint)
    images = res.json.get("images") if isinstance(res.json, dict) else None
    contract(res, isinstance(images, list) and len(images) > 0,
             "Tavily answered 200 without any images, so the image-search MCP finds nothing for a slide.", hint)


# --- the configuration side ---------------------------------------------------------------------

EXPECTED_TOOLS = ["generate_presentation", "open_presentation", "show_slide", "edit_slide", "edit_slide_image",
                  "get_presentation_state", "close_presentation"]
PLACEHOLDER = "%existing_presentations%"


def test_agent_has_its_tools_and_prompt_placeholder():
    """MavSlidesAgent, when this environment defines it, is assigned the seven tools MavSlidesAgentTools implements and
    keeps the %existing_presentations% placeholder its prompt relies on."""
    cfg = remote.config()
    agent = cfg.agent(usage.MAV_SLIDES)
    if agent is None:
        pytest.skip("MavSlidesAgent is not defined in this environment (the feature is not rolled out here).")
    missing = [t for t in EXPECTED_TOOLS if t not in agent.assigned_tools]
    if missing:
        raise ConfigDefect(
            f"MavSlidesAgent is not assigned: {', '.join(missing)}.",
            "SlidesService.IsSlidesTool / MavSlidesAgentTools implement these tool names; the agent prompt names all seven.",
            "The agent tells the user to use a tool it does not have, or cannot perform that part of the request.",
            "Assign the missing tools to MavSlidesAgent in Maverick Config Manager.")
    if PLACEHOLDER not in (agent.instructions or ""):
        raise ConfigDefect(
            f"The prompt of MavSlidesAgent does not contain {PLACEHOLDER}.",
            "SlidesService.InjectSystemPromptContextAsync fills that placeholder with the saved presentations.",
            "The agent does not know which presentations exist, so it creates duplicates or cannot open one.",
            "Restore the placeholder in the agent prompt in Maverick Config Manager.")
