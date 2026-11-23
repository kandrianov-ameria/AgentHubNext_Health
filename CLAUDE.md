# agenthub-health: guidance for working on this suite

This file is context for future sessions that work on this suite or on the
AgentHubNext repository it checks. Everything below was established from the
repository source, its docs, or real runs. Where something is still unknown, it
says so.

## 1. Purpose

A Windows-only pytest suite that checks every external service and LLM that
AgentHubNext depends on. It checks that each one is up, that its credentials
are accepted, that the remote configuration is valid, and that responses have
the shape the app parses. It must run on **any Windows PC with Python 3.9+**.

- No checks may run on a Maverick machine or on local Maverick software.
- No macOS services are in scope.
- A normal run reads `.env` (credentials) and `suite.env` (everything else) and
  downloads the remote configuration. **It never reads the local repository.** The one exception (1.11.0)
is the version check: one `git fetch` of the AgentHub branch from GitHub (see Version 1.11.0).

One command runs everything: `run_tests.bat`. The report is written to
`results\result.html`, the logs to `logs\<start time>\`.

## 2. Locations

| What | Path |
|---|---|
| Suite root (this folder) | `D:\MAVERICK\_AgentHubNext\agenthub-health\` |
| AgentHubNext repo (.NET 10, Windows build, version 4.0.69 at review time) | `D:\MAVERICK\_AgentHubNext\agent-hub-backend\` |
| Copy of the Tavily image MCP server | `D:\MAVERICK\_AgentHubNext\agent-hub-backend\index.js` |
| Tavily image MCP on a real Maverick | `C:\ProgramData\Maverick\Packages\<ENV>\Maverick-ai-hub-mcp-servers\<VER>\node-js-mcp\mcp-tavily-search-image\dist\index.js` |
| Human view of pat-config | `https://aihub.ameriadev.de/ai-hub-service/admin/pat-config/<ENV>` |

## 3. Security rules (non-negotiable)

- `.env` holds live credentials copied from the app's build secrets file
  (`secrets.local.txt` in the agent-hub-backend root; since 4.0.64 they are no longer
  hardcoded in the source). Since 4.0.71 that is only `AIHUB_WIN_TOKEN` and `SEQ_API_KEY`; the other
  service credentials come from the AgentHub section of pat-config (section 4).
  - **Never** print, paste, commit or upload its values.
  - **Never** overwrite the user's `.env`. (Exception made once, at the user's
    request, in 1.3.0: non-secret keys moved out; backup `.env.backup-20261015`.)
  - Nothing secret goes into `suite.env`; it is committed.
  - Only `scripts/refresh_env.py` creates it, and it writes file-to-file. It refuses to write when
    any value is missing or still a build placeholder, so a working `.env` is never replaced by a
    half-filled one.
- Every string that reaches the console or the report goes through
  `redact.text()`.
  - Register every secret found at runtime with `redact.register()`: LLM
    provider headers, MCP headers, the MCP `--api-key` argument,
    `ProxyAuthHeader`, the Deepgram key, and (1.9.0) `MavStarkitApiKey`, `DeviceMappingBearerToken`
    and every `*ApiKey` / `*Token` of `AgentHub.MavSlides` (`bootstrap._register_secrets`).
  - Masks look like `****last4`.
- `remote_config/` holds the downloaded configuration as plain JSON, including
  LLM provider keys, MCP headers, the Tavily key, `DefaultDeepgramApiKey`,
  `ProxyAuthHeader`, `MavStarkitApiKey`, `DeviceMappingBearerToken` and the MAV Slides keys. Treat it like `.env`. (The user did not choose between
  plain and encrypted storage; plain was used. The app itself encrypts its
  pat-config cache with AES-GCM.)
- Logs (`logs/`) go through `redact.text()` line by line, like the console.
- `.gitignore` excludes `.env`, `.env.*` (except `.env.example`), `.venv/`,
  `results/`, `remote_config/`, `logs/` and `__pycache__/`, followed by GitHub's
  standard Python template (added by the merge of 2026-11-14). `suite.env` is
  committed on purpose.
- Security note found in the SAM3 service README: a real `HF_TOKEN` was once
  hardcoded in its `docker-compose.yaml` and is still in git history, and the
  README says it must be revoked. Whether that was done is unknown.

## 4. Credentials (`.env`) and settings (`suite.env`)

Precedence, highest first: real environment variable (and `--env`), `.env`,
`suite.env`, the default in `settings.py` (`load_dotenv(override=False)` is
called for `.env` first, then `suite.env`).

### Build secrets of agent-hub-backend (since 4.0.64; only three left since 4.0.71)

The app no longer has credentials in its source (git history before 4.0.64 still does, and those
old values were rotated). The developer keeps them in the git-ignored `secrets.local.txt` in the
repository root (`NAME=value` per line; template `secrets.local.example.txt`);
`build/Secrets.targets` compiles them into `BuildSecrets` at build time. Changing one needs a
rebuild and a rollout; after that, update `secrets.local.txt` and rerun `refresh_env.py`, which reads
that file (or `--secrets <path>`).

Since 4.0.71 only the **bootstrap** secrets are left, the ones needed before the remote configuration can be
downloaded (`docs/pat-config-api.md`, `secrets.local.example.txt`):

| `.env` key | `secrets.local.txt` name | Used by |
|---|---|---|
| `AIHUB_WIN_TOKEN` | `AIHUB_SERVICE_AUTH_WINDOWS` | `RemoteConfigurationManager.WindowsApiToken`. The template says the full Authorization header (`Bearer <id>|<token>`); the suite adds `Bearer ` itself, so `refresh_env.py` strips a leading `Bearer `. Also used by `tools/mav-starkit-api/*.bat`. |
| `SEQ_API_KEY` | `AGENTHUB_SEQ_API_KEY` | `WriteTo.Seq(...)`, `src/AgentHub/Global.cs` |

`AIHUB_SERVICE_AUTH_MAC` is also in that file; the Windows-only suite does not use it. Base URLs are
still constants in the source and are still read from there.

**Moved to pat-config in 4.0.71** (no longer in `secrets.local.txt`, `.env` or `suite.env`; the suite
reads them from the downloaded AgentHub section, `remote.agenthub_value()` / `remote.mavslides()`):

| AgentHub setting | Old `.env` key | Used by |
|---|---|---|
| `MavStarkitApiKey` | `STARKIT_API_KEY` | `RemoteSettingsManager.ApplyServiceCredentials` -> `ImageTo3DAgentSettings.MavStarkitApiKey` (`X-API-Key`) |
| `DeviceMappingBearerToken` (`<id>|<token>`, no `Bearer `) | `AIHUB_DEVICE_MAPPING_TOKEN` | same -> `ImageTo3DAgentSettings.DeviceMappingBearerToken`: device mapping, `/api/logs-session` (LogUploadService), `/api/logs/session-image` (SessionImageUploader), all as `AuthenticationHeaderValue("Bearer", token)` |
| `MavSlides.*` (14 strings, see section 5) | `MAVSLIDES_*` in `.env` and `suite.env` | `SlidesService.Configure` -> `MavSlidesServiceConfig` -> `EngineSettings.Create` |

Old keys that are still in a PC's `.env` (`STARKIT_API_KEY`, `AIHUB_DEVICE_MAPPING_TOKEN`, `MAVSLIDES_*`)
are ignored. The suite deliberately does not fall back to them: the app does not either, so a pass
means the app has the value. `refresh_env.py` leaves them out when it writes a new `.env`.

### Optional `.env` keys

- `TWO_D_TO_3D_BASIC_AUTH`, `TWO_D_TO_VIDEO_BASIC_AUTH` (empty means no auth
  header; `refresh_env.py` keeps values already set).
- (1.8.0 had six `MAVSLIDES_*` keys here; removed in 1.9.0, they are `AgentHub.MavSlides` in pat-config now.
  A key value with a space is sent as the whole Authorization header, anything else as `Bearer <value>`:
  `LlmClient.SetAuthorization`, mirrored in `test_42._authorization`.)
- `.env.example` lists the `.env` keys with no values.

### `suite.env` keys (committed, no secrets)

