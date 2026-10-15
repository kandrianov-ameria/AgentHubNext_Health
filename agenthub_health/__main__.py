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
import sys
import time
import webbrowser


def open_report(report) -> bool:
    """Open the report in the default web browser. On Windows the file is handed to the shell
    (os.startfile), which opens it with the program registered for .html - the default browser.
    Elsewhere, and if that fails, Python's webbrowser module is used. The outcome is logged."""
    from . import runlog
    attempts = []
    if sys.platform.startswith("win"):
        attempts.append(("os.startfile", lambda: os.startfile(str(report))))  # noqa: S606
    attempts.append(("webbrowser", lambda: webbrowser.open(report.as_uri(), new=2)))
    for name, attempt in attempts:
        try:
            if attempt() is False:
                raise OSError("no browser could be started")
            runlog.log.info("Report opened in the default browser (%s)", name)
            return True
        except Exception as exc:  # noqa: BLE001 - try the next way
            runlog.log.warning("Could not open the report with %s: %s", name, exc)
    msg = f"Could not open the report automatically. Open it by hand: {report}"
    print(msg)
    runlog.console_line(msg)
    return False


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
