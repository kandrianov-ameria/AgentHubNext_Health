"""
Version of AgentHubNext on GitHub compared with the version this suite was written against.

Run once at the start of every run (__main__), before any check. It does NOT read the local clone of
the repository: it fetches one commit of the configured branch from GitHub without file contents
(`--depth 1 --filter=blob:none`) into remote_config/agenthub-next-git and reads only the version line of
src/AgentHub/AgentHub.csproj (`<Version>`), the value the app reports. Git uses this PC's own GitHub
sign-in (Git Credential Manager); no token is stored by the suite and prompts are disabled.

"Suite version" = AGENTHUB_VERSION_USED in suite.env. Nobody can derive it from the code, so whoever
reviews the suite against a new AgentHubNext version bumps it by hand (see CLAUDE.md, section 8).

A failure (no git, no network, no access, no <Version>) never fails the run: the report shows the
GitHub version as unknown and suite.log says why.
"""
from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass

from . import redact, settings
from .runlog import log

CSPROJ = "src/AgentHub/AgentHub.csproj"
_TIMEOUT = 60
_cache: "RepoVersion | None" = None


@dataclass
class RepoVersion:
    used: str            # version the suite was written against (suite.env)
    remote: str          # version on GitHub, "" when unknown
    branch: str
    state: str           # "ahead" | "current" | "unknown"
    detail: str = ""     # why it is unknown, or a note


def _parse(v: str) -> tuple[int, ...] | None:
    m = re.fullmatch(r"\s*v?(\d+(?:\.\d+)*)\s*", v or "")
    return tuple(int(x) for x in m.group(1).split(".")) if m else None


def _git(args: list[str], cwd) -> str:
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never")
    p = subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True,
                       timeout=_TIMEOUT, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        lines = (p.stderr or p.stdout).strip().splitlines()
        raise RuntimeError(redact.text(lines[-1] if lines else f"git {args[0]} failed"))
    return p.stdout


def fetch_remote_version(url: str, branch: str) -> str:
    cache = settings.REMOTE_CONFIG_DIR / "agenthub-next-git"
    if not (cache / "HEAD").exists():
        cache.mkdir(parents=True, exist_ok=True)
        _git(["init", "--bare", "-q"], cache)
    _git(["fetch", "-q", "--depth", "1", "--filter=blob:none", url, branch], cache)
    text = _git(["show", f"FETCH_HEAD:{CSPROJ}"], cache)
    m = re.search(r"<Version>\s*([^<\s]+)\s*</Version>", text)
    if not m:
        raise RuntimeError(f"no <Version> in {CSPROJ} on {branch}")
    return m.group(1)


def check(force: bool = False) -> RepoVersion:
    global _cache
    if _cache is not None and not force:
        return _cache
    used = settings.get("AGENTHUB_VERSION_USED", "")
    url = settings.get("AGENTHUB_REPO_URL", "https://github.com/ameria-AG/agent-hub-backend")
    branch = settings.get("AGENTHUB_REPO_BRANCH", "next")
    try:
        remote = fetch_remote_version(url, branch)
    except Exception as exc:  # noqa: BLE001 - informational check, must never stop the run
        detail = redact.text(f"{type(exc).__name__}: {exc}")
        log.warning("AgentHubNext version on GitHub (%s) could not be read: %s", branch, detail)
        _cache = RepoVersion(used, "", branch, "unknown", detail)
        return _cache
    a, b = _parse(remote), _parse(used)
    if b is None:
        state, detail = "unknown", "AGENTHUB_VERSION_USED in suite.env is missing or not a version"
    else:
        state, detail = ("ahead" if a and a > b else "current"), ""
    log.info("AgentHubNext version: suite %s, GitHub %s (%s) -> %s", used or "?", remote, branch, state)
    _cache = RepoVersion(used, remote, branch, state, detail)
    return _cache
