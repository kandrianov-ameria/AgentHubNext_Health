"""
Run logs. Every run gets its own folder under logs/, named after its start time:

  logs/<YYYYmmdd-HHMMSS>/suite.log     what the suite itself did and how long each phase took:
                                       configuration downloads, snapshot use, collection, report
  logs/<YYYYmmdd-HHMMSS>/tests.log     one entry per check: outcome, duration, message, requests
  logs/<YYYYmmdd-HHMMSS>/console.log   everything the run printed to the console (pytest output,
                                       and a traceback if the run crashed)

Only the newest settings.LOG_RUNS_TO_KEEP folders (5 by default) are kept; older ones are
deleted when a new run starts. Every line goes through redact.text() before it is written,
the same masking the console and the HTML report use.
"""
from __future__ import annotations

import datetime as _dt
import io
import logging
import re
import shutil
import threading
import time
from pathlib import Path

from . import redact, settings

LOGGER_NAME = "agenthub_health"
log = logging.getLogger(LOGGER_NAME)

_RUN_NAME = re.compile(r"^\d{8}-\d{6}(-\d+)?$")
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")

RUN_DIR: Path | None = None
_owner = ""      # who opened the logs ("main" or "plugin"); only the owner closes them
_tests_file: io.TextIOBase | None = None
_lock = threading.Lock()
_tees: list["_Tee"] = []


class _RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact.text(super().format(record))


def _new_run_dir() -> Path:
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    d = settings.LOGS_DIR / stamp
    n = 1
    while d.exists():
        n += 1
        d = settings.LOGS_DIR / f"{stamp}-{n}"
    d.mkdir(parents=True)
    return d


def _prune(keep: int) -> list[str]:
    """Delete all but the newest `keep` run folders. Folder names sort by start time."""
    def order(p: Path):
        stamp, _, n = p.name.partition("-")[2].partition("-")
        return (p.name[:8], stamp, int(n or 1))
    runs = sorted((p for p in settings.LOGS_DIR.iterdir() if p.is_dir() and _RUN_NAME.match(p.name)), key=order)
    removed = []
    for old in runs[:-keep] if len(runs) > keep else []:
        try:
            shutil.rmtree(old)
            removed.append(old.name)
        except OSError as exc:  # a file still open in an editor, for example
            log.warning("Could not delete the old log folder %s: %s", old.name, exc)
    return removed


def start(owner: str = "main") -> Path:
    """Create this run's log folder, attach the log files and prune old runs. Idempotent: the
    first caller owns the logs (__main__ when started by run_tests.bat, the plugin when pytest
    is run directly)."""
    global RUN_DIR, _tests_file, _owner
    if RUN_DIR is not None:
        return RUN_DIR
    _owner = owner
    settings.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    RUN_DIR = _new_run_dir()

    handler = logging.FileHandler(RUN_DIR / "suite.log", encoding="utf-8")
    handler.setFormatter(_RedactingFormatter("%(asctime)s.%(msecs)03d  %(levelname)-7s  %(message)s",
                                             "%Y-%m-%d %H:%M:%S"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False  # keep suite messages out of pytest's own log capture

    _tests_file = open(RUN_DIR / "tests.log", "a", encoding="utf-8")  # noqa: SIM115 - closed in finish()
    removed = _prune(settings.LOG_RUNS_TO_KEEP)
    log.info("Run log folder: %s", RUN_DIR)
    if removed:
        log.info("Deleted %d old run folder(s), keeping the newest %d: %s",
                 len(removed), settings.LOG_RUNS_TO_KEEP, ", ".join(removed))
    return RUN_DIR


def test_entry(text: str) -> None:
    """Append one entry to tests.log."""
    if _tests_file is None:
        return
    with _lock:
        _tests_file.write(redact.text(text).rstrip("\n") + "\n")
        _tests_file.flush()


class _Tee:
    """Wraps the stream pytest's terminal writer prints to: passes everything through unchanged
    and writes a masked copy to console.log. Masking works on whole lines, so a secret split
    across two writes is still masked.

    sys.stdout itself is never replaced. On Windows, pytest reopens sys.stdout and sys.stderr
    at start-up (_pytest.capture._windowsconsoleio_workaround) and expects real io streams
    there; a wrapper in sys.stdout made it fail with "'_Tee' object has no attribute
    'line_buffering'" (1.1.0 / 1.1.1)."""

    def __init__(self, stream, path: Path):
        self._stream = stream
        self._file = open(path, "a", encoding="utf-8")  # noqa: SIM115 - closed in finish()
        self._buf = ""

    def write(self, s: str) -> int:
        n = self._stream.write(s)
        with _lock:
            if not self._file.closed:
                self._buf += s
                if "\n" in self._buf:
                    done, self._buf = self._buf.rsplit("\n", 1)
                    self._file.write(_ANSI.sub("", redact.text(done)) + "\n")
                    self._file.flush()
        return len(s) if n is None else n

    def flush(self) -> None:
        self._stream.flush()

    def close_log(self) -> None:
        with _lock:
            if self._file.closed:
                return
            if self._buf:
                self._file.write(_ANSI.sub("", redact.text(self._buf)) + "\n")
                self._buf = ""
            self._file.close()

    def __getattr__(self, name):
        # isatty, encoding, fileno ... are answered by the real stream.
        return getattr(self._stream, name)


def console_line(text: str) -> None:
    """Write a line to console.log that did not come through pytest (the suite's own
    messages printed before and after pytest runs, or a crash)."""
    if RUN_DIR is None:
        return
    with _lock:
        with open(RUN_DIR / "console.log", "a", encoding="utf-8") as fh:
            fh.write(_ANSI.sub("", redact.text(text)).rstrip("\n") + "\n")


def wrap_terminal(stream):
    """Return a stream that copies pytest's terminal output into console.log."""
    if RUN_DIR is None or isinstance(stream, _Tee):
        return stream
    tee = _Tee(stream, RUN_DIR / "console.log")
    _tees.append(tee)
    return tee


def finish(owner: str, started: float) -> None:
    global _tests_file, _owner
    if owner != _owner:
        return
    _owner = ""
    log.info("Run finished after %.1f s", time.time() - started)
    for tee in _tees:
        try:
            tee.close_log()
        except Exception:  # noqa: BLE001 - logging must never break the run
            pass
    if _tests_file is not None:
        _tests_file.close()
        _tests_file = None
    for h in list(log.handlers):
        h.close()
        log.removeHandler(h)
