"""
Secret masking. Every string that reaches the console or the HTML report goes
through `text()`. Secrets from `.env` are registered at import; secrets the
suite discovers at runtime (Deepgram key, proxy header, LLM provider keys, MCP
headers) are registered as soon as they are parsed.
"""
from __future__ import annotations

import re
from typing import Iterable

from . import settings

_SECRETS: set[str] = set()
_MIN_LEN = 6


def register(value: str | None) -> None:
    if not value:
        return
    value = value.strip()
    if len(value) < _MIN_LEN:
        return
    _SECRETS.add(value)
    # "Bearer abc", "Basic abc", "Token abc" - also mask the bare credential.
    parts = value.split(" ", 1)
    if len(parts) == 2 and len(parts[1]) >= _MIN_LEN:
        _SECRETS.add(parts[1].strip())


def register_many(values: Iterable[str | None]) -> None:
    for v in values:
        register(v)


def mask(value: str) -> str:
    return f"****{value[-4:]}" if len(value) > 8 else "****"


def text(s: object) -> str:
    if s is None:
        return ""
    out = str(s)
    # Longest first, so a full header is masked before its bare token.
    for secret in sorted(_SECRETS, key=len, reverse=True):
        if secret in out:
            out = out.replace(secret, mask(secret))
    # Defence in depth: header-shaped "name: <credential>" pairs whose value looks like a secret.
    out = re.sub(r"(?i)(authorization|x-api-key|x-goog-api-key|x-seq-apikey)(\"?\s*[:=]\s*\"?)"
                 r"((?:bearer|basic|token)\s+)?([A-Za-z0-9._~+/=|-]{16,})",
                 lambda m: m.group(1) + m.group(2) + (m.group(3) or "") + mask(m.group(4)), out)
    return out


for _name in settings.SECRET_VARS + settings.OPTIONAL_SECRET_VARS:
    register(settings.get(_name))
