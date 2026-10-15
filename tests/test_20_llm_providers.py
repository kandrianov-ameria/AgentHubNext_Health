"""
LLM providers - one tiny request to every provider an agent of this
environment uses, built exactly the way Ameria.LlmClient builds it:

  open_ai            POST {base_url}/chat/completions      Authorization
  anthropic          POST {base_url}/messages               x-api-key + anthropic-version
  gemini             POST {base_url}/v1beta/models/{model}:generateContent   x-goog-api-key
  open_ai_embedding  POST {base_url}/embeddings             Authorization

(The suffix is only appended when base_url does not already end with it.)
"""
from __future__ import annotations

import pytest

from agenthub_health import remote, settings
from agenthub_health.probe import ConfigDefect, ProbeResult, ServiceFailure, call, contract, expect_ok

pytestmark = pytest.mark.smoke

PROMPT = "Reply with the single word PONG."


def _providers_under_test():
    """[(provider, used_by)] or [("unavailable", exc)] when the list cannot be fetched."""
    try:
        cfg = remote.config()
    except ServiceFailure as exc:
        return [("unavailable", exc)]
    used: dict = {}
    for a in cfg.agents:
        for role, pid in (("primary", a.llm_provider_id), ("secondary", a.secondary_llm_provider_id)):
            if pid is not None:
                used.setdefault(pid, []).append(f"{a.name} ({role})")
    out = []
    for pid, agents in used.items():
        p = cfg.provider(pid)
        if p is not None:
            out.append((p, agents))
    emb = next((p for p in cfg.providers
                if p.get("primary") and p.get("provider_type") == "open_ai_embedding"), None)
    if emb is not None and emb.get("id") not in used:
        out.append((emb, ["Embedding Client"]))
    return out


def pytest_generate_tests(metafunc):
    if "provider" in metafunc.fixturenames:
        items = _providers_under_test()
        ids = ["unavailable" if p == "unavailable" else f"{p.get('name') or p.get('id')}-{p.get('provider_type')}"
               for p, _ in items]
        metafunc.parametrize("provider,used_by", items, ids=ids)


def _suffix(base: str, suffix: str) -> str:
    base = base.rstrip("/")
    return base if base.lower().endswith(suffix) else base + suffix


def _request(p: dict) -> tuple[str, dict, dict]:
    ptype = p.get("provider_type")
    base = str(p.get("base_url") or "")
    model = p.get("model")
    h = remote.parse_headers(p.get("headers"))
    if ptype == "open_ai":
        return (_suffix(base, "/chat/completions"), {"Authorization": h.get("Authorization", "")},
                {"model": model, "messages": [{"role": "user", "content": PROMPT}]})
    if ptype == "anthropic":
        return (_suffix(base, "/messages"),
                {"x-api-key": h.get("x-api-key", ""), "anthropic-version": h.get("anthropic-version", "")},
                {"model": model, "max_tokens": 16, "messages": [{"role": "user", "content": PROMPT}]})
    if ptype == "gemini":
        key = h.get("x-goog-api-key") or h.get("Authorization", "")
        if key.lower().startswith("bearer "):
            key = key[7:]
        return (f"{base.rstrip('/')}/v1beta/models/{model}:generateContent", {"x-goog-api-key": key},
                {"contents": [{"role": "user", "parts": [{"text": PROMPT}]}]})
    if ptype == "open_ai_embedding":
        return (_suffix(base, "/embeddings"), {"Authorization": h.get("Authorization", "")},
                {"model": model, "input": ["agenthub health probe"], "encoding_format": "float"})
    raise ValueError(ptype)


def _answer(ptype: str, body) -> bool:
    try:
        if ptype == "open_ai":
            return isinstance(body["choices"][0]["message"], dict)
        if ptype == "anthropic":
            return isinstance(body["content"], list)
        if ptype == "gemini":
            return isinstance(body["candidates"][0]["content"], dict)
        if ptype == "open_ai_embedding":
            return len(body["data"][0]["embedding"]) > 0
    except (KeyError, IndexError, TypeError):
        return False
    return False


def test_provider_answers(provider, used_by):
    """An LLM provider used by AgentHubNext answers a minimal request with the configured key and model."""
    if provider == "unavailable":
        raise used_by
    ptype = provider.get("provider_type")
    name = provider.get("name") or provider.get("id")
    if ptype not in ("open_ai", "anthropic", "gemini", "open_ai_embedding"):
        pytest.skip(f"Provider '{name}' has type '{ptype}', which AgentLight does not support - "
                    "reported by test_agent_providers_are_usable.")
    problem = remote.header_problem(provider.get("headers"))
    if problem:
        # The application cannot build this provider at all (AgentLight.CreateProviderFromId ->
        # GetHeaders), so a request with guessed headers would test something the app never sends.
        raise ConfigDefect(f"Provider '{name}': {problem}",
                           "AgentLight.CreateProviderFromId throws for an unsupported provider type or a missing header.",
                           "The agent cannot be created when a session starts, so it cannot answer.",
                           "Correct the provider's headers in Maverick Config Manager.")
    url, headers, body = _request(provider)
    res = call("llm", f"{name} ({ptype})", "POST", url, headers=headers, json=body,
               timeout=settings.TIMEOUT_LLM, subject=f"LLM provider '{name}'")
    hint = f"Model '{provider.get('model')}'. Used by: {', '.join(used_by)}."
    expect_ok(res, f"Provider '{name}' ({ptype})", hint)
    contract(res, _answer(ptype, res.json),
             f"Provider '{name}' answered 200 but without the fields Ameria.LlmClient reads for '{ptype}'.", hint)
