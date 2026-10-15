"""
HTTP probing with outcome classification.

The value of this suite is telling "the service is down" apart from "the key
was rejected" apart from "the network path is blocked". Every request goes
through `call()`, which returns a ProbeResult with one of the Status values
below, and records it against the test that made it so the report can show
exactly what was sent and what came back.
"""
from __future__ import annotations

import contextlib
import contextvars
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable

import httpx

from . import redact, settings


class Status(str, Enum):
    OK = "ok"
    AUTH_FAILED = "auth_failed"            # 401 / 403
    NOT_FOUND = "not_found"                # 404
    CLIENT_ERROR = "client_error"          # other 4xx
    SERVER_ERROR = "server_error"          # 5xx except 503
    UNAVAILABLE = "unavailable"            # 503
    TIMEOUT = "timeout"
    DNS_FAILED = "dns_failed"
    TLS_FAILED = "tls_failed"
    CONNECTION_FAILED = "connection_failed"
    CONTRACT = "contract"                  # 2xx, but the body is not what AgentHubNext parses
    UNEXPECTED_ACCESS = "unexpected_access"  # a request that must be refused was accepted


@dataclass
class ProbeResult:
    service: str
    name: str
    method: str
    url: str
    status: Status
    http_status: int | None
    latency_ms: int
    body: str = ""
    error: str = ""
    json: Any = field(default=None, repr=False)
    content: bytes = field(default=b"", repr=False)
    subject: str = ""   # what the credential belongs to: the service, or one provider / MCP server
    content_type: str = ""

    @property
    def cause_key(self) -> str:
        """Checks that failed for the same reason share a key. A rejected credential or a
        broken network path is one cause per subject, whichever endpoint hit it."""
        subject = self.subject or self.service
        if self.status in _SUBJECT_WIDE:
            return f"{subject}|{self.status.value}"
        return f"{subject}|{self.name}|{self.status.value}"

    @property
    def ok(self) -> bool:
        return self.status is Status.OK

    def to_dict(self) -> dict:
        return {
            "service": self.service, "name": self.name, "method": self.method,
            "url": redact.text(self.url), "status": self.status.value,
            "http_status": self.http_status, "latency_ms": self.latency_ms,
            "body": redact.text(self.body), "error": redact.text(self.error),
            "subject": self.subject or self.service,
        }


_SUBJECT_WIDE = {Status.AUTH_FAILED, Status.TIMEOUT, Status.DNS_FAILED, Status.TLS_FAILED,
                 Status.CONNECTION_FAILED, Status.UNAVAILABLE}


# --- attribution of probes to the running test --------------------------------

_current_test: contextvars.ContextVar[str | None] = contextvars.ContextVar("current_test", default=None)
PROBES: dict[str, list[ProbeResult]] = {}


def set_current_test(nodeid: str | None) -> None:
    _current_test.set(nodeid)


def _record(result: ProbeResult) -> None:
    nodeid = _current_test.get()
    if nodeid:
        PROBES.setdefault(nodeid, []).append(result)


def attach(result: ProbeResult | None) -> None:
    """Show a request made outside the running check (the start-up configuration download)
    as evidence of the running check."""
    if result is not None:
        _record(result)


# --- failures ------------------------------------------------------------------

class ServiceFailure(AssertionError):
    """A dependency of AgentHubNext did not behave as the app requires."""

    def __init__(self, probe: ProbeResult | None, message: str, hint: str = "",
                 service: str | None = None, cause_key: str | None = None):
        self.probe = probe
        self.message = message
        self.hint = hint
        self.service = service or (probe.service if probe else "suite")
        self.cause_key = cause_key or (probe.cause_key if probe else f"{self.service}|{message[:80]}")
        self.affects_app = True
        self.no_effect_reason = ""
        super().__init__(redact.text(message))


class ConfigDefect(AssertionError):
    """The remote configuration contains something AgentHubNext rejects or mishandles."""

    def __init__(self, message: str, rule: str, impact: str, remediation: str,
                 service: str = "aihub-service"):
        self.message, self.rule, self.impact, self.remediation = message, rule, impact, remediation
        self.service = service
        self.cause_key = f"config|{rule}"
        self.affects_app = True
        self.no_effect_reason = ""
        super().__init__(redact.text(message))


class SuiteIssue(Exception):
    """The suite itself cannot run a check (missing input, missing asset, ...)."""

    def __init__(self, message: str, remediation: str = ""):
        self.message, self.remediation = message, remediation
        super().__init__(redact.text(message))


@contextlib.contextmanager
def unused_by_app(reason: str, when: bool = True):
    """A failure inside this block concerns something AgentHubNext does not use today.
    It is still reported, but under its own heading and without turning the verdict red."""
    try:
        yield
    except (ServiceFailure, ConfigDefect) as failure:
        if when:
            failure.affects_app = False
            failure.no_effect_reason = reason
        raise


