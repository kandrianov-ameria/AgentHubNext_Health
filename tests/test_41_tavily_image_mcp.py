"""
Image search MCP - the locally installed Node.js server mcp-tavily-search-image
(C:\\ProgramData\\Maverick\\Packages\\<ENV>\\Maverick-ai-hub-mcp-servers\\<VER>\\
node-js-mcp\\mcp-tavily-search-image\\dist\\index.js), started over stdio by McpWrapper.

The server itself only runs on a Maverick machine, but everything it depends on
can be checked from any PC:
  * its command line, as parseCliArgs in dist/index.js reads it
    (--api-key and --folder are both required, otherwise it throws at start);
  * the Tavily Search API it calls, with the same request tavilySearch() sends.
"""
from __future__ import annotations

import re

import pytest

from agenthub_health import remote, settings
from agenthub_health.probe import ConfigDefect, ServiceFailure, call, contract, expect_ok, unused_by_app

pytestmark = pytest.mark.smoke

SERVER = "mcp-tavily-search-image"


def _servers():
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
    found = []
    for m in cfg.mcps:
        text = f"{m.get('name') or ''} {m.get('command') or ''} {m.get('arguments') or ''}"
        if m.get("type") == "stdio" and SERVER in text:
            found.append((m, sorted(users.get(m.get("name"), []))))
    return found or [(None, [])]


def pytest_generate_tests(metafunc):
    if "server" in metafunc.fixturenames:
        items = _servers()
        ids = ["unavailable" if s == "unavailable" else "not-configured" if s is None else str(s.get("name"))
               for s, _ in items]
        metafunc.parametrize("server,agents", items, ids=ids)


UNASSIGNED = ("No agent in this environment lists this MCP server in AssignedMCPs, so AgentHubNext "
              "never starts it and is not affected today.")


def _args(server, agents) -> dict:
    if server == "unavailable":
        raise agents
    if server is None:
        pytest.skip(f"No stdio MCP record in /api/mcps starts {SERVER}.")
    args = remote.split_arguments(str(server.get("arguments") or "").replace("<ENV>", settings.env_name()))
    out = {}
    for i, a in enumerate(args):
        if a in ("--api-key", "--folder"):
            out[a] = args[i + 1] if i + 1 < len(args) else ""
    return out


def test_command_line_has_required_arguments(server, agents):
    """The MCP record passes --api-key and --folder, which the Node server requires at start."""
    args = _args(server, agents)
    missing = [k for k in ("--api-key", "--folder") if not args.get(k)]
    if missing:
        used = f" Used by: {', '.join(agents)}." if agents else ""
        with unused_by_app(UNASSIGNED, when=not agents):
            raise ConfigDefect(
                f"MCP '{server.get('name')}' does not pass {' and '.join(missing)}.{used}",
                "parseCliArgs in dist/index.js throws 'Missing required argument --api-key' / "
                "'--folder' when either is absent or empty.",
                "The Node process exits at start, so tavily_search_image is unavailable.",
                "Add the argument to the MCP record's arguments in Maverick Config Manager.",
                service="mcp")


def test_tavily_returns_images(server, agents):
    """Tavily Search answers the request tavily_search_image sends, with images in the result."""
    key = _args(server, agents).get("--api-key")
    if not key:
        pytest.skip("No --api-key in the MCP record - reported by test_command_line_has_required_arguments.")
    body = {"query": "wooden chair", "max_results": 5, "include_images": True, "include_image_descriptions": True}
    headers = {"Authorization": f"Bearer {key}", "accept": "application/json",
               "content-type": "application/json", "X-Client-Source": "MCP"}
    res = call("tavily", "search", "POST", settings.TAVILY_SEARCH_URL, headers=headers, json=body, timeout=60,
               subject="Tavily API key of the image search MCP")
    hint = f"Used by: {', '.join(agents)}." if agents else "Not assigned to any agent in this environment."
    with unused_by_app(UNASSIGNED, when=not agents):
        expect_ok(res, "Tavily search", hint)
        images = res.json.get("images") if isinstance(res.json, dict) else None
        contract(res, isinstance(images, list) and len(images) > 0,
                 "Tavily answered 200 without any images. The MCP server then throws "
                 "'No images found in Tavily response'.", hint)
