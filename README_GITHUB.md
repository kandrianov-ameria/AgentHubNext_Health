# AgentHubNext health suite

An automatic check-up for the services AgentHubNext depends on.

## What is this?

AgentHubNext is an AI assistant app. To work, it talks to many outside services: AI language models, speech-to-text, image recognition, 3D and video generation, file storage, logging, and a central service that hands the app its settings when it starts.

If any of those services is down, rejects the app's password, or answers in a way the app does not expect, the app breaks or loses a feature. This is often hard to see from inside the app.

This project checks all of those services in one go and produces a readable report. Think of it as a doctor's check-up for everything around the app, not the app itself.

## What it checks

In plain terms, each run answers these questions:

- Can the app download its settings when it starts, and are those settings valid?
- Is each AI model reachable, and does it accept the key the app uses?
- Do speech-to-text and image recognition work?
- Do the 3D and video generation services respond?
- Does file storage accept, return and delete a test file?
- Can the app send its logs?
- Are the connected tools (MCP servers) set up correctly?

It does not test the app's screens or buttons, and it never runs on a Maverick device.

## How to run it

You need a Windows PC with Python 3.9 or newer installed (from python.org, with "Add python.exe to PATH" ticked during setup) and access to the company network.

1. Open this folder.
2. Double-click `run_tests.bat`.
3. Wait. The first run takes about a minute longer because it sets itself up. A normal run takes under a minute.
4. When it finishes, the report opens in your browser.

That is all. You do not need to install anything else by hand.

### First run on a new PC

The suite reads its settings from two files:

- `suite.env` holds the addresses of the services, the environment to test (QAS by default), and timeouts. It has no passwords and is part of this repository, so you can read and change it.
- `.env` holds the passwords. It is not in this repository, on purpose, because it holds live credentials.

On the first run, `run_tests.bat` creates it automatically by reading the AgentHubNext source code. It looks for that code in `D:\MAVERICK\_AgentHubNext\agent-hub-backend`. If your copy is somewhere else, open a command prompt in this folder and run:

```
.venv\Scripts\python scripts\refresh_env.py C:\path\to\agent-hub-backend
```

Then double-click `run_tests.bat` again.

## How to read the report

The report is a web page (`results\result.html`). At the top is an overall verdict:

| Colour | Meaning |
|---|---|
| Green | Everything works. |
| Amber | Something failed, but the app does not use it today. Or the suite itself had a problem with one of its checks. Worth a look, not urgent. |
| Red | Something the app needs is broken. Users are likely affected. |

Below the verdict, results are grouped into sections:

- Failed checks: what broke, the evidence, what it means for the app, who owns the service, and how to fix it.
- Failed, no effect on the app: broken, but the app does not use it at the moment.
- Suite issues: the test itself could not run properly. This says nothing about the services.
- Passed checks: everything that works.
- Known issues: problems already known and tracked.
- Skipped: checks that did not apply this time.
- Run details: when the run happened, which environment was tested, and where the logs are.

Passwords and keys are always hidden in the report. Only the last four characters are shown.

## Options

You can add these after `run_tests.bat` in a command prompt. All are optional.

| Option | What it does |
|---|---|
| `--env DEV` | Test another environment (DEV, QAS, STG or PRD) for this run only. |
| `--live` | Also run a real 3D and a real video generation. Slow, and it costs money. |
| `--no-open` | Do not open the report when finished. |

Example:

```
run_tests.bat --env DEV --no-open
```

## Is it safe to run?

Yes. A normal run only asks questions and leaves almost nothing behind:

- File storage: uploads one small test file named `qa-probe-<random>.glb` and deletes it again.
- Logging (Seq): writes one entry marked `app=agenthub-health`.
- Each AI model: sends one very short request.
- Speech, image recognition, segmentation: one small request each.
- Image search (Tavily): one real search, which counts against the search quota.

Nothing is generated (no 3D, no video) unless you add `--live`.

## Where things are saved

| Place | What is in it | Shared in this repository? |
|---|---|---|
| `results\result.html` | The latest report. Replaced on every run. | No |
| `logs\<date>-<time>\` | Logs of each run. Only the newest five runs are kept. | No |
| `remote_config\<environment>\` | The settings the app downloaded, saved as a fallback in case the next download fails. Contains live credentials. | No |
| `suite.env` | Service addresses, environment name, timeouts. No passwords. | Yes |
| `.env` | Passwords only. | No |

Everything marked "No" stays on your PC. The `.gitignore` file makes sure it is never uploaded. Do not share these files by other means either.

## When a password changes

Some passwords are built into the AgentHubNext app. When the developers change one, update this suite once:

```
.venv\Scripts\python scripts\refresh_env.py
```

Normal runs never read the app's source code, only `.env` and `suite.env`. The same command also checks the service addresses in `suite.env` against the app's source code and updates any that changed.

## Changing the environment or an address

Open `suite.env` in any text editor. To test another environment every time, change `AGENTHUB_ENV=QAS` to `DEV`, `STG` or `PRD`. Service addresses and timeouts are in the same file, each with a short comment.

## For technical readers

### Requirements

- Windows, Python 3.9 or newer on PATH.
- Network access to the AI Hub configuration service, Seq, and the AI model and proxy hosts named in the downloaded configuration.
- Python packages are listed in `requirements.txt` and installed automatically into `.venv` by `run_tests.bat`. They are reinstalled only when `requirements.txt` changes. Installation output goes to `logs\setup.log`.

### How a run works

1. `run_tests.bat` creates `.venv` if needed, installs dependencies, creates `.env` if missing, then runs `python -m agenthub_health`. Settings come from a real environment variable first, then `.env`, then `suite.env`.
2. The suite downloads the remote configuration exactly as AgentHubNext does at start-up: the agent, tool, MCP and LLM provider lists, and the pat-config of the environment. All checks use this one download.
3. A successful download is saved to `remote_config\<ENV>\`. If a download fails, the checks use the copy from the latest successful run, and the report says so.
4. pytest runs the checks in `tests\`. Checks marked `live` run only with `--live`.
5. The report is written to `results\result.html` and the logs to `logs\<date>-<time>\`.

### Logs

| File | Content |
|---|---|
| `suite.log` | What the suite did and how long each phase took. |
| `tests.log` | One entry per check: outcome, duration, message, requests made. |
| `console.log` | Everything the run printed to the console. |

### Project layout

| Path | Purpose |
|---|---|
| `run_tests.bat` | The one command to run everything. |
| `agenthub_health\` | The suite's own code: configuration download, report, log handling, masking of secrets. |
| `tests\` | The checks, one file per area (`test_00_setup.py` to `test_90_live_generation.py`). |
| `tests\assets\` | Small sample image and audio files sent to the services. Not secret. |
| `suite.env` | Non-secret settings: environment, service addresses, timeouts. |
| `scripts\refresh_env.py` | Creates `.env` from the AgentHubNext source code and keeps the addresses in `suite.env` current. |
| `scripts\mock_aihub.py` | A local fake of the configuration service, for testing the suite itself. |
| `.env.example` | The list of credentials `.env` needs, with no values. |
| `CLAUDE.md` | Detailed notes on how the app uses each service and why each check exists. |

### Services the app does not use

Some services only matter if the current configuration uses them (for example 3D generation only if an agent that can generate 3D is reachable). The suite works this out again on every run. A failure in a service the app does not use is reported under "Failed, no effect on the app" and does not turn the verdict red.
