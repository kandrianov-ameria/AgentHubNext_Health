"""
Golden scenario replays (1.13.0). Report section "Golden scenarios", never the health verdict
(marker `golden`: the plugin keeps these records out of the counts, the history and the exit status).

For the golden scenarios that are one model call over a screenshot (GS-03.1 products, GS-10.1
translation, GS-11.1 chart), the screenshot (tests/assets/golden/, the workbook's page rendered at
1920x1080) and the spoken request go to the LLM provider of PointAndTalkAgent, the way AgentLight
builds them: system message = the agent's InnerInstructions with the placeholders replaced
(AgentLight.BuildSystemMessage), one user message of text + screenshot (AiMessage.CreateUser).

Differences from the app, stated in the report: no tools are offered to the model, the screenshot is
a PNG of the whole page (the app sends a JPEG of the screen plus crops of the pointed zones), the
user text is the spoken request only, and the answer is read as text. The model is not
deterministic: a failed criterion is a signal to look at, not proof of a regression.
"""
from __future__ import annotations

import base64

import pytest

from agenthub_health import golden, remote, settings
from agenthub_health.probe import ConfigDefect, call, contract, expect_ok

pytestmark = [pytest.mark.golden]


def pytest_generate_tests(metafunc):
    if "scenario" in metafunc.fixturenames:
        items = [s for s in golden.catalogue() if "replay" in s]
        metafunc.parametrize("scenario", items, ids=[s["id"] for s in items])


def _build(provider: dict, system: str, text: str, image: bytes, max_tokens: int):
    ptype = provider.get("provider_type")
    base = str(provider.get("base_url") or "").rstrip("/")
    h = remote.parse_headers(provider.get("headers"))
    b64 = base64.b64encode(image).decode("ascii")
    if ptype == "open_ai":
        url = base if base.lower().endswith("/chat/completions") else base + "/chat/completions"
        body = {"model": provider.get("model"), "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": [{"type": "text", "text": text},
                                         {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}]}]}
        return url, {"Authorization": h.get("Authorization", "")}, body
    if ptype == "anthropic":
        url = base if base.lower().endswith("/messages") else base + "/messages"
        body = {"model": provider.get("model"), "max_tokens": max_tokens, "system": system, "messages": [
            {"role": "user", "content": [
                {"type": "text", "text": text},
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}}]}]}
        return url, {"x-api-key": h.get("x-api-key", ""), "anthropic-version": h.get("anthropic-version", "")}, body
    return None


def _answer(ptype: str, body) -> str | None:
    try:
        if ptype == "open_ai":
            c = body["choices"][0]["message"]["content"]
            return c if isinstance(c, str) else None
        return "".join(p.get("text", "") for p in body["content"] if p.get("type") == "text")
    except (KeyError, IndexError, TypeError, AttributeError):
        return None


def test_golden_replay(scenario, cfg, asset):
    """Golden scenario replay: the model of PointAndTalkAgent answers the scenario's screenshot and spoken request."""
    if not settings.GOLDEN_REPLAY:
        pytest.skip("Golden replays are switched off (GOLDEN_REPLAY=0 in suite.env).")
    sid, rp = scenario["id"], scenario["replay"]
    root = cfg.agent(remote.ROOT_AGENT)
    if root is None:
        pytest.skip("PointAndTalkAgent is not defined - reported by test_root_agent_exists.")
    provider = cfg.provider(root.llm_provider_id)
    if provider is None:
        raise ConfigDefect(f"PointAndTalkAgent uses LLM provider id {root.llm_provider_id!r}, which does not exist.",
                           "AgentLight creates the agent's provider from llm_provider_id.",
                           "The agent cannot answer.", "Fix llm_provider_id in Maverick Config Manager.")
    max_tokens = int((root.schema or {}).get("AnthropicRequestMaxTokens") or 1024)
    built = _build(provider, golden.system_prompt(cfg, root), scenario["request"],
                   asset(rp["asset"]).read_bytes(), max_tokens)
    if built is None:
        pytest.skip(f"The replay supports open_ai and anthropic providers; this one is "
                    f"'{provider.get('provider_type')}'.")
    url, headers, body = built
    record = {"request": scenario["request"], "provider": f"{provider.get('name')} ({provider.get('model')})",
              "asset": rp["asset"], "not_replayed": rp.get("not_replayed", ""), "answer": "", "checks": []}
    golden.REPLAYS[sid] = record
    res = call("llm", f"golden replay {sid}", "POST", url, headers=headers, json=body,
               timeout=settings.TIMEOUT_LLM, subject=f"LLM provider '{provider.get('name')}'")
    record["latency_ms"] = res.latency_ms
    expect_ok(res, f"Provider '{provider.get('name')}'", f"Replay of {sid}.")
    answer = _answer(provider.get("provider_type"), res.json)
    contract(res, answer is not None, "The provider answered 200 without the text AgentLight reads.")
    record["answer"] = answer
    record["checks"] = golden.run_checks(answer, rp["checks"])
    failed = [f"{label} ({detail})" for label, ok, detail in record["checks"] if not ok]
    assert not failed, f"{sid} answer did not meet: " + "; ".join(failed)
