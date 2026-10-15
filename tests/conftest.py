"""
Shared fixtures. Anything that must come from the network is wrapped so a
failure there becomes a *Failed* check with the original HTTP evidence (or a
*Skipped* one when the input legitimately does not exist) - never a crash that
would be misreported as a suite issue.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agenthub_health import remote, settings
from agenthub_health.probe import SuiteIssue


def pytest_configure(config):
    # When pytest is run directly (not through run_tests.bat) still load the
    # report plugin exactly once.
    if not config.pluginmanager.has_plugin("agenthub_health.plugin"):
        config.pluginmanager.import_plugin("agenthub_health.plugin")


@pytest.fixture(scope="session")
def env() -> str:
    return settings.env_name()


@pytest.fixture(scope="session")
def cfg() -> remote.Config:
    """Agents, tools, MCPs and LLM providers from the download this run started with (or the saved
    copy), loaded the way AgentHubNext loads them. Fails with one root cause when the application
    could not load them at all."""
    return remote.config()


@pytest.fixture(scope="session")
def agenthub_section() -> dict:
    """The AgentHub group of pat-config for this environment."""
    fetch, section = remote.agenthub_section()
    fetch.require("The AgentHub section of pat-config")
    if section is None:
        pytest.skip(f"pat-config/{settings.env_name()} has no 'AgentHub' section, so there are no "
                    "Deepgram / Whisper / segmentation settings to test. See the pat-config check.")
    return section


@pytest.fixture(scope="session")
def asset():
    """asset('probe.jpg') -> absolute path in tests/assets."""
    def _get(name: str) -> Path:
        p = settings.ASSETS_DIR / name
        if not p.exists():
            raise SuiteIssue(f"Test asset tests/assets/{name} is missing.",
                             "Restore the file from the project repository.")
        return p
    return _get

