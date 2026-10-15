"""
MCP servers - the definitions from /api/mcps, checked the way McpWrapper uses
them. streamable_http servers are reachable from any machine, so they get a
real MCP 'initialize' handshake; stdio servers only exist on a Maverick and
are checked for a well-formed definition only.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

import pytest

from agenthub_health import remote
from agenthub_health.probe import ConfigDefect, ServiceFailure, call, contract, expect_ok, unused_by_app

pytestmark = pytest.mark.smoke


def _mcps():
    try:
        cfg = remote.config()
    except ServiceFailure as exc:
        return [("unavailable", exc)]
    users: dict = {}
    for a in cfg.agents:
        for ref in a.assigned_mcps:
            m = re.match(r"^\[(.*?)\]", ref)
            if m:
                users.setdefault(m.group(1), set()).add(a.name)
    return [(m, sorted(users.get(m.get("name"), []))) for m in cfg.mcps]


def pytest_generate_tests(metafunc):
    if "mcp" in metafunc.fixturenames:
        items = _mcps()
        ids = ["unavailable" if m == "unavailable" else str(m.get("name")) for m, _ in items]
        metafunc.parametrize("mcp,agents", items, ids=ids)
    if "http_mcp" in metafunc.fixturenames:
        # Only streamable_http servers: a stdio server is a local process that starts on a
        # Maverick machine only, which this suite never runs on.
        items = [(m, a) for m, a in _mcps() if m == "unavailable" or m.get("type") == "streamable_http"]
        ids = ["unavailable" if m == "unavailable" else str(m.get("name")) for m, _ in items]
        metafunc.parametrize("http_mcp,agents", items, ids=ids)


def _unavailable(mcp, agents):
    if mcp == "unavailable":
        raise agents


UNASSIGNED = ("No agent in this environment lists this MCP server in AssignedMCPs, so AgentHubNext cannot "
              "reach its tools and is not affected today. It becomes a real failure as soon as an agent is "
              "assigned one of its tools.")


def test_definition_is_well_formed(mcp, agents):
    """An MCP definition has a transport McpWrapper supports and the fields that transport needs."""
    _unavailable(mcp, agents)
    with unused_by_app(UNASSIGNED, when=not agents):
        _check_definition(mcp, agents)


def _check_definition(mcp, agents):
    name, typ = mcp.get("name"), mcp.get("type")
    used = f" Used by: {', '.join(agents)}." if agents else " Not assigned to any agent in this environment."
    if typ not in ("stdio", "streamable_http"):
        raise ConfigDefect(f"MCP '{name}' has type '{typ}'. McpWrapper throws \"Not supported MCP type {typ}\".{used}",
                           "type must be 'stdio' or 'streamable_http'.",
                           "The MCP server cannot be connected, so its tools are unavailable.",
                           "Correct the MCP record in Maverick Config Manager.", service="mcp")
    if typ == "stdio":
        if not str(mcp.get("command") or "").strip():
            raise ConfigDefect(f"stdio MCP '{name}' has no command.{used}", "A stdio MCP needs a startup command.",
                               "The MCP server cannot be started.", "Set the command in Maverick Config Manager.",
                               service="mcp")
        text = f"{mcp.get('command') or ''} {mcp.get('arguments') or ''}"
        unknown = sorted(set(re.findall(r"<([A-Za-z_]+)>", text)) - {"ENV", "VER"})
        if unknown:
            raise ConfigDefect(f"stdio MCP '{name}' uses placeholder(s) {', '.join('<'+u+'>' for u in unknown)}; "
                               f"only <ENV> and <VER> are resolved.{used}",
                               "RemoteConfigurationManager resolves <ENV> and <VER> only.",
                               "The placeholder is passed through literally and the launch fails.",
                               "Fix the command/arguments in Maverick Config Manager.", service="mcp")
    else:
        u = urlparse(str(mcp.get("url") or ""))
        if u.scheme not in ("http", "https") or not u.netloc:
            raise ConfigDefect(f"streamable_http MCP '{name}' has no valid url ('{mcp.get('url')}').{used}",
                               "A streamable_http MCP needs an absolute http(s) URL.",
                               "The MCP transport cannot be created.", "Set the url in Maverick Config Manager.",
                               service="mcp")


def test_http_server_completes_handshake(http_mcp, agents):
    """A streamable_http MCP server answers the MCP 'initialize' request with its configured headers."""
    mcp = http_mcp
    _unavailable(mcp, agents)
    headers = dict(remote.parse_headers(mcp.get("headers")))
    headers.update({"Accept": "application/json, text/event-stream", "Content-Type": "application/json"})
    body = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                       "clientInfo": {"name": "agenthub-health", "version": "1.0"}}}
    res = call("mcp", f"{mcp.get('name')} initialize", "POST", str(mcp.get("url")), headers=headers, json=body,
               subject=f"MCP server '{mcp.get('name')}'")
    hint = f"Used by: {', '.join(agents)}." if agents else "Not assigned to any agent in this environment."
    with unused_by_app(UNASSIGNED, when=not agents):
        expect_ok(res, f"MCP '{mcp.get('name')}' initialize", hint)
        contract(res, '"result"' in res.body or (isinstance(res.json, dict) and "result" in res.json),
                 f"MCP '{mcp.get('name')}' answered 200 but without a JSON-RPC result.", hint)