def need(var: str) -> str:
    """A required setting (.env or suite.env), or a suite issue naming it."""
    v = settings.get(var)
    if not v:
        where = ".env" if settings.fix_for(var) == settings.FIX_SECRET else "suite.env"
        raise SuiteIssue(f"{var} is not set in {where} or the environment.", settings.fix_for(var))
    return v


def basic_auth(var: str):
    """('user', 'password') from a .env value 'user:password' or 'Basic <base64>', or None."""
    import base64
    v = settings.get(var)
    if not v:
        return None
    if v.lower().startswith("basic "):
        v = base64.b64decode(v[6:]).decode()
    user, _, pwd = v.partition(":")
    return (user, pwd)


# --- the call ------------------------------------------------------------------

_client: httpx.Client | None = None


def _verify():
    """Trust the operating system's certificate store, as AgentHubNext (.NET) does. Falls back to
    certifi when truststore is unavailable."""
    try:
        import ssl

        import truststore
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except Exception:  # noqa: BLE001
        return True


def _http() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(follow_redirects=True, verify=_verify(),
                               headers={"User-Agent": "agenthub-health/1.0"})
    return _client


def _classify_exception(exc: Exception) -> Status:
    msg = str(exc).lower()
    if isinstance(exc, httpx.TimeoutException):
        return Status.TIMEOUT
    if "certificate" in msg or "ssl" in msg or "tls" in msg:
        return Status.TLS_FAILED
    if any(s in msg for s in ("getaddrinfo", "name or service not known", "nodename nor servname",
                               "no address associated", "name resolution", "11001")):
        return Status.DNS_FAILED
    return Status.CONNECTION_FAILED


def _classify_status(code: int) -> Status:
    if 200 <= code < 300:
        return Status.OK
    if code in (401, 403):
        return Status.AUTH_FAILED
    if code == 404:
        return Status.NOT_FOUND
    if code == 503:
        return Status.UNAVAILABLE
    if code >= 500:
        return Status.SERVER_ERROR
    return Status.CLIENT_ERROR


def call(service: str, name: str, method: str, url: str, *, timeout: float | None = None,
         record: bool = True, subject: str = "", **kwargs) -> ProbeResult:
    """Send one request. Never raises for HTTP or network problems."""
    t0 = time.perf_counter()
    try:
        r = _http().request(method, url, timeout=timeout or settings.TIMEOUT_DEFAULT, **kwargs)
    except Exception as exc:  # noqa: BLE001 - every transport problem becomes a Status
        res = ProbeResult(service, name, method, url, _classify_exception(exc), None,
                          int((time.perf_counter() - t0) * 1000), error=f"{type(exc).__name__}: {exc}",
                          subject=subject)
        if record:
            _record(res)
        return res

    parsed = None
    ctype = r.headers.get("content-type", "")
    body_text = ""
    if "json" in ctype or r.text[:1] in ("{", "["):
        try:
            parsed = r.json()
        except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
            parsed = None
    if not ctype.startswith(("video/", "model/", "image/", "application/octet-stream")):
        body_text = r.text[:1500]
    res = ProbeResult(service, name, method, str(r.request.url), _classify_status(r.status_code),
                      r.status_code, int((time.perf_counter() - t0) * 1000), body=body_text,
                      json=parsed, content=r.content, subject=subject, content_type=ctype)
    if record:
        _record(res)
    return res


# --- expectations --------------------------------------------------------------

def expect_ok(res: ProbeResult, what: str, hint: str = "") -> ProbeResult:
    if not res.ok:
        raise ServiceFailure(res, f"{what}: {describe(res)}", hint)
    return res


def expect_status(res: ProbeResult, codes: Iterable[int], what: str, hint: str = "") -> ProbeResult:
    codes = set(codes)
    if res.http_status in codes:
        return res
    if res.http_status is not None and 200 <= res.http_status < 300 and not (codes & set(range(200, 300))):
        res.status = Status.UNEXPECTED_ACCESS
    raise ServiceFailure(res, f"{what}: expected HTTP {sorted(codes)}, got {describe(res)}", hint)


def expect_refused(res: ProbeResult, what: str, hint: str = "") -> ProbeResult:
    """The request must be refused as unauthorized (401/403)."""
    if res.http_status in (401, 403):
        return res
    if res.http_status is not None and 200 <= res.http_status < 300:
        res.status = Status.UNEXPECTED_ACCESS
    raise ServiceFailure(res, f"{what}: expected 401/403, got {describe(res)}", hint)


def contract(res: ProbeResult, condition: bool, what: str, hint: str = "") -> None:
    """2xx arrived, but the body does not match what AgentHubNext parses."""
    if not condition:
        res.status = Status.CONTRACT
        raise ServiceFailure(res, what, hint)


def describe(res: ProbeResult) -> str:
    if res.http_status is None:
        return f"{res.status.value} after {res.latency_ms} ms ({res.error})"
    return f"HTTP {res.http_status} ({res.status.value}) after {res.latency_ms} ms"
