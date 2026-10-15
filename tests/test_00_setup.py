"""Suite setup - the inputs every other check depends on. No network."""
from __future__ import annotations

from urllib.parse import urlparse

import pytest

from agenthub_health import settings
from agenthub_health.probe import SuiteIssue

pytestmark = pytest.mark.config


def test_env_file_present():
    """The .env file with the AgentHubNext credentials exists."""
    if not settings.ENV_FILE.exists() and not all(settings.get(v) for v in settings.SECRET_VARS):
        raise SuiteIssue(".env is missing from the project root and the credentials are not set "
                         "in the environment either.",
                         "Run: .venv\\Scripts\\python scripts\\refresh_env.py")


def test_suite_config_file_present():
    """suite.env with the base URLs and other non-secret settings exists."""
    if not settings.SUITE_CONFIG_FILE.exists() and not all(settings.get(v) for v in settings.URL_VARS):
        raise SuiteIssue("suite.env is missing from the project root and the base URLs are not set "
                         "in the environment either.",
                         "Restore suite.env from the repository (git checkout -- suite.env).")


@pytest.mark.parametrize("var", settings.SECRET_VARS)
def test_credential_is_set(var):
    """A credential AgentHubNext ships with is available to the suite."""
    if not settings.get(var):
        raise SuiteIssue(f"{var} is empty.", "Run: .venv\\Scripts\\python scripts\\refresh_env.py")


@pytest.mark.parametrize("var", settings.URL_VARS)
def test_base_url_is_valid(var):
    """A service base URL is set and is an absolute https URL (plain http only for localhost)."""
    value = settings.url(var)
    if not value:
        raise SuiteIssue(f"{var} is empty.", settings.FIX_SETTING)
    u = urlparse(value)
    local = u.hostname in ("localhost", "127.0.0.1")
    if not u.netloc or not (u.scheme == "https" or (u.scheme == "http" and local)):
        raise SuiteIssue(f"{var}={value} is not an absolute https URL.",
                         "Correct it in suite.env, or re-run scripts/refresh_env.py.")


def test_environment_name_is_valid():
    """AGENTHUB_ENV is one of the four environments pat-config accepts."""
    env = settings.env_name()
    if env not in ("DEV", "QAS", "STG", "PRD"):
        raise SuiteIssue(f"AGENTHUB_ENV={env} is not DEV, QAS, STG or PRD (docs/pat-config-api.md).",
                         "Set AGENTHUB_ENV in suite.env, or pass --env to run_tests.bat.")


@pytest.mark.parametrize("name", ["probe.jpg", "probe_silence.wav"])
def test_asset_present(asset, name):
    """A file the network checks upload is present in tests/assets."""
    assert asset(name).stat().st_size > 0
