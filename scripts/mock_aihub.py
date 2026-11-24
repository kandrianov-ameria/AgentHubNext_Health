"""
Local mock of the AI-Hub configuration service (plus one OpenAI-style LLM and one HTTP MCP)
for verifying changes to agenthub-health without touching the real services. Every value in
it is fake.

    python scripts/mock_aihub.py            listens on 127.0.0.1:8765

Point a test copy of the suite at it with a separate .env (never the real one); a value
set in .env overrides suite.env, so the base URL can go there too:
    AIHUB_SERVICE_BASE_URL=http://127.0.0.1:8765
    AIHUB_WIN_TOKEN=12|mocktokenmocktokenmocktoken
and set NO_PROXY=127.0.0.1 when a proxy is configured.

The scenario is read from mode.txt next to this script on every request:
    healthy     everything valid
    down        every configuration endpoint answers 503 (fallback to the saved copy)
    agents-500  /api/agents answers 500
    empty       /api/tools answers 200 with an empty body
    notjson     /api/mcps answers 200 with HTML
    badtypes    an agent has llm_provider_id null (Json.NET throws) and a numeric string
    notes       only values Json.NET converts silently
    pat-bad     RemoteSyncOnSessionCreate is the string "true" (System.Text.Json throws)
    pat-down    pat-config answers 502
    lowtier-ok / lowtier-bad / lowtier-badtype   low_tier_llm_provider_id valid / unknown id (warning only) / "abc" (throws)
    dupheader   a provider has the Authorization header twice (GetHeaders throws)
    imagegen    PointAndTalkAgent hands off to an ImageTo3DAgent with generate_3d_object, and
                WhisperUrl is empty (exercises agenthub_health/usage.py)
    slides      PointAndTalkAgent hands off to MavSlidesAgent (11 tools, prompt with the placeholder);
                the MAV Slides endpoints below answer (LLM /v1/chat/completions, OpenRouter /openrouter/images,
                web-search MCP /mcp, Tavily /tavily/search). Fake keys: Authorization "Bearer slideskeyslideskey1"
    slides-rejected   as slides, but OpenRouter and Tavily reject the key (401) and the LLM answers an empty message
    slides-nocredit   as slides, but OpenRouter answers 402
    slides-noplaceholder   as slides, but the prompt lacks %existing_presentations% and show_slide is not assigned
  Since AgentHub 4.0.71 the service credentials are in the AgentHub section of pat-config (AgentHubRemoteSettings):
  every mode carries MavStarkitApiKey and DeviceMappingBearerToken, and the slides modes carry the MavSlides object
  (LLM, OpenRouter, web-search MCP, Tavily, all pointing at this mock). More modes for that section:
    creds-missing   MavStarkitApiKey and DeviceMappingBearerToken are empty
    token-bearer    DeviceMappingBearerToken starts with "Bearer "
    slides-missing  as slides, but MavSlides.LlmUrl / LlmModel / OpenRouterApiKey are empty
    slides-nosection  as slides, but the AgentHub section has no MavSlides object at all (an older server)
    slides-badtype  as slides, but MavSlides is a string and MavSlides.LlmUrl would be a number (System.Text.Json throws)
Services other than these are not mocked; their checks fail with connection errors.
"""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MODE = Path(__file__).with_name("mode.txt")
TOKEN = "Bearer 12|mocktokenmocktokenmocktoken"
PORT = 8765

