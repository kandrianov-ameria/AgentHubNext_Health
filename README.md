# AgentHubNext health suite

Checks that every external service, LLM provider and configuration record the
Windows build of AgentHubNext depends on is up, accepts the credentials the app
ships with, and answers in the shape the app parses.

## Run it

Double-click `run_tests.bat`, or from a terminal in this folder:

```
run_tests.bat
```

That is the whole procedure. The first run creates `.venv` and installs the
dependencies (about a minute); later runs start immediately. When it finishes,
`results\result.html` opens in your browser.

Options, all optional:

| Option | Effect |
|---|---|
| `--live` | also run a real 3D and video generation (slow, billable) |
| `--env DEV` | test another environment for this run (DEV / QAS / STG / PRD) |
| `--no-open` | do not open the report afterwards |

Requirements: Windows with Python 3.9 or newer on PATH, and network access to
`aihub.ameriadev.de`, `seq.ameria.de` and the LLM / proxy hosts named in the
remote configuration.

## What happens first

Every run starts by downloading the remote configuration exactly as AgentHubNext does when it
starts: the agent, tool, MCP and LLM provider lists and the pat-config of the environment. All
checks then use that one download.

- A download that succeeds is saved to `remote_config\<ENV>\`.
- When a download fails, the checks use the copy saved by the latest run in which it
  succeeded, and the report says so (check "start-up download of this configuration document
  succeeds", and the "Remote configuration used" card under Run details).
- `remote_config\` holds live credentials (LLM keys, the Deepgram key). It is gitignored like
  `.env`; do not share it.

## Logs

Each run writes its logs to `logs\<date>-<time>\`:

| File | Content |
|---|---|
| `suite.log` | what the suite did and how long each phase took: downloads, fallback, collection, report |
| `tests.log` | one entry per check: outcome, duration, message, requests made |
| `console.log` | everything the run printed to the console |

Only the newest five run folders are kept. Dependency installation output goes to
`logs\setup.log`. Credentials are masked in all of them.

## The report

`results\result.html` is overwritten on every run. It groups results into:

- **Failed checks** - a dependency did not behave as AgentHubNext requires,
  grouped by root cause, each with the HTTP evidence, the effect on the app and
  how to fix it.
- **Suite issues** - the suite itself could not run a check (missing input,
  unexpected answer shape, a bug in a check). These say nothing about the services.
- **Passed checks**, **Known issues** (tracked configuration defects) and **Skipped**.
- **Run details** - including which configuration each check used (downloaded now, or the
  saved copy and its date) and the log folder of the run.

Credentials are masked everywhere in the output.

## Configuration

Settings are split into two files in this folder:

| File | Content | In git |
|---|---|---|
| `suite.env` | environment name, service base URLs, public API URLs, timeouts, number of log folders kept | yes |
| `.env` | the four credentials (and the optional basic-auth values), extracted from the constants in agent-hub-backend | no |

A real environment variable wins over both files, and a value in `.env` wins over
`suite.env`. To test another environment permanently, change `AGENTHUB_ENV` in
`suite.env`; for one run, use `--env`.

Normal runs never read the repository. After a credential has been rotated in
the application source, regenerate `.env` once. The same script also compares
the base URLs in `suite.env` with the source and updates any that changed:

```
.venv\Scripts\python scripts\refresh_env.py
```

Checks of a service that the downloaded configuration does not use (for example
2d-to-3d when no reachable ImageTo3DAgent is assigned `generate_3d_object`, or Whisper
when `WhisperUrl` is empty in pat-config) are reported under "Failed, no effect on
the app". This is worked out again on every run; the report's Run details show the
result for each service.

## What a run does to shared systems

- mav-starkit-api: stores and then deletes one file named `qa-probe-<random>.glb`.
- Seq: writes one event with `app=agenthub-health`.
- Each LLM provider: one request of a few tokens.
- Whisper / vision / SAM3: one small request each.
- Nothing else is created. The log-upload checks are built so the service must
  reject them, and no generation is started unless `--live` is given.
