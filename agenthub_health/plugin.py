"""
pytest plugin: collects every outcome, classifies it, and writes
results/result.html when the session ends.

Classification rules (applied to the first failing phase of each test):
  ServiceFailure              -> Failed        (a dependency misbehaved)
  ConfigDefect                -> Failed        (remote configuration defect)
    ...raised inside unused_by_app() -> Failed, no effect on the app (something the app does not use today)
  plain AssertionError        -> Failed        (a check did not hold)
  SuiteIssue                  -> Suite issue   (the suite could not run the check)
  any other exception         -> Suite issue   (suite bug, or an answer shape the suite does not handle)
  collection error            -> Suite issue
  skipped                     -> Skipped
  xfail / xpass               -> Known issue / Known issue fixed
"""
from __future__ import annotations

import platform
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from . import __version__, bootstrap, causes, redact, runlog, settings, services, usage
from . import report as html_report
from .probe import PROBES, ConfigDefect, ServiceFailure, SuiteIssue, set_current_test
from .runlog import log


@dataclass
class Record:
    nodeid: str
    module: str
    name: str
    objective: str
    markers: list[str]
    category: str = "passed"      # passed | failed | unused | suite | skipped | known | known_fixed
    duration: float = 0.0
    phase: str = ""
    reason: str = ""
    failure: dict = field(default_factory=dict)
    probes: list[dict] = field(default_factory=list)


_records: dict[str, Record] = {}
_collection_issues: list[dict] = []
_started = 0.0
_argv: list[str] = []
_phase_t0 = 0.0
_test_started: dict[str, float] = {}

_LABELS = {"passed": "PASSED", "failed": "FAILED", "unused": "FAILED-NO-EFFECT", "suite": "SUITE-ISSUE",
           "skipped": "SKIPPED", "known": "KNOWN", "known_fixed": "KNOWN-FIXED"}


def _objective(item) -> str:
    fn = getattr(item, "function", None)
    doc = (fn.__doc__ or "").strip() if fn else ""
    text = " ".join(doc.split("\n\n")[0].split()) if doc else item.name
    callspec = getattr(item, "callspec", None)
    if callspec is not None and callspec.id:
        text += f" [{callspec.id}]"
    return text


def _location(excinfo) -> str:
    """The deepest frame in tests/ (where the check lives), else the deepest project frame."""
    import os
    root = settings.PROJECT_ROOT
    norm_root = os.path.normcase(str(root))
    norm_tests = os.path.normcase(str(root / "tests"))
    fallback = ""
    for entry in reversed(excinfo.traceback):
        path = os.path.normcase(str(entry.path))
        if "site-packages" in path or not path.startswith(norm_root):
            continue
        loc = f"{os.path.relpath(str(entry.path), str(root)).replace(os.sep, '/')}:{entry.lineno + 1}"
        if path.startswith(norm_tests):
            return loc
        fallback = fallback or loc
    return fallback


def _assert_message(exc) -> str:
    msg = str(exc)
    # pytest's assertion rewriting appends "assert ..." introspection - keep the author's message.
    if "\nassert " in msg:
        msg = msg.split("\nassert ", 1)[0]
    return msg.strip()


def _apply_usage(exc) -> None:
    """A failure of a service the configuration of this run does not use has no effect on the
    app (usage.py). Checked for every failure, from this run's configuration."""
    if not getattr(exc, "affects_app", False):
        return
    keys = {exc.service}
    probe = getattr(exc, "probe", None)
    if probe is not None:
        keys.add(probe.service)
    for key in keys:
        try:
            why = usage.unused_reason(key)
        except Exception:  # noqa: BLE001 - never let the classification break the report
            log.exception("Could not decide whether %s is used", key)
            why = ""
        if why:
            exc.affects_app = False
            exc.no_effect_reason = why
            return


