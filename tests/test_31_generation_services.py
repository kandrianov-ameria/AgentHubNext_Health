"""
Generation services - reachability and request validation of 2d-to-3d and
2d-to-video. These checks never start a generation; the live ring
(test_90_live_generation.py, run_tests.bat --live) does.
"""
from __future__ import annotations

import pytest

from agenthub_health.probe import basic_auth, call, contract, expect_ok, expect_status, need

pytestmark = pytest.mark.smoke

SERVICES = {
    "2d-to-3d": ("TWO_D_TO_3D_BASE_URL", "TWO_D_TO_3D_BASIC_AUTH"),
    "2d-to-video": ("TWO_D_TO_VIDEO_BASE_URL", "TWO_D_TO_VIDEO_BASIC_AUTH"),
}


@pytest.mark.parametrize("service", list(SERVICES))
def test_health(service):
    """GET /health answers 200 {"status": "healthy"} (no auth required)."""
    base = need(SERVICES[service][0])
    res = call(service, "health", "GET", f"{base}/health")
    expect_ok(res, "GET /health")
    contract(res, isinstance(res.json, dict) and res.json.get("status") == "healthy",
             "GET /health did not return {\"status\": \"healthy\"}.")


@pytest.mark.parametrize("service", list(SERVICES))
def test_empty_task_is_refused(service):
    """POST /task with neither prompt nor files is refused with 400 (and starts nothing)."""
    base_var, auth_var = SERVICES[service]
    res = call(service, "task {}", "POST", f"{need(base_var)}/task", json={}, auth=basic_auth(auth_var))
    expect_status(res, [400], "POST /task with an empty body",
                  f"A 401 here means the service has AUTH_ENABLED=true - set {auth_var} in .env.")


@pytest.mark.parametrize("service", list(SERVICES))
def test_unknown_file_token_is_refused(service):
    """POST /task with a file token that was never uploaded is refused with 400."""
    base_var, auth_var = SERVICES[service]
    res = call(service, "task (unknown token)", "POST", f"{need(base_var)}/task",
               json={"prompt": "agenthub health probe", "files": [{"file_token": "agenthub-health-does-not-exist"}]},
               auth=basic_auth(auth_var))
    expect_status(res, [400], "POST /task with an unknown file_token",
                  f"A 401 here means the service has AUTH_ENABLED=true - set {auth_var} in .env.")


@pytest.mark.parametrize("service", list(SERVICES))
def test_unknown_task_is_404(service):
    """GET /task/{id} for an id that does not exist answers 404."""
    base_var, auth_var = SERVICES[service]
    res = call(service, "task status (unknown id)", "GET", f"{need(base_var)}/task/agenthub-health-no-such-task",
               auth=basic_auth(auth_var))
    expect_status(res, [404], "GET /task/<unknown id>")
