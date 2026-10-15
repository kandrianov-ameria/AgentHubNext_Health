"""
How AgentHubNext turns the downloaded JSON into objects, reproduced in Python so the
suite accepts, converts and rejects exactly what the application does.

Two different .NET serializers are involved:

  * The four lists (/api/agents, /api/tools, /api/mcps, /api/llm-providers) are read by
    RemoteConfigurationManager with Newtonsoft.Json (Json.NET):
    JsonConvert.DeserializeObject<List<RemoteXxxDto>>(json) and, inside json_schema,
    the JObject indexer, Value<int?>() and ToObject<List<string>>().
  * The AgentHub section of pat-config is read by RemoteSettingsManager with
    System.Text.Json (JsonSerializer, PropertyNameCaseInsensitive = true).

Json.NET converts many mismatched JSON types silently (a number into a string property,
"5" into an int); System.Text.Json converts none. Where Json.NET converts, the converted
value is what the rest of the suite sees, and a Note records it. Where the application
throws, a Fatal is recorded. Rules this module is not sure of are named as such in the
text they produce.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from typing import Any, Callable

INT32_MIN, INT32_MAX = -(2 ** 31), 2 ** 31 - 1

# Characters that make File.WriteAllTextAsync / Path.Combine fail on Windows, and path
# separators (which point into a sub-folder that GetConfigurationAsync never creates).
_BAD_FILE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


@dataclass
class Findings:
    fatal: list[str] = field(default_factory=list)   # the application throws
    notes: list[str] = field(default_factory=list)   # the application converts the value


def _kind(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, (int, float)):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "array"
    return "object"


def _round_half_even_int(x: float) -> int:
    # Convert.ToInt32(double) rounds to the nearest integer, ties to even - Python's round().
    return int(round(x))


# --- parsing the response text ---------------------------------------------------------

class JsonError(ValueError):
    pass


def _reject_constant(name: str):
    raise JsonError(f"'{name}' is not valid JSON")


def parse_newtonsoft(text: str) -> Any:
    """What LoadString's JsonPrettify reads: the first JSON value, anything after it ignored
    (JsonTextWriter.WriteToken copies one value). Json.NET is more lenient than Python's
    parser (comments, single quotes); such bodies are reported as invalid here, which the
    application might accept. The AI-Hub service is not known to produce them."""
    s = text.lstrip(" \t\r\n﻿")
    try:
        value, _end = json.JSONDecoder().raw_decode(s)
    except json.JSONDecodeError as exc:
        raise JsonError(str(exc)) from None
    return value


def parse_system_text_json(text: str) -> Any:
    """JsonDocument.Parse with default options: strict JSON, no NaN / Infinity, no trailing data."""
    try:
        return json.loads(text.lstrip("﻿"), parse_constant=_reject_constant)
    except (json.JSONDecodeError, JsonError) as exc:
        raise JsonError(str(exc)) from None


# --- Json.NET: reading a JSON value into a typed DTO property -----------------------------

def _nj_string(v: Any, where: str, f: Findings) -> str | None:
    """JsonReader.ReadAsString: strings and null as they are; numbers and booleans are turned into
    text; objects and arrays throw."""
    if v is None or isinstance(v, str):
        return v
    if isinstance(v, bool):
        f.notes.append(f"{where} is a JSON boolean; Json.NET reads it as the text '{'True' if v else 'False'}'.")
        return "True" if v else "False"
    if isinstance(v, int):
        f.notes.append(f"{where} is the number {v}; Json.NET reads it as the text '{v}'.")
        return str(v)
    if isinstance(v, float):
        txt = repr(v) if not v.is_integer() else str(int(v))
        f.notes.append(f"{where} is the number {v}; Json.NET reads it as text (probably '{txt}').")
        return txt
    f.fatal.append(f"{where} is a JSON {_kind(v)}, but the property is a string. Json.NET throws "
                   "\"Error reading string. Unexpected token\".")
    return None


def _nj_number_from_string(s: str, integer: bool) -> float | int | None:
    pattern = r"^\s*[+-]?\d+\s*$" if integer else r"^\s*[+-]?(\d[\d,]*\.?\d*|\.\d+)([eE][+-]?\d+)?\s*$"
    if not re.match(pattern, s):
        return None
    return int(s.strip()) if integer else float(s.strip().replace(",", ""))


def _nj_int(v: Any, where: str, f: Findings, nullable: bool) -> int | None:
    """JsonReader.ReadAsInt32, then the null check for a non-nullable int."""
    if isinstance(v, bool):
        f.fatal.append(f"{where} is a JSON boolean, but the property is an integer. Json.NET throws "
                       "\"Error reading integer. Unexpected token: Boolean\".")
        return None
    if isinstance(v, str):
        if v == "":
            v = None
        else:
            n = _nj_number_from_string(v, integer=True)
            if n is None:
                f.fatal.append(f"{where} is the text '{v}', but the property is an integer. Json.NET throws "
                               "\"Could not convert string to integer\".")
                return None
            f.notes.append(f"{where} is the text '{v}'; Json.NET reads it as the integer {n}.")
            v = n
    if v is None:
        if not nullable:
            f.fatal.append(f"{where} is null, but the property is a non-nullable integer. Json.NET throws "
                           "\"Error converting value {null} to type 'System.Int32'\".")
        return None
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            f.fatal.append(f"{where} is {v}, which does not fit an integer; Json.NET throws.")
            return None
        n = _round_half_even_int(v)
        f.notes.append(f"{where} is the number {v}; Json.NET converts it to the integer {n} "
                       "(Convert.ToInt32 rounding).")
        v = n
    if isinstance(v, int):
        if not INT32_MIN <= v <= INT32_MAX:
            f.fatal.append(f"{where} is {v}, outside the range of System.Int32; Json.NET throws.")
            return None
        return v
    f.fatal.append(f"{where} is a JSON {_kind(v)}, but the property is an integer. Json.NET throws.")
    return None


def _nj_double(v: Any, where: str, f: Findings) -> float | None:
    """JsonReader.ReadAsDouble into a non-nullable double."""
    if isinstance(v, bool) or isinstance(v, (list, dict)):
        f.fatal.append(f"{where} is a JSON {_kind(v)}, but the property is a number (double). Json.NET throws.")
        return None
    if isinstance(v, str):
        if v == "":
            v = None
        else:
            n = _nj_number_from_string(v, integer=False)
            if n is None:
                f.fatal.append(f"{where} is the text '{v}', but the property is a number (double). "
                               "Json.NET throws \"Could not convert string to double\".")
                return None
            f.notes.append(f"{where} is the text '{v}'; Json.NET reads it as the number {n}.")
            v = n
    if v is None:
        f.fatal.append(f"{where} is null, but the property is a non-nullable double. Json.NET throws "
                       "\"Error converting value {null} to type 'System.Double'\".")
        return None
    return float(v)


def _nj_bool(v: Any, where: str, f: Findings) -> bool | None:
    """JsonReader.ReadAsBoolean into a non-nullable bool."""
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        # 0 and 1 are how the AI-Hub service stores booleans (every "primary" on QAS, first seen
        # 2026-09-30). Json.NET reads them as false / true, which is what the value means, so they
        # are not reported. Any other number is still reported: it is true, but probably not meant.
        if v not in (0, 1):
            f.notes.append(f"{where} is the number {v}; Json.NET reads it as {'true' if v != 0 else 'false'}.")
        return v != 0
    if isinstance(v, str):
        if v == "":
            v = None
        elif v.strip().lower() in ("true", "false"):
            b = v.strip().lower() == "true"
            f.notes.append(f"{where} is the text '{v}'; Json.NET reads it as {str(b).lower()}.")
            return b
        else:
            f.fatal.append(f"{where} is the text '{v}', but the property is a boolean. Json.NET throws "
                           "\"Could not convert string to boolean\".")
            return None
    if v is None:
        f.fatal.append(f"{where} is null, but the property is a non-nullable boolean. Json.NET throws "
                       "\"Error converting value {null} to type 'System.Boolean'\".")
        return None
    f.fatal.append(f"{where} is a JSON {_kind(v)}, but the property is a boolean. Json.NET throws.")
    return None


def _nj_jobject(v: Any, where: str, f: Findings) -> dict | None:
    if v is None or isinstance(v, dict):
        return v
    f.fatal.append(f"{where} is a JSON {_kind(v)}, but the property is a JObject. Json.NET throws.")
    return None


_READERS: dict[str, Callable] = {
    "string": lambda v, w, f: _nj_string(v, w, f),
    "int": lambda v, w, f: _nj_int(v, w, f, nullable=False),
    "int?": lambda v, w, f: _nj_int(v, w, f, nullable=True),
    "double": lambda v, w, f: _nj_double(v, w, f),
    "bool": lambda v, w, f: _nj_bool(v, w, f),
    "jobject": lambda v, w, f: _nj_jobject(v, w, f),
}
_DEFAULTS = {"string": None, "int": 0, "int?": None, "double": 0.0, "bool": False, "jobject": None}

# [JsonProperty] names and CLR types of the DTOs in src/AgentHub/RemoteConfiguration/.
AGENT_DTO = {"category": "string", "keyword": "string", "description": "string", "version": "double",
             "llm_provider_id": "int", "secondary_llm_provider_id": "int?", "json_schema": "jobject"}
TOOL_DTO = {"category": "string", "keyword": "string", "json_schema": "jobject"}
PROVIDER_DTO = {"id": "int", "name": "string", "headers": "string", "base_url": "string", "model": "string",
                "provider_type": "string", "primary": "bool"}
MCP_DTO = {"id": "int", "name": "string", "description": "string", "type": "string", "url": "string",
           "headers": "string", "command": "string", "arguments": "string", "cmd_shell": "string"}
DTOS = {"agents": ("RemoteAgentDto", AGENT_DTO), "tools": ("RemoteToolDto", TOOL_DTO),
        "llm-providers": ("RemoteLlmProviderDto", PROVIDER_DTO), "mcps": ("RemoteMcpDto", MCP_DTO)}


def bind_newtonsoft(obj: dict, props: dict[str, str], where: str, f: Findings) -> dict:
    """Json.NET binds JSON property names to [JsonProperty] names exactly first and then
    case-insensitively; unknown properties are ignored; a later duplicate overwrites."""
    out = {name: _DEFAULTS[kind] for name, kind in props.items()}
    lower = {name.lower(): name for name in props}
    for key, value in obj.items():
        name = key if key in props else lower.get(key.lower())
        if name is None:
            continue
        out[name] = _READERS[props[name]](value, f"{where}.{key}", f)
    return out


def read_list(data: Any, entity: str, f: Findings) -> list[dict | None]:
    """JsonConvert.DeserializeObject<List<Dto>>(json)."""
    dto_name, props = DTOS[entity]
    if data is None:
        f.fatal.append(f"/api/{entity} returned the JSON literal null. DeserializeObject returns null and "
                       "GetConfigurationAsync throws a NullReferenceException when it uses the list.")
        return []
    if not isinstance(data, list):
        f.fatal.append(f"/api/{entity} returned a JSON {_kind(data)}, not an array. Json.NET throws "
                       f"\"Cannot deserialize the current JSON {_kind(data)} into type List<{dto_name}>\".")
        return []
    out: list[dict | None] = []
    for i, item in enumerate(data):
        where = f"/api/{entity}[{i}]"
        if item is None:
            out.append(None)
        elif isinstance(item, dict):
            out.append(bind_newtonsoft(item, props, where, f))
        else:
            f.fatal.append(f"{where} is a JSON {_kind(item)}, not an object. Json.NET throws "
                           f"\"Error converting value to type '{dto_name}'\".")
    return out


# --- Json.NET: reading values out of json_schema (a JObject) -----------------------------

_MISSING = object()


def jtoken_string(schema: dict, key: str, where: str, f: Findings) -> str | None:
    """schema[key]?.ToString(): a missing key gives null; JSON null gives the empty string;
    other values give their text form."""
    if key not in schema:            # the JObject indexer is case-sensitive
        return None
    v = schema[key]
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, bool):
        f.notes.append(f"{where}.{key} is a JSON boolean; the application reads it as '{'True' if v else 'False'}'.")
        return "True" if v else "False"
    if isinstance(v, int):
        f.notes.append(f"{where}.{key} is the number {v}; the application reads it as the text '{v}'.")
        return str(v)
    if isinstance(v, float):
        f.notes.append(f"{where}.{key} is the number {v}; the application reads it as text formatted with "
                       "the Windows culture (for example '1,5' on a German system).")
        return repr(v)
    f.notes.append(f"{where}.{key} is a JSON {_kind(v)}; the application reads its JSON text as the value.")
    return json.dumps(v, indent=2)


def jtoken_int(schema: dict, key: str, where: str, f: Findings) -> int | None:
    """schema.Value<int?>(key): Convert.ChangeType on the JValue."""
    v = schema.get(key, None) if key in schema else None
    w = f"{where}.{key}"
    if v is None:
        return None
    if isinstance(v, bool):
        f.notes.append(f"{w} is a JSON boolean; Value<int?>() converts it to {int(v)}.")
        return int(v)
    if isinstance(v, int):
        if not INT32_MIN <= v <= INT32_MAX:
            f.fatal.append(f"{w} is {v}, outside System.Int32. Value<int?>() throws an OverflowException.")
            return None
        return v
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v) or not INT32_MIN <= v <= INT32_MAX:
            f.fatal.append(f"{w} is {v}. Value<int?>() throws an OverflowException.")
            return None
        n = _round_half_even_int(v)
        f.notes.append(f"{w} is the number {v}; Value<int?>() converts it to {n}.")
        return n
    if isinstance(v, str):
        n = _nj_number_from_string(v, integer=True)
        if n is None:
            f.fatal.append(f"{w} is the text '{v}'. Value<int?>() throws a FormatException.")
            return None
        if not INT32_MIN <= n <= INT32_MAX:
            f.fatal.append(f"{w} is {v}, outside System.Int32. Value<int?>() throws an OverflowException.")
            return None
        f.notes.append(f"{w} is the text '{v}'; Value<int?>() converts it to {n}.")
        return n
    f.fatal.append(f"{w} is a JSON {_kind(v)}. Value<int?>() throws an InvalidCastException.")
    return None


def jtoken_string_list(schema: dict, key: str, where: str, f: Findings) -> list[str | None] | None:
    """schema[key]?.ToObject<List<string>>()."""
    if key not in schema:
        return None
    v = schema[key]
    w = f"{where}.{key}"
    if v is None:
        return None
    if not isinstance(v, list):
        f.fatal.append(f"{w} is a JSON {_kind(v)}, not an array. ToObject<List<string>>() throws.")
        return None
    return [_nj_string(item, f"{w}[{i}]", f) for i, item in enumerate(v)]


# --- the application's loading pass ------------------------------------------------------

@dataclass
class Loaded:
    agents: list[dict]       # as GetConfigurationAsync builds AgentDto
    tools: list[dict]        # as FunctionDto
    providers: list[dict]    # RemoteLlmProviderDto, null entries removed
    mcps: list[dict]         # RemoteMcpDto, null entries removed
    findings: Findings


def load(raw: dict[str, Any], env: str) -> Loaded:
    """Replays RemoteConfigurationManager.GetConfigurationAsync up to the point where it writes
    the agent and tool files. Validation rules (empty lists, duplicates, invalid references) are
    left to tests/test_01_remote_config.py, which reports them one rule at a time."""
    f = Findings()
    providers = read_list(raw.get("llm-providers"), "llm-providers", f)
    mcps = read_list(raw.get("mcps"), "mcps", f)
    if any(m is None for m in mcps):
        f.fatal.append("/api/mcps contains a null entry. mcps.Where(x => x.Type == \"stdio\") throws a "
                       "NullReferenceException.")

    agents: list[dict] = []
    for i, dto in enumerate(read_list(raw.get("agents"), "agents", f)):
        where = f"/api/agents[{i}]"
        if dto is None:
            f.fatal.append(f"{where} is null. remoteAgents.Where(x => x.Category == ...) throws a "
                           "NullReferenceException.")
            continue
        if dto["category"] != env:
            continue
        schema = dto["json_schema"]
        if schema is None:
            f.fatal.append(f"{where} ({dto['keyword'] or 'no keyword'}) has no json_schema. dto.JsonSchema[\"Name\"] throws a "
                           "NullReferenceException.")
            continue
        w = f"{where}.json_schema"
        agents.append({
            "keyword": dto["keyword"],
            "name": jtoken_string(schema, "Name", w, f),
            "llm_provider_id": dto["llm_provider_id"],
            "secondary_llm_provider_id": dto["secondary_llm_provider_id"],
            "schema": schema,
            "AgentDescription": jtoken_string(schema, "AgentDescription", w, f),
            "InnerInstructions": jtoken_string(schema, "InnerInstructions", w, f),
            "ThinkingMessagePrompt": jtoken_string(schema, "ThinkingMessagePrompt", w, f),
            "MaxTokenCount": jtoken_int(schema, "MaxTokenCount", w, f),
            "AnthropicRequestMaxTokens": jtoken_int(schema, "AnthropicRequestMaxTokens", w, f),
            "SessionKillIdleTimeMinutes": jtoken_int(schema, "SessionKillIdleTimeMinutes", w, f),
            "AssignedTools": jtoken_string_list(schema, "AssignedTools", w, f),
            "AssignedMCPs": jtoken_string_list(schema, "AssignedMCPs", w, f),
            "AssignedAgents": jtoken_string_list(schema, "AssignedAgents", w, f),
        })

    tools: list[dict] = []
    for i, dto in enumerate(read_list(raw.get("tools"), "tools", f)):
        where = f"/api/tools[{i}]"
        if dto is None:
            f.fatal.append(f"{where} is null. remoteTools.Where(x => x.Category == ...) throws a "
                           "NullReferenceException.")
            continue
        if dto["category"] != env:
            continue
        schema = dto["json_schema"]
        if schema is None:
            f.fatal.append(f"{where} ({dto['keyword'] or 'no keyword'}) has no json_schema. dto.JsonSchema[\"name\"] throws a "
                           "NullReferenceException.")
            continue
        w = f"{where}.json_schema"
        schema = dict(schema)
        name = jtoken_string(schema, "name", w, f)
        mcp = jtoken_string(schema, "mcp", w, f)
        if mcp and name and "[" not in name:
            schema["name"] = f"[{mcp}]{name}"
        # new FunctionDto(JsonConvert.SerializeObject(schema)) reads the fields back with
        # JsonHelper.GetString -> obj[field]?.ToString(). Notes were recorded above already.
        quiet = Findings()
        tools.append({"name": jtoken_string(schema, "name", w, quiet),
                      "mcp": jtoken_string(schema, "mcp", w, quiet),
                      "schema": schema})

    # Validation loop: Regex.Match(null) throws for a null AssignedMCPs entry.
    for a in agents:
        for ref in a["AssignedMCPs"] or []:
            if ref is None:
                f.fatal.append(f"Agent '{a['name']}' has a null entry in AssignedMCPs. Regex.Match(null) throws an "
                               "ArgumentNullException.")

    # Provider lookups iterate the list in order and dereference every entry they pass.
    if any(p is None for p in providers):
        def lookup(pred) -> bool:
            for p in providers:
                if p is None:
                    return True    # NullReferenceException before a match
                if pred(p):
                    return False
            return False
        hit = False
        for a in agents:
            hit = hit or lookup(lambda p, a=a: p["id"] == a["llm_provider_id"])
            if a["secondary_llm_provider_id"] is not None:
                hit = hit or lookup(lambda p, a=a: p["id"] == a["secondary_llm_provider_id"])
        hit = hit or lookup(lambda p: p["primary"] and p["provider_type"] == "open_ai_embedding")
        if hit:
            f.fatal.append("/api/llm-providers contains a null entry that the provider lookups reach. "
                           "llmProviders.FirstOrDefault(x => x.Id == ...) throws a NullReferenceException.")

    # After validation the agents and tools are written to Data/Agents/<Name>.agent.json and
    # Data/Functions/<name>.json. A name with a character Windows does not allow in a file name
    # (or a path separator) makes File.WriteAllTextAsync throw.
    for a in agents:
        if a["name"] and _BAD_FILE_CHARS.search(a["name"]):
            f.fatal.append(f"Agent name '{a['name']}' contains a character that is not allowed in a Windows file "
                           "name. Writing Data/Agents/<Name>.agent.json throws.")
    for t in tools:
        if t["name"] and _BAD_FILE_CHARS.search(t["name"]):
            f.fatal.append(f"Tool name '{t['name']}' contains a character that is not allowed in a Windows file "
                           "name. Writing Data/Functions/<name>.json throws.")

    return Loaded(agents, tools, [p for p in providers if p is not None], [m for m in mcps if m is not None], f)


# --- headers -----------------------------------------------------------------------------

def parse_headers(raw: str | None) -> dict[str, str]:
    """RemoteLlmProviderDto.GetHeaders / RemoteMcpDto.GetHeaders: split on CRLF or LF, drop empty
    lines, split each line once on ': ', keep lines with two parts. (The application throws on a
    duplicate name and on null; see header_problem().)"""
    out: dict[str, str] = {}
    for line in re.split(r"\r\n|\n", raw or ""):
        if not line:
            continue
        parts = line.split(": ", 1)
        if len(parts) == 2:
            out[parts[0]] = parts[1]
    return out


def header_problem(raw: str | None) -> str:
    """Why GetHeaders() would throw for this value, or ''."""
    if raw is None:
        return "headers is null, so GetHeaders() throws a NullReferenceException."
    seen: set[str] = set()
    for line in re.split(r"\r\n|\n", raw):
        parts = line.split(": ", 1) if line else []
        if len(parts) == 2:
            if parts[0] in seen:
                return (f"the header name '{parts[0]}' appears twice, so GetHeaders() (ToDictionary) throws an "
                        "ArgumentException.")
            seen.add(parts[0])
    return ""


# --- System.Text.Json: the AgentHub section of pat-config --------------------------------

# AgentHubRemoteSettings: [JsonPropertyName] and CLR type.
AGENTHUB_SETTINGS = {
    "DefaultDeepgramApiKey": "string", "WhisperUrl": "string", "WhisperModel": "string",
    "RemoteSyncOnSessionCreate": "bool", "VisionUrl": "string", "VisionModel": "string",
    "SamPredictTextUrl": "string", "SamPredictUrl": "string", "ProxyAuthHeader": "string",
}
SECTION_NAME = "AgentHub"


def read_agenthub_section(root: Any) -> tuple[dict | None, str]:
    """RemoteSettingsManager.DownloadAsync after a 2xx answer: (settings, '') or (None, why the
    application treats the download as failed and falls back to its cache)."""
    if not isinstance(root, dict):
        return None, f"the response is a JSON {_kind(root)}, not an object"
    if SECTION_NAME not in root:        # JsonElement.TryGetProperty is case-sensitive
        return None, f"the response contains no '{SECTION_NAME}' section"
    section = root[SECTION_NAME]
    if not isinstance(section, dict):
        return None, f"'{SECTION_NAME}' is a JSON {_kind(section)}, not an object"
    lower = {k.lower(): k for k in AGENTHUB_SETTINGS}
    out: dict[str, Any] = {k: ("" if t == "string" else False) for k, t in AGENTHUB_SETTINGS.items()}
    extra: dict[str, Any] = {}
    for key, value in section.items():
        name = lower.get(key.lower())
        if name is None:
            extra[key] = value           # ignored by the application
            continue
        kind = AGENTHUB_SETTINGS[name]
        if kind == "string":
            if value is not None and not isinstance(value, str):
                return None, (f"'{key}' is a JSON {_kind(value)}, but AgentHubRemoteSettings.{name} is a string. "
                              "System.Text.Json throws \"The JSON value could not be converted to System.String\"")
        elif not isinstance(value, bool):
            return None, (f"'{key}' is a JSON {_kind(value)}, but AgentHubRemoteSettings.{name} is a boolean. "
                          "System.Text.Json throws \"The JSON value could not be converted to System.Boolean\"")
        out[name] = value
    # Fields the application ignores stay visible to the checks that look at them
    # (SpeechToTextUrl, for example), under their original names.
    for k, v in extra.items():
        out.setdefault(k, v)
    return out, ""
