"""
Facts about every external dependency, used to explain failures in the report.
Each statement is taken from the agent-hub-backend source or its docs/ folder;
the location is given so a reader can check it.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Service:
    key: str
    title: str
    owner: str
    credential: str        # where the app keeps the credential
    impact: str            # what breaks in AgentHubNext when this service fails
    rotation: str = ""     # what fixing a rejected credential takes


REBUILD = ("The credential is a constant compiled into AgentHubNext, so replacing it needs a new "
           "build, a new package and a rollout through Maverick Web Manager. After updating the "
           "source, run scripts/refresh_env.py so this suite tests the new value.")

SERVICES: dict[str, Service] = {s.key: s for s in [
    Service(
        "aihub-service", "AI-Hub service (Windows)", "AI-Hub team / Maverick Config Manager",
        "WindowsApiToken in src/AgentHub/RemoteConfiguration/RemoteConfigurationManager.cs",
        "RemoteConfigurationManager.LoadString throws on any non-2xx answer, so GetConfigurationAsync "
        "cannot download agents, tools, MCPs or LLM providers. For pat-config, RemoteSettingsManager "
        "falls back to the encrypted cache and logs a warning; with no cache the application shuts "
        "down (docs/pat-config-api.md).",
        REBUILD),
    Service(
        "device-mapping", "AI-Hub device mapping", "AI-Hub team",
        "DeviceMappingBearerToken in src/Ameria.LlmExecutionEngine/Services/ImageTo3DAgentSettings.cs",
        "send_file_to_srd and the %online_srd_devices% prompt placeholder of ImageTo3DAgent and "
        "ImageToVideoAgent cannot resolve which Starkit controllers are paired with this AgentHub "
        "(DeviceMappingClient, ImageGenerationAgentToolsBase.GetSrdRoutingStateAsync).",
        REBUILD),
    Service(
        "log-upload", "AI-Hub log upload", "AI-Hub team",
        "DeviceMappingBearerToken in src/Ameria.LlmExecutionEngine/Services/ImageTo3DAgentSettings.cs "
        "(LogUploadService sends it to /api/logs-session, SessionImageUploader to /api/logs/session-image)",
        "Session log archives are not accepted - they stay in Temp/AgenHubLogs and are retried every "
        "5 minutes (README.md, Runtime layout). The screenshots and crops that AgentHubNext sends right "
        "after capture for online monitoring are lost: SessionImageUploader does not retry, and only the "
        "archive upload carries the same files later.",
        REBUILD),
    Service(
        "mav-starkit-api", "mav-starkit-api", "mav-starkit-api developer",
        "MavStarkitApiKey in src/Ameria.LlmExecutionEngine/Services/ImageTo3DAgentSettings.cs",
        "generate_3d_object and generate_video cannot store their GLB/MP4 results, the existing-assets "
        "lists injected into the ImageTo3DAgent and ImageToVideoAgent prompts cannot be built, and "
        "send_file_to_srd cannot queue show_file commands for the Sony SRD.",
        REBUILD),
    Service(
        "2d-to-3d", "2d-to-3d service", "2d-to-3d service owner",
        "TwoDToThreeDBasicAuth in ImageTo3DAgentSettings.cs (not set by default - the service has auth disabled)",
        "generate_3d_object (ImageTo3DAgent) cannot create new 3D models."),
    Service(
        "2d-to-video", "2d-to-video service", "2d-to-video service owner",
        "IMAGE_TO_VIDEO_BASIC_AUTH / TWO_D_TO_VIDEO_BASIC_AUTH environment variables (not set by default)",
        "generate_video (ImageToVideoAgent) cannot create new videos."),
    Service(
        "seq", "Seq log server", "Infrastructure / logging",
        "apiKey argument of WriteTo.Seq(...) in src/AgentHub/Global.cs",
        "AgentHubNext's Serilog events do not reach central search in Seq; local log files are "
        "unaffected.",
        REBUILD),
    Service(
        "deepgram", "Deepgram", "Owner of the Deepgram account",
        "DefaultDeepgramApiKey in the AgentHub section of pat-config",
        "Live Deepgram transcription does not work; the app degrades to listening without "
        "transcription instead of failing (README.md, Voice control).",
        "Update DefaultDeepgramApiKey in Maverick Config Manager - no rebuild needed."),
    Service(
        "whisper", "Whisper transcription endpoint", "AI proxy owner",
        "WhisperUrl, WhisperModel and ProxyAuthHeader in the AgentHub section of pat-config",
        "'Use Whisper instead of Deepgram' and 'Use Whisper for final transcription' do not work "
        "(docs/all-settings.md, README.md Noise isolation and Whisper).",
        "Update the AgentHub section in Maverick Config Manager - no rebuild needed."),
    Service(
        "vision", "Vision model (object naming)", "AI proxy owner",
        "VisionUrl, VisionModel and ProxyAuthHeader in the AgentHub section of pat-config",
        "VisionObjectClient returns no terms on a failed request, so no object on the frozen screen "
        "gets named or highlighted.",
        "Update the AgentHub section in Maverick Config Manager - no rebuild needed."),
    Service(
        "sam3", "SAM3 segmentation", "AI proxy owner",
        "SamPredictTextUrl, SamPredictUrl and ProxyAuthHeader in the AgentHub section of pat-config",
        "Named objects cannot be turned into pixel masks, so nothing lights up under the user's pointer.",
        "Update the AgentHub section in Maverick Config Manager - no rebuild needed."),
    Service(
        "llm", "LLM provider", "Maverick Config Manager (AI providers)",
        "headers of the provider record returned by /api/llm-providers",
        "Every agent that uses this provider cannot answer.",
        "Update the provider in Maverick Config Manager - no rebuild needed."),
    Service(
        "mcp", "MCP server", "AI-Hub MCP Servers package owner",
        "url / headers / command of the MCP record returned by /api/mcps",
        "Tools from this MCP server are unavailable to the agents that assign them.",
        "Update the MCP record in Maverick Config Manager, or the MCP server itself."),
    Service(
        "tavily", "Tavily Search API (image search MCP)", "Owner of the Tavily account",
        "--api-key argument of the stdio MCP record for mcp-tavily-search-image, returned by /api/mcps "
        "(the Node server reads it with parseCliArgs in dist/index.js)",
        "The tavily_search_image tool of the locally installed Node MCP server fails, so agents that "
        "assign it cannot fetch images from the web.",
        "Update the --api-key value in the MCP record in Maverick Config Manager - no rebuild needed."),
    Service(
        "suite", "This test suite", "Whoever maintains agenthub-health",
        ".env (credentials) and suite.env (addresses, settings) in the project root", "Nothing in AgentHubNext - the suite itself cannot run this check."),
]}


def get(key: str) -> Service:
    return SERVICES.get(key, SERVICES["suite"])
