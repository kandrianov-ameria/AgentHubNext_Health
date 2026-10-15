"""
The configuration download every run starts with.

AgentHubNext downloads five documents when it starts (Program.cs):

  RemoteSettingsManager.SynchronizeAsync     GET {base}/api/pat-config/{env}
  RemoteConfigurationManager.GetConfigurationAsync
                                             GET {base}/api/agents, /api/tools, /api/mcps, /api/llm-providers

`run()` makes the same five requests once, before pytest collects the checks, and decides
for each one whether the application would accept the download - using the application's
own rules, listed below. Every check then works from this one download (remote.py); no
check fetches the configuration again.

A download the application would accept is saved to remote_config/<ENV>/. When a download
fails, the checks run on the copy saved by the latest run in which it succeeded, and
tests/test_05_config_download.py reports the failure and the age of the copy in use.

When the application treats a download as failed
  the four lists (RemoteConfigurationManager.LoadString)
    - no answer (network, TLS, timeout), or a non-2xx status: "Error downloading remote configuration"
    - an empty body: "... Response is empty."
    - a body that is not JSON: JsonPrettify throws
  pat-config (RemoteSettingsManager.DownloadAsync returns null and the application uses its cache)
    - no answer, or a non-2xx status
    - a body that is not JSON, or not an object
    - no "AgentHub" object in it
    - an AgentHub section that System.Text.Json cannot deserialize

The four lists are saved and restored together: GetConfigurationAsync needs all four, so
mixing a fresh agent list with an old provider list could produce combinations that never
existed on the server.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import __version__, dotnet, redact, settings
from .probe import ProbeResult, Status, call
from .runlog import log

SERVICE = "aihub-service"
LISTS = ["agents", "tools", "mcps", "llm-providers"]
PAT = "pat-config"
SNAPSHOT_META = "snapshot.json"


def pat_entity() -> str:
    return f"{PAT}/{settings.env_name()}"


def entities() -> list[str]:
    return LISTS + [pat_entity()]


def _file_key(entity: str) -> str:
    return PAT if entity.startswith(PAT + "/") else entity


@dataclass
class Download:
    entity: str
    probe: ProbeResult | None = None
    accepted: bool = False          # the application would accept this download
    reason: str = ""                # why not
    suite_input_missing: str = ""   # setting (.env / suite.env) the request needs but does not have
    fresh_text: str | None = None   # the body that was downloaded (also when not accepted)
    text: str | None = None         # the body the checks use: fresh, or from the snapshot
    source: str = "none"            # "download" | "snapshot" | "none"
    snapshot_saved_at: str = ""     # when the snapshot in use was saved
    snapshot_base_url: str = ""
    saved: bool = False             # this run saved the fresh body as the new snapshot
    save_failed: bool = False       # accepted, but writing remote_config/ failed
    section_problem: bool = False   # pat-config: the answer arrived, but its AgentHub section is unusable

    @property
    def available(self) -> bool:
        return self.text is not None

    def describe_source(self) -> str:
        if self.source == "download":
            return "downloaded in this run"
        if self.source == "snapshot":
            return f"snapshot saved {self.snapshot_saved_at}"
        return "unavailable"


STATE: dict[str, Download] = {}
_done = False


# --- paths and snapshot files -------------------------------------------------------

def env_dir() -> Path:
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", settings.env_name()) or "UNKNOWN"
    return settings.REMOTE_CONFIG_DIR / safe


def _now() -> str:
    return _dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_meta() -> dict:
    p = env_dir() / SNAPSHOT_META
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    os.replace(tmp, path)


def _save(group: str, bodies: dict[str, str]) -> bool:
    """Write the bodies of one group ("lists" or "pat-config") and record them in snapshot.json."""
    try:
        d = env_dir()
        d.mkdir(parents=True, exist_ok=True)
        files = {}
        for entity, text in bodies.items():
            name = f"{_file_key(entity)}.json"
            _write_atomic(d / name, text)
            files[_file_key(entity)] = {"file": name, "sha256": _sha(text), "bytes": len(text.encode("utf-8"))}
        meta = _read_meta()
        meta.update({"environment": settings.env_name(), "note": "Written by agenthub-health. Holds live "
                     "credentials - do not commit or share."})
        meta[group] = {"saved_at": _now(), "suite_version": __version__,
                       "service_base_url": settings.url("AIHUB_SERVICE_BASE_URL"), "files": files}
        _write_atomic(d / SNAPSHOT_META, json.dumps(meta, indent=2))
        log.info("Saved %s snapshot to %s (%s)", group, d, ", ".join(files))
        return True
    except OSError as exc:
        log.error("Could not save the %s snapshot to %s: %s", group, env_dir(), exc)
        return False


def _load(group: str) -> tuple[dict[str, str], dict] | None:
    """The bodies of one snapshot group, or None when it is missing or does not match snapshot.json."""
    meta = _read_meta().get(group)
    if not meta:
        return None
    out = {}
    for key, info in (meta.get("files") or {}).items():
        try:
            with open(env_dir() / info["file"], encoding="utf-8", newline="") as fh:
                text = fh.read()
        except (OSError, KeyError):
            log.warning("Snapshot file %s of group %s is missing", info.get("file"), group)
            return None
        if _sha(text) != info.get("sha256"):
            log.warning("Snapshot file %s does not match the checksum in %s; not using it",
                        info.get("file"), SNAPSHOT_META)
            return None
        out[key] = text
    return out, meta


# --- deciding whether the application would accept a download ----------------------

def _decode(res: ProbeResult) -> str:
    """HttpContent.ReadAsStringAsync: the charset from Content-Type, else UTF-8 (BOM removed)."""
    charset = ""
    m = re.search(r"charset=([\w.-]+)", res.content_type or "", re.I)
    if m:
        charset = m.group(1)
    try:
        text = res.content.decode(charset or "utf-8", errors="replace")
    except LookupError:
        text = res.content.decode("utf-8", errors="replace")
    return text.lstrip("﻿")


def _judge_list(d: Download) -> None:
    res = d.probe
    if not res.ok:
        got = f"HTTP {res.http_status}" if res.http_status else res.status.value
        d.reason = (f"{got}; LoadString throws \"Error downloading remote configuration\", so the application "
                    "stops at start-up (\"Please restart application.\")")
        return
    text = _decode(res)
    d.fresh_text = text
    if text == "":
        d.reason = ("the body is empty; LoadString throws \"... Response is empty.\", so the application stops "
                    "at start-up")
        res.status = Status.CONTRACT
        return
    try:
        dotnet.parse_newtonsoft(text)
    except dotnet.JsonError as exc:
        d.reason = f"the body is not JSON ({exc}); JsonPrettify throws, so the application stops at start-up"
        res.status = Status.CONTRACT
        return
    d.accepted = True


def _judge_pat(d: Download) -> None:
    res = d.probe
    if not res.ok:
        d.reason = (f"HTTP {res.http_status}" if res.http_status else res.status.value) + \
                   "; the application would log a warning and use its local cache"
        return
    text = _decode(res)
    d.fresh_text = text
    try:
        root = dotnet.parse_system_text_json(text)
    except dotnet.JsonError as exc:
        d.reason = f"the body is not valid JSON ({exc}); the application would use its local cache"
        res.status = Status.CONTRACT
        return
    section, why = dotnet.read_agenthub_section(root)
    if section is None:
        d.reason = f"{why}; the application would use its local cache"
        d.section_problem = True
        return
    d.accepted = True


def _register_secrets(entity: str, text: str | None) -> None:
    """Mask every credential the configuration carries, as soon as it is read."""
    if not text:
        return
    try:
        data = json.loads(text)
    except ValueError:
        return
    if entity in ("llm-providers", "mcps") and isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            h = item.get("headers")
            if isinstance(h, str):
                redact.register_many(dotnet.parse_headers(h).values())
            if entity == "mcps":
                args = [a.strip() for a in str(item.get("arguments") or "").split(",") if a.strip()]
                redact.register_many(args[i + 1] for i, a in enumerate(args[:-1]) if a == "--api-key")
    if entity.startswith(PAT) and isinstance(data, dict) and isinstance(data.get("AgentHub"), dict):
        for key, value in data["AgentHub"].items():
            if key.lower() in ("defaultdeepgramapikey", "proxyauthheader") and isinstance(value, str):
                redact.register(value)


# --- the run ----------------------------------------------------------------------------

def _download(entity: str) -> Download:
    d = Download(entity)
    base = settings.url("AIHUB_SERVICE_BASE_URL")
    token = settings.get("AIHUB_WIN_TOKEN")
    missing = [n for n, v in (("AIHUB_SERVICE_BASE_URL", base), ("AIHUB_WIN_TOKEN", token)) if not v]
    if missing:
        d.suite_input_missing = " and ".join(missing)
        d.reason = (f"{d.suite_input_missing} is not set (base URLs belong in suite.env, credentials "
                    f"in .env), so the suite cannot send the request")
        return d
    d.probe = call(SERVICE, entity, "GET", f"{base}/api/{entity}",
                   headers={"Authorization": f"Bearer {token}"}, timeout=settings.TIMEOUT_CONFIG, record=False)
    return d


def run() -> dict[str, Download]:
    """Download everything once per run. Safe to call again; later calls return the first result."""
    global _done
    if _done:
        return STATE
    _done = True
    t0 = time.perf_counter()
    log.info("Downloading the remote configuration for environment %s from %s",
             settings.env_name(), settings.url("AIHUB_SERVICE_BASE_URL") or "(AIHUB_SERVICE_BASE_URL not set)")

    for entity in entities():
        try:
            d = _download(entity)
            if d.probe is not None:
                (_judge_pat if entity.startswith(PAT) else _judge_list)(d)
            _register_secrets(entity, d.fresh_text)
        except Exception as exc:  # noqa: BLE001 - a bug here must not stop the run
            log.exception("Download of %s failed inside the suite", entity)
            d = Download(entity, reason=f"the suite failed while downloading: {type(exc).__name__}: {exc}")
        STATE[entity] = d
        p = d.probe
        log.info("GET /api/%s -> %s, %s ms, %s bytes: %s", entity,
                 (f"HTTP {p.http_status}" if p and p.http_status else (p.status.value if p else "not sent")),
                 p.latency_ms if p else "-", len(p.content) if p else "-",
                 "accepted" if d.accepted else f"NOT accepted ({d.reason})")

    # The four lists: all fresh, or all from the snapshot.
    lists = [STATE[e] for e in LISTS]
    if all(d.accepted for d in lists):
        saved = _save("lists", {d.entity: d.fresh_text for d in lists})
        for d in lists:
            d.text, d.source, d.saved, d.save_failed = d.fresh_text, "download", saved, not saved
    else:
        failed = ", ".join(d.entity for d in lists if not d.accepted)
        snap = _load("lists")
        if snap:
            bodies, meta = snap
            log.warning("Download of %s failed; using the list snapshot saved %s", failed, meta.get("saved_at"))
            for d in lists:
                d.text, d.source = bodies.get(d.entity), "snapshot"
                d.snapshot_saved_at = meta.get("saved_at", "")
                d.snapshot_base_url = meta.get("service_base_url", "")
                _register_secrets(d.entity, d.text)
        else:
            log.error("Download of %s failed and no list snapshot exists in %s", failed, env_dir())
            for d in lists:
                if d.accepted:
                    d.text, d.source = d.fresh_text, "download"

    # pat-config on its own, like RemoteSettingsManager and its cache.
    d = STATE[pat_entity()]
    if d.accepted:
        d.saved = _save(PAT, {d.entity: d.fresh_text})
        d.save_failed = not d.saved
        d.text, d.source = d.fresh_text, "download"
    else:
        snap = _load(PAT)
        if snap:
            bodies, meta = snap
            d.text, d.source = bodies.get(PAT), "snapshot"
            d.snapshot_saved_at = meta.get("saved_at", "")
            d.snapshot_base_url = meta.get("service_base_url", "")
            _register_secrets(d.entity, d.text)
            log.warning("pat-config download not usable; using the snapshot saved %s", d.snapshot_saved_at)
        else:
            log.error("pat-config download not usable and no snapshot exists in %s", env_dir())

    log.info("Configuration ready in %.1f s: %s", time.perf_counter() - t0,
             "; ".join(f"{e}={STATE[e].describe_source()}" for e in entities()))
    return STATE


def get(entity: str) -> Download:
    run()
    return STATE.get(entity) or Download(entity, reason="not downloaded")


def summary() -> list[dict[str, Any]]:
    """For the report's run details."""
    return [{"entity": e, "source": STATE[e].describe_source(), "accepted": STATE[e].accepted,
             "reason": redact.text(STATE[e].reason)} for e in entities() if e in STATE]


def reset_for_tests() -> None:  # used by the mock verification only
    global _done
    _done = False
    STATE.clear()
