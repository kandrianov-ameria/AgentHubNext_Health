"""
AI-Hub service - authentication of the endpoints AgentHubNext calls at start-up.

Whether the start-up downloads themselves succeed with the shipped token is checked by
test_05_config_download, which reports on the one download every run starts with.
"""
from __future__ import annotations

import pytest

from agenthub_health import remote
from agenthub_health.probe import ServiceFailure, call, expect_refused, need

pytestmark = pytest.mark.smoke

SERVICE = "aihub-service"


@pytest.mark.parametrize("entity", ["agents", remote.pat_config_entity()])
def test_endpoint_refuses_a_request_without_token(entity):
    """The service refuses a request that carries no token."""
    base = need("AIHUB_SERVICE_BASE_URL")
    res = call(SERVICE, f"{entity} (no token)", "GET", f"{base}/api/{entity}")
    expect_refused(res, f"GET /api/{entity} without Authorization")


@pytest.mark.parametrize("entity", ["agents", remote.pat_config_entity()])
def test_endpoint_refuses_a_wrong_token(entity):
    """The service refuses a well-formed but wrong token (it validates, not just accepts)."""
    base = need("AIHUB_SERVICE_BASE_URL")
    res = call(SERVICE, f"{entity} (wrong token)", "GET", f"{base}/api/{entity}",
               headers={"Authorization": "Bearer 99|" + "z" * 40})
    expect_refused(res, f"GET /api/{entity} with a wrong token")


def test_unknown_environment_is_refused():
    """pat-config answers 404 for an environment name that does not exist."""
    base = need("AIHUB_SERVICE_BASE_URL")
    res = call(SERVICE, "pat-config/NOTREAL", "GET", f"{base}/api/pat-config/NOTREAL",
               headers=remote.auth_headers())
    if res.http_status != 404:
        raise ServiceFailure(res, f"GET /api/pat-config/NOTREAL: expected 404 'Environment not found' "
                                  f"(docs/pat-config-api.md), got HTTP {res.http_status}")

