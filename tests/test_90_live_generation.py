"""
Live generation - a real 3D model and a real video, end to end. Slow and
billable, so excluded by default. Run with: run_tests.bat --live
"""
from __future__ import annotations

import time

import pytest

from agenthub_health import settings
from agenthub_health.probe import ServiceFailure, basic_auth, call, contract, expect_ok, need

pytestmark = pytest.mark.live


def _generate(service: str, base_var: str, auth_var: str, prompt: str, image: bytes):
    base, auth = need(base_var), basic_auth(auth_var)
    up = call(service, "upload", "POST", f"{base}/upload", files={"file": ("probe.jpg", image, "image/jpeg")}, auth=auth)
    expect_ok(up, "POST /upload")
    token = ((up.json or {}).get("data") or {}).get("image_token")
    contract(up, bool(token), "POST /upload did not return data.image_token.")
    task = call(service, "task", "POST", f"{base}/task", json={"prompt": prompt, "files": [{"file_token": token}]}, auth=auth)
    expect_ok(task, "POST /task")
    task_id = ((task.json or {}).get("data") or {}).get("task_id")
    contract(task, bool(task_id), "POST /task did not return data.task_id.")
    deadline = time.time() + settings.TIMEOUT_GENERATION
    while True:
        st = call(service, "task status", "GET", f"{base}/task/{task_id}", auth=auth)
        expect_ok(st, f"GET /task/{task_id}")
        data = (st.json or {}).get("data") or {}
        if data.get("status") in ("success", "failed"):
            return st, data
        if time.time() > deadline:
            raise ServiceFailure(st, f"Task {task_id} still '{data.get('status')}' after "
                                     f"{int(settings.TIMEOUT_GENERATION)} s (progress {data.get('progress')}).")
        time.sleep(10)


def test_3d_model_is_generated(asset):
    """2d-to-3d turns the probe image into a downloadable GLB model."""
    st, data = _generate("2d-to-3d", "TWO_D_TO_3D_BASE_URL", "TWO_D_TO_3D_BASIC_AUTH",
                         "Generate a 3D model of the main object in this image", asset("probe.jpg").read_bytes())
    contract(st, data.get("status") == "success", f"Generation ended with status 'failed': {data.get('error')}")
    url = ((data.get("output") or {}).get("model") or {}).get("url") or ""
    contract(st, bool(url) and not url.startswith("test-mode://"),
             f"No real model URL in the output ('{url}'). A test-mode:// URL means the service runs with "
             "TEST_MODE_SKIP_3D_GENERATION.")
    glb = call("2d-to-3d", "download model", "GET", url, auth=basic_auth("TWO_D_TO_3D_BASIC_AUTH"))
    expect_ok(glb, "Download model.glb")
    contract(glb, glb.content[:4] == b"glTF", "The downloaded model is not a GLB file.")


def test_stereo_video_is_generated(asset):
    """2d-to-video produces a video with the stereo variant generate_video requires."""
    st, data = _generate("2d-to-video", "TWO_D_TO_VIDEO_BASE_URL", "TWO_D_TO_VIDEO_BASIC_AUTH",
                         "the object in this image slowly rotating", asset("probe.jpg").read_bytes())
    contract(st, data.get("status") == "success", f"Generation ended with status 'failed': {data.get('error')}")
    out = data.get("output") or {}
    contract(st, bool(out.get("video_url")) and not str(out.get("video_url")).startswith("test-mode://"),
             "No real video_url in the output - the service may run with TEST_MODE_SKIP_VIDEO_GENERATION.")
    contract(st, bool(out.get("video_3d_url")),
             "video_3d_url is null. The task succeeded, but generate_video downloads only the stereo variant and "
             "fails without it. Check VIDEO_3D_ENABLED on the 2d-to-video service.")
