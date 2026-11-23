"""
Entry point: `python -m agenthub_health [options] [extra pytest args]`.
run_tests.bat calls this after making sure .venv exists.

Options
  --live       also run the slow, billable generation checks (marker: live)
  --env NAME   override AGENTHUB_ENV for this run (DEV / QAS / STG / PRD)
  --no-open    do not open results/result.html in the default browser afterwards
               (it opens automatically otherwise)

Each run writes its logs to logs/<start time>/ (suite.log, tests.log, console.log); the
newest five run folders are kept.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
import webbrowser


def _windows_default_browser() -> str | None:
    """Path of the executable behind the default browser's http handler, read from the registry.
    Returns None when it cannot be found. Launching it directly avoids relying on the shell."""
    import winreg
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, r"Software\Microsoft\Windows\Shell\Associations"
                                      r"\UrlAssociations\http\UserChoice") as key:
                prog_id = winreg.QueryValueEx(key, "ProgId")[0]
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf"{prog_id}\shell\open\command") as key:
                command = winreg.QueryValueEx(key, "")[0]
        except OSError:
            continue
        match = re.match(r'\s*"([^"]+\.exe)"|\s*(\S+\.exe)', command, re.IGNORECASE)
        if match:
            path = match.group(1) or match.group(2)
            if os.path.isfile(path):
                return path
    return None


def open_report(report) -> bool:
    """Send the report to the default web browser. On Windows the browser executable is started
    directly with the report's file:// address; if that is not possible, the file is handed to the
    shell (os.startfile), then Python's webbrowser module is tried. os.startfile and webbrowser
    return no window status, so the log says the file was handed over, not that a window appeared."""
    from . import runlog
    attempts = []
    if sys.platform.startswith("win"):
        attempts.append(("default browser", lambda: _start_browser(report)))
        attempts.append(("os.startfile", lambda: os.startfile(str(report))))  # noqa: S606
    attempts.append(("webbrowser", lambda: webbrowser.open(report.as_uri(), new=2)))
    for name, attempt in attempts:
        try:
            if attempt() is False:
                raise OSError("no browser could be started")
            runlog.log.info("Report handed to %s: %s. Check that a browser window appeared.",
                            name, report)
            return True
        except Exception as exc:  # noqa: BLE001 - try the next way
            runlog.log.warning("Could not open the report with %s: %s", name, exc)
    msg = f"Could not open the report automatically. Open it by hand: {report}"
    print(msg)
    runlog.console_line(msg)
    return False


def _start_browser(report):
    """Start the default browser executable on the report. Raises OSError if none is found."""
    from . import runlog
    browser = _windows_default_browser()
    if browser is None:
        raise OSError("the default browser executable was not found in the registry")
    proc = subprocess.Popen([browser, report.as_uri()], stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    runlog.log.info("Started %s (pid %s)", browser, proc.pid)
    return True


def main(argv: list[str]) -> int:
    live = "--live" in argv
    no_open = "--no-open" in argv
    rest: list[str] = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--live", "--no-open"):
            i += 1
            continue
        if a == "--env" and i + 1 < len(argv):
            os.environ["AGENTHUB_ENV"] = argv[i + 1].upper()
            i += 2
            continue
        rest.append(a)
        i += 1

    # Import after --env is applied: settings reads the environment at import time.
    import pytest

    from . import runlog, settings

    started = time.time()
    run_dir = runlog.start(owner="main")

    args = ["-p", "agenthub_health.plugin", str(settings.PROJECT_ROOT / "tests"),
            "-c", str(settings.PROJECT_ROOT / "pytest.ini"), "--rootdir", str(settings.PROJECT_ROOT)]
    if not any(a == "-m" or a.startswith("-m") for a in rest):
        args += ["-m", "not live"] if not live else []
    args += rest

    header = (f"AgentHubNext health suite - environment {settings.env_name()}"
              f"{' - including live generation' if live else ''}")
    print(header)
    runlog.console_line(header)
    from . import repo_version
    repo_version.check()  # GitHub version of AgentHubNext, for the report header; never fails the run
    try:
        code = pytest.main(args)
    except BaseException:
        import traceback
        text = traceback.format_exc()
        runlog.log.error("The run stopped with an unhandled error:\n%s", text)
        runlog.console_line(text)
        runlog.finish(owner="main", started=started)
        raise

    report = settings.REPORT_FILE
    print(f"\nLogs:   {run_dir}")
    runlog.console_line(f"Logs:   {run_dir}")
    if report.exists():
        print(f"Report: {report}")
        runlog.console_line(f"Report: {report}")
        if no_open or os.getenv("AGENTHUB_HEALTH_NO_OPEN") == "1":
            runlog.log.info("Report not opened (--no-open or AGENTHUB_HEALTH_NO_OPEN=1)")
        else:
            open_report(report)
    runlog.finish(owner="main", started=started)
    return int(code)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
