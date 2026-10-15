"""
Speech - Deepgram key and Whisper transcription contract.

Whisper requests are built like Ameria.Speech.WhisperClient: multipart with
file=voice.wav, model, response_format=verbose_json, and language only when
it is not 'auto'; the Authorization header is ProxyAuthHeader verbatim.
The two response shapes the client accepts are checked the same way it
checks them.
"""
from __future__ import annotations

import pytest

from agenthub_health import settings
from agenthub_health.probe import ServiceFailure, call, contract, expect_ok

pytestmark = pytest.mark.smoke


def test_deepgram_key_is_accepted(agenthub_section):
    """Deepgram accepts DefaultDeepgramApiKey.

    Uses Deepgram's public REST API (GET https://api.deepgram.com/v1/projects,
    'Authorization: Token <key>'), which the Deepgram SDK in the app talks to.
    """
    key = str(agenthub_section.get("DefaultDeepgramApiKey") or "")
    if not key:
        pytest.skip("DefaultDeepgramApiKey is empty - reported by test_field_is_set.")
    res = call("deepgram", "projects", "GET", f"{settings.DEEPGRAM_API_URL}/v1/projects",
               headers={"Authorization": f"Token {key}"})
    if res.http_status == 404:
        raise ServiceFailure(res, "Deepgram answered 404 on /v1/projects. The key was not judged - the suite's "
                                  "probe endpoint may need updating.")
    expect_ok(res, "Deepgram key check")


def _whisper(section: dict, wav: bytes, language: str | None, name: str):
    url = str(section.get("WhisperUrl") or "")
    model = str(section.get("WhisperModel") or "")
    if not url or not model:
        pytest.skip("WhisperUrl / WhisperModel empty - reported by test_field_is_set.")
    data = {"model": model, "response_format": "verbose_json"}
    if language:
        data["language"] = language
    headers = {"Accept": "application/json"}
    auth = str(section.get("ProxyAuthHeader") or "")
    if auth:
        headers["Authorization"] = auth
    return call("whisper", name, "POST", url, headers=headers, data=data,
                files={"file": ("voice.wav", wav, "audio/wav")}, timeout=60)


def _shape(body) -> str:
    if not isinstance(body, dict):
        return ""
    if isinstance(body.get("text"), str) and isinstance(body.get("language"), str) and body["language"]:
        return "verbose_json"
    if isinstance(body.get("transcription"), list) and isinstance(body.get("is_silence_detected"), bool) \
            and all(isinstance(x, str) for x in body["transcription"]):
        return "segmented"
    return ""


@pytest.mark.parametrize("language", ["en", "de", None], ids=["en", "de", "auto"])
def test_whisper_accepts_the_app_request(agenthub_section, asset, language):
    """Whisper accepts the multipart request AgentHubNext sends and answers in a shape the client accepts."""
    wav = asset("probe_silence.wav").read_bytes()
    label = language or "auto (field omitted)"
    res = _whisper(agenthub_section, wav, language, "transcribe")
    expect_ok(res, f"Whisper, language {label}")
    contract(res, bool(_shape(res.json)),
             "Whisper answered 200, but neither with 'text' + 'language' (verbose JSON) nor with a "
             "'transcription' string array + boolean 'is_silence_detected' (segmented). WhisperClient "
             "treats that as a failure.")
