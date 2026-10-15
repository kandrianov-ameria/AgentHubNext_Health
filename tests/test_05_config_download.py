"""
Configuration download - the five requests AgentHubNext makes when it starts.

The suite makes them once, before any check runs (agenthub_health/bootstrap.py), with the
token and the 20-second timeout the application uses. These checks report whether each
download succeeded by the application's own rules:

  /api/agents, /api/tools, /api/mcps, /api/llm-providers
      RemoteConfigurationManager.LoadString throws on no answer, a non-2xx status or an empty
      body, and JsonPrettify throws on a body that is not JSON. The application then stops.
  /api/pat-config/<ENV>
      RemoteSettingsManager.DownloadAsync returns null on no answer, a non-2xx status or a body
      that is not a JSON object. The application then uses its encrypted local cache, and shuts
      down when there is none. (A missing or unreadable AgentHub section is reported by
      test_11_pat_config::test_agenthub_section_present.)

When a download failed, every other check runs on the copy saved in remote_config/<ENV>/ by
the latest run in which the download succeeded; the failure message names its date.
"""
from __future__ import annotations

import pytest

from agenthub_health import bootstrap
from agenthub_health.probe import ServiceFailure, SuiteIssue, attach

pytestmark = [pytest.mark.config, pytest.mark.smoke]


def _fallback(d: bootstrap.Download) -> str:
    if d.source == "snapshot":
        other = ""
        if d.snapshot_base_url and d.snapshot_base_url != bootstrap.settings.url("AIHUB_SERVICE_BASE_URL"):
            other = f" from {d.snapshot_base_url}"
        return (f" The other checks of this run use the copy saved {d.snapshot_saved_at}{other} "
                f"(remote_config/{bootstrap.env_dir().name}/).")
    return (" No earlier run saved a copy, so the checks that need this document cannot run and "
            "fail with the same cause.")


@pytest.mark.parametrize("entity", bootstrap.entities())
def test_download_succeeded(entity):
    """AgentHubNext's start-up download of this configuration document succeeds."""
    d = bootstrap.get(entity)
    attach(d.probe)
    if d.suite_input_missing:
        raise SuiteIssue(f"GET /api/{entity} was not sent: {d.reason}.",
                         "Set the base URL in suite.env; for the token run: "
                             ".venv\\Scripts\\python scripts\\refresh_env.py")
    if d.accepted or d.section_problem:
        return
    raise ServiceFailure(d.probe, f"GET /api/{entity}: {d.reason}.{_fallback(d)}",
                         service="aihub-service")


def test_downloads_were_saved_for_the_next_run():
    """A successful download was saved to remote_config/, so a later run can fall back on it."""
    unsaved = [d.entity for d in bootstrap.STATE.values() if d.save_failed]
    if unsaved:
        raise SuiteIssue(f"The download of {', '.join(unsaved)} succeeded but could not be saved to "
                         f"{bootstrap.env_dir()}. A later run whose download fails has no copy to use.",
                         "Check that the folder is writable; suite.log in logs/ has the error.")