def _failure(excinfo) -> tuple[str, dict]:
    exc = excinfo.value
    loc = _location(excinfo)
    if isinstance(exc, (ServiceFailure, ConfigDefect)):
        _apply_usage(exc)
    if isinstance(exc, ServiceFailure):
        svc = services.get(exc.service)
        d = {"kind": "service", "cause_key": exc.cause_key, "message": exc.message, "hint": exc.hint,
             "service": svc.title, "owner": svc.owner, "credential": svc.credential,
             "impact": svc.impact, "rotation": causes.fix(exc.probe, svc.owner, svc.rotation), "location": loc,
             "no_effect_reason": exc.no_effect_reason}
        if exc.probe:
            d["probe"] = exc.probe.to_dict()
            if exc.probe.subject:
                d["service"] = exc.probe.subject
            d["title"] = causes.TITLES.get(exc.probe.status, "Check failed")
            d["explanation"] = causes.explain(exc.probe)
        else:
            d["title"], d["explanation"] = "Check failed", exc.message
        return ("failed" if exc.affects_app else "unused"), d
    if isinstance(exc, ConfigDefect):
        svc = services.get(exc.service)
        return ("failed" if exc.affects_app else "unused"), {
            "kind": "config", "cause_key": exc.cause_key, "message": exc.message,
            "title": "Remote configuration defect", "explanation": exc.rule,
            "impact": exc.impact, "rotation": exc.remediation, "service": svc.title,
            "owner": svc.owner, "credential": "", "hint": "", "location": loc,
            "no_effect_reason": exc.no_effect_reason}
    if isinstance(exc, SuiteIssue):
        return "suite", {"kind": "suite", "type": "Suite input missing", "message": exc.message,
                         "remediation": exc.remediation, "location": loc,
                         "meaning": "The suite could not run this check. Nothing is known about the "
                                    "service it was meant to test."}
    if isinstance(exc, AssertionError):
        msg = _assert_message(exc)
        return "failed", {"kind": "assert", "cause_key": f"assert|{msg[:120]}", "message": msg,
                          "title": "Check did not hold", "explanation": msg, "impact": "",
                          "rotation": "", "service": "", "owner": "", "credential": "", "hint": "",
                          "location": loc}
    tb = "".join(traceback.format_exception_only(type(exc), exc)).strip()
    return "suite", {"kind": "suite", "type": type(exc).__name__, "message": tb, "location": loc,
                     "remediation": "Open the location above. If the code is right, the service "
                                    "returned a shape this check does not handle and the check needs "
                                    "updating.",
                     "meaning": "The test code raised an unexpected exception instead of reaching a "
                                "verdict. This is either a bug in the suite or an answer shape it "
                                "does not handle - it is not evidence about the service."}


# --- hooks ---------------------------------------------------------------------

@pytest.hookimpl(trylast=True)
def pytest_configure(config):
    # Open the run logs as early as possible, then copy pytest's terminal output into
    # console.log. The terminal reporter registers in its own pytest_configure, hence trylast.
    runlog.start(owner="plugin")
    tr = config.pluginmanager.get_plugin("terminalreporter")
    tw = getattr(tr, "_tw", None)
    if tw is not None and hasattr(tw, "_file"):
        tw._file = runlog.wrap_terminal(tw._file)


def pytest_sessionstart(session):
    global _started, _argv, _phase_t0
    _started = time.time()
    _argv = list(sys.argv)
    runlog.start(owner="plugin")
    log.info("agenthub-health %s, environment %s, %s %s on %s", __version__, settings.env_name(),
             platform.python_implementation(), platform.python_version(), platform.platform())
    log.info("Command: %s", " ".join(_argv))
    # Download the configuration before collection: some modules parametrise their checks
    # from it (one check per LLM provider, per MCP server).
    try:
        bootstrap.run()
    except Exception as exc:  # noqa: BLE001 - reported as a suite issue, the run continues
        log.exception("The configuration download failed inside the suite")
        _collection_issues.append({
            "kind": "suite", "type": type(exc).__name__, "location": "agenthub_health/bootstrap.py",
            "message": redact.text(f"{type(exc).__name__}: {exc}"),
            "meaning": "The suite could not download or load the remote configuration, so every check that "
                       "needs it has no input.",
            "remediation": "See suite.log in the newest folder under logs/ for the traceback."})
    _phase_t0 = time.time()


def _log_usage() -> None:
    try:
        for u in usage.all_services().values():
            log.info("Service %s: %s - %s", u.service, "used" if u.used else "NOT used", u.why)
    except Exception:  # noqa: BLE001
        log.exception("Could not work out which services the configuration uses")


def pytest_collection_finish(session):
    global _phase_t0
    _log_usage()
    log.info("Collected %d checks in %.1f s (%d collection error(s))", len(session.items),
             time.time() - _phase_t0, len(_collection_issues))
    _phase_t0 = time.time()


def _log_test(rec: Record, started: float) -> None:
    import datetime as _dt
    stamp = _dt.datetime.fromtimestamp(started).strftime("%Y-%m-%d %H:%M:%S")
    lines = [f"{stamp}  {_LABELS.get(rec.category, rec.category.upper()):<16} {rec.duration:7.2f}s  {rec.nodeid}",
             f"    Check:   {rec.objective}"]
    if rec.reason:
        lines.append(f"    Reason:  {rec.reason}")
    if rec.failure:
        msg = rec.failure.get("message") or ""
        lines.append("    Result:  " + "\n             ".join(str(msg).splitlines() or [""]))
        if rec.failure.get("location"):
            lines.append(f"    Where:   {rec.failure['location']}")
    for p in rec.probes:
        code = f"HTTP {p['http_status']}" if p.get("http_status") else p.get("error") or p["status"]
        lines.append(f"    Request: {p['method']} {p['url']} -> {code} ({p['status']}), {p['latency_ms']} ms")
    runlog.test_entry("\n".join(lines))