def agents(mode):
    base = [
        {"category": "QAS", "keyword": "PointAndTalkAgent", "version": 1, "llm_provider_id": 1,
         "secondary_llm_provider_id": None, "low_tier_llm_provider_id": None,
         "json_schema": {"Name": "PointAndTalkAgent", "InnerInstructions": "Use memory_search. Hand off to HelperAgent.",
                         "AssignedTools": ["memory_search"], "AssignedMCPs": ["[srv]lookup"],
                         "AssignedAgents": ["HelperAgent"], "MaxTokenCount": 1000}},
        {"category": "QAS", "keyword": "HelperAgent", "version": 1, "llm_provider_id": 1,
         "json_schema": {"Name": "HelperAgent", "AssignedTools": [], "AssignedAgents": []}},
        {"category": "DEV", "keyword": "Other", "version": 1, "llm_provider_id": 99, "json_schema": {"Name": "Other"}},
    ]
    if mode == "imagegen":
        base[0]["json_schema"]["AssignedAgents"] = ["HelperAgent", "ImageTo3DAgent"]
        base.append({"category": "QAS", "keyword": "ImageTo3DAgent", "version": 1, "llm_provider_id": 1,
                     "json_schema": {"Name": "ImageTo3DAgent", "AssignedTools": ["generate_3d_object"],
                                     "InnerInstructions": "Known objects: %existing_3d_objects%"}})
    if mode.startswith("slides"):
        base[0]["json_schema"]["AssignedAgents"] = ["HelperAgent", "MavSlidesAgent"]
        tools_ = list(SLIDES_TOOLS)
        prompt = "Presentations: %existing_presentations%"
        if mode == "slides-noplaceholder":
            tools_.remove("show_slide")
            prompt = "Presentations: none"
        base.append({"category": "QAS", "keyword": "MavSlidesAgent", "version": 1, "llm_provider_id": 1,
                     "json_schema": {"Name": "MavSlidesAgent", "AssignedTools": tools_, "InnerInstructions": prompt}})
    if mode == "badtypes":
        base[1]["llm_provider_id"] = None           # fatal: null into int
        base[0]["json_schema"]["MaxTokenCount"] = "1000"   # note
    if mode == "notes":
        base[0]["json_schema"]["MaxTokenCount"] = "1000"   # note only
        base[1]["llm_provider_id"] = "1"                   # note only
    if mode == "lowtier-ok":
        base[0]["low_tier_llm_provider_id"] = 1
    if mode == "lowtier-bad":
        base[0]["low_tier_llm_provider_id"] = 99           # app warns and ignores (4.0.72)
    if mode == "lowtier-badtype":
        base[0]["low_tier_llm_provider_id"] = "abc"        # Json.NET throws
    return base

SLIDES_TOOLS = ["generate_presentation", "open_presentation", "show_slide", "edit_slide", "edit_slide_image",
                "insert_slide", "delete_slides", "undo_change", "redo_change",
                "get_presentation_state", "close_presentation"]

def tools(mode):
    extra = [{"category": "QAS", "keyword": "generate_3d_object", "json_schema": {"name": "generate_3d_object"}}] \
        if mode == "imagegen" else []
    if mode.startswith("slides"):
        extra += [{"category": "QAS", "keyword": t, "json_schema": {"name": t}} for t in SLIDES_TOOLS]
    return extra + [{"category": "QAS", "keyword": "memory_search", "json_schema": {"name": "memory_search"}},
            {"category": "QAS", "keyword": "lookup", "json_schema": {"name": "lookup", "mcp": "srv"}}]

def mcps(mode):
    return [{"id": 1, "name": "srv", "type": "streamable_http", "url": f"http://127.0.0.1:{PORT}/mcp",
             "headers": "Authorization: Bearer mcpsecretmcpsecret123"}]

def providers(mode):
    p = [{"id": 1, "name": "mock-openai", "provider_type": "open_ai", "base_url": f"http://127.0.0.1:{PORT}/v1",
          "model": "gpt-mock", "primary": 1, "headers": "Authorization: Bearer sk-llmsecretllmsecret9999"},
         {"id": 2, "name": "mock-embed", "provider_type": "open_ai_embedding", "base_url": f"http://127.0.0.1:{PORT}/v1",
          "model": "emb", "primary": True, "headers": "Authorization: Bearer sk-embsecretembsecret8888"}]
    if mode == "dupheader":
        p[0]["headers"] = "Authorization: Bearer sk-llmsecretllmsecret9999\nAuthorization: Bearer x"
    return p