- **Environment:** `AGENTHUB_ENV` (DEV / QAS / STG / PRD; currently QAS).
- **Base URLs:** `AIHUB_SERVICE_BASE_URL`, `MAV_STARKIT_BASE_URL`,
  `TWO_D_TO_3D_BASE_URL`, `TWO_D_TO_VIDEO_BASE_URL`,
  `DEVICE_MAPPING_BASE_URL`, `SEQ_BASE_URL`.
  `refresh_env.py` compares them with the source constants and updates
  changed lines in place.
  (`AGENTHUB_DEVICE_ID` was removed in 1.2.0 with the SRD pairing checks, and
  from the user's `.env` in 1.3.0.)
- **Public APIs, timeouts, logs** (also defaulted in `settings.py`): `DEEPGRAM_API_URL`,
  `TAVILY_SEARCH_URL`, and the timeouts `AGENTHUB_HEALTH_TIMEOUT` (20 s),
  `AGENTHUB_HEALTH_LLM_TIMEOUT` (60 s),
  `AGENTHUB_HEALTH_GENERATION_TIMEOUT` (900 s),
  `AGENTHUB_HEALTH_CONFIG_TIMEOUT` (20 s, the app's value for the config
  downloads) and `AGENTHUB_HEALTH_LOG_RUNS` (7 runs kept, since 1.9.1: log folders and `results/history.json`).
- **MAV Slides** (1.8.0 had eight `MAVSLIDES_*` address and model keys here; removed in 1.9.0): the addresses and
  models are `AgentHub.MavSlides` in pat-config since 4.0.71. An empty coder or vision url and model means "same as
  the main LLM" (`EngineSettings.Fallback`, mirrored in `test_42._endpoint`); an empty `OpenRouterUrl` means
  `https://openrouter.ai/api/v1` (`EngineSettings.OpenRouterUrl`, `test_42.OPENROUTER_DEFAULT_URL`).

### Credentials the suite reads at runtime

These are never stored in `.env`. They come from the download at the start of
each run and are saved with it in `remote_config/<ENV>/`:

- **From `/api/pat-config/<ENV>` → AgentHub section:** `DefaultDeepgramApiKey`
  and `ProxyAuthHeader` (Whisper, vision and SAM3); since 1.9.0 also `MavStarkitApiKey`,
  `DeviceMappingBearerToken` and `MavSlides.*` (see "Moved to pat-config" above).
- **From `/api/llm-providers`:** provider keys, in `headers`.
- **From `/api/mcps`:** MCP headers, and the Tavily key as `--api-key` in the
  stdio record's `arguments`.

## 5. How AgentHubNext uses its dependencies (facts the checks mirror)

### Remote configuration

- The endpoints are `/api/agents`, `/tools`, `/mcps`, `/llm-providers` and
  `/pat-config/<ENV>`, called with the Windows bearer token
  (`ServiceAuthorizationHeader`; the value is the `AIHUB_SERVICE_AUTH_WINDOWS` build secret, meant to
  include `Bearer `; the suite sends `Bearer <AIHUB_WIN_TOKEN>`)
  and a 20 s timeout.
- Only pat-config has the environment in its URL. The four lists are the same
  for every environment; agents and tools are filtered by `category`, MCPs and
  providers are not filtered.
- Start-up order (`Program.cs`): `RemoteSettingsManager.SynchronizeAsync(env)`
  (pat-config), then, inside the main loop,
  `RemoteConfigurationManager.GetConfigurationAsync()`. An exception there is
  rethrown to the outer catch ("Global Error", "Please restart application.")
  and the app shuts down. The lists have no local cache.
- `LoadString` throws on no answer, a non-2xx status, an empty body, and on a
  body `JsonPrettify` cannot read (it copies the first JSON value only).
- `RemoteSettingsManager.DownloadAsync` returns null (the app then uses its
  AES-GCM cache at `C:\ProgramData\Maverick\agenthub.remote.settings.json`, and
  shuts down without one) on no answer, a non-2xx status, a body that is not a
  JSON object, no `AgentHub` object (case-sensitive `TryGetProperty`), or a
  section System.Text.Json cannot deserialize.
- With `RemoteSyncOnSessionCreate=true` every new session downloads the lists
  again (`AgentHubSessionManager.SyncRemoteConfigurationAsync`).
- Each list is a JSON array.
- Agents and tools are filtered by `category == ENV`.
- **Agent name:** `json_schema.Name`, which must equal `keyword`.
- **Tool name:** `json_schema.name`, rewritten to `[mcp]name` when
  `json_schema.mcp` is set.
- **Assignments:**
  - `AssignedTools` holds local tools only.
  - `AssignedMCPs` holds `[mcpName]toolName`.
  - `AssignedAgents` holds handoffs.
  - `handoff_to_agent` is injected automatically and must not be assigned.
- Provider and MCP `headers` are `Name: value` lines.
- Validation errors in `RemoteConfigurationManager.GetConfigurationAsync`
  throw "Remote configuration error."
- A primary `open_ai_embedding` provider is expected; without one the app
  only warns. At start-up `Program.cs` reads its `Authorization` header; when
  it is missing the Embedding Client is not created ("Failed") and the app
  continues.
- `GetHeaders()` throws on null headers (NullReferenceException) and on a
  duplicate header name (`ToDictionary`, ArgumentException).

### How the app deserializes the configuration (mirrored in `dotnet.py`)

The rules below come from how Json.NET and System.Text.Json behave, read against
the DTOs and calls in `src/AgentHub/RemoteConfiguration/`. They were not
confirmed by running AgentHubNext against a faulty configuration.

- The lists use Json.NET: `JsonConvert.DeserializeObject<List<Dto>>`, property
  names exact first then case-insensitive, unknown properties ignored.
  - Throws: null into a non-nullable `int`/`double`/`bool` (`llm_provider_id`,
    `id`, `version`, `primary`); an object or array into a string; a boolean
    into an int; a non-numeric string into a number; a non-object list entry;
    a list that is not an array or is the literal null.
  - Converts silently (reported as no-effect notes): numbers and booleans into
    strings, numeric strings into numbers, floats into ints (rounded),
    numbers and `"true"`/`"false"` into bool.
- Inside `json_schema` (JObject, case-sensitive keys):
  - `schema["Name"]?.ToString()`: missing is null, JSON null is `""`.
  - `Value<int?>()`: non-numeric strings, objects and overflows throw.
  - `ToObject<List<string>>()`: a non-array throws.
- Null list entries, a null `json_schema` in the environment's category, and a
  null `AssignedMCPs` entry (`Regex.Match(null)`) throw.
- Agent and tool names are file names (`Data/Agents/<Name>.agent.json`,
  `Data/Functions/<name>.json`); `<>:"/\|?*` or control characters make the
  write throw.
- `FunctionDto.MCP` is null when `json_schema` has no `mcp`, so an
  `AssignedMCPs` entry without brackets can match such a tool (`x.MCP == null`).
- pat-config uses System.Text.Json with `PropertyNameCaseInsensitive`: strings
  only as JSON strings or null, `RemoteSyncOnSessionCreate` only as
  `true`/`false`; anything else fails the whole section.
- Not certain: exact text of floats converted to strings (culture), and
  Json.NET leniencies (comments, single quotes) that Python's parser rejects.

### LLM provider URLs

| `provider_type` | URL | Auth header |
|---|---|---|
| `open_ai` | base + `/chat/completions` | `Authorization` |
| `anthropic` | base + `/messages` | `x-api-key`, plus `anthropic-version` |
| `gemini` | base + `/v1beta/models/{model}:generateContent` | `x-goog-api-key` |
| `open_ai_embedding` | base + `/embeddings` | — |

### MCP servers

- Types are `stdio` or `streamable_http`.
- `McpWrapper` splits `arguments` on commas, trims each entry and drops empty
  ones.
- Only the `<ENV>` and `<VER>` placeholders are resolved.

### Tavily image MCP (`index.js`)

- It is a local Node stdio server. `parseCliArgs` requires both `--api-key`
  and `--folder`, and throws at start if either is missing.
- It sends `POST https://api.tavily.com/search`:
  - headers: `Authorization: Bearer <key>` and `X-Client-Source: MCP`;
  - body: `query`, `max_results: 5`, `include_images: true`,
    `include_image_descriptions: true`.
- It downloads the returned images. With none usable it throws "No images
  found in Tavily response".
- The HTTP MCP entry `tavily-search-image`
  (`https://aihub.ameriadev.de/mcp-tavily-search-image-server/mcp`) is a
  different entry and no agent assigns it.

### pat-config AgentHub section

- Fields: `DefaultDeepgramApiKey`, `WhisperUrl`, `WhisperModel`,
  `ProxyAuthHeader`, `RemoteSyncOnSessionCreate`, `VisionUrl`, `VisionModel`,
  `SamPredictTextUrl` and `SamPredictUrl`; since 4.0.71 also `MavStarkitApiKey`,
  `DeviceMappingBearerToken` and the object `MavSlides`.
- `MavSlides` (`MavSlidesRemoteSettings`, no `[JsonPropertyName]`, so names match case-insensitively): `LlmUrl`,
  `LlmApiKey`, `LlmModel`, `CoderUrl`, `CoderApiKey`, `CoderModel`, `VisionUrl`, `VisionApiKey`, `VisionModel`,
  `OpenRouterUrl`, `OpenRouterApiKey`, `TavilyApiKey`, `WebSearchMcpUrl`, `WebSearchMcpToken`, all strings.
  JSON null for `MavSlides` gives an empty object (the setter); a non-object or a non-string member fails the
  whole section (mirrored in `dotnet.read_agenthub_section`; read against the DTO, not run against the app).
- Missing fields (an older server or cache) read as empty strings: the app still starts, logs a Warning naming the
  field (`ApplyServiceCredentials`; `SlidesService` and the engine report "not configured"), and the feature that
  needs it fails or degrades. Both tokens are trimmed, and the device-mapping token must not contain `Bearer `.
- `docs/pat-config-api.md` (2026-11-20): the Windows service serves the section in every environment, but only
  **DEV** carries `MavStarkitApiKey`, `DeviceMappingBearerToken` and `MavSlides`; QAS, STG and PRD "must be filled
  in before a build relying on them is rolled out there". Not checked against the real QAS.
- `SpeechToTextUrl` is ignored by the app (`docs/pat-config-api.md`: "The old
  `SpeechToTextUrl` server field is ignored and no longer cached or used").
- On QAS, `SpeechToTextUrl` equals `WhisperUrl`
  (`https://proxy-ai.ameriadev.de:7006/transcribe/`, model
  `whisper-large-v3`). The suite passes when the two are equal.
- Whether another client reads `SpeechToTextUrl` is unknown.
- `docs/pat-config-api.md` says the section exists only in DEV, but QAS has it
  too. The docs are outdated.

### Whisper

- The request is multipart: `file=voice.wav`, `model`, and
  `response_format=verbose_json`.
- `language` is left out when set to `auto`.
- The response comes in one of two accepted shapes:
  - `text` + `language`;
  - `transcription[]` + `is_silence_detected`.

### Vision

The URL is built by the rule in `VisionObjectClient.ChatCompletionsUrl`:

- a URL ending in `/chat/completions` is used as is;
- one ending in `/v1` gets `/chat/completions` appended;
- anything else gets `/v1/chat/completions` appended.

The app reads `choices[0].message.content`.

Since 4.0.53 the request body also carries `chat_template_kwargs: {"enable_thinking": false}`
(`VisionObjectClient.CompleteAsync`); the suite sends the same body.

### SAM3 (`src/Ameria.Segmentation/Sam3Client.cs`)

- **Text** (`SegmentByTextAsync`): `image_file`, `return_zip=false`,
  `text_prompt`, `threshold` and `mask_threshold`.
- **Point** (`SegmentByPointAsync`): `point_coords=[[x,y]]`,
  `point_labels=[1]` and `mask_threshold`.
  - It is documented as "Not used by the current flow" and has no callers.
- **Response:** the client parses the parallel arrays `masks`, `boxes` and
  `scores`.

## 6. Suite structure

```
run_tests.bat            one command: creates .venv, installs deps when requirements.txt changes
                         (stamp .venv\requirements.installed), runs refresh_env.py once if .env
                         is missing, then runs python -m agenthub_health %*
                         options: --live, --env NAME, --no-open
requirements.txt         pytest>=8,<9; httpx>=0.27,<1; python-dotenv>=1,<2;
                         truststore>=0.9,<1 (Python >= 3.10)
pytest.ini               pythonpath=., --strict-markers, --continue-on-collection-errors,
                         markers: config, smoke, live
.gitattributes           tests/assets/* binary; *.bat eol=crlf
agenthub_health/
  __init__.py            __version__ (bump on every change; currently 1.11.0)
  __main__.py            opens the run logs, copies the console to console.log, runs pytest with the
                         plugin; -m "not live" unless --live; opens the report
  settings.py            paths, .env + suite.env loading, URL/secret var lists, fix_for() hints,
                         timeouts, DEEPGRAM/TAVILY URLs
  redact.py              secret registry and masking
  probe.py               Status, ProbeResult, call(), ServiceFailure, ConfigDefect, SuiteIssue,
                         unused_by_app(), need(), basic_auth(), expect_ok/status/refused, contract()
  bootstrap.py           the start-up download: the five requests once per run (before collection),
                         the app's accept rules, snapshots in remote_config/<ENV>/ (lists as one
                         group, pat-config alone, sha256 in snapshot.json), fallback to them
  dotnet.py              Json.NET / System.Text.Json behaviour: typed DTO binding, json_schema
                         readers, load() replaying GetConfigurationAsync, parse_headers,
                         header_problem, read_agenthub_section
  remote.py              fetch() over the bootstrap data, load_result() (never raises for load
                         problems), config() (raises ConfigUnloadable, a ServiceFailure, when the app
                         could not load the lists), agenthub_section(), fresh_agenthub_problem()
  usage.py               per run, from this run's configuration: which config-dependent services the
                         app uses (2d-to-3d, 2d-to-video, mav-starkit-api, device-mapping via
                         ImageTo3DAgent / ImageToVideoAgent reachable from PointAndTalkAgent;
                         deepgram, whisper, vision, sam3 via pat-config fields; mavslides-llm,
                         mavslides-openrouter, mavslides-websearch, mavslides-tavily via the tools
                         assigned to MavSlidesAgent; mavslides-vision is always "unused", see 1.8.0).
                         plugin._apply_usage turns a failure of an unused service into "no effect on the app"
  runlog.py              logs/<YYYYmmdd-HHMMSS>/suite.log, tests.log, console.log; keeps the newest
                         LOG_RUNS_TO_KEEP folders; every line redacted. console.log copies pytest's
                         terminal writer (plugin.pytest_configure wraps tr._tw._file); sys.stdout is
                         never replaced (see 1.1.2)
  services.py            per-service facts: owner, where the credential lives, impact, rotation
  causes.py              explain(res) and status-aware fix(res, owner, service_fix)
  plugin.py              classifies outcomes, records evidence, renders the report at sessionfinish
  report.py              bento dashboard HTML (see section 7); also writes results/history.json
  report_theme.py        visual layer applied to the rendered report (report_assets/proto.css, proto.js; Motion)
remote_config/<ENV>/     created at run time: agents.json, tools.json, mcps.json, llm-providers.json,
                         pat-config.json (bodies exactly as downloaded) and snapshot.json
logs/                    created at run time: one folder per run, plus setup.log from run_tests.bat
scripts/
  refresh_env.py         regenerates .env (AIHUB_WIN_TOKEN, SEQ_API_KEY and the two basic-auth values) from the
                         repo's secrets.local.txt and updates changed base URLs in suite.env (only after a rotation)
  mock_aihub.py          local mock of the configuration service with fault scenarios (mode.txt); the
                         `slides*` modes also mock the MAV Slides endpoints (see its docstring)
  sam3_point_formats.py  one-off: posts SAM3 /predict in the README format and the Sam3Client format
tests/assets/            probe.jpg (640x360, text "MAVERICK"), probe_silence.wav (3 s, 16 kHz),
                         probe_voice.wav, README.md
```

### Probe status values

`OK`, `AUTH_FAILED`, `NOT_FOUND`, `CLIENT_ERROR`, `SERVER_ERROR`,
`UNAVAILABLE`, `TIMEOUT`, `DNS_FAILED`, `TLS_FAILED`, `CONNECTION_FAILED`,
`CONTRACT`, `UNEXPECTED_ACCESS`.

Failures are grouped by `cause_key`. For auth and transport statuses the key
is per subject, so one bad token is one root cause, not one per endpoint.

### Coverage by file

| File | Checks |
|---|---|
| `test_00_setup` | `.env` present; `suite.env` present; credentials set; base URLs valid (http only for localhost); environment name; assets present |
| `test_01_remote_config` | The app can load the lists (Json.NET, typed DTOs); silent type conversions (no-effect); then the app's startup validation: non-empty lists, keyword equals Name, duplicates, provider ids, assignments, embedding provider and its Authorization header, provider headers (incl. null and duplicate names) |
| `test_05_config_download` | Each of the five start-up downloads succeeds by the app's rules; failures name the snapshot in use; a successful download was saved |
| `test_02_agent_graph` | Root agent exists; handoff tool not assigned; agents named in the root prompt are reachable; memory tools assigned; orphan agents (informational) |
| `test_10_aihub_service` | Refuses no token and a wrong token; unknown environment returns 404 (the shipped-token check moved to `test_05`) |
| `test_11_pat_config` | The downloaded AgentHub section is present and deserializable (System.Text.Json rules, incl. the sync flag type); required fields; `WhisperUrl` absolute; segmentation fields all-or-nothing; `SpeechToTextUrl` equals `WhisperUrl`; (1.9.0) `MavStarkitApiKey` and `DeviceMappingBearerToken` set, the token without `Bearer `, `AgentHub.MavSlides` URLs absolute |
| `test_20_llm_providers` | Every provider answers a minimal request with its key and model (parametrised when tests are collected) |
| `test_21_speech` | Deepgram `/v1/projects`; Whisper in en, de and auto |
| `test_22_segmentation` | Vision naming; SAM3 text; SAM3 point (marked no-effect) |
| `test_30_mav_starkit` | Health; files with, without and with a wrong key; controllers online; metadata; stereo marker; upload (with `device_id` + `environment`, echoed and listed)/download/overwrite/delete round trip on `qa-probe-*.glb`; bad extension (SRD pairing checks removed in 1.2.0) |
| `test_31_generation_services` | 2d-to-3d and 2d-to-video: health; empty task returns 400; unknown file token returns 400; unknown task returns 404 |
| `test_40_mcp_servers` | Definition is well formed (all servers); initialize handshake for `streamable_http` servers only (stdio servers run only on a Maverick machine and get no handshake check from 1.2.0). Servers no agent assigns are marked no-effect. |
| `test_41_tavily_image_mcp` | stdio record passes `--api-key` and `--folder`; Tavily `/search` returns images. **One real, quota-using search per run.** |
| `test_42_mavslides` | MAV Slides (1.8.0; settings from `AgentHub.MavSlides` of pat-config since 1.9.0): the main, coder and vision LLM each answer `chat/completions` (vision with an image); OpenRouter `/images` refuses no key, and accepts the key (a request without a prompt must be rejected as invalid, not unauthorized; 402 = no credit); web-search MCP `initialize`; the MAV Slides Tavily key returns images (**one more quota-using search per run**); `MavSlidesAgent` has its 7 tools and `%existing_presentations%`. Marker `live`: one real OpenRouter image (billable). An empty value skips the check when the service is unused, and is a `ConfigDefect` (named `AgentHub.MavSlides.<Field>`) when it is used. |
| `test_50_logs_mapping_seq` | Device mapping (service `device-mapping`); log-upload token for `/api/logs-session` and `/api/logs/session-image` (refused without a token; token accepted; service `log-upload`, always used); Seq ingestion |
| `test_90_live_generation` | Marker `live`: real 3D and stereo video generation. Slow and billable; only with `--live`. |

### Known defects

These are `xfail` with `raises=ConfigDefect`, confirmed on real QAS:

- `NanoBananaImageEditorAgent` cannot be handed off to.
- `memory_save` is not assigned to `PointAndTalkAgent`.

Orphan agents on QAS: `GoogleWorkspaceAgent`, `NanoBananaImageEditorAgent` and
`ResearchAgent`.

## 7. Results presentation (`results/result.html`)

- **Style (1.7.0):** `report.py` still renders the 1.6.0 NextUI / HeroUI page (CSS and JS inline, no build
  step). On top of it `report_theme.apply()` adds a visual layer from `agenthub_health/report_assets/`
  (`proto.css`, `proto.js`): shadcn "zinc" tokens, aurora bento, floating glass shell, Geist fonts, and
  Motion (motion.dev). **Motion is loaded from `cdn.jsdelivr.net` (`motion@12.23.12`), the only script from
  outside**; offline, a 2.5 s fail-safe drops the `js-motion` class and the page shows as plain CSS.
  The 1.6.0 look is the base, so the "Tokens" note below still describes the underlying variables.
  1.10.0 adds hover and entrance motion on top (see "Version 1.10.0" below). Geist is requested as a variable
  font (`wght@100..900`), which the heading weight shift needs.
- **Tokens and where they come from:** light values are from
  `designsystems.one/design-systems/nextui` (a catalogue page titled "HeroUI Design System";
  it says its values are "indicative, not canonical"): primary `#006fee`, secondary `#7828c8`,
  foreground `#11181c`, background `#fff`, content2 `#f4f4f5`, border `#d4d4d8`, success
  `#17c964`, warning `#f5a524`, danger `#f31260`, radii 8 / 12 / 14 px, medium shadow
  `0 4px 12px rgba(0,0,0,.08)`, motion 250 ms ease, Inter 400-700. **Not on that page, filled
  in from memory of the HeroUI docs and to be checked against heroui.com/docs/customization/colors:**
  all dark values (background `#000`, cards `#18181b`, content2 `#27272a`, text `#ecedee`,
  secondary `#9353d3`, primary text `#338ef7`, no shadow) and the darker text shades used in the light
  theme for contrast (success `#12a150`, warning `#c4841d`, danger `#c20e4d`).
- **Status colours:** passed = success, failed = danger, no app effect = warning, known = primary,
  skipped = grey, suite issues = secondary purple (NextUI has no orange; the CSS name is `--suite`).
  Variants are "flat" (a tint of the colour on the surface); the verdict icon is "solid".
  No gradients, no glow. `data-verdict` on `<html>` picks the verdict tile colour.
- **Theme:** Auto / Light / Dark button (system by default, saved in
  `localStorage` key `agenthub-health-theme`).
- **Icons:** every status has an icon as well as a colour (inline SVG sprite).
- **Sidebar order = page order:** Overview, Failed, Failed with no app effect,
  Suite issues, Known issues, Passed, Skipped, Run details. A scroll-spy marks the
  section in view. Under 920 px the sidebar becomes a bottom bar.
- **Sticky toolbar:** search (`/` or Ctrl+K), status filter, service filter chip,
  Expand all / Collapse all, "Copy failures for Teams". The filter state is kept in
  the page URL (`?status=`, `?q=`, `?service=`). Keys: `j`/`k` next/previous card,
  `e` open or close it, `Esc` clears the search.
- **Overview (bento):** verdict tile with links to the root causes, a segmented
  donut, one clickable chip per status, a service health grid (one tile per service
  key found in the probes; click filters the cards), "Changes since the last run",
  and the five slowest requests drawn against `AGENTHUB_HEALTH_TIMEOUT` (amber above
  half of it, same rule as `suite.log`, LLM and live checks excluded).
- **Run history:** `results/history.json` (gitignored with `results/`) keeps the
  check ids and categories of the last `AGENTHUB_HEALTH_LOG_RUNS` (7) runs per environment. It feeds the
  badges "new" and "still failing - N runs" on failure cards, "fixed since last run"
  on passed cards, and the changes tile. Nothing from responses is stored. A broken
  or missing file only means "first run recorded".
- **Kept on purpose:** the section categories and ids, collapsed `<details>` cards,
  and the Teams copy. `copyCard` builds the Teams text from the card's DOM
  (`summary .eyebrow`, `summary h3`, `summary .badges .badge`, then `.card-b`), so
  those classes must not change. "Copy as Markdown" (end of every card) and "Copy
  failures for Teams" reuse the same card structure.
- **Passed checks** are grouped by area (collapsed `details.group`); each group
  shows its count and request time. The cards inside are unchanged.
- **Print:** all cards are opened for printing, navigation is hidden.

### Sections

1. Overview (verdict, donut, status chips, service health, changes, slowest requests)
2. Failed checks
3. Failed, no effect on the app
4. Suite issues
5. Passed checks
6. Known issues
7. Skipped
8. Run details

### Verdict

- **Red:** any failure affects the app.
- **Amber:**
  - only no-effect failures: "Nothing AgentHubNext uses today has failed...";
  - or suite issues only.
- **Green:** everything passed.

### Each failure card shows

- the root cause;
- the evidence (masked);
- the location: the deepest frame under `tests/`;
- the impact and the owner;
- "How to fix", which depends on the status:
  - 5xx or 503: report to the owner with the response;
  - timeout: rerun;
  - network: check this machine's path;
  - auth: rotate the credential where it lives.

No-effect cards also show "Why AgentHubNext is not affected today".

### How outcomes are classified

- `ServiceFailure` and `ConfigDefect` count as failed, or as "unused" when
  inside `unused_by_app(reason, when=...)`.
- `SuiteIssue` and collection errors are suite issues. Collection errors keep
  only their last 14 lines.
- A known xfail is "known"; if it unexpectedly passes, it is "known_fixed".

## 8. Rules when changing the suite

- Ground every check and every explanation in agent-hub-backend source or docs,
  and cite the file.
  - Do not invent endpoints, fields or behaviour.
  - If something is not in the source, say "I do not know".
- Mirror the app's request exactly (fields, headers, URL rules), so a pass
  means the app would succeed too.
- Use `unused_by_app()` for anything the app does not call today, or that no
  agent assigns. It still reports, but does not turn the verdict red.
- For a service whose use depends on the configuration, add its rule to
  `usage.py` (grounded in the backend source) instead of per-test logic, and
  make the checks `call()` it under that service key. The rule is re-evaluated
  on every run, so a service becomes a real failure again as soon as the
  configuration starts using it.
- Put new services in `services.py`, with owner, credential location and
  impact.
- Bump `__version__` on every change.
- Verify against a local mock before handing over.
  - `scripts/mock_aihub.py` mocks the configuration service (scenarios in its
    docstring). Other services are not mocked; the earlier all-services mock
    (`FAULTS=1/2`) was a throwaway and is lost.
  - Run a copy of the suite with a fake `.env` pointing at `127.0.0.1:8765`,
    never the real `.env`.
  - For configuration changes check at least: healthy, down with and without
    a saved copy, badtypes, notes, pat-bad, dupheader.
- No check may fetch the configuration itself; use `remote.fetch()`,
  `remote.config()` or `remote.agenthub_section()`.
- The session workspace on the user's PC cannot reach the Ameria services
  (proxy 403). Real runs happen only on the user's PC.
- Deliver changed files into this folder. Never touch `.env`. Non-secret settings
  go into `suite.env`, never into `.env`.
- Commands for the user:
  - Say whether they are for PowerShell or cmd.
  - PowerShell uses `$env:NAME`, `` `n `` and a single `%` in curl `-w`.
  - cmd uses `set` and `%NAME%`, and needs `%%` inside a `.bat` file.
  - Prefer a Python script that reads credentials from pat-config over having
    the user paste secrets.

## 9. Real-run history and open items

### First real run

Windows 11, Python 3.13.3, QAS, 13.9 s: 105 checks, 91 passed, 3 failed,
0 suite issues, 2 known issues, 9 skipped.

**Healthy:** all 3 LLM providers, Deepgram, Whisper (en, de, auto), vision,
SAM3 text, mav-starkit-api, the generation services, device mapping, log
upload, Seq, and 2 of the HTTP MCPs.

**The 3 failures, none of which affects the app:**

1. `SpeechToTextUrl` set.
   - Resolved in 1.0.2: it equals `WhisperUrl` on QAS, so the check passes.
2. **SAM3 `POST https://proxy-ai.ameriadev.de:7005/predict` returns HTTP
   500.** Response: `Internal processing error (request_id=28071c2eabf4)`.
   - The user reports a 500 even with the README format
     (`point_coords=100,60`, `point_labels=1`), so the `[[x,y]]` format of
     `Sam3Client` is not the only cause.
   - The service README says its errors are opaque on purpose: only the
     exception type is logged, under the `request_id`.
   - The cause is **unknown**. Next steps:
     - the service owner checks the container log (`docker compose logs`) for
       the request id(s);
     - confirm that proxy port 7005 routes to the service documented on port
       8005;
     - optionally compare with `/predict_text_point`.
   - Separate latent bug: `Sam3Client.SegmentByPointAsync` sends `[[x,y]]`
     and `[1]`, while the README documents `x1,y1` and `1`. It is also
     `mask_threshold`, which `/predict` does not document. This matters only
     if the point flow is ever used.
3. HTTP MCP `tavily-search-image` returns 503 from Apache.
   - No agent assigns it, so there is no effect on the app.
   - Either restart it or remove the record.

### Version 1.0.2 (added after the first run; no real run yet)

- `test_41` (the Tavily key and the MCP command line).
- The `SpeechToTextUrl` rule.
- Redaction of `--api-key`.
- `scripts/sam3_point_formats.py`.

The first real 1.0.2 run should show whether the Tavily key and quota work.

### Version 1.1.0 (no real run yet)

- The configuration is downloaded once at the start of every run
  (`bootstrap.py`) and saved to `remote_config/<ENV>/`; a failed download
  falls back to the latest saved copy.
- `test_05_config_download` replaces `test_10::test_endpoint_answers_with_the_shipped_token`.
- Json.NET and System.Text.Json behaviour mirrored (`dotnet.py`), closing gaps
  2 and 3 of the 2026-09-30 review: typed deserialization of the lists and of
  the pat-config section.
- New checks: `test_app_can_load_the_lists`,
  `test_values_have_the_types_the_app_expects`,
  `test_embedding_provider_has_authorization`; header nulls and duplicates.
- `test_11::test_remote_sync_flag_is_boolean` removed; the type rule is part of
  `test_agenthub_section_present`.
- Logs in `logs/` (5 runs kept), `logs/setup.log` for pip.
- MCP checks (`test_40`, `test_41`) unchanged at the user's request; they now
  read the configuration from the start-up download like every other check.
- Open gaps from the review: one environment per run; `application.config.json`
  overrides (`TwoDToVideoBaseUrl`, `TwoDToVideoBasicAuth`) not visible to the
  suite; the `.env` base URL is not compared with the hardcoded
  `ServiceBaseUrl`.

### Version 1.1.2

- 1.1.0 and 1.1.1 did not start on Windows: `AttributeError: '_Tee' object has
  no attribute 'line_buffering'`. On Windows pytest reopens `sys.stdout` at
  start-up (`_pytest.capture._windowsconsoleio_workaround`) and 1.1.0 had
  replaced `sys.stdout` with a wrapper. Fix: `sys.stdout` stays untouched;
  console.log copies pytest's terminal writer, and `__main__` writes its own
  lines and any crash traceback to console.log and suite.log.
- Verified on Linux by forcing that workaround on (it reproduced the error
  with 1.1.1 and passes with 1.1.2). Not yet run on Windows.

### Second real run (1.1.2, 2026-09-30)

Windows 11, Python 3.13.3, QAS, 38 s: 110 checks, 96 passed, 3 failed with no
effect on the app, 0 failed, 0 suite issues, 2 known, 9 skipped. All five
configuration downloads were accepted and saved to `remote_config/QAS/`. No
credential appeared in the logs or the report (checked against every secret
in `.env` and the downloaded configuration).

- `/api/llm-providers` serves `primary` as the numbers 1 / 0, not JSON booleans.
  Json.NET reads them as true / false. From 1.1.3, 0 and 1 are not reported by
  `test_values_have_the_types_the_app_expects`; other numbers still are.
- SAM3 `/predict` still HTTP 500; HTTP MCP `tavily-search-image` still 503
  (both no effect, see first run).
- The Tavily key and quota work (`test_41` passed, 2.5 s).
- `2d-to-3d /health` took 15.2 s against the 20 s timeout (2d-to-video: 44 ms).
  Cause unknown (possibly a cold start). From 1.1.3 `suite.log` lists the five
  slowest requests and warns about any non-LLM request that used more than
  half of `AGENTHUB_HEALTH_TIMEOUT`.
- 6 of the 9 skips are `test_40` handshake checks parametrised over stdio MCP
  servers; left as they are because MCP checks are on hold at the user's request.

### Version 1.2.0 (no real run yet)

- Removed: `test_40` handshake checks for stdio MCP servers; the two SRD pairing
  checks in `test_30`, the `srd` marker and `AGENTHUB_DEVICE_ID`.
- New `usage.py` (see section 6). On QAS on 2026-09-30 every rule said "used":
  ImageTo3DAgent (`generate_3d_object`, `send_file_to_srd`,
  `%existing_3d_objects%`, `%online_srd_devices%`) and ImageToVideoAgent
  (`generate_video`, `send_file_to_srd`, ...) are both handed off to by
  PointAndTalkAgent, and all pat-config service fields are set. So the verdict
  on QAS does not change today.
- `test_11::test_field_is_set`: an empty field now counts as that service not
  being configured (no effect), following the user's rule; `ProxyAuthHeader`
  empty is no effect only when none of Whisper, vision, SAM3 is configured.
- Log-upload checks now use the service key `log-upload` (always used), not
  `device-mapping`.
- The known-issue text of `test_root_agent_has_the_memory_tools_its_prompt_uses`
  was stale: on QAS `memory_save` is assigned now; the missing tool is
  `save_user_memory`.
- The "Services this configuration uses" card in Run details and one
  `Service ...` line per service in suite.log show the per-run result.

### Version 1.2.1

- The report opens in the default browser when a run finishes
  (`__main__.open_report`): on Windows `os.startfile` (the program registered
  for .html), then `webbrowser` as fallback. Before, a failed
  `webbrowser.open` was swallowed silently; now the outcome is logged in
  suite.log and a failure prints the report path. `--no-open` or
  `AGENTHUB_HEALTH_NO_OPEN=1` still turn it off.

### Version 1.2.2 (real run 2026-10-12)

- `test_22::test_vision_model_names_objects` now sends `chat_template_kwargs: {"enable_thinking": false}`,
  as `VisionObjectClient` does since 4.0.53. Real run on QAS: HTTP 200 in 256 ms with
  `choices[0].message.content`, so the vision server accepts the field.
- Same run: 102 checks, 97 passed, 2 known, 1 skipped, 2 failed with no app effect (SAM3 `/predict` HTTP 500,
  HTTP MCP `tavily-search-image` 503, both unchanged), 0 suite issues.
- Reviewed 4.0.49 to 4.0.54 against the suite: the other commits are UI, local voice matching, and a
  Seq `device-name` property; no endpoint, credential or config change.

### Version 1.2.3 (no real run yet)

- AgentHubNext 4.0.55 (commit 523d78f, 2026-10-14) adds `Logging/SessionImageUploader.cs`: every saved
  screenshot or crop is posted at once, in the background, to `POST {ServiceBaseUrl}/api/logs/session-image`
  (multipart: `file`, `device_id`, `session_guid`, `filename`, `meta` = JSON `{message_index, user_message}`,
  `environment`, `version`; Bearer = `DeviceMappingBearerToken`; 10 MB cap; no retry). It also halves the
  archive upload interval to 5 minutes.
- New in `test_50`: `test_session_image_upload_refused_without_token` and
  `test_session_image_upload_token_accepted`, modelled on the two `/api/logs-session` checks (service key
  `log-upload`; no file is sent, so nothing is stored). A 404 counts as a failure (route missing).
- `services.py`: the `log-upload` entry now names both endpoints and the 5-minute interval.
- Not known: how the server answers a request that has the token but no `file`. `docs/api-logs-session.md`
  covers only `/api/logs-session`; the repository has no document for `/api/logs/session-image`. The check
  accepts any 4xx other than 401/403/404 and was modelled on the sibling endpoint, so the first real run
  must confirm it.
### Version 1.3.0 (2026-10-15)

- Non-secret settings moved out of `.env` into the committed `suite.env`: `AGENTHUB_ENV`, the six base
  URLs, `DEEPGRAM_API_URL`, `TAVILY_SEARCH_URL`, the timeouts and `AGENTHUB_HEALTH_LOG_RUNS`. `.env` now
  holds only the four credentials and the two optional basic-auth values. The obsolete
  `AGENTHUB_DEVICE_ID` was dropped. The user's previous `.env` is kept as `.env.backup-20261015`
  (gitignored by `.env.*`).
- `settings.py` loads `.env`, then `suite.env`; `fix_for()` / `FIX_SETTING` point missing settings at
  `suite.env` and missing credentials at `refresh_env.py` (used by `probe.need`, `test_00`, `bootstrap`,
  `remote`, `test_05`).
- `test_00::test_suite_config_file_present` added.
- `refresh_env.py` writes only credentials, keeps existing basic-auth values, and updates changed base
  URLs in `suite.env`.
- Verified on a copy on Linux: all 13 previous `.env` values resolve identically; `test_00` 15 passed;
  missing `suite.env` gives clear suite issues; `refresh_env.py` reproduced the cleaned `.env` byte for
  byte and detected a changed URL; `git add` stages `suite.env` but not `.env`; no credential value in
  any tracked file. Not yet run on Windows.

### Real run of 1.3.0 (2026-10-15 13:18)

Windows 11, Python 3.13.3, QAS, 13.9 s: 105 checks, 100 passed, 2 failed with no effect on the app,
0 failed, 0 suite issues, 2 known, 1 skipped (orphan agents). All five configuration downloads accepted
and saved. `suite.env` was read correctly (`test_suite_config_file_present` and every base-URL check
passed). No credential from `.env` or pat-config appears in the logs or the report.

- Confirms the open item of 1.2.3: `POST /api/logs/session-image` answers 401 without a token and 422
  with the token and no file, so both new checks pass.
- Unchanged: SAM3 `/predict` HTTP 500, HTTP MCP `tavily-search-image` 503 (both no effect).


### Version 1.3.5 (no real run yet)

- Reviewed backend 4.0.55 to 4.0.59 (2026-10-28). Only mav-starkit-api changed: since 4.0.58
  `MavStarkitApiClient.UploadFileAsync` also sends optional `device_id` and `environment` (from
  `ImageTo3DAgentSettings`, set in `Program.cs`) on `POST /files`. `docs/mav-starkit-api.md` adds
  `modified_at`, `device_id`, `environment` to `GET /files`, a `.json` sidecar removed by `DELETE`, and
  `POST /files/{name}/rename`, `POST /files/{name}/device-info` and a public file-manager page at `/`.
  The app calls none of the new endpoints, so the suite does not check them.
- `test_30::test_upload_download_delete_round_trip` now sends `device_id=agenthub-health-probe` and
  `environment=<AGENTHUB_ENV>` and checks that the upload response and `GET /files` return them.
  Not known: whether the live server already runs the version that stores them; the first real run
  must confirm it. A failure there would be a CONTRACT failure on mav-starkit-api.
- No change in 4.0.56 to 4.0.59 to credentials, base URLs, remote configuration, pat-config, Whisper,
  vision, SAM3, Deepgram, Seq, log upload or MCP code. 4.0.59 turns the "Hey Maverick" wake word off by
  default (local only).
- Versions 1.3.1 to 1.3.4 were made in the working copy without an entry here.

### Version 1.4.0 (2026-11-14, no real run yet)

- Backend 4.0.64 (commit 0b3927f, 2026-11-04) removed every committed credential from
  agent-hub-backend. `WindowsApiToken`, `MacApiToken`, `MavStarkitApiKey`, `DeviceMappingBearerToken` and
  the Seq `apiKey` are now `BuildSecrets.*`, compiled in from the local `secrets.local.txt`
  (`build/Secrets.targets`, `secrets.local.example.txt`). Result: all four regexes of the old
  `refresh_env.py` stopped matching, so it would have refused to write `.env` and a new PC
  (`run_tests.bat` runs it when `.env` is missing) could not be set up.
- Compared by hash only, none of the four values in the user's `secrets.local.txt` equals the value in the
  suite's `.env` (lengths differ too). So the credentials were rotated and the current `.env` is
  stale; the first real run will likely show AUTH_FAILED on aihub-service, mav-starkit-api,
  device-mapping, log-upload and Seq until `refresh_env.py` is rerun. Not verified against the
  servers: the session workspace cannot reach them.
- `refresh_env.py` now reads `secrets.local.txt` (repo root, or `--secrets <path>`), parses it like
  `Secrets.targets` does, strips a leading `Bearer ` from the Windows token, and refuses to write on a
  missing, empty or placeholder value. Base URLs are still extracted from the source; all six patterns
  still match and agree with `suite.env`. Tested on a copy with fake values: healthy, placeholder,
  missing key, missing file, default location; `.env` unchanged on every refusal.
- Texts updated: `services.py`, `settings.py`, `suite.env`, `.env.example`, `run_tests.bat`,
  `README_GITHUB.md`, `README.md`, this file.
- The suite's working copy was in an unfinished merge of the local initial commit (2873347) with
  GitHub commit c7c8488 (2026-10-15, README wording). Resolved in the files on 2026-11-14:
  `README.md` now equals `README_GITHUB.md` (the plain-language text from GitHub, plus the
  `secrets.local.txt` wording); `.gitignore` keeps the suite rules first, then GitHub's standard
  Python template. Checked with `git check-ignore`: `.env`, `.env.backup-20261015`, `remote_config/`,
  `results/`, `logs/`, `.venv/` are ignored; no tracked file is ignored; no `.env*` or `remote_config`
  file was ever committed. Still to do by the user: `git add README.md .gitignore` and commit (the
  session shell cannot finish git operations: it cannot delete git's lock files).
- 2026-11-14: the user ran the new `refresh_env.py`. All four `.env` values now equal the
  `secrets.local.txt` values (checked by comparison only, never printed). No real suite run yet.
- Noticed in the user's `secrets.local.txt`: the Windows service value has no `Bearer ` prefix, while the
  template says it must be the full Authorization header and `RemoteConfigurationManager` sends the
  constant as the header value unchanged. A build with that value probably sends no scheme. Not
  confirmed.
- Reviewed backend 4.0.59 to 4.0.69 (HEAD 9b0e542, 2026-11-09). No change to remote configuration DTOs,
  pat-config, Whisper, vision, SAM3, Deepgram, log upload or MCP code. Other changes: secrets (above),
  mav-starkit-api uploads send `device_id`/`environment` (already covered in 1.3.5), generation
  clients report stages and support cancellation, background requests, HandPose, LLM error
  classification and context recovery (`LlmClient`, `AgentLight`), and a `_frozen` flag in
  ObjectSegmentationService. No endpoint or request-shape change found in `LlmClient.cs` by grepping its
  diff for URLs and headers; not read line by line.
- Not changed, known: `docs/mav-starkit-api.md` gained `POST /files/{name}/rename` and a public file manager
  at `/`; the app calls neither.

## 10. SAM3 service reference (from its README, provided by the user)

- **Stack:** `facebook/sam3` on Linux with NVIDIA, run with docker compose.
- **Service port in the docs:** 8005. We call it through the proxy on 7005.
- **Endpoints:**
  - `POST /segment`
  - `POST /predict`: `image_file`, `point_coords` as `x1,y1,...`,
    `point_labels` as `1,0`, `threshold` (0.7), `border_size` (10), `raw`,
    `return_zip`. Returns `masks` and `scores`.
  - `POST /predict_multiple`
  - `POST /predict_text`: `text_prompt`, `threshold` (0.5), `mask_threshold`
    (0.5), `return_zip`. Returns `masks`, `boxes` and `scores`.
  - `POST /predict_text_multiple`
  - `POST /predict_text_point`
  - `GET /health`, which returns `{"status":"ok"}`
  - `GET /docs`
- **Limits:** `MAX_UPLOAD_BYTES` defaults to 25 MiB; larger uploads get 413.

### Version 1.5.0 (2026-11-15, no real run yet)

- `report.py` rewritten: dark-first bento design, sticky search and filter toolbar, service health
  grid, slowest requests, run history (`results/history.json`), "Copy failures for Teams",
  "Copy as Markdown", keyboard navigation, scroll-spy, printable. Section 7 describes it.
- Passed checks are grouped by area; the card markup that the Teams copy reads is unchanged.
  Verified with synthetic records (`render()` called directly, never the real `.env` or services):
  Teams text of a failed card equals the old format plus the "new" badge; Markdown copy; dark and light;
  healthy and suite-issue verdicts; narrow width; filter by status and by search text.
- Not verified: a real suite run (the first one writes the first history entry, so the changes tile
  says "first run" until the second), Microsoft Teams paste, Edge and Safari (tested in Chrome only).
- Sidebar order now follows the page order; before, Passed was listed second but shown fifth.
- Suite issues are orange now; before they shared nearly the same gold as no-effect.

### Version 1.6.0 (2026-11-15)

- Restyled `report.py` with NextUI / HeroUI tokens (section 7, with what came from the page and what did not).
  Layout, behaviour, ids, Teams copy and history are unchanged from 1.5.0; `results/history.json` is still read.
- Real run after the change: QAS, 9.6 s, 106 checks, 100 passed, 3 failed (Seq 401, SAM3 `/predict` 500,
  `tavily-search-image` 503, unchanged), 2 known, 1 skipped. Seen in a screenshot of the top of the
  page only; not scrolled through, no Teams paste.
- Suite issues changed from orange to purple (NextUI palette). The 1.5.0 look is kept as
  `report.py.v1.5.0-bento.bak` in the session scratchpad only, not in the repository.

### Version 1.7.0 (2026-11-17)

- New `agenthub_health/report_theme.py` + `report_assets/proto.css` and `proto.js`, applied by `report.render()`
  to the finished HTML (the report's own markup, ids, script, Teams copy and history are unchanged).
  Added: shadcn-style tokens and components, aurora background, floating sidebar and toolbar, Motion
  reveals, count-up numbers, sliding nav pill and filter thumb, Ctrl+K command palette, copy toasts, and the
  donut animation. The donut plays when the cursor enters the ring or a status chip; a chip ends on only its
  own segment with that count in the centre, and a category without a segment plays the full default draw.
- Designed in a prototype first (`results/result.prototype.html`, built by the throwaway
  `results/prototype/build_prototype.py`, both gitignored); this version moves the same files into the package.
- Verified in the built-in browser on a real report: light, dark, 375 px width, command palette, donut
  hover and chip hover through scripted events. Not verified: a real mouse hover, a full suite run with
  this version, Edge, Safari, Teams paste. The footer and `suite_version` show 1.7.0 after the next run.

### Version 1.8.0 (2026-11-20, no real run yet)

- Backend 4.0.70 (HEAD dcf3f95, 2026-11-19, merge of PR #6) adds MAV Slides: `MavSlidesAgent` with the tools
  `generate_presentation`, `open_presentation`, `show_slide`, `edit_slide`, `edit_slide_image`,
  `get_presentation_state`, `close_presentation` (files under `src/remote_prompts/windows/`), and an engine in
  `src/Windows/MavSlides/Engine` that calls its own services. Their addresses, keys and models are build secrets
  (12 new `MAVSLIDES_*` names in `secrets.local.example.txt`), not remote configuration. No change to
  `RemoteConfiguration/`, pat-config, Whisper, vision, SAM3, Deepgram, log upload, mav-starkit-api or the existing
  MCP code was found (diff searched for URLs, headers and endpoints; not read line by line).
- At review time the saved QAS copy of 2026-11-20 10:14 already contained `MavSlidesAgent` and
  `generate_presentation`, so the feature is live on QAS. Not checked: whether `PointAndTalkAgent` hands off to it
  there (the app's `PointAndTalkAgent` file did not change in the repository).
- New `tests/test_42_mavslides.py` (see section 6), five services in `services.py` and `usage.py`
  (`mavslides-llm`, `-openrouter`, `-websearch`, `-tavily`, `-vision`), settings in `settings.py` / `suite.env` /
  `.env.example`, `refresh_env.py` copies the new values, `mock_aihub.py` has `slides*` modes.
- Usage rules: llm = `generate_presentation` or `edit_slide`; openrouter = `edit_slide_image`, or
  `generate_presentation` as the picture fallback; web search and Tavily = `generate_presentation` (a failed web
  search or image search does not stop a presentation: the engine continues without it, so the impact texts say
  "degraded"). **Vision is always reported as no effect**: the engine calls it only when "remove watermarks" or
  "expand web images" is on in the AgentHub settings window, both off by default, and that setting lives on each PC
  (`agenthub.settings.json`), invisible to the suite. If the team turns them on by default, change that rule in
  `usage.py`.
- Not grounded in the source, to confirm on the first real run:
  - `test_openrouter_key_accepted` sends `/images` without a prompt and expects 400 or 422 (a 2xx with an `error`
    object is also accepted; a 2xx without one is reported as `UNEXPECTED_ACCESS`, because an image may have been
    generated and billed). How OpenRouter answers that is not known. `test_openrouter_refuses_without_key` expects
    401/403 without a key.
  - The model name in that request is the first of `OpenRouterOptions.DefaultImageModels`.
  - The web-search MCP check is `initialize` only. It does not list tools or search (that needs the session id
    header, which `probe.call` does not expose), so it does not prove `tavily_search` exists.
  - Which of the owners named in `services.py` is right is a guess ("MAV Slides developer / owner of the endpoint").
- Verified on a copy against `scripts/mock_aihub.py` with a fake `.env`: `slides` (15 passed), `slides-rejected`
  (LLM, OpenRouter, Tavily fail; vision is no-effect), `slides-nocredit` (402), `slides-noplaceholder`
  (ConfigDefect), `healthy` (agent absent: checks skipped, agent check skipped), unset values (suite issue when the
  service is used, skip when not), and `refresh_env.py` with a fake `secrets.local.txt` (keys to `.env`, addresses
  to `suite.env`, empty coder/vision left alone). Not verified: a real run, the real services, the report page for
  the new rows.
- After this version the user must rerun `refresh_env.py` once to get the MAV Slides keys into `.env`. Until then
  the MAV Slides checks are suite issues (the agent is live on QAS), not failures.
  **Superseded by 1.9.0:** the MAV Slides values are no longer in `.env` or `suite.env`; no rerun is needed for them.

### Version 1.9.0 (2026-11-21, no real run yet)

- Pulled backend 4.0.71 (commit 6024af4, `next`, one commit after dcf3f95). Its change: the service credentials
  `MavStarkitApiKey`, `DeviceMappingBearerToken` and the MAV Slides endpoints, models and keys are no longer build
  secrets. They are read from the AgentHub section of pat-config (`AgentHubRemoteSettings`, new `MavSlides` object;
  `RemoteSettingsManager.ApplyServiceCredentials`; `SlidesService.Configure`). `BuildSecret` items of
  `Ameria.LlmExecutionEngine` and `MavSlides` and `Engine/Secrets.cs` were deleted. Only `AGENTHUB_SEQ_API_KEY` and the
  two AI-Hub tokens stay in `secrets.local.txt`. Base URLs are unchanged constants. Other files in the commit are
  docs, build scripts, `tools/mav-starkit-api/*.bat` and tests; none changes an endpoint or a request shape.
- Suite: `dotnet.read_agenthub_section` reads the three new members (the `MavSlides` object with 14 string members);
  `remote.agenthub_value()` / `remote.mavslides()` return a value from the downloaded section, skip when there is no
  usable section, and raise a `ConfigDefect` per setting when it is empty (service `mav-starkit-api`, `log-upload`, or
  the MAV Slides service of the check). `test_30`, `test_50` and `test_42` use them instead of `.env` / `suite.env`.
- `settings.SECRET_VARS` is now `AIHUB_WIN_TOKEN` and `SEQ_API_KEY`; `MAVSLIDES_*` lists and the `suite.env` /
  `.env.example` entries are gone; `refresh_env.py` writes only the two credentials plus the basic-auth values and no
  longer reads MAV Slides values; `bootstrap._register_secrets` masks the new secrets; `services.py` names pat-config as the
  credential location and "no rebuild needed" as the rotation (`PAT_FIX`).
- New checks in `test_11`: `test_service_credential_is_set[MavStarkitApiKey|DeviceMappingBearerToken]`,
  `test_device_mapping_token_has_no_bearer_prefix`, `test_mavslides_urls_are_absolute`.
- Decision: no fallback to old `.env` keys (see section 4). Consequence on a real QAS: if QAS does not carry the new
  values yet (the docs say only DEV did on 2026-11-20), the checks of mav-starkit-api, device mapping and log upload
  fail with a configuration defect that affects the app (`log-upload` is always used), and the MAV Slides checks fail
  as defects because `MavSlidesAgent` is live on QAS. That is the app's own situation, not a suite fault.
- Verified on a copy in the session scratchpad with a fake `.env` against `scripts/mock_aihub.py` (new modes
  `creds-missing`, `token-bearer`, `slides-missing`, `slides-nosection`, `slides-badtype`; the `slides` and `healthy`
  modes): `test_00`, `test_11` and `test_42` give 32 passed and 1 skipped on `slides`; each fault mode produced the
  expected failure and nothing else; a scan of logs and report for the fake secret values found them only in
  `remote_config/`. Not verified: a real run on the user's PC, the real QAS, the report page for the new rows.
### Version 1.9.1 (2026-11-21)

- At the user's request the suite keeps the **7 most recent runs** and deletes older ones automatically at every
  run: `AGENTHUB_HEALTH_LOG_RUNS=7` in `suite.env` (default in `settings.py` also 7) now governs both the run folders
  in `logs/` (`runlog._prune`) and the runs per environment in `results/history.json` (`report.HISTORY_KEEP`, was a
  fixed 10). `logs/setup.log` and `remote_config/` are single files per environment and are not affected.

### Version 1.10.0 (2026-11-21)

Report motion, designed in the prototype first (`results/prototype/`, gitignored) and moved into
`agenthub_health/report_assets/proto.css` and `proto.js`; `report_theme._EARLY` now requests Geist as
`wght@100..900`. No change to checks, classification or the report's own markup and script.

- **Overview entrance:** one sequence instead of independent reveals: verdict tile, its icon (spring) and headline,
  ring tile, then the six status chips. Each non-zero chip gets a share meter along its bottom edge (width =
  share of all checks, minimum 6 %). A red verdict shakes its icon once; a green one gives off a slow ring pulse.
  The verdict and ring tiles tilt up to 7 degrees toward the cursor. Shift+R replays the sequence.
- **Section headings:** the heading text shifts weight 500 to 800 and brightens while its section is hovered or has
  focus (reference: codefronts.com "Variable Font Weight Shift"). Each heading's text is wrapped in
  `span.h-t[data-text]`; an invisible bold twin (`::after`) reserves the widest width, so nothing reflows.
- **Sidebar:** hovering or Tab-focusing an unselected item blurs the other unselected items (1.6 px, opacity .45;
  reference: "Blur to Focus Text Effect"). The selected item stays sharp.
- **Cards:** a conic gradient ring in the card's colour circles its border on hover (reference: "Gradient Border
  Draw"). It applies to `.card` (check cards and Run details cards), `details.cause`, `details.group`
  (only when its own header is hovered), overview tiles except `.t-verdict`, status chips and service tiles. It is
  off while a `details` card or group is open, in print, and static under reduced motion.
- **Prototype build:** `results/prototype/build_prototype.py` now strips the layer that `report.py` bakes in before
  adding the prototype files. Before, both layers ran at once and fought over the same tiles.
- Verified in the user's Chrome (served from a local http server; the built-in browser pane blocks the CDN):
  entrance sequence, meters, counters, ring on cards and groups, ring off when open, sidebar blur, weight shift with
  an unchanged heading box. Not verified: frame-by-frame timing and the tilt by eye (the automated tab throttles
  animation frames), Edge, Safari, a full suite run with this version.

### Version 1.11.0 (2026-11-23, no full real run yet)

- New `agenthub_health/repo_version.py`, called by `__main__` before pytest starts. It fetches one commit of
  `AGENTHUB_REPO_BRANCH` (suite.env, `next`) from `AGENTHUB_REPO_URL` without file contents (`--depth 1
  --filter=blob:none`) into `remote_config/agenthub-next-git`, and reads `<Version>` from
  `src/AgentHub/AgentHub.csproj`. It uses this PC's own Git sign-in, prompts are off, nothing is stored. It never
  reads the local clone and never fails the run: if git, the network or access is missing, the report shows the
  GitHub version as "unknown" and `suite.log` says why.
- "Version the suite uses" = `AGENTHUB_VERSION_USED` in suite.env (4.0.71). It cannot be derived from code: **bump it by hand
  after reviewing the suite against a new AgentHubNext version.** Compared numerically.
- Report header (`report._app_version`, in `div.meta`): `suite <used>` and `GitHub <remote>`. GitHub ahead = red and
  glowing (static under reduced motion); equal or behind = green; unknown = grey. The tooltip names the branch.
- Checked on 2026-11-23 from the user's PC: `next` has 4.0.72, `main` has 4.0.69. The branch is a choice: the suite was
  built against `next`; set `AGENTHUB_REPO_BRANCH=main` to follow `main`.
- Verified: the fetch and version read against the real GitHub repo; the header rendered by `report.render()` with a
  synthetic run, red state in the in-app browser, green state by class swap only. Not verified: a full suite run, a PC
  without GitHub access, Edge, Safari.
