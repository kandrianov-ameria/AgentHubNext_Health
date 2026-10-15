"""
Log upload, device mapping and Seq.

The log-upload checks never create a record: one sends no token, the other a
valid token with the required fields missing, so the service must reject both.
This holds for /api/logs-session (session archives) and /api/logs/session-image
(the per-image upload added in AgentHubNext 4.0.55).
The Seq check writes one event tagged app=agenthub-health.
"""
from __future__ import annotations

import datetime as dt
import json

import pytest

from agenthub_health.probe import ServiceFailure, Status, call, contract, expect_ok, expect_refused, need

pytestmark = pytest.mark.smoke


def _bearer() -> dict:
    return {"Authorization": f"Bearer {need('AIHUB_DEVICE_MAPPING_TOKEN')}"}


def test_device_mapping_answers():
    """GET /starkit-device-mapping answers 200 with a data list to the token AgentHubNext ships with."""
    base = need("DEVICE_MAPPING_BASE_URL")
    res = call("device-mapping", "starkit-device-mapping", "GET", f"{base}/starkit-device-mapping", headers=_bearer())
    expect_ok(res, "GET /starkit-device-mapping")
    contract(res, isinstance(res.json, dict) and isinstance(res.json.get("data"), list),
             "GET /starkit-device-mapping did not return {\"data\": [...]}, which DeviceMappingClient reads.")


def test_device_mapping_refused_without_token():
    """GET /starkit-device-mapping is refused without a token."""
    base = need("DEVICE_MAPPING_BASE_URL")
    res = call("device-mapping", "starkit-device-mapping (no token)", "GET", f"{base}/starkit-device-mapping")
    expect_refused(res, "GET /starkit-device-mapping without Authorization")


def test_log_upload_refused_without_token():
    """POST /api/logs-session is refused without a token."""
    base = need("AIHUB_SERVICE_BASE_URL")
    res = call("log-upload", "logs-session (no token)", "POST", f"{base}/api/logs-session",
               data={"device_id": "agenthub-health"})
    expect_refused(res, "POST /api/logs-session without Authorization")


def test_log_upload_token_accepted():
    """POST /api/logs-session accepts the upload token (a request missing the file is rejected as invalid, not unauthorized)."""
    base = need("AIHUB_SERVICE_BASE_URL")
    res = call("log-upload", "logs-session (no file)", "POST", f"{base}/api/logs-session", headers={
        **_bearer(), "Accept": "application/json"}, data={"device_id": "agenthub-health"})
    if res.status is Status.AUTH_FAILED:
        raise ServiceFailure(res, "POST /api/logs-session refused the upload token: session log archives from "
                                  "AgentHubNext are not being accepted.")
    if res.http_status is not None and 200 <= res.http_status < 300:
        res.status = Status.UNEXPECTED_ACCESS
        raise ServiceFailure(res, "POST /api/logs-session accepted a request without the required 'file' field "
                                  "(docs/api-logs-session.md lists device_id and file as required).")
    if res.http_status is None or res.http_status >= 500:
        expect_ok(res, "POST /api/logs-session")


def test_session_image_upload_refused_without_token():
    """POST /api/logs/session-image is refused without a token (the endpoint SessionImageUploader posts to)."""
    base = need("AIHUB_SERVICE_BASE_URL")
    res = call("log-upload", "logs/session-image (no token)", "POST", f"{base}/api/logs/session-image",
               data={"device_id": "agenthub-health"})
    expect_refused(res, "POST /api/logs/session-image without Authorization",
                   "A 404 here means the AI-Hub service has no such route: AgentHubNext 4.0.55 and later "
                   "post every screenshot and crop to it.")


def test_session_image_upload_token_accepted():
    """POST /api/logs/session-image accepts the upload token (a request missing the file is rejected as invalid, not unauthorized)."""
    base = need("AIHUB_SERVICE_BASE_URL")
    # SessionImageUploader sends: file, device_id, session_guid, filename, meta, environment, version
    # (src/AgentHub/Logging/SessionImageUploader.cs). The file is left out on purpose so nothing is stored.
    res = call("log-upload", "logs/session-image (no file)", "POST", f"{base}/api/logs/session-image", headers={
        **_bearer(), "Accept": "application/json"},
        data={"device_id": "agenthub-health", "session_guid": "agenthub-health-probe",
              "filename": "probe.jpg", "environment": "probe", "version": "probe",
              "meta": json.dumps({"message_index": 0, "user_message": ""})})
    if res.status is Status.AUTH_FAILED:
        raise ServiceFailure(res, "POST /api/logs/session-image refused the upload token: the screenshots and "
                                  "crops AgentHubNext sends for online monitoring are not being accepted.")
    if res.status is Status.NOT_FOUND:
        raise ServiceFailure(res, "POST /api/logs/session-image answered 404: the AI-Hub service has no such route, "
                                  "so every image upload of AgentHubNext 4.0.55 and later is rejected "
                                  "(logged to Seq as '[ImageUpload] Upload of ... rejected').")
    if res.http_status is not None and 200 <= res.http_status < 300:
        res.status = Status.UNEXPECTED_ACCESS
        raise ServiceFailure(res, "POST /api/logs/session-image accepted a request without the 'file' field.")
    if res.http_status is None or res.http_status >= 500:
        expect_ok(res, "POST /api/logs/session-image")


def test_seq_accepts_events():
    """Seq ingests an event with the API key AgentHubNext's Serilog sink uses."""
    base = need("SEQ_BASE_URL")
    key = need("SEQ_API_KEY")
    event = {"@t": dt.datetime.now(dt.timezone.utc).isoformat(), "@l": "Information",
             "@mt": "AgentHub health probe from {Source}", "Source": "agenthub-health", "app": "agenthub-health"}
    res = call("seq", "ingest", "POST", f"{base}/api/events/raw?clef",
               headers={"X-Seq-ApiKey": key, "Content-Type": "application/vnd.serilog.clef"},
               content=json.dumps(event).encode())
    expect_ok(res, "POST /api/events/raw")