def pytest_collectreport(report):
    if report.failed:
        _collection_issues.append({
            "kind": "suite", "type": "Collection error", "location": str(report.nodeid or report.fspath),
            "message": "\n".join(redact.text(str(report.longrepr)).splitlines()[-14:]),
            "meaning": "pytest could not import or collect this module, so none of its checks ran.",
            "remediation": "Fix the import or syntax error shown above.",
        })


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item, nextitem):
    set_current_test(item.nodeid)
    _test_started[item.nodeid] = time.time()
    _records[item.nodeid] = Record(
        nodeid=item.nodeid, module=item.module.__name__.split(".")[-1] if item.module else "",
        name=item.name, objective=_objective(item),
        markers=sorted({m.name for m in item.iter_markers()
                        if m.name in ("config", "smoke", "live")}))
    yield
    set_current_test(None)
    rec = _records[item.nodeid]
    rec.probes = [p.to_dict() for p in PROBES.get(item.nodeid, [])]
    try:
        _log_test(rec, _test_started.get(item.nodeid, time.time()))
    except Exception:  # noqa: BLE001 - logging must never change an outcome
        log.exception("Could not write the tests.log entry for %s", item.nodeid)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    rec = _records.get(item.nodeid)
    if rec is None:
        return
    rec.duration += rep.duration
    if rec.category not in ("passed",):
        return  # first non-passing phase decides
    if hasattr(rep, "wasxfail"):
        rec.category = "known_fixed" if rep.passed else "known"
        rec.reason = redact.text(rep.wasxfail)
        rec.phase = rep.when
        return
    if rep.skipped:
        rec.category = "skipped"
        lr = rep.longrepr
        rec.reason = redact.text(lr[2] if isinstance(lr, tuple) and len(lr) == 3 else lr).replace("Skipped: ", "")
        rec.phase = rep.when
        return
    if rep.failed and call.excinfo is not None:
        rec.category, rec.failure = _failure(call.excinfo)
        if rep.when == "teardown" and rec.category in ("failed", "unused"):
            rec.category = "suite"
            rec.failure.setdefault("meaning", "Cleanup after the check failed.")
        rec.phase = rep.when


def _log_slowest(n: int = 5) -> None:
    """The slowest requests of the run, and any that used more than half of the default timeout
    (settings.TIMEOUT_DEFAULT) - a service that gets slower shows up here before it times out."""
    reqs = [(p["latency_ms"], p["method"], p["url"], r.nodeid) for r in _records.values() for p in r.probes
            if p.get("latency_ms") is not None]
    if not reqs:
        return
    reqs.sort(reverse=True)
    log.info("Slowest requests: %s", "; ".join(f"{m} {u} {ms} ms" for ms, m, u, _ in reqs[:n]))
    limit = settings.TIMEOUT_DEFAULT * 1000 / 2
    for ms, m, u, nodeid in reqs:
        # LLM and generation checks have their own, longer timeouts.
        if ms > limit and "test_20_llm" not in nodeid and "test_90_live" not in nodeid:
            log.warning("%s %s took %d ms, more than half of the %g s timeout (%s)",
                        m, u, ms, settings.TIMEOUT_DEFAULT, nodeid)


def pytest_sessionfinish(session, exitstatus):
    counts: dict[str, int] = {}
    for r in _records.values():
        counts[r.category] = counts.get(r.category, 0) + 1
    log.info("Ran %d checks in %.1f s: %s", len(_records), time.time() - _phase_t0,
             ", ".join(f"{_LABELS.get(k, k).lower()} {v}" for k, v in sorted(counts.items())) or "none")
    for issue in _collection_issues:
        log.error("Suite issue at %s: %s", issue.get("location"), issue.get("message"))
    _log_slowest()
    t_report = time.time()
    meta = {
        "suite_version": __version__,
        "environment": settings.env_name(),
        "started": _started,
        "finished": time.time(),
        "python": f"{platform.python_implementation()} {platform.python_version()}",
        "platform": platform.platform(),
        "command": " ".join(Path(a).name if i == 0 else a for i, a in enumerate(_argv)),
        "exit_status": int(exitstatus),
        "base_urls": {k: settings.url(k) for k in settings.URL_VARS},
        "markers": session.config.getoption("-m") or "",
        "remote_config": bootstrap.summary(),
        "service_usage": [{"service": u.service, "used": u.used, "why": u.why}
                          for u in usage.all_services().values()],
        "remote_config_dir": str(bootstrap.env_dir()),
        "log_dir": str(runlog.RUN_DIR or ""),
    }
    path = html_report.render(list(_records.values()), _collection_issues, meta)
    log.info("Report written to %s in %.1f s", path, time.time() - t_report)
    session.config._agenthub_report = path  # read by __main__
    tr = session.config.pluginmanager.get_plugin("terminalreporter")
    if tr:
        tr.write_sep("=", f"report: {path}")


def pytest_unconfigure(config):
    runlog.finish(owner="plugin", started=_started or time.time())
