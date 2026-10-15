"""
mav-starkit-api - file storage and controllers (docs/mav-starkit-api.md, MavStarkitApiClient).

AgentHubNext calls it from ImageTo3DAgent and ImageToVideoAgent only (their tools and prompt
placeholders, see agenthub_health/usage.py). When neither agent uses it in this run's
configuration, failures here are reported as having no effect on the app.
"""
from __future__ import annotations

import uuid

import pytest

from agenthub_health.probe import (ServiceFailure, call, contract, expect_ok, expect_refused,
                                   expect_status, need)

pytestmark = pytest.mark.smoke

SERVICE = "mav-starkit-api"


def _base() -> str:
    return need("MAV_STARKIT_BASE_URL")


def _key() -> dict:
    return {"X-API-Key": need("STARKIT_API_KEY")}


def test_health_endpoint():
    """GET /health answers 200 with ok=true (no key required)."""
    res = call(SERVICE, "health", "GET", f"{_base()}/health")
    expect_ok(res, "GET /health")
    contract(res, isinstance(res.json, dict) and res.json.get("ok") is True,
             "GET /health did not return {\"ok\": true, ...} (docs/mav-starkit-api.md).")


def test_file_list_with_shipped_key():
    """GET /files answers 200 to the X-API-Key AgentHubNext ships with."""
    res = call(SERVICE, "files", "GET", f"{_base()}/files", headers=_key())
    expect_ok(res, "GET /files")
    contract(res, isinstance(res.json, dict) and isinstance(res.json.get("files"), list),
             "GET /files did not return {\"files\": [...]}, which MavStarkitApiClient.ListFilesAsync reads.")


def test_file_list_refused_without_key():
    """GET /files is refused without an X-API-Key."""
    res = call(SERVICE, "files (no key)", "GET", f"{_base()}/files")
    if res.http_status == 503:
        raise ServiceFailure(res, "GET /files without a key answered 503: the server has no API_KEY configured, "
                                  "so authentication is not active (docs/mav-starkit-api.md).")
    expect_refused(res, "GET /files without X-API-Key")


def test_file_list_refused_with_wrong_key():
    """GET /files is refused with a wrong X-API-Key."""
    res = call(SERVICE, "files (wrong key)", "GET", f"{_base()}/files", headers={"X-API-Key": "wrong-" + "z" * 16})
    expect_refused(res, "GET /files with a wrong X-API-Key")


def test_online_controllers_listed():
    """GET /controllers/online answers 200 with a controllers list."""
    res = call(SERVICE, "controllers/online", "GET", f"{_base()}/controllers/online", headers=_key())
    expect_ok(res, "GET /controllers/online")
    contract(res, isinstance(res.json, dict) and isinstance(res.json.get("controllers"), list),
             "GET /controllers/online did not return {\"controllers\": [...]}.")


def _files() -> list:
    res = call(SERVICE, "files", "GET", f"{_base()}/files", headers=_key())
    expect_ok(res, "GET /files")
    return (res.json or {}).get("files") or []


def test_stored_files_have_metadata():
    """Every stored GLB/MP4 has a metadata description (the agents match requests against it)."""
    empty = [f.get("name") for f in _files() if not f.get("metadata")]
    assert not empty, (f"{len(empty)} stored file(s) have no .meta description, so ImageTo3DAgent / "
                       f"ImageToVideoAgent cannot match a request to them: {', '.join(map(str, empty[:15]))}")


def test_stored_videos_are_marked_stereo():
    """Every stored MP4 carries the 'stereo-video' marker generate_video always appends."""
    bad = [f.get("name") for f in _files()
           if str(f.get("name", "")).lower().endswith(".mp4") and "stereo-video" not in str(f.get("metadata") or "")]
    assert not bad, (f"{len(bad)} MP4 file(s) lack the stereo-video metadata marker that "
                     f"ImageToVideoAgentTools.AppendStereoVideoTag adds: {', '.join(map(str, bad[:15]))}")


def test_upload_download_delete_round_trip():
    """A GLB can be stored, read back, is protected from overwrite, and can be deleted.

    Writes a file named qa-probe-<random>.glb to the shared storage and removes it again.
    """
    name = f"qa-probe-{uuid.uuid4().hex[:10]}.glb"
    payload = b"glTF" + b"\x02\x00\x00\x00" + b"\x00" * 56
    url = f"{_base()}/files"
    try:
        up = call(SERVICE, "upload", "POST", url, headers=_key(),
                  files={"file": (name, payload, "model/gltf-binary")},
                  data={"metadata": "agenthub-health probe - safe to delete", "overwrite": "false"})
        expect_status(up, [201, 200], "POST /files")
        down = call(SERVICE, "download", "GET", f"{url}/{name}", headers=_key())
        expect_ok(down, f"GET /files/{name}")
        contract(down, down.content[:4] == b"glTF", "The downloaded file is not the bytes that were uploaded.")
        again = call(SERVICE, "upload again (no overwrite)", "POST", url, headers=_key(),
                     files={"file": (name, payload, "model/gltf-binary")}, data={"overwrite": "false"})
        expect_status(again, [409], "POST /files for an existing name without overwrite")
    finally:
        call(SERVICE, "delete", "DELETE", f"{url}/{name}", headers=_key())
    gone = call(SERVICE, "download after delete", "GET", f"{url}/{name}", headers=_key())
    expect_status(gone, [404], f"GET /files/{name} after DELETE")


def test_disallowed_extension_refused():
    """A file type other than .glb / .mp4 is refused with 400."""
    res = call(SERVICE, "upload .txt", "POST", f"{_base()}/files", headers=_key(),
               files={"file": ("qa-probe.txt", b"probe", "text/plain")})
    expect_status(res, [400], "POST /files with a .txt file")
