"""
Object segmentation - the vision model and SAM3, called the way
Ameria.Segmentation calls them (VisionObjectClient, Sam3Client).
"""
from __future__ import annotations

import pytest

from agenthub_health.probe import call, contract, expect_ok, unused_by_app

pytestmark = pytest.mark.smoke


def _auth(section: dict) -> dict:
    v = str(section.get("ProxyAuthHeader") or "")
    return {"Authorization": v} if v else {}


def _vision_url(configured: str) -> str:
    """Same rule as VisionObjectClient.ChatCompletionsUrl."""
    u = configured.rstrip("/")
    if u.lower().endswith("/chat/completions"):
        return u
    return u + "/chat/completions" if u.lower().endswith("/v1") else u + "/v1/chat/completions"


def _need(section: dict, key: str) -> str:
    v = str(section.get(key) or "")
    if not v:
        pytest.skip(f"{key} is not configured - object segmentation is off in this environment.")
    return v


def test_vision_model_names_objects(agenthub_section):
    """The vision model answers a text-only object-naming request (as used while the user speaks)."""
    url = _vision_url(_need(agenthub_section, "VisionUrl"))
    model = _need(agenthub_section, "VisionModel")
    # Same body as VisionObjectClient.CompleteAsync (4.0.53): reasoning is always disabled.
    body = {"model": model, "stream": False, "messages": [{"role": "user", "content": [
        {"type": "text", "text": "List the physical objects named in this sentence as a comma-separated "
                                 "list and nothing else: the blue cup is on the wooden table."}]}],
            "chat_template_kwargs": {"enable_thinking": False}}
    res = call("vision", "chat/completions", "POST", url, headers=_auth(agenthub_section), json=body, timeout=60)
    expect_ok(res, "Vision model", f"Model '{model}'.")
    try:
        answer = res.json["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        answer = None
    contract(res, isinstance(answer, str),
             "The vision model answered 200 without choices[0].message.content, which VisionObjectClient reads.")


def test_sam3_segments_by_text(agenthub_section, asset):
    """SAM3 accepts a text-prompt segmentation request for an image."""
    url = _need(agenthub_section, "SamPredictTextUrl")
    files = {"image_file": ("screen.jpg", asset("probe.jpg").read_bytes(), "image/jpeg")}
    data = {"return_zip": "false", "text_prompt": "text", "threshold": "0.7", "mask_threshold": "0.5"}
    res = call("sam3", "predict by text", "POST", url, headers=_auth(agenthub_section),
               data=data, files=files, timeout=60)
    expect_ok(res, "SAM3 text-prompt segmentation")
    contract(res, res.json is not None, "SAM3 answered 200 with a body that is not JSON.")


POINT_UNUSED = ("Sam3Client.SegmentByPointAsync, the only caller of SamPredictUrl, is documented as "
                "'Not used by the current flow' and nothing in agent-hub-backend calls it. Object "
                "highlighting uses the text-prompt endpoint (SamPredictTextUrl), which has its own check.")


def test_sam3_segments_by_point(agenthub_section, asset):
    """SAM3 accepts a point-prompt segmentation request for an image (endpoint not used by the current flow)."""
    url = _need(agenthub_section, "SamPredictUrl")
    files = {"image_file": ("screen.jpg", asset("probe.jpg").read_bytes(), "image/jpeg")}
    data = {"return_zip": "false", "point_coords": "[[100,60]]", "point_labels": "[1]", "mask_threshold": "0.5"}
    res = call("sam3", "predict by point", "POST", url, headers=_auth(agenthub_section),
               data=data, files=files, timeout=60)
    with unused_by_app(POINT_UNUSED):
        expect_ok(res, "SAM3 point-prompt segmentation")
        contract(res, res.json is not None, "SAM3 answered 200 with a body that is not JSON.")
