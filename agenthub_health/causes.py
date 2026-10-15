"""
What each probe outcome means, in plain words. The report combines this with
the concrete evidence (HTTP code, response snippet, assertion) and the service
facts from services.py, so every failure explanation is derived from what the
run actually observed.
"""
from __future__ import annotations

from .probe import ProbeResult, Status

TITLES = {
    Status.AUTH_FAILED: "Credential rejected",
    Status.NOT_FOUND: "Endpoint or resource not found",
    Status.CLIENT_ERROR: "Request rejected by the service",
    Status.SERVER_ERROR: "Service error",
    Status.UNAVAILABLE: "Service unavailable",
    Status.TIMEOUT: "No answer in time",
    Status.DNS_FAILED: "Host name could not be resolved",
    Status.TLS_FAILED: "TLS / certificate problem",
    Status.CONNECTION_FAILED: "Connection could not be established",
    Status.CONTRACT: "Answer does not match what AgentHubNext parses",
    Status.UNEXPECTED_ACCESS: "Request that must be refused was accepted",
    Status.OK: "Unexpected result",
}


def explain(res: ProbeResult) -> str:
    code = res.http_status
    s = res.status
    if s is Status.AUTH_FAILED:
        return (f"The service answered HTTP {code}: it refused the credential sent with the request. "
                "The key or token is wrong, has been revoked, or has expired. The suite sends exactly "
                "the value AgentHubNext ships with, so the application is refused in the same way.")
    if s is Status.NOT_FOUND:
        return (f"The service answered HTTP {code}. The path does not exist on this host, the resource "
                "was removed, or (for pat-config) the environment name is not one of DEV/QAS/STG/PRD.")
    if s is Status.CLIENT_ERROR:
        return (f"The service answered HTTP {code} to a request built the same way AgentHubNext builds it. "
                "Either the request contract changed on the service side, or the stored configuration "
                "(model name, URL, parameters) is not valid for this service.")
    if s is Status.SERVER_ERROR:
        return f"The service answered HTTP {code}: it failed while handling the request. The fault is on the service side."
    if s is Status.UNAVAILABLE:
        text = (f"The service answered HTTP {code}: the host is reachable, but the service behind it cannot "
                "serve right now (stopped backend, maintenance, or overload).")
        if res.service == "mav-starkit-api":
            text += " For mav-starkit-api a 503 specifically means the server has no API_KEY configured (docs/mav-starkit-api.md)."
        return text
    if s is Status.TIMEOUT:
        return (f"No answer arrived within {res.latency_ms} ms. The service is overloaded or hanging, or a "
                "firewall is silently dropping the traffic.")
    if s is Status.DNS_FAILED:
        return ("The host name could not be resolved from the machine running the suite. Check DNS, VPN, "
                "and whether this machine is allowed to reach the host at all.")
    if s is Status.TLS_FAILED:
        return ("The TLS handshake failed. Typical causes are a TLS-inspecting corporate proxy whose "
                "certificate Python does not trust, or an expired / mismatched server certificate. If a "
                "proxy is involved, point SSL_CERT_FILE at its CA bundle.")
    if s is Status.CONNECTION_FAILED:
        return ("The connection could not be opened (refused, reset, or no route). The service is down, "
                "the port is closed, or a firewall blocks the path.")
    if s is Status.CONTRACT:
        return ("The service answered successfully, but the body does not have the shape AgentHubNext "
                "reads. The app would fail or silently get nothing from this answer.")
    if s is Status.UNEXPECTED_ACCESS:
        return (f"The service answered HTTP {code} to a request that must be refused (missing or wrong "
                "credential, or an invalid payload). Authentication or validation is not being enforced.")
    return "The check did not get the result it requires."


def fix(res: ProbeResult | None, owner: str, service_fix: str) -> str:
    """How to fix, chosen by what actually happened rather than by service alone."""
    if res is None:
        return service_fix
    s = res.status
    if s in (Status.SERVER_ERROR, Status.UNAVAILABLE):
        return (f"The fault is on the service side - no configuration change on this end will fix it. "
                f"Report it to {owner} with the time of this run and the response body under Evidence "
                "(it may contain a request id they can look up).")
    if s is Status.TIMEOUT:
        return (f"Run again to rule out a one-off. If it persists, report it to {owner}; if other machines reach "
                "the service normally, check this machine's network path instead.")
    if s in (Status.DNS_FAILED, Status.TLS_FAILED, Status.CONNECTION_FAILED):
        return (f"Check this machine's network path first (VPN, proxy, firewall). If other machines see the "
                f"same, report it to {owner}.")
    return service_fix