def pat(mode):
    sec = {"DefaultDeepgramApiKey": "dgsecretdgsecret7777", "WhisperUrl": f"http://127.0.0.1:{PORT}/transcribe/",
           "WhisperModel": "whisper-large-v3", "ProxyAuthHeader": "Basic cHJveHk6c2VjcmV0cHJveHk=",
           "RemoteSyncOnSessionCreate": False, "SpeechToTextUrl": f"http://127.0.0.1:{PORT}/transcribe/"}
    if mode == "imagegen":
        sec["WhisperUrl"] = ""
    sec["MavStarkitApiKey"] = "starkitkeystarkitkey5555"
    sec["DeviceMappingBearerToken"] = "21|devicetokendevicetoken4444"
    if mode.startswith("slides"):
        base = f"http://127.0.0.1:{PORT}"
        sec["MavSlides"] = {"LlmUrl": f"{base}/v1", "LlmApiKey": "slideskeyslideskey1", "LlmModel": "slides-mock",
                            "OpenRouterUrl": f"{base}/openrouter", "OpenRouterApiKey": "slideskeyslideskey1",
                            "TavilyApiKey": "slidestavilyslidestavily1", "WebSearchMcpUrl": f"{base}/mcp",
                            "WebSearchMcpToken": "slideswebtokenslideswebtoken"}
    if mode == "slides-missing":
        sec["MavSlides"].update({"LlmUrl": "", "LlmModel": "", "OpenRouterApiKey": ""})
    if mode == "slides-nosection":
        sec.pop("MavSlides", None)
    if mode == "slides-badtype":
        sec["MavSlides"] = "not an object"
    if mode == "creds-missing":
        sec["MavStarkitApiKey"] = ""
        sec["DeviceMappingBearerToken"] = ""
    if mode == "token-bearer":
        sec["DeviceMappingBearerToken"] = "Bearer " + sec["DeviceMappingBearerToken"]
    if mode == "pat-bad":
        sec["RemoteSyncOnSessionCreate"] = "true"
    return {"AgentHub": sec, "PointAndTalk.Other": {"x": 1}}

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else (json.dumps(body) if not isinstance(body, str) else body).encode()
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(data)))
        self.end_headers(); self.wfile.write(data)
    def do_GET(self):
        mode = MODE.read_text().strip() if MODE.exists() else "healthy"
        path = self.path.split("?")[0]
        if path.startswith("/api/"):
            if self.headers.get("Authorization") != TOKEN:
                return self._send(401, {"message": "Unauthenticated."})
            ent = path[5:]
            if mode == "down":
                return self._send(503, "<html>Service Unavailable</html>", "text/html")
            if mode == "agents-500" and ent == "agents":
                return self._send(500, {"error": "boom"})
            if mode == "empty" and ent == "tools":
                return self._send(200, b"")
            if mode == "notjson" and ent == "mcps":
                return self._send(200, "<html>login</html>", "text/html")
            if ent.startswith("pat-config/"):
                env = ent.split("/", 1)[1]
                if env not in ("DEV", "QAS", "STG", "PRD"):
                    return self._send(404, {"message": "Environment not found"})
                if mode == "pat-down":
                    return self._send(502, "bad gateway", "text/plain")
                return self._send(200, pat(mode))
            fn = {"agents": agents, "tools": tools, "mcps": mcps, "llm-providers": providers}.get(ent)
            if not fn:
                return self._send(404, {})
            return self._send(200, fn(mode))
        self._send(404, {})
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0); raw = self.rfile.read(n)
        path = self.path
        mode = MODE.read_text().strip() if MODE.exists() else "healthy"
        slides_ok = self.headers.get("Authorization") == "Bearer slideskeyslideskey1"
        if path == "/openrouter/images":
            if not slides_ok or mode == "slides-rejected":
                return self._send(401, {"error": {"code": 401, "message": "No auth credentials found"}})
            if mode == "slides-nocredit":
                return self._send(402, {"error": {"code": 402, "message": "Insufficient credits"}})
            try:
                has_prompt = bool(json.loads(raw).get("prompt"))
            except ValueError:
                has_prompt = False
            if not has_prompt:
                return self._send(400, {"error": {"code": 400, "message": "prompt is required"}})
            png = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg==")
            return self._send(200, {"data": [{"b64_json": png}]})
        if path == "/tavily/search":
            if self.headers.get("Authorization") != "Bearer slidestavilyslidestavily1" or mode == "slides-rejected":
                return self._send(401, {"detail": {"error": "Unauthorized: missing or invalid API key."}})
            return self._send(200, {"results": [], "images": [{"url": "http://x/y.jpg", "description": "chair"}]})
        if path.endswith("/chat/completions"):
            if mode == "slides-rejected" and slides_ok:
                return self._send(200, {"choices": [{"message": {"role": "assistant", "content": ""}}]})
            return self._send(200, {"choices": [{"message": {"role": "assistant", "content": "PONG"}}]})
        if path.endswith("/embeddings"):
            return self._send(200, {"data": [{"embedding": [0.1, 0.2]}]})
        if path == "/mcp":
            return self._send(200, {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2025-03-26", "capabilities": {}, "serverInfo": {"name": "m", "version": "1"}}})
        self._send(404, {})

ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
