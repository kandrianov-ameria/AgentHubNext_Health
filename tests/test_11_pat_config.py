"""
pat-config - the AgentHub section AgentHubNext reads at startup
(RemoteSettingsManager, docs/pat-config-api.md).

The section is read like AgentHubRemoteSettings reads it with System.Text.Json: property names
case-insensitively, strings only as JSON strings or null, RemoteSyncOnSessionCreate only as
true or false. A section that breaks those rules is reported by test_agenthub_section_present,
and the other checks then use the copy saved by an earlier run, as the application uses its cache.
"""
from __future__ import annotations

from urllib.parse import urlparse

import pytest

from agenthub_health import bootstrap, remote, settings, usage
from agenthub_health.probe import ConfigDefect, attach, unused_by_app

pytestmark = [pytest.mark.config, pytest.mark.smoke]

FIX = "Update the AgentHub group of pat-config for this environment in Maverick Config Manager."


def test_agenthub_section_present():
    """The pat-config downloaded in this run has an AgentHub section AgentHubNext can read."""
    d = bootstrap.get(remote.pat_config_entity())
    attach(d.probe)
    if d.fresh_text is None:
        pytest.skip("pat-config was not downloaded in this run - reported by test_05_config_download.")
    problem = remote.fresh_agenthub_problem()
    if problem:
        using = (f" The other checks of this run use the copy saved {d.snapshot_saved_at}."
                 if d.source == "snapshot" else " No earlier run saved a copy, so the speech and segmentation "
                                                "checks cannot run.")
        raise ConfigDefect(
            f"GET /api/pat-config/{settings.env_name()}: {problem}.{using}",
            "RemoteSettingsManager.DownloadAsync treats a response without a readable AgentHub section as a "
            "failed download (System.Text.Json, AgentHubRemoteSettings).",
            "AgentHubNext falls back to its encrypted cache and logs a warning; on a machine with no cache "
            "it logs an error and shuts down.",
            FIX)


@pytest.mark.parametrize("field", ["DefaultDeepgramApiKey", "WhisperUrl", "WhisperModel", "ProxyAuthHeader"])
def test_field_is_set(agenthub_section, field):
    """A field the speech features depend on is present and not empty."""
    v = agenthub_section.get(field)
    if not (isinstance(v, str) and v.strip()):
        effects = {
            "DefaultDeepgramApiKey": "Deepgram transcription has no key; the app listens without transcription.",
            "WhisperUrl": "Whisper requests are disabled with a warning; the app does not fall back to Deepgram "
                          "in replacement mode.",
            "WhisperModel": "Whisper requests are disabled with a warning.",
            "ProxyAuthHeader": "Whisper, the vision model and SAM3 are called without authorization.",
        }
        # An empty field switches its service off in this environment (usage.py), which the
        # plugin then reports as no effect on the app. ProxyAuthHeader matters only while one
        # of the services it authorizes is configured.
        service = {"DefaultDeepgramApiKey": "deepgram", "WhisperUrl": "whisper", "WhisperModel": "whisper"}
        proxied = [s for s in ("whisper", "vision", "sam3") if not usage.unused_reason(s)]
        with unused_by_app("No service that uses ProxyAuthHeader (Whisper, vision, SAM3) is configured in this "
                           "environment.", when=field == "ProxyAuthHeader" and not proxied):
            raise ConfigDefect(f"'{field}' is missing or empty in the AgentHub section.",
                               f"{field} must be a non-empty string.", effects[field], FIX,
                               service=service.get(field, "aihub-service"))


def test_whisper_url_is_absolute(agenthub_section):
    """WhisperUrl is an absolute http(s) URL."""
    v = str(agenthub_section.get("WhisperUrl") or "")
    if not v:
        pytest.skip("WhisperUrl is empty - reported by test_field_is_set.")
    u = urlparse(v)
    if u.scheme not in ("http", "https") or not u.netloc:
        raise ConfigDefect(f"WhisperUrl '{v}' is not an absolute URL.", "WhisperUrl must be an absolute URL.",
                           "Whisper requests are disabled with a warning.", FIX)


def test_segmentation_endpoints_all_or_nothing(agenthub_section):
    """VisionUrl, VisionModel, SamPredictTextUrl and SamPredictUrl are either all set or all absent."""
    keys = ["VisionUrl", "VisionModel", "SamPredictTextUrl", "SamPredictUrl"]
    present = [k for k in keys if agenthub_section.get(k)]
    if not present:
        pytest.skip("No segmentation endpoints configured - object highlighting is intentionally off.")
    missing = [k for k in keys if k not in present]
    if missing:
        raise ConfigDefect(f"Segmentation is partly configured: {', '.join(present)} set, {', '.join(missing)} empty.",
                           "Object segmentation needs all four values.",
                           "Without the endpoints the feature is silently off, so a partial set hides a "
                           "misconfiguration (README.md).", FIX)


def test_removed_field_matches_whisper(agenthub_section):
    """SpeechToTextUrl, if still set, points where WhisperUrl points (AgentHubNext reads only WhisperUrl)."""
    old = str(agenthub_section.get("SpeechToTextUrl") or "").strip()
    whisper = str(agenthub_section.get("WhisperUrl") or "").strip()
    if not old or old.rstrip("/").lower() == whisper.rstrip("/").lower():
        return
    with unused_by_app("AgentHubNext no longer reads SpeechToTextUrl: 'The old SpeechToTextUrl server field is "
                       "ignored and no longer cached or used' (docs/pat-config-api.md)."):
        raise ConfigDefect(f"SpeechToTextUrl is '{old}' but WhisperUrl is '{whisper}'.",
                           "AgentHubNext sends Whisper requests to WhisperUrl only.",
                           "None for AgentHubNext. Anyone who edits SpeechToTextUrl expecting the app to "
                           "follow will see no change.",
                           "Make the two values equal, or remove SpeechToTextUrl if no other client reads it.")
