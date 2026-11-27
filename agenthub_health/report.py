"""
results/result.html - a single self-contained file (no build step, no external script).

Design (1.6.0): NextUI / HeroUI tokens (designsystems.one/design-systems/nextui) on the 1.5.0 "bento" layout. A sticky glass toolbar (search, status filter,
expand/collapse, copy for Teams), a verdict tile tinted by the outcome, a segmented donut,
clickable status chips, a per-service health grid, the slowest requests and the changes since
the previous run. Below that the sections keep their categories and their collapsed cards:
Failed, Failed with no effect on the app, Suite issues, Passed (grouped by area), Known
issues, Skipped, Run details.

What the page promises to keep (the suite's users rely on it):
  * the section categories and their ids (#failed #unused #suite #passed #known #skipped #run);
  * every card is a collapsed <details> with a "Copy for Teams" button in its summary; the
    Teams text is built from the DOM of the card (summary .eyebrow, summary h3, summary
    .badges .badge, then .card-b), so those parts must keep their classes;
  * nothing secret: every string goes through redact.text() via e().

Run history: results/history.json keeps the outcome of the last runs per environment so the
page can say "new", "still failing for N runs" and "fixed". It holds check ids and categories
only, no response bodies.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
from collections import OrderedDict, defaultdict
from types import SimpleNamespace

from . import impact, redact, report_golden, report_theme, services, settings

AREAS = {
    "test_00_setup": "Suite setup",
    "test_01_remote_config": "Remote configuration",
    "test_02_agent_graph": "Agent graph",
    "test_05_config_download": "Configuration download",
    "test_10_aihub_service": "AI-Hub service",
    "test_11_pat_config": "pat-config",
    "test_20_llm_providers": "LLM providers",
    "test_21_speech": "Speech (Deepgram, Whisper)",
    "test_22_segmentation": "Object segmentation",
    "test_30_mav_starkit": "mav-starkit-api",
    "test_31_generation_services": "Generation services",
    "test_40_mcp_servers": "MCP servers",
    "test_41_tavily_image_mcp": "Tavily image MCP",
    "test_42_mavslides": "MAV Slides",
    "test_50_logs_mapping_seq": "Log upload, device mapping, Seq",
    "test_90_live_generation": "Live generation",
}

# key, label, colour variable, icon. The order is the order of the sections on the page.
STATUSES = [
    ("failed", "Failed", "--bad", "x"),
    ("unused", "No app effect", "--warn", "minus"),
    ("suite", "Suite issues", "--suite", "alert"),
    ("known", "Known issues", "--info", "info"),
    ("passed", "Passed", "--ok", "check"),
    ("skipped", "Skipped", "--neu", "skip"),
]
_BAD = {"failed", "unused", "suite"}
HISTORY_KEEP = settings.LOG_RUNS_TO_KEEP  # same limit as the log folders (AGENTHUB_HEALTH_LOG_RUNS)


def e(s) -> str:
    return html.escape(redact.text(s), quote=True)


def _area(module: str) -> str:
    return AREAS.get(module, module)


def _ts(t: float) -> str:
    return dt.datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S") if t else "-"


def _dur(sec: float) -> str:
    if sec < 1:
        return f"{int(sec * 1000)} ms"
    if sec < 60:
        return f"{sec:.1f} s"
    return f"{int(sec // 60)} min {int(sec % 60)} s"


def _ms(ms: float) -> str:
    return f"{ms / 1000:.1f} s" if ms >= 10000 else f"{int(ms)} ms"


def _badge(text, kind: str) -> str:
    return f'<span class="badge badge-{kind}">{e(text)}</span>'


def _app_version(av: dict | None) -> str:
    """Header chips: the AgentHubNext version the suite was written against and the one on GitHub.
    Red and glowing when GitHub is ahead, green otherwise, grey when GitHub could not be read."""
    if not av:
        return ""
    state = av.get("state", "unknown")
    remote = av.get("remote") or "unknown"
    tip = f"Branch {av.get('branch', '')} on GitHub. " + {
        "ahead": "GitHub is ahead of the version this suite was written against: review the new commits.",
        "current": "GitHub has no newer version than the suite was written against.",
    }.get(state, av.get("detail") or "Could not be read; see suite.log.")
    return (f'<span class="appver" title="{e(tip)}"><span class="appver-l">AgentHubNext</span>'
            f'<span class="appver-i">suite <b>{e(av.get("used") or "?")}</b></span>'
            f'<span class="appver-i appver-{e(state)}">GitHub <b>{e(remote)}</b></span></span>')


def _ico(name: str, cls: str = "i") -> str:
    return f'<svg class="{cls}" aria-hidden="true"><use href="#i-{name}"/></svg>'


def _aid(kind: str, nodeid: str) -> str:
    return f"{kind}-{hashlib.md5(nodeid.encode('utf-8')).hexdigest()[:8]}"


def _clip(text: str, n: int = 170) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _first_sentence(text: str, n: int = 170) -> str:
    text = " ".join((text or "").split())
    cut = text.find(". ")
    if 0 < cut < n:
        text = text[: cut + 1]
    return _clip(text, n)


def _svc_title(key: str) -> str:
    return services.SERVICES[key].title if key in services.SERVICES else key


def _svc_keys(r) -> list[str]:
    keys = {p["service"] for p in r.probes if p.get("service")}
    fp = (r.failure or {}).get("probe")
    if fp and fp.get("service"):
        keys.add(fp["service"])
    return sorted(keys)


def _probe_rows(probes: list[dict]) -> str:
    if not probes:
        return ""
    rows = []
    for p in probes:
        kind = "success" if p["status"] == "ok" else "danger"
        code = p["http_status"] if p["http_status"] is not None else "-"
        rows.append(
            f'<tr><td class="mono">{e(p["method"])}</td><td class="mono url">{e(p["url"])}</td>'
            f'<td>{_badge(code, kind)}</td><td>{e(p["status"])}</td><td class="num">{p["latency_ms"]} ms</td></tr>')
    return ('<table class="tbl tbl-compact"><thead><tr><th>Method</th><th>URL</th><th>HTTP</th>'
            '<th>Outcome</th><th class="num">Latency</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table>")


def _kv(label: str, value: str, mono: bool = False) -> str:
    if not value:
        return ""
    cls = ' class="mono"' if mono else ""
    return f"<dt>{e(label)}</dt><dd{cls}>{e(value)}</dd>"


COPY_BUTTON = '<button class="copy" type="button" onclick="copyCard(this)">Copy for Teams</button>'
MD_BUTTON = ('<div class="card-actions"><button class="copy" type="button" onclick="copyMarkdown(this)">'
             'Copy as Markdown</button></div>')


def _chev() -> str:
    return _ico("chev", "i chev")


# --- run history -------------------------------------------------------------------

def _history_path():
    return settings.RESULTS_DIR / "history.json"


def _read_history_file() -> dict:
    try:
        data = json.loads(_history_path().read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("runs"), list):
            return data
    except Exception:
        pass
    return {"runs": []}


def _compare(records, env: str) -> SimpleNamespace:
    """What changed against the previous run of the same environment (check ids and categories)."""
    runs = [r for r in _read_history_file()["runs"] if r.get("env") == env]
    h = SimpleNamespace(has_prev=bool(runs), prev_time=runs[-1].get("finished") if runs else None,
                        new=set(), still=set(), fixed=set(), streak={})
    prev = runs[-1].get("states", {}) if runs else {}
    for r in records:
        now_bad = r.category in _BAD
        was_bad = prev.get(r.nodeid) in _BAD
        if now_bad:
            n = 1
            for run in reversed(runs):
                if run.get("states", {}).get(r.nodeid) in _BAD:
                    n += 1
                else:
                    break
            h.streak[r.nodeid] = n
            (h.still if was_bad else h.new).add(r.nodeid)
        elif was_bad and r.category in ("passed", "known_fixed"):
            h.fixed.add(r.nodeid)
    return h


def _save_history(records, env: str, finished: float, version: str) -> None:
    try:
        data = _read_history_file()
        counts: dict[str, int] = defaultdict(int)
        for r in records:
            counts[r.category] += 1
        data["runs"].append({"finished": finished, "env": env, "version": version, "counts": dict(counts),
                             "states": {r.nodeid: r.category for r in records}})
        kept: list[dict] = []
        per_env: dict[str, int] = defaultdict(int)
        for run in reversed(data["runs"]):
            per_env[run.get("env", "")] += 1
            if per_env[run.get("env", "")] <= HISTORY_KEEP:
                kept.append(run)
        data["runs"] = list(reversed(kept))
        tmp = _history_path().with_suffix(".tmp")
        tmp.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
        tmp.replace(_history_path())
    except Exception:
        try:
            from .runlog import log
            log.warning("Could not save results/history.json", exc_info=True)
        except Exception:
            pass


def _change_badges(nodeids, h) -> str:
    if not h.has_prev:
        return ""
    if any(n in h.new for n in nodeids):
        return " " + _badge("new", "danger")
    streak = max((h.streak.get(n, 0) for n in nodeids), default=0)
    if streak >= 2:
        return " " + _badge(f"still failing · {streak} runs", "neutral")
    return ""


# --- cards -------------------------------------------------------------------------

def _data(status: str, services_: list[str], search: str) -> str:
    return (f'data-status="{status}" data-service="{e(" ".join(services_))}" '
            f'data-search="{e(" ".join(search.lower().split()))}"')


def _check_card(r, kind: str, h) -> str:
    """One collapsible card per check: facts, what it means, and the requests it made."""
    if kind == "passed":
        badge, title, text = _badge("passed", "success"), "Result", "Passed."
        if h.has_prev and r.nodeid in h.fixed:
            badge += " " + _badge("fixed since last run", "success")
        n = len(r.probes)
        lat = sum(p["latency_ms"] for p in r.probes if p.get("latency_ms") is not None)
        line = (f"{n} request{'s' if n != 1 else ''} · {_ms(lat)}" if n
                else "No network request - checks configuration or files")
        ico = "check"
    elif kind == "known":
        badge = _badge("fixed - remove xfail", "success") if r.category == "known_fixed" else _badge("known", "info")
        title, text, line, ico = "Known issue", r.reason, _clip(r.reason), "info"
    else:
        badge, title, text, line, ico = _badge("skipped", "neutral"), "Why it was skipped", r.reason, _clip(r.reason), "skip"
    facts = "".join([
        _kv("Area", _area(r.module)),
        _kv("Check", r.nodeid, mono=True),
        _kv("Duration", _dur(r.duration)),
        _kv("Latency", ", ".join(f'{p["latency_ms"]} ms' for p in r.probes)),
    ])
    requests = (f'<details class="block"><summary>Requests made</summary>{_probe_rows(r.probes)}</details>'
                if r.probes else "")
    svcs = _svc_keys(r)
    search = f"{r.objective} {r.nodeid} {_area(r.module)} {r.reason} " + " ".join(p["url"] for p in r.probes)
    return f"""
<details class="card check {kind}" id="{_aid(kind, r.nodeid)}" {_data(kind, svcs, search)}>
  <summary class="card-h">{_chev()}<span class="st-ico">{_ico(ico)}</span>
    <div class="hm"><div class="eyebrow">{e(_area(r.module))}</div><h3>{e(r.objective)}</h3><div class="sum">{e(line)}</div></div>
    <div class="badges">{badge}{COPY_BUTTON}</div>
  </summary>
  <div class="card-b">
    <dl class="facts">{facts}</dl>
    <div class="block"><h4>{title}</h4><p>{e(text)}</p></div>
    {requests}
    {MD_BUTTON}
  </div>
</details>"""


def _check_list(records, kind: str, h) -> str:
    if not records:
        return '<div class="empty">None.</div>'
    return "".join(_check_card(r, kind, h) for r in sorted(records, key=lambda r: (_area(r.module), r.nodeid)))


def _passed_groups(records, h) -> str:
    if not records:
        return '<div class="empty">None.</div>'
    by: "OrderedDict[str, list]" = OrderedDict()
    for r in records:
        by.setdefault(r.module, []).append(r)
    order = [m for m in AREAS if m in by] + sorted(m for m in by if m not in AREAS)
    out = []
    for m in order:
        recs = sorted(by[m], key=lambda r: r.nodeid)
        lat = sum(p["latency_ms"] for r in recs for p in r.probes if p.get("latency_ms") is not None)
        nreq = sum(len(r.probes) for r in recs)
        meta = f"{nreq} request{'s' if nreq != 1 else ''} · {_ms(lat)}" if nreq else "no network requests"
        out.append(f"""
<details class="group" data-group>
  <summary>{_chev()}<span class="st-ico ok">{_ico('check')}</span>
    <span class="g-title">{e(_area(m))}</span><span class="g-count">{len(recs)} passed</span>
    <span class="g-meta">{e(meta)}</span></summary>
  <div class="g-body">{''.join(_check_card(r, 'passed', h) for r in recs)}</div>
</details>""")
    return "".join(out)


def _group_causes(records, prefix: str):
    groups: "OrderedDict[str, list]" = OrderedDict()
    for r in records:
        groups.setdefault(r.failure.get("cause_key", r.nodeid), []).append(r)
    ordered = sorted(groups.values(), key=lambda g: -len(g))
    return [(g, f"{prefix}{i}") for i, g in enumerate(ordered, 1)]


def _impact_block(imp) -> str:
    """'Affected in this configuration' (impact.py). Plain structure so the Teams copy can turn it into
    bold group labels and names, regular explanations and italic notes: <p><b>label</b></p><ul><li>."""
    if imp is None:
        return ""
    parts = []
    for kind, entries in imp.ordered().items():
        items = "".join(
            f'<li><b>{e(x.name)}</b>' + (f" – {e(x.how)}" if x.how else "")
            + (f" <i>({e(x.note)})</i>" if x.note else "") + "</li>" for x in entries)
        parts.append(f'<p class="il"><b>{e(kind)}</b></p><ul>{items}</ul>')
    return (f'<div class="block impact"><h4>Affected in this configuration</h4><p>{e(imp.summary)}</p>'
            + "".join(parts) + "</div>")


def _impact_search(imp) -> str:
    if imp is None:
        return ""
    return " ".join(f"{x.name} {x.how}" for entries in imp.groups.values() for x in entries)


def _failed_section(groups, h, empty: str = "No failed checks.", records=()) -> str:
    if not groups:
        return f'<div class="empty">{e(empty)}</div>'
    cards = []
    for i, (group, cid) in enumerate(groups, 1):
        f = group[0].failure
        noeff = bool(f.get("no_effect_reason"))
        status = "unused" if noeff else "failed"
        probe = f.get("probe")
        head_badges = _badge(f"{len(group)} check{'s' if len(group) != 1 else ''}", "warning" if noeff else "danger")
        if probe:
            head_badges += " " + _badge(probe["status"], "neutral")
            if probe["http_status"] is not None:
                head_badges += " " + _badge(f"HTTP {probe['http_status']}", "neutral")
        head_badges += _change_badges([r.nodeid for r in group], h)
        facts = "".join([
            _kv("Service", f.get("service", "")),
            _kv("Owner", f.get("owner", "")),
            _kv("Request", f"{probe['method']} {probe['url']}" if probe else "", mono=True),
            _kv("Latency", f"{probe['latency_ms']} ms" if probe else ""),
            _kv("Credential", f.get("credential", "")),
        ])
        evidence = []
        if probe and probe.get("error"):
            evidence.append(f'<div class="ev-label">Transport error</div><pre>{e(probe["error"])}</pre>')
        if probe and probe.get("body"):
            evidence.append(f'<div class="ev-label">Response body (first 1500 characters)</div><pre>{e(probe["body"])}</pre>')
        affected = "".join(
            f'<tr><td><div class="t-obj">{e(r.objective)}</div><div class="t-id mono">{e(r.nodeid)}</div></td>'
            f'<td>{e(r.failure.get("message", ""))}'
            + (f'<div class="t-hint">{e(r.failure["hint"])}</div>' if r.failure.get("hint") else "")
            + (f'<div class="t-id mono">{e(r.failure["location"])}</div>' if r.failure.get("location") else "")
            + "</td></tr>" for r in group)
        line_parts = [p for p in (f.get("service", ""), f.get("owner", "")) if p]
        effect = f.get("no_effect_reason") or f.get("impact") or ""
        # What the failure touches in this run's configuration. Only for failures that affect the app: the
        # others already say, in "Why AgentHubNext is not affected today", that nothing uses them.
        imp = None if noeff else impact.analyse(group, records)
        search = " ".join([f.get("title", ""), f.get("service", ""), f.get("owner", ""), f.get("message", ""),
                           probe["url"] if probe else "", " ".join(r.objective + " " + r.nodeid for r in group),
                           _impact_search(imp)])
        svcs = sorted({k for r in group for k in _svc_keys(r)})
        why = ""
        if noeff:
            why = f'<div class="block"><h4>Why AgentHubNext is not affected today</h4><p>{e(f["no_effect_reason"])}</p></div>'
        elif f.get("impact"):
            why = f'<div class="block"><h4>Effect on AgentHubNext</h4><p>{e(f["impact"])}</p></div>'
        fix = f'<div class="block"><h4>How to fix</h4><p>{e(f["rotation"])}</p></div>' if f.get("rotation") else ""
        ev = f'<details class="block"><summary>Evidence</summary>{"".join(evidence)}</details>' if evidence else ""
        cards.append(f"""
<details class="card cause{' noimpact' if noeff else ''}" id="{cid}" {_data(status, svcs, search)}>
  <summary class="card-h">{_chev()}<span class="st-ico">{_ico('minus' if noeff else 'x')}</span>
    <div class="hm"><div class="eyebrow">Root cause {i}</div><h3>{e(f.get('title', 'Check failed'))}</h3>
      <div class="sum"><b>{e(' · '.join(line_parts))}</b>{(' — ' + e(_first_sentence(effect))) if effect else ''}</div></div>
    <div class="badges">{head_badges}{COPY_BUTTON}</div>
  </summary>
  <div class="card-b">
    <dl class="facts">{facts}</dl>
    <div class="block"><h4>What happened</h4><p>{e(f.get('explanation', ''))}</p></div>
    {why}
    {_impact_block(imp)}
    {fix}
    {ev}
    <h4 class="mt">Affected checks</h4>
    <table class="tbl"><thead><tr><th style="width:42%">Check</th><th>Observed</th></tr></thead><tbody>{affected}</tbody></table>
    {MD_BUTTON}
  </div>
</details>""")
    return "".join(cards)


def _suite_section(records, collection_issues) -> str:
    items = [(c, None) for c in collection_issues] + [(r.failure, r) for r in records]
    if not items:
        return '<div class="empty">No suite issues. Every check ran to a verdict.</div>'
    cards = []
    for f, r in items:
        title = e(r.objective) if r else e(f.get("location", "Collection"))
        ident = f'<div class="t-id mono">{e(r.nodeid)} &middot; phase: {e(r.phase)}</div>' if r else ""
        cid = f' id="{_aid("suite", r.nodeid)}"' if r else ""
        search = " ".join([f.get("type", ""), f.get("message", ""), f.get("location", ""),
                           r.objective if r else "", r.nodeid if r else ""])
        cards.append(f"""
<details class="card issue"{cid} {_data('suite', _svc_keys(r) if r else [], search)}>
  <summary class="card-h">{_chev()}<span class="st-ico">{_ico('alert')}</span>
  <div class="hm"><div class="eyebrow">{e(f.get('type', 'Suite issue'))}</div><h3>{title}</h3>{ident}<div class="sum">{e(_clip(f.get('message', '')))}</div></div>
  <div class="badges">{_badge('suite issue', 'suite')}{COPY_BUTTON}</div></summary>
  <div class="card-b">
    <div class="block"><h4>What this means</h4><p>{e(f.get('meaning', ''))}</p></div>
    <div class="block"><h4>Detail</h4><pre>{e(f.get('message', ''))}</pre></div>
    {f'<dl class="facts">{_kv("Location", f.get("location", ""), mono=True)}</dl>' if f.get('location') and r else ''}
    {f'<div class="block"><h4>How to fix</h4><p>{e(f["remediation"])}</p></div>' if f.get('remediation') else ''}
    {MD_BUTTON}
  </div>
</details>""")
    return "".join(cards)


# --- overview tiles ------------------------------------------------------------------

def _donut(counts: list[tuple[int, str]], total: int, pct: int) -> str:
    r = 54.0
    c = 2 * 3.141592653589793 * r
    segs, cum = [], 0.0
    live = [(n, col) for n, col in counts if n > 0]
    gap = 2.0 if len(live) > 1 else 0.0
    for n, col in live:
        ln = max(n / total * c if total else 0, 3.0)
        segs.append(f'<circle class="seg-c" cx="70" cy="70" r="{r}" style="--len:{max(ln - gap, 1):.2f};--off:{-cum:.2f};stroke:var({col})"/>')
        cum += ln
    return (f'<svg class="donut" viewBox="0 0 140 140" style="--C:{c:.2f}" role="img" aria-label="{pct}% of checks passed">'
            f'<circle cx="70" cy="70" r="{r}" class="track"/>{"".join(segs)}'
            f'<text x="70" y="68" text-anchor="middle" class="d-n">{pct}%</text>'
            f'<text x="70" y="88" text-anchor="middle" class="d-l">passed</text></svg>')


def _service_grid(records) -> str:
    stats: dict[str, dict] = {}
    for r in records:
        keys = {p["service"] for p in r.probes if p.get("service")}
        if not keys:
            continue
        fp = (r.failure or {}).get("probe")
        blamed = {fp["service"]} if fp and fp.get("service") else keys
        for k in keys:
            s = stats.setdefault(k, {"checks": 0, "bad": 0, "noeff": 0, "lat": []})
            s["checks"] += 1
            s["lat"] += [p["latency_ms"] for p in r.probes if p.get("service") == k and p.get("latency_ms") is not None]
            if r.category == "failed" and k in blamed:
                s["bad"] += 1
            elif r.category == "unused" and k in blamed:
                s["noeff"] += 1
    if not stats:
        return '<div class="muted">No service was called in this run.</div>'
    rank = {"bad": 0, "warn": 1, "ok": 2}
    tiles = []
    for k, s in stats.items():
        st = "bad" if s["bad"] else "warn" if s["noeff"] else "ok"
        lat = sorted(s["lat"])
        med = lat[len(lat) // 2] if lat else None
        word = {"bad": f"{s['bad']} failing", "warn": f"{s['noeff']} failing, no effect", "ok": "healthy"}[st]
        icon = {"bad": "x", "warn": "minus", "ok": "check"}[st]
        tiles.append((rank[st], _svc_title(k).lower(), f"""
<button type="button" class="svc {st}" data-svc="{e(k)}" title="Show only the checks that call {e(_svc_title(k))}">
  <span class="svc-dot">{_ico(icon)}</span>
  <span class="svc-t">{e(_svc_title(k))}</span>
  <span class="svc-m">{e(word)} · {s['checks']} check{'s' if s['checks'] != 1 else ''}{(' · median ' + _ms(med)) if med is not None else ''}</span>
</button>"""))
    tiles.sort(key=lambda t: (t[0], t[1]))
    return '<div class="svcs">' + "".join(t[2] for t in tiles) + "</div>"


def _latency_tile(records) -> str:
    reqs = [(p["latency_ms"], p["method"], p["url"], r.nodeid) for r in records for p in r.probes
            if p.get("latency_ms") is not None]
    if not reqs:
        return '<div class="muted">No request was made in this run.</div>'
    reqs.sort(reverse=True)
    lat = sorted(x[0] for x in reqs)
    med, p95 = lat[len(lat) // 2], lat[min(len(lat) - 1, int(0.95 * len(lat)))]
    timeout_ms = settings.TIMEOUT_DEFAULT * 1000
    half = timeout_ms / 2
    scale = max(timeout_ms, reqs[0][0])
    rows = []
    for ms, method, url, nodeid in reqs[:5]:
        flagged = ms > half and "test_20_llm" not in nodeid and "test_90_live" not in nodeid
        w = max(2.0, 100 * ms / scale)
        rows.append(f'<li class="{"slow" if flagged else ""}"><span class="l-u mono" title="{e(url)}">{e(method)} {e(url.split("://", 1)[-1])}</span>'
                    f'<span class="l-b"><i style="width:{w:.1f}%"></i></span><span class="l-v mono">{_ms(ms)}</span></li>')
    stats = (f'<div class="l-stats"><div><b>{len(reqs)}</b><span>requests</span></div><div><b>{_ms(med)}</b><span>median</span></div>'
             f'<div><b>{_ms(p95)}</b><span>95th percentile</span></div></div>')
    note = (f'<p class="muted small">Bars are drawn against the {settings.TIMEOUT_DEFAULT:g} s request timeout; '
            f'amber means more than half of it (LLM and live checks have longer timeouts of their own).</p>')
    return stats + '<ol class="lat">' + "".join(rows) + "</ol>" + note


def _changes_tile(records, h) -> str:
    if not h.has_prev:
        return ('<div class="muted">This is the first run recorded for this environment. '
                'From the next run on, new failures, failures that persist and fixes are listed here.</div>')
    by_id = {r.nodeid: r for r in records}

    def chips(ids, kind, anchor):
        out = []
        for n in sorted(ids):
            r = by_id[n]
            out.append(f'<a class="chg {kind}" href="#{anchor(r)}" title="{e(n)}">{e(_clip(r.objective, 90))}</a>')
        return "".join(out)

    cause_of = h.cause_of
    new = [n for n in h.new if n in by_id]
    still = [n for n in h.still if n in by_id]
    fixed = [n for n in h.fixed if n in by_id]
    blocks = []
    for label, ids, kind in (("New since the last run", new, "bad"),
                             ("Still failing", still, "warn"),
                             ("Fixed since the last run", fixed, "ok")):
        if ids:
            anchor = (lambda r: cause_of.get(r.nodeid, _aid("suite", r.nodeid))) if kind != "ok" \
                else (lambda r: _aid("passed", r.nodeid))
            blocks.append(f'<div class="chg-g"><h4>{label} <span class="badge badge-neutral">{len(ids)}</span></h4>'
                          f'<div class="chg-l">{chips(ids, kind, anchor)}</div></div>')
    head = f'<p class="muted small">Compared with the run of {e(_ts(h.prev_time))}.</p>'
    if not blocks:
        return head + '<div class="chg-none">' + _ico("check") + " No change in the failing checks.</div>"
    return head + "".join(blocks)


# --- page ------------------------------------------------------------------------

CSS = r"""
:root{interpolate-size:allow-keywords;color-scheme:light;
--bg:#fff;--surface:#fff;--surface-2:#f4f4f5;--line:#e4e4e7;--line-2:#d4d4d8;--text:#11181c;--body:#3f3f46;--muted:#71717a;
--accent:#006fee;--primary:#006fee;--ok:#12a150;--bad:#c20e4d;--warn:#c4841d;--suite:#7828c8;--info:#006fee;--neu:#71717a;
--ok-fill:#17c964;--bad-fill:#f31260;--warn-fill:#f5a524;
--r-s:8px;--r-m:12px;--r-l:14px;--shadow:0 4px 12px 0 rgba(0,0,0,.08);--ease:.25s ease;
--f:"Inter",ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;--fm:"JetBrains Mono",ui-monospace,Consolas,monospace;--hdr:128px}
html[data-theme=dark]{color-scheme:dark;
--bg:#000;--surface:#18181b;--surface-2:#27272a;--line:rgba(255,255,255,.12);--line-2:#3f3f46;--text:#ecedee;--body:#d4d4d8;--muted:#a1a1aa;
--accent:#338ef7;--primary:#006fee;--ok:#17c964;--bad:#f31260;--warn:#f5a524;--suite:#9353d3;--info:#338ef7;--neu:#a1a1aa;
--shadow:none;--ok-fill:#17c964;--bad-fill:#f31260;--warn-fill:#f5a524}
html[data-verdict=bad]{--glow:var(--bad);--glow-fill:var(--bad-fill)}html[data-verdict=warn]{--glow:var(--warn);--glow-fill:var(--warn-fill)}html[data-verdict=ok]{--glow:var(--ok);--glow-fill:var(--ok-fill)}
:root{--ok-s:color-mix(in srgb,var(--ok) 14%,var(--surface));--bad-s:color-mix(in srgb,var(--bad) 13%,var(--surface));
--warn-s:color-mix(in srgb,var(--warn) 15%,var(--surface));--suite-s:color-mix(in srgb,var(--suite) 14%,var(--surface));
--info-s:color-mix(in srgb,var(--info) 14%,var(--surface));--neu-s:color-mix(in srgb,var(--neu) 14%,var(--surface))}
*{box-sizing:border-box}html{scroll-behavior:smooth}html,body{margin:0}[hidden]{display:none!important}
body{background:var(--bg);color:var(--body);font:14px/1.6 var(--f);-webkit-font-smoothing:antialiased;font-feature-settings:"cv11","ss01"}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
.i{width:1em;height:1em;fill:none;stroke:currentColor;stroke-width:2.2;stroke-linecap:round;stroke-linejoin:round;flex:none;vertical-align:-.125em}
.mono{font-family:var(--fm);font-size:12px}.muted{color:var(--muted)}.small{font-size:12.5px}
::selection{background:color-mix(in srgb,var(--accent) 35%,transparent)}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:6px}

/* shell */
.side{position:fixed;inset:0 auto 0 0;width:236px;padding:20px 14px;display:flex;flex-direction:column;gap:6px;border-right:1px solid var(--line);
background:color-mix(in srgb,var(--surface) 70%,transparent);backdrop-filter:blur(16px);z-index:30}
.brand{display:flex;align-items:center;gap:11px;padding:4px 10px 18px;font:600 15px var(--f);color:var(--text);letter-spacing:-.2px}
.logo{width:30px;height:30px;border-radius:var(--r-s);display:grid;place-items:center;color:#fff;font:700 15px var(--f);
background:var(--primary)}
.nav{display:flex;flex-direction:column;gap:2px;overflow:auto}
.nav .sec{font-size:10.5px;letter-spacing:1.4px;text-transform:uppercase;color:var(--muted);padding:14px 10px 6px}
.nav a{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:7px 10px;border-radius:var(--r-s);color:var(--body);font-weight:500;font-size:13.5px;text-decoration:none;position:relative}
.nav a .l{display:flex;align-items:center;gap:10px}.nav a .i{color:var(--c,var(--muted))}
.nav a:hover{background:var(--surface-2);color:var(--text)}
.nav a.on{background:color-mix(in srgb,var(--c,var(--accent)) 12%,transparent);color:var(--text)}
.nav a.on::before{content:"";position:absolute;left:-14px;top:8px;bottom:8px;width:3px;border-radius:3px;background:var(--c,var(--accent))}
.pill{font:600 11px var(--fm);min-width:24px;text-align:center;padding:1px 7px;border-radius:999px;background:var(--surface-2);color:var(--muted)}
.nav a.has .pill{background:color-mix(in srgb,var(--c) 18%,transparent);color:var(--c)}
.keys{margin-top:auto;padding:12px 10px 0;border-top:1px solid var(--line);font-size:12px;color:var(--muted);line-height:1.9}
kbd{font:500 11px var(--fm);padding:1px 6px;border-radius:6px;border:1px solid var(--line-2);background:var(--surface);color:var(--body);border-bottom-width:2px}
.main{margin-left:236px;min-height:100vh;display:flex;flex-direction:column}
.top{position:sticky;top:0;z-index:25;padding:14px 40px 12px;border-bottom:1px solid var(--line);
background:color-mix(in srgb,var(--bg) 74%,transparent);backdrop-filter:blur(16px) saturate(1.5)}
.appver{display:inline-flex;align-items:center;gap:10px;flex-wrap:wrap;margin-left:6px;padding-left:12px;border-left:1px solid var(--line-2)}
.appver-l{color:var(--muted)}
.appver-i b{font-weight:600;font-family:var(--fm,monospace)}
.appver-current b{color:var(--ok)}
.appver-unknown b{color:var(--muted)}
.appver-ahead b{color:var(--bad-fill);text-shadow:0 0 6px var(--bad-fill),0 0 14px var(--bad-fill);animation:appverGlow 1.8s ease-in-out infinite alternate}
@keyframes appverGlow{from{text-shadow:0 0 3px var(--bad-fill),0 0 8px var(--bad-fill)}to{text-shadow:0 0 8px var(--bad-fill),0 0 20px var(--bad-fill)}}
@media (prefers-reduced-motion:reduce){.appver-ahead b{animation:none}}
.top-row{display:flex;justify-content:space-between;align-items:center;gap:14px;flex-wrap:wrap}
.top h1{margin:0;font:650 19px/1.2 var(--f);letter-spacing:-.35px;color:var(--text)}
.meta{display:flex;align-items:center;gap:10px;color:var(--muted);font-size:12.5px;flex-wrap:wrap}
.toolbar{display:flex;gap:10px;align-items:center;margin-top:12px;flex-wrap:wrap}
.search{position:relative;flex:1 1 240px;max-width:380px}
.search .i{position:absolute;left:11px;top:50%;transform:translateY(-50%);color:var(--muted)}
.search input{width:100%;height:36px;border-radius:var(--r-m);border:1px solid var(--line-2);background:var(--surface);color:var(--text);padding:0 38px 0 34px;font:inherit;font-size:13.5px}
.search input::placeholder{color:var(--muted)}.search input:focus{outline:2px solid var(--accent);outline-offset:0;border-color:transparent}
.search kbd{position:absolute;right:8px;top:50%;transform:translateY(-50%)}
.seg{display:flex;gap:2px;padding:3px;border-radius:12px;background:var(--surface-2);border:1px solid var(--line);overflow:auto;max-width:100%}
.seg button{border:0;background:transparent;color:var(--muted);font:500 12.5px var(--f);padding:5px 10px;border-radius:var(--r-s);cursor:pointer;white-space:nowrap;display:flex;gap:6px;align-items:center}
.seg button b{font:600 11px var(--fm);color:var(--c,var(--muted))}
.seg button:hover{color:var(--text)}.seg button[aria-pressed=true]{background:var(--surface);color:var(--text);box-shadow:0 1px 3px rgba(0,0,0,.18)}
.tools{display:flex;gap:8px;align-items:center;margin-left:auto;flex-wrap:wrap}
.btn{display:inline-flex;align-items:center;gap:7px;border:1px solid var(--line-2);background:var(--surface);color:var(--text);border-radius:var(--r-m);padding:6px 12px;font:500 12.5px var(--f);cursor:pointer;white-space:nowrap}
.btn:hover{border-color:var(--accent)}.btn.primary{background:var(--primary);border-color:var(--primary);color:#fff}
.btn.done{border-color:var(--ok);color:var(--ok)}
.activef{display:inline-flex;align-items:center;gap:6px;font-size:12.5px;padding:4px 6px 4px 11px;border-radius:999px;background:color-mix(in srgb,var(--accent) 14%,transparent);color:var(--text)}
.activef button{border:0;background:transparent;color:var(--muted);cursor:pointer;font-size:15px;line-height:1;padding:0 4px}
.shown{font-size:12px;color:var(--muted)}
.content{padding:36px 40px 72px;display:flex;flex-direction:column;gap:56px;flex:1;max-width:1320px;width:100%}
section,.card{scroll-margin-top:calc(var(--hdr) + 12px)}
section>h2{margin:0 0 6px;font:650 24px/1.2 var(--f);letter-spacing:-.6px;color:var(--text);display:flex;align-items:center;gap:12px}
section>h2 .h-ico{width:30px;height:30px;border-radius:var(--r-s);display:grid;place-items:center;background:color-mix(in srgb,var(--c) 16%,transparent);color:var(--c);font-size:16px}
section>p.sub{margin:0 0 20px;color:var(--muted);max-width:90ch;text-wrap:pretty}

/* bento */
.bento{display:grid;grid-template-columns:repeat(12,minmax(0,1fr));gap:16px}
.tile{background:var(--surface);border:1px solid var(--line);border-radius:var(--r-l);padding:22px;box-shadow:var(--shadow);min-width:0;container-type:inline-size}
.tile>h3{margin:0 0 14px;font:600 11px var(--f);letter-spacing:1.4px;text-transform:uppercase;color:var(--muted)}
.t-verdict{grid-column:span 8;position:relative;overflow:hidden;display:flex;flex-direction:column;justify-content:center;background:color-mix(in srgb,var(--glow) 9%,var(--surface));border-color:color-mix(in srgb,var(--glow) 30%,var(--line))}
.t-verdict .v-ico{width:46px;height:46px;border-radius:var(--r-m);display:grid;place-items:center;font-size:24px;color:#fff;background:var(--glow-fill)}
.v-head{display:flex;gap:16px;align-items:center}
.v-head h2{margin:0;font:700 clamp(22px,3.2vw,32px)/1.1 var(--f);letter-spacing:-1px;color:var(--text)}
.v-head p{margin:6px 0 0;color:var(--body);max-width:62ch;text-wrap:pretty}
.v-causes{display:flex;flex-wrap:wrap;gap:8px;margin-top:18px}
.vc{display:inline-flex;align-items:center;gap:8px;padding:7px 12px;border-radius:12px;font-size:13px;color:var(--text);background:color-mix(in srgb,var(--c) 13%,var(--surface));border:1px solid color-mix(in srgb,var(--c) 30%,transparent);text-decoration:none}
.vc .i{color:var(--c)}.vc:hover{text-decoration:none;border-color:var(--c)}.vc small{color:var(--muted)}
.t-ring{grid-column:span 4;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:10px}
.donut{width:176px;max-width:100%;height:auto;transform:rotate(-90deg)}
.donut .track{fill:none;stroke:var(--surface-2);stroke-width:12}
.donut .seg-c{fill:none;stroke-width:12;stroke-linecap:butt;stroke-dasharray:var(--len) var(--C);stroke-dashoffset:var(--off);animation:sweep .9s cubic-bezier(.2,.8,.2,1) both}
.donut text{transform:rotate(90deg);transform-origin:70px 70px;fill:var(--text)}
.donut .d-n{font:700 30px var(--f);letter-spacing:-1px}.donut .d-l{font:500 10px var(--f);fill:var(--muted);letter-spacing:1.2px;text-transform:uppercase}
@keyframes sweep{from{stroke-dasharray:0 var(--C)}}
.ring-sub{font-size:12.5px;color:var(--muted);text-align:center}.ring-sub b{color:var(--text)}
.chips{grid-column:span 12;display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:12px}
.chip{display:flex;flex-direction:column;gap:2px;align-items:flex-start;text-align:left;padding:14px 16px;border-radius:var(--r-l);border:1px solid var(--line);background:var(--surface);cursor:pointer;color:var(--body);font:inherit;box-shadow:var(--shadow);position:relative;transition:transform var(--ease),border-color var(--ease)}
.chip:hover{transform:translateY(-2px);border-color:var(--c)}
.chip .i{color:var(--c);font-size:17px}.chip .n{font:700 30px/1.1 var(--f);letter-spacing:-1px;color:var(--text);margin-top:6px}
.chip .l{font-size:12.5px;color:var(--muted)}
.chip:not(.zero){background:color-mix(in srgb,var(--c) 9%,var(--surface))}
.chip.zero .n{color:var(--muted)}.chip.zero .i{opacity:.55}
.chip[aria-pressed=true]{border-color:var(--c);box-shadow:0 0 0 3px color-mix(in srgb,var(--c) 22%,transparent)}
.t-svcs{grid-column:span 7}.t-chg{grid-column:span 5}.t-lat{grid-column:span 12}
.svcs{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:10px}
.svc{display:grid;grid-template-columns:auto 1fr;gap:2px 10px;align-items:center;text-align:left;padding:10px 12px;border-radius:var(--r-m);border:1px solid var(--line);background:var(--surface-2);cursor:pointer;color:var(--body);font:inherit}
.svc:hover{border-color:var(--c)}.svc[aria-pressed=true]{border-color:var(--c);box-shadow:0 0 0 3px color-mix(in srgb,var(--c) 22%,transparent)}
.svc.ok{--c:var(--ok)}.svc.warn{--c:var(--warn)}.svc.bad{--c:var(--bad)}
.svc.bad{background:var(--bad-s)}.svc.warn{background:var(--warn-s)}
.svc-dot{grid-row:span 2;width:26px;height:26px;border-radius:50%;display:grid;place-items:center;font-size:13px;color:var(--c);background:color-mix(in srgb,var(--c) 18%,transparent);position:relative}
.svc.bad .svc-dot::after{content:"";position:absolute;inset:-4px;border-radius:50%;border:2px solid var(--bad);opacity:.5;animation:pulse 2s ease-out infinite}
@keyframes pulse{from{transform:scale(.8);opacity:.7}to{transform:scale(1.35);opacity:0}}
.svc-t{font-weight:600;color:var(--text);font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.svc-m{font-size:11.5px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;grid-column:2}
.chg-g+.chg-g{margin-top:14px}.chg-g h4{margin:0 0 8px;font:600 12px var(--f);color:var(--text);display:flex;gap:8px;align-items:center}
.chg-l{display:flex;flex-direction:column;gap:6px}
.chg{display:block;padding:7px 11px;border-radius:var(--r-m);font-size:13px;color:var(--text);border:1px solid var(--line);border-left:3px solid var(--c);background:var(--surface-2)}
.chg.bad{--c:var(--bad)}.chg.warn{--c:var(--warn)}.chg.ok{--c:var(--ok)}.chg:hover{text-decoration:none;background:color-mix(in srgb,var(--c) 12%,var(--surface))}
.chg-none{display:flex;gap:8px;align-items:center;color:var(--ok);font-weight:500}
.l-stats{display:flex;gap:28px;flex-wrap:wrap;margin-bottom:16px}.l-stats b{display:block;font:700 22px/1.1 var(--f);letter-spacing:-.6px;color:var(--text)}
.l-stats span{font-size:11.5px;color:var(--muted)}
.lat{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:8px}
.lat li{display:grid;grid-template-columns:minmax(0,38%) 1fr 70px;gap:14px;align-items:center}
.l-u{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--body)}
.l-b{height:8px;border-radius:99px;background:var(--surface-2);overflow:hidden}.l-b i{display:block;height:100%;border-radius:99px;background:var(--primary)}
.lat li.slow .l-b i{background:var(--warn-fill)}.lat li.slow .l-v{color:var(--warn);font-weight:600}
.l-v{text-align:right;color:var(--text)}

/* cards */
.card{--st:var(--neu);background:var(--surface);border:1px solid var(--line);border-radius:var(--r-l);margin-bottom:12px;overflow:hidden;box-shadow:var(--shadow);transition:border-color var(--ease)}
.card[data-status=failed]{--st:var(--bad)}.card[data-status=unused]{--st:var(--warn)}.card[data-status=suite]{--st:var(--suite)}
.card[data-status=known]{--st:var(--info)}.card[data-status=passed]{--st:var(--ok)}.card[data-status=skipped]{--st:var(--neu)}
.card[data-status]{box-shadow:inset 3px 0 0 var(--st),var(--shadow)}.card:hover{border-color:var(--line-2)}
.card.flash{animation:flash 1.6s ease-out}@keyframes flash{from{box-shadow:inset 3px 0 0 var(--st),0 0 0 4px color-mix(in srgb,var(--st) 40%,transparent)}}
.card-h{display:flex;align-items:flex-start;gap:12px;padding:15px 20px;flex-wrap:wrap}
details.card>summary,details.group>summary{list-style:none;cursor:pointer;color:var(--text)}
details.card>summary::-webkit-details-marker,details.group>summary::-webkit-details-marker{display:none}
.cause .card-h{background:color-mix(in srgb,var(--bad) 7%,transparent)}
.cause.noimpact .card-h{background:color-mix(in srgb,var(--warn) 8%,transparent)}
.issue .card-h{background:color-mix(in srgb,var(--suite) 7%,transparent)}
.st-ico{width:28px;height:28px;border-radius:var(--r-s);display:grid;place-items:center;font-size:14px;color:var(--st,var(--ok));background:color-mix(in srgb,var(--st,var(--ok)) 15%,transparent);flex:none}
.st-ico.ok{--st:var(--ok)}
.hm{flex:1;min-width:0}.hm h3{margin:0;font:600 15px/1.35 var(--f);letter-spacing:-.2px;color:var(--text)}
.eyebrow{font-size:10.5px;letter-spacing:1.3px;text-transform:uppercase;color:var(--muted);margin-bottom:2px}
.sum{margin-top:3px;font-size:12.8px;color:var(--muted);display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}.sum b{color:var(--body);font-weight:600}
.chev{margin-top:6px;color:var(--muted);font-size:13px;transition:transform var(--ease)}
details[open]>summary>.chev{transform:rotate(90deg)}
.badges{display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end;align-items:center;margin-left:auto}
.badge{display:inline-block;font:600 11px var(--fm);padding:2px 9px;border-radius:999px;white-space:nowrap}
.badge-success{background:var(--ok-s);color:var(--ok)}.badge-danger{background:var(--bad-s);color:var(--bad)}
.badge-warning{background:var(--warn-s);color:var(--warn)}.badge-suite{background:var(--suite-s);color:var(--suite)}
.badge-info{background:var(--info-s);color:var(--info)}.badge-neutral{background:var(--neu-s);color:var(--neu)}
.badge-primary{background:var(--primary);color:#fff;letter-spacing:1.2px;text-transform:uppercase;font-family:var(--f);font-weight:700}

section>h2 .badge{font-size:12px;padding:3px 11px}
.card-b{padding:6px 22px 22px;border-top:1px solid var(--line)}
.card-b.p0{padding:0;overflow-x:auto;border:0}
.facts{display:grid;grid-template-columns:132px 1fr;gap:7px 18px;margin:16px 0 4px}
.facts dt{color:var(--muted)}.facts dd{margin:0;word-break:break-word;color:var(--text)}
.block{margin-top:16px}.block h4,h4.mt{margin:0 0 5px;font:600 11px var(--f);text-transform:uppercase;letter-spacing:1.3px;color:var(--muted)}
h4.mt{margin:24px 0 10px}.block p{margin:0;max-width:80ch;text-wrap:pretty}
.impact p.il{margin:12px 0 2px;font-size:12.5px;color:var(--text)}.impact ul{margin:2px 0 0;padding-left:20px;max-width:80ch}.impact li{margin:3px 0;line-height:1.5}.impact li i{color:var(--muted)}
details.block>summary{cursor:pointer;font:600 13px var(--f);color:var(--accent)}
pre{margin:8px 0 0;padding:14px 16px;background:var(--surface-2);color:var(--text);border-radius:var(--r-m);border:1px solid var(--line);font:12px/1.6 var(--fm);white-space:pre-wrap;word-break:break-word;max-height:320px;overflow:auto}
.ev-label{margin-top:12px;font-size:12px;color:var(--muted)}
.tbl{width:100%;border-collapse:collapse}
.tbl th{text-align:left;font:600 10.5px var(--f);text-transform:uppercase;letter-spacing:1.3px;color:var(--muted);background:var(--surface-2);padding:9px 16px;border-bottom:1px solid var(--line)}
.tbl td{padding:10px 16px;border-bottom:1px solid var(--line);vertical-align:top}
.tbl tr:last-child td{border-bottom:none}.tbl .num{text-align:right;white-space:nowrap;font-family:var(--fm);font-size:12px}
.card-b>.tbl,details.block>.tbl{border:1px solid var(--line);border-radius:12px;overflow:hidden;margin-top:6px}
.tbl-compact td,.tbl-compact th{padding:7px 14px}.url{word-break:break-all}
.card-b.p0 .tbl td:first-child,.card-b.p0 .tbl th:first-child{padding-left:20px}
.t-obj{font-weight:500;color:var(--text)}.t-id{color:var(--muted);font-size:11px;margin-top:2px;word-break:break-all}.t-hint{color:var(--info);margin-top:4px}
.copy{border:1px solid var(--line-2);background:var(--surface);color:var(--text);border-radius:var(--r-s);padding:4px 11px;font:500 12px var(--f);cursor:pointer;white-space:nowrap}
.copy:hover{border-color:var(--accent);color:var(--accent)}.copy.done{color:var(--ok);border-color:var(--ok)}
.card-actions{margin-top:18px;padding-top:14px;border-top:1px dashed var(--line);display:flex;justify-content:flex-end}
.empty,.nomatch{background:var(--surface);border:1px dashed var(--line-2);border-radius:var(--r-l);padding:26px;color:var(--muted);font-weight:500;text-align:center}
.empty{color:var(--ok)}.nomatch{margin-top:8px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px}.grid2 .card{margin:0}
.grid2 .card-h{padding:14px 20px;border-bottom:1px solid var(--line)}.grid2 .card-h h3{font-size:14px}
.grid2 .card .sub{margin:0}

/* passed groups */
details.group{border:1px solid var(--line);border-radius:var(--r-l);background:color-mix(in srgb,var(--surface) 70%,transparent);margin-bottom:10px;overflow:hidden}
details.group>summary{display:flex;align-items:center;gap:12px;padding:12px 18px}
details.group>summary:hover{background:var(--surface-2)}
.g-title{font-weight:600;color:var(--text);flex:1}.g-count{font:600 11px var(--fm);color:var(--ok);background:var(--ok-s);padding:2px 9px;border-radius:99px}
.g-meta{font-size:12px;color:var(--muted);min-width:170px;text-align:right}
.g-body{padding:4px 14px 6px 14px;border-top:1px solid var(--line)}.g-body .card{margin:10px 0}
.g-body .card[data-status]{box-shadow:inset 3px 0 0 var(--st)}
details.group>summary .chev{margin-top:0}

@supports selector(::details-content){
details.card::details-content,details.group::details-content,details.block::details-content{block-size:0;overflow:clip;transition:block-size var(--ease),content-visibility var(--ease) allow-discrete}
details.card[open]::details-content,details.group[open]::details-content,details.block[open]::details-content{block-size:auto}}
@supports (animation-timeline:view()){
section>h2,.bento>*{animation:rise linear both;animation-timeline:view();animation-range:entry 0% entry 35%}
@keyframes rise{from{opacity:0;transform:translateY(14px)}}}

.foot{padding:26px 40px;color:var(--muted);font-size:12.5px;border-top:1px solid var(--line)}
.bnav{display:none}

@media (max-width:1180px){.t-verdict,.t-ring,.t-svcs,.t-chg{grid-column:span 12}.t-ring{flex-direction:row;justify-content:flex-start;gap:28px}.chips{grid-template-columns:repeat(3,1fr)}.grid2{grid-template-columns:1fr}}
@media (max-width:920px){:root{--hdr:12px}.top{position:static}.side{display:none}.main{margin-left:0}.top,.content,.foot{padding-left:16px;padding-right:16px}.top{padding-top:10px}
.bnav{display:flex;position:fixed;left:10px;right:10px;bottom:10px;z-index:40;gap:2px;padding:6px;border-radius:18px;background:color-mix(in srgb,var(--surface) 82%,transparent);backdrop-filter:blur(18px);border:1px solid var(--line-2);box-shadow:0 12px 36px -8px rgba(0,0,0,.45)}
.bnav a{flex:1;display:flex;flex-direction:column;align-items:center;gap:1px;padding:6px 2px;border-radius:12px;font-size:10.5px;color:var(--muted);text-decoration:none}
.bnav a .i{font-size:17px;color:var(--c,var(--muted))}.bnav a b{font:600 10px var(--fm);color:var(--text)}
.content{padding-bottom:110px}.keys-hint{display:none}.top h1{font-size:16px}.tools{margin-left:0}
.g-meta{display:none}.lat li{grid-template-columns:1fr 60px}.lat .l-b{display:none}.facts{grid-template-columns:1fr}.chips{grid-template-columns:repeat(2,1fr)}}
@media (prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition:none!important;scroll-behavior:auto!important}}
@media print{.side,.top,.bnav,.copy,.card-actions{display:none!important}.main{margin-left:0}body{background:#fff}.content{max-width:none;padding:0}.card,.tile{box-shadow:none;break-inside:avoid}}
"""

JS = r"""
(function(){
var root=document.documentElement,KEY='agenthub-health-theme';
var mq=window.matchMedia?window.matchMedia('(prefers-color-scheme: dark)'):null;
var reduce=window.matchMedia&&window.matchMedia('(prefers-reduced-motion: reduce)').matches;
function pref(){var v=null;try{v=localStorage.getItem(KEY);}catch(e){}return v==='light'||v==='dark'?v:'system';}
function applyTheme(p){var t=p==='system'?(mq&&mq.matches?'dark':'light'):p;root.setAttribute('data-theme',t);root.setAttribute('data-pref',p);
  var b=document.getElementById('themeBtn');if(b){b.querySelector('use').setAttribute('href','#i-'+(p==='system'?'monitor':p==='dark'?'moon':'sun'));b.querySelector('.t').textContent=p==='system'?'Auto':p==='dark'?'Dark':'Light';}}
applyTheme(pref());
if(mq&&mq.addEventListener){mq.addEventListener('change',function(){if(pref()==='system'){applyTheme('system');}});}
window.cycleTheme=function(){var o=['system','light','dark'],n=o[(o.indexOf(pref())+1)%3];
  var run=function(){try{localStorage.setItem(KEY,n);}catch(e){}applyTheme(n);};
  if(document.startViewTransition&&!reduce){document.startViewTransition(run);}else{run();}};

/* ---- Teams / Markdown text from a card ---- */
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function txt(el){return esc(el.textContent.replace(/\s+/g,' ').trim());}
function cell(el){var parts=[];Array.from(el.childNodes).forEach(function(n){var t=n.textContent.replace(/\s+/g,' ').trim();if(t){parts.push(esc(t));}});return parts.join('<br>');}
function tableHtml(t){var rows=Array.from(t.querySelectorAll('tr')).map(function(tr){return '<tr>'+Array.from(tr.children).map(function(td){var th=td.tagName==='TH';return (th?'<th>':'<td>')+cell(td)+(th?'</th>':'</td>');}).join('')+'</tr>';}).join('');return '<table border="1" cellpadding="4" cellspacing="0">'+rows+'</table>';}
/* Inline text with its bold and italic kept - the only two styles used in the Teams copy (plus regular). */
function inl(el){var o='';Array.from(el.childNodes).forEach(function(n){
  if(n.nodeType===3){o+=esc(n.textContent.replace(/\s+/g,' '));}
  else if(n.nodeType===1){var t=n.tagName;
    if(t==='B'||t==='STRONG'){o+='<b>'+inl(n)+'</b>';}
    else if(t==='I'||t==='EM'){o+='<i>'+inl(n)+'</i>';}
    else if(t==='BR'){o+='<br>';}
    else{o+=inl(n);}}});
  return o.trim();}
function walk(el,out){Array.from(el.children).forEach(function(c){
  if(c.tagName==='SUMMARY'||c.classList.contains('card-actions')){return;}
  if(c.tagName==='DL'){var kids=Array.from(c.children);for(var i=0;i+1<kids.length;i+=2){out.push('<p><b>'+txt(kids[i])+':</b> '+cell(kids[i+1])+'</p>');}}
  else if(c.tagName==='H4'){out.push('<p><b>'+txt(c)+'</b></p>');}
  else if(c.tagName==='P'){out.push('<p>'+inl(c)+'</p>');}
  else if(c.tagName==='UL'){out.push('<ul>'+Array.from(c.children).map(function(li){return '<li>'+inl(li)+'</li>';}).join('')+'</ul>');}
  else if(c.tagName==='PRE'){out.push('<pre>'+esc(c.textContent)+'</pre>');}
  else if(c.tagName==='TABLE'){out.push(tableHtml(c));}
  else if(c.tagName==='DETAILS'){var s=c.querySelector('summary');if(s){out.push('<p><b>'+txt(s)+'</b></p>');}walk(c,out);}
  else if(c.classList.contains('ev-label')){out.push('<p><i>'+txt(c)+'</i></p>');}
  else {walk(c,out);}
});}
function teamsHtml(card){
  var out=[];
  var eyebrow=card.querySelector('summary .eyebrow');
  if(eyebrow){out.push('<p><b>'+txt(eyebrow)+'</b></p>');}
  out.push('<p><b>'+txt(card.querySelector('summary h3'))+'</b></p>');
  var badges=Array.from(card.querySelectorAll('summary .badges .badge')).map(txt).join(' | ');
  if(badges){out.push('<p>'+badges+'</p>');}
  var body=card.querySelector(':scope > .card-b');
  if(body){walk(body,out);}
  return out.join('');
}
function copyHtml(html,btn,label){
  var box=document.createElement('div');
  box.contentEditable='true';box.style.position='fixed';box.style.left='-10000px';
  box.innerHTML=html;
  document.body.appendChild(box);
  var range=document.createRange();range.selectNodeContents(box);
  var sel=window.getSelection();sel.removeAllRanges();sel.addRange(range);
  var ok=false;try{ok=document.execCommand('copy');}catch(err){}
  sel.removeAllRanges();box.remove();
  flash(btn,ok,label);
}
function flash(btn,ok,label){btn.textContent=ok?'Copied':'Copy failed';btn.classList.toggle('done',ok);
  setTimeout(function(){btn.textContent=label;btn.classList.remove('done');},1800);}
window.copyCard=function(btn){copyHtml(teamsHtml(btn.closest('details')),btn,'Copy for Teams');};
function mdt(el){return el.textContent.replace(/\s+/g,' ').trim();}
function mdCell(c){var parts=[];Array.from(c.childNodes).forEach(function(n){var t=n.textContent.replace(/\s+/g,' ').trim();if(t){parts.push(t.replace(/\|/g,'\\|'));}});return parts.join('<br>');}
function mdTable(t){var rows=Array.from(t.querySelectorAll('tr')).map(function(tr){return '| '+Array.from(tr.children).map(mdCell).join(' | ')+' |';});
  if(rows.length>1){rows.splice(1,0,'|'+' --- |'.repeat(t.querySelector('tr').children.length));}return rows.join('\n');}
function mdi(el){var o='';Array.from(el.childNodes).forEach(function(n){
  if(n.nodeType===3){o+=n.textContent.replace(/\s+/g,' ');}
  else if(n.nodeType===1){var t=n.tagName;
    if(t==='B'||t==='STRONG'){o+='**'+mdi(n).trim()+'**';}
    else if(t==='I'||t==='EM'){o+='_'+mdi(n).trim()+'_';}
    else{o+=mdi(n);}}});
  return o.replace(/\s+/g,' ').trim();}
function mdWalk(el,out){Array.from(el.children).forEach(function(c){
  if(c.tagName==='SUMMARY'||c.classList.contains('card-actions')){return;}
  if(c.tagName==='DL'){var k=Array.from(c.children);for(var i=0;i+1<k.length;i+=2){out.push('- **'+mdt(k[i])+':** '+mdt(k[i+1]));}out.push('');}
  else if(c.tagName==='H4'){out.push('**'+mdt(c)+'**');}
  else if(c.tagName==='P'){out.push(mdi(c),'');}
  else if(c.tagName==='UL'){Array.from(c.children).forEach(function(li){out.push('- '+mdi(li));});out.push('');}
  else if(c.tagName==='PRE'){out.push('```',c.textContent.replace(/\s+$/,''),'```','');}
  else if(c.tagName==='TABLE'){out.push(mdTable(c),'');}
  else if(c.tagName==='DETAILS'){var s=c.querySelector('summary');if(s){out.push('**'+mdt(s)+'**');}mdWalk(c,out);}
  else if(c.classList.contains('ev-label')){out.push('_'+mdt(c)+'_');}
  else {mdWalk(c,out);}
});}
function mdCard(card){
  var out=[],ey=card.querySelector('summary .eyebrow');
  if(ey){out.push('_'+mdt(ey)+'_');}
  out.push('### '+mdt(card.querySelector('summary h3')));
  var b=Array.from(card.querySelectorAll('summary .badges .badge')).map(mdt).join(' · ');
  if(b){out.push(b,'');}
  var body=card.querySelector(':scope > .card-b');if(body){mdWalk(body,out);}
  return out.join('\n');
}
function copyText(text,btn,label){
  var done=function(ok){flash(btn,ok,label);};
  if(navigator.clipboard&&window.isSecureContext){navigator.clipboard.writeText(text).then(function(){done(true);},function(){fallback();});}else{fallback();}
  function fallback(){var ta=document.createElement('textarea');ta.value=text;ta.style.position='fixed';ta.style.left='-10000px';document.body.appendChild(ta);ta.select();var ok=false;try{ok=document.execCommand('copy');}catch(e){}ta.remove();done(ok);}
}
window.copyMarkdown=function(btn){copyText(mdCard(btn.closest('details')),btn,'Copy as Markdown');};
window.copyFailures=function(btn){
  var m=document.getElementById('report-meta').dataset;
  var cards=Array.from(document.querySelectorAll('#failed details.cause'));var heading='Failed checks';
  if(!cards.length){cards=Array.from(document.querySelectorAll('#unused details.cause'));heading='Failed, no effect on the app';}
  var html='<p><b>AgentHubNext dependency health – '+esc(m.env)+' – '+esc(m.time)+'</b></p><p>'+esc(m.verdict)+'</p>';
  if(cards.length){html+='<p><b>'+heading+'</b></p>'+cards.map(teamsHtml).join('<hr>');}
  copyHtml(html,btn,'Copy failures for Teams');
};

/* ---- filtering ---- */
var state={status:'all',q:'',svc:''};
function cards(){return Array.from(document.querySelectorAll('details.card[data-status]'));}
function visibleCards(){return cards().filter(function(c){return !c.hidden&&!c.closest('[hidden]');});}
function pushState(){try{var p=new URLSearchParams();if(state.status!=='all')p.set('status',state.status);if(state.q)p.set('q',state.q);if(state.svc)p.set('service',state.svc);
  var s=p.toString();history.replaceState(null,'',location.pathname+(s?'?'+s:'')+location.hash);}catch(e){}}
function applyFilter(){
  var q=state.q.trim().toLowerCase(),svc=state.svc,filtering=!!(q||svc||state.status!=='all');
  cards().forEach(function(c){
    var ok=(state.status==='all'||c.dataset.status===state.status)&&(!svc||(' '+c.dataset.service+' ').indexOf(' '+svc+' ')>-1)&&(!q||c.dataset.search.indexOf(q)>-1);
    c.hidden=!ok;});
  document.querySelectorAll('details.group').forEach(function(g){
    var n=g.querySelectorAll('details.card:not([hidden])').length;g.hidden=n===0;
    if((q||svc)&&n>0){g.open=true;}});
  document.querySelectorAll('section[data-status]').forEach(function(s){
    var all=s.querySelectorAll('details.card[data-status]'),vis=s.querySelectorAll('details.card[data-status]:not([hidden])');
    s.hidden=state.status!=='all'&&s.dataset.status!==state.status;
    var nm=s.querySelector('.nomatch');if(nm){nm.hidden=!(all.length>0&&vis.length===0);}
    var b=s.querySelector('h2 .badge');if(b){var t=b.dataset.total;b.textContent=(filtering&&vis.length!==all.length)?vis.length+' of '+t:t;}
    var ph=s.querySelector('.sub');});
  document.querySelectorAll('[data-status-btn]').forEach(function(b){b.setAttribute('aria-pressed',String(b.dataset.statusBtn===state.status));});
  document.querySelectorAll('.svc').forEach(function(b){b.setAttribute('aria-pressed',String(b.dataset.svc===state.svc));});
  var af=document.getElementById('activef');
  if(af){af.hidden=!state.svc;if(state.svc){af.querySelector('span').textContent='Service: '+(document.querySelector('.svc[data-svc="'+state.svc+'"] .svc-t')||{textContent:state.svc}).textContent;}}
  var sh=document.getElementById('shown');if(sh){var v=visibleCards().length;sh.textContent=filtering?(v+' of '+cards().length+' checks shown'):'';}
  pushState();
}
window.setStatus=function(s,scroll){state.status=(state.status===s&&s!=='all'&&scroll===false)?'all':s;applyFilter();
  if(scroll!==false){var t=s==='all'?document.getElementById('failed'):document.getElementById(s);if(t&&!t.hidden){t.scrollIntoView({block:'start'});}}};
window.setService=function(k){state.svc=state.svc===k?'':k;applyFilter();if(state.svc){var t=document.getElementById('failed');if(t){}}};
window.clearFilters=function(){state={status:'all',q:'',svc:''};document.getElementById('q').value='';applyFilter();};
window.toggleAll=function(open){document.querySelectorAll('details.card[data-status],details.group,details.card[data-status] details.block').forEach(function(d){d.open=open;});};

/* ---- links to cards, scroll-spy, keyboard, print ---- */
function openTarget(){
  var id=decodeURIComponent(location.hash.slice(1));if(!id){return;}
  var el=document.getElementById(id);if(!el){return;}
  if(el.hidden||el.closest('[hidden]')){window.clearFilters();}
  for(var d=el;d;d=d.parentElement){if(d.tagName==='DETAILS'){d.open=true;}}
  if(el.classList.contains('card')){el.scrollIntoView({block:'start'});el.classList.remove('flash');void el.offsetWidth;el.classList.add('flash');}
}
window.addEventListener('hashchange',openTarget);
function spy(){
  var links={};document.querySelectorAll('.nav a[href^="#"]').forEach(function(a){links[a.getAttribute('href').slice(1)]=a;});
  if(!('IntersectionObserver' in window)){return;}
  var io=new IntersectionObserver(function(es){es.forEach(function(en){if(en.isIntersecting){Object.keys(links).forEach(function(k){links[k].classList.toggle('on',k===en.target.id);});}});},{rootMargin:'-22% 0px -65% 0px'});
  document.querySelectorAll('main section[id]').forEach(function(s){io.observe(s);});
}
function focusCard(i){var v=visibleCards();if(!v.length){return;}i=Math.max(0,Math.min(v.length-1,i));var s=v[i].querySelector('summary');s.focus({preventScroll:true});v[i].scrollIntoView({block:'center'});}
document.addEventListener('keydown',function(ev){
  var q=document.getElementById('q'),tag=(ev.target.tagName||'').toLowerCase();
  if((ev.key==='k'&&(ev.ctrlKey||ev.metaKey))||(ev.key==='/'&&tag!=='input'&&tag!=='textarea')){ev.preventDefault();q.focus();q.select();return;}
  if(ev.key==='Escape'&&ev.target===q){if(q.value){q.value='';state.q='';applyFilter();}else{q.blur();}return;}
  if(tag==='input'||tag==='textarea'||ev.ctrlKey||ev.metaKey||ev.altKey){return;}
  var v=visibleCards(),cur=v.indexOf(document.activeElement&&document.activeElement.closest?document.activeElement.closest('details.card[data-status]'):null);
  if(ev.key==='j'){ev.preventDefault();focusCard(cur+1);}
  else if(ev.key==='k'){ev.preventDefault();focusCard(cur<0?0:cur-1);}
  else if(ev.key==='e'&&cur>-1){ev.preventDefault();v[cur].open=!v[cur].open;}
});
var wasOpen=[];
window.addEventListener('beforeprint',function(){wasOpen=Array.from(document.querySelectorAll('details')).filter(function(d){return d.open;});document.querySelectorAll('details').forEach(function(d){d.open=true;});});
window.addEventListener('afterprint',function(){document.querySelectorAll('details').forEach(function(d){d.open=wasOpen.indexOf(d)>-1;});});

document.addEventListener('DOMContentLoaded',function(){
  applyTheme(pref());
  var p=new URLSearchParams(location.search);
  state.status=p.get('status')||'all';state.q=p.get('q')||'';state.svc=p.get('service')||'';
  var q=document.getElementById('q');q.value=state.q;
  var t=null;q.addEventListener('input',function(){clearTimeout(t);t=setTimeout(function(){state.q=q.value;applyFilter();},90);});
  applyFilter();spy();openTarget();
});
})();
"""

_ICONS = """<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs>
<symbol id="i-check" viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5"/></symbol>
<symbol id="i-x" viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></symbol>
<symbol id="i-minus" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M8 12h8"/></symbol>
<symbol id="i-alert" viewBox="0 0 24 24"><path d="M12 4l9 16H3z"/><path d="M12 10v4M12 17.2v.1"/></symbol>
<symbol id="i-info" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 7.8v.1"/></symbol>
<symbol id="i-skip" viewBox="0 0 24 24"><path d="M6 5l9 7-9 7z"/><path d="M19 5v14"/></symbol>
<symbol id="i-chev" viewBox="0 0 24 24"><path d="M9 6l6 6-6 6"/></symbol>
<symbol id="i-search" viewBox="0 0 24 24"><circle cx="11" cy="11" r="6.5"/><path d="M16 16l4 4"/></symbol>
<symbol id="i-sun" viewBox="0 0 24 24"><circle cx="12" cy="12" r="4"/><path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6L7 7M17 17l1.4 1.4M5.6 18.4L7 17M17 7l1.4-1.4"/></symbol>
<symbol id="i-moon" viewBox="0 0 24 24"><path d="M20 14.5A8 8 0 019.5 4 8 8 0 1020 14.5z"/></symbol>
<symbol id="i-monitor" viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/></symbol>
<symbol id="i-run" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></symbol>
<symbol id="i-grid" viewBox="0 0 24 24"><rect x="4" y="4" width="7" height="7" rx="1.5"/><rect x="13" y="4" width="7" height="7" rx="1.5"/><rect x="4" y="13" width="7" height="7" rx="1.5"/><rect x="13" y="13" width="7" height="7" rx="1.5"/></symbol>
<symbol id="i-copy" viewBox="0 0 24 24"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 012-2h9"/></symbol>
</defs></svg>"""


def render(records, collection_issues, meta) -> str:
    settings.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    # Golden scenario replays have a section of their own (report_golden); they are not health checks.
    golden_records = [r for r in records if "golden" in r.markers]
    records = [r for r in records if "golden" not in r.markers]
    cat = defaultdict(list)
    for r in records:
        cat[r.category].append(r)
    passed, failed, suite, unused = cat["passed"], cat["failed"], cat["suite"], cat["unused"]
    skipped, known, fixed = cat["skipped"], cat["known"], cat["known_fixed"]
    n_suite = len(suite) + len(collection_issues)
    total = len(records)
    n_passed, n_known = len(passed) + len(fixed), len(known) + len(fixed)

    h = _compare(records, meta["environment"])
    failed_groups = _group_causes(failed, "cause-")
    unused_groups = _group_causes(unused, "cause-u")
    h.cause_of = {r.nodeid: cid for groups in (failed_groups, unused_groups) for g, cid in groups for r in g}
    root_causes = len(failed_groups)

    if failed:
        verdict = ("bad", "AgentHubNext is affected", "x",
                   f"{len(failed)} check(s) failed across {root_causes} root cause(s). "
                   "AgentHubNext is affected - see Failed checks.")
    elif unused:
        verdict = ("warn", "No impact on AgentHubNext", "minus",
                   f"Nothing AgentHubNext uses today has failed. {len(unused)} check(s) failed on "
                   "things the app does not use - see Failed, no effect on the app.")
    elif n_suite:
        verdict = ("warn", "Some checks could not run", "alert",
                   f"No dependency failures, but {n_suite} check(s) could not run. "
                   "See Suite issues before trusting this result.")
    else:
        verdict = ("ok", "Everything is healthy", "check", "Every executed check passed.")

    counts = {"failed": len(failed), "unused": len(unused), "suite": n_suite, "known": n_known,
              "passed": n_passed, "skipped": len(skipped)}
    colour = {k: c for k, _l, c, _i in STATUSES}
    label = {k: l for k, l, _c, _i in STATUSES}
    icon = {k: i for k, _l, _c, i in STATUSES}
    pct = round(100 * n_passed / total) if total else 0
    donut = _donut([(n_passed, "--ok"), (len(failed), "--bad"), (len(unused), "--warn"), (n_suite, "--suite"),
                    (len(known), "--info"), (len(skipped), "--neu")], total, pct)

    cause_chips = "".join(
        f'<a class="vc" style="--c:var({"--warn" if cid.startswith("cause-u") else "--bad"})" href="#{cid}">'
        f'{_ico("minus" if cid.startswith("cause-u") else "x")}<span>{e(g[0].failure.get("title", "Check failed"))}'
        f' <small>{e(g[0].failure.get("service", ""))}</small></span></a>'
        for g, cid in (failed_groups[:4] + (unused_groups[:3] if not failed_groups else [])))

    chips = "".join(
        f'<button type="button" class="chip{" zero" if not counts[k] else ""}" data-status-btn="{k}" aria-pressed="false" '
        f'style="--c:var({colour[k]})" onclick="setStatus(\'{k}\')">{_ico(icon[k])}<span class="n">{counts[k]}</span>'
        f'<span class="l">{label[k]}</span></button>' for k, *_ in STATUSES)

    seg = (f'<button type="button" data-status-btn="all" aria-pressed="true" onclick="setStatus(\'all\',false)">All <b>{total}</b></button>'
           + "".join(f'<button type="button" data-status-btn="{k}" aria-pressed="false" style="--c:var({colour[k]})" '
                     f'onclick="setStatus(\'{k}\',false)">{label[k]} <b>{counts[k]}</b></button>' for k, *_ in STATUSES))

    def nav(key, text):
        n = counts[key]
        return (f'<a href="#{key}" class="{"has" if n and key not in ("passed", "skipped", "known") else ""}" style="--c:var({colour[key]})">'
                f'<span class="l">{_ico(icon[key])}{text}</span><span class="pill">{n}</span></a>')

    bnav = "".join(f'<a href="#{k}" style="--c:var({colour[k]})">{_ico(icon[k])}<b>{counts[k]}</b>{t}</a>'
                   for k, t in (("failed", "Failed"), ("unused", "No effect"), ("passed", "Passed"), ("known", "Known")))
    bnav = f'<a href="#overview" style="--c:var(--accent)">{_ico("grid")}<b>&nbsp;</b>Overview</a>' + bnav

    duration = _dur(meta["finished"] - meta["started"]) if meta["started"] else "-"
    urls = "".join(f"<tr><td class='mono'>{e(k)}</td><td class='mono url'>{e(v or '(not set)')}</td></tr>"
                   for k, v in meta["base_urls"].items())
    usage_rows = "".join(
        f"<tr><td class='mono'>{e(u['service'])}</td><td>{_badge('used' if u['used'] else 'not used', 'success' if u['used'] else 'neutral')}"
        f"</td><td>{e(u['why'])}</td></tr>" for u in meta.get("service_usage", []))
    rc_rows = "".join(
        f"<tr><td class='mono'>/api/{e(c['entity'])}</td><td>"
        f"{_badge(c['source'], 'success' if c['source'].startswith('downloaded') else 'warning' if c['source'].startswith('snapshot') else 'danger')}"
        f"</td></tr>" for c in meta.get("remote_config", []))

    def section(key, title, sub, body, count):
        return f"""
    <section id="{key}" data-status="{key}">
      <h2><span class="h-ico" style="--c:var({colour[key]})">{_ico(icon[key])}</span>{title} <span class="badge badge-{ {'failed': 'danger', 'unused': 'warning', 'suite': 'suite', 'known': 'info', 'passed': 'success', 'skipped': 'neutral'}[key] }" data-total="{count}">{count}</span></h2>
      <p class="sub">{sub}</p>
      {body}
      <div class="nomatch" hidden>No check in this section matches the current search or filter.</div>
    </section>"""

    sections = "".join([
        section("failed", "Failed checks",
                "A dependency of AgentHubNext did not behave as the application requires. Checks that failed for the same reason are grouped under one root cause, largest first. Every explanation is derived from the HTTP answer, transport error or configuration value this run observed.",
                _failed_section(failed_groups, h, records=records), len(failed)),
        section("unused", "Failed, no effect on the app",
                "These checks failed, but on something AgentHubNext does not use today - an MCP server no agent is assigned, an endpoint no code path calls, or a setting the app ignores. Each card names the reason. They become real failures the moment the app starts using them.",
                _failed_section(unused_groups, h, "None."), len(unused)),
        section("suite", "Suite issues",
                "Problems with the test suite itself: a check could not run, or its code raised an unexpected error. These say nothing about the services - fix them before trusting the rest of the report.",
                _suite_section(suite, collection_issues), n_suite),
        section("known", "Known issues",
                'Defects already identified in the configuration, tracked as expected failures. A check marked "fixed" now passes and its expected-failure marker can be removed.',
                _check_list(known + fixed, "known", h), n_known),
        section("passed", "Passed checks",
                "Grouped by area; open an area to see its checks. Service latency is the time each request made by the check took.",
                _passed_groups(passed + fixed, h), n_passed),
        section("skipped", "Skipped",
                "Checks that did not apply to this run, with the reason each one names.",
                _check_list(skipped, "skipped", h), len(skipped)),
    ])

    golden_rows = meta.get("golden") or []
    golden_html = report_golden.section(golden_rows, golden_records) if golden_rows else ""
    golden_nav = (f'<div class="sec">Golden set</div><a href="#golden" style="--c:var(--accent)"><span class="l">'
                  f'{_ico("grid")}Golden scenarios</span><span class="pill">{len(golden_rows)}</span></a>'
                  if golden_rows else "")

    all_requests = "".join(
        f'<div class="t-obj" style="margin-top:14px">{e(r.objective)}</div><div class="t-id mono">{e(r.nodeid)}</div>{_probe_rows(r.probes)}'
        for r in records if r.probes)

    doc = f"""<!doctype html>
<html lang="en" data-theme="dark" data-verdict="{verdict[0]}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark light">
<title>AgentHubNext Health Report</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>{CSS}{report_golden.CSS}</style><script>{JS}</script></head>
<body>
{_ICONS}
<span id="report-meta" hidden data-env="{e(meta['environment'])}" data-time="{e(_ts(meta['finished']))}" data-verdict="{e(verdict[3])}"></span>
<aside class="side">
  <div class="brand"><span class="logo">A</span>AgentHub Health</div>
  <nav class="nav">
    <div class="sec">Report</div>
    <a href="#overview" style="--c:var(--accent)"><span class="l">{_ico('grid')}Overview</span></a>
    {nav('failed', 'Failed checks')}
    {nav('unused', 'Failed, no app effect')}
    {nav('suite', 'Suite issues')}
    {nav('known', 'Known issues')}
    {nav('passed', 'Passed checks')}
    {nav('skipped', 'Skipped')}
    {golden_nav}
    <div class="sec">Run</div>
    <a href="#run" style="--c:var(--muted)"><span class="l">{_ico('run')}Run details</span></a>
  </nav>
  <div class="keys keys-hint"><kbd>/</kbd> search<br><kbd>j</kbd> <kbd>k</kbd> next, previous card<br><kbd>e</kbd> open or close card<br><kbd>Esc</kbd> clear search</div>
</aside>
<div class="main">
  <header class="top">
    <div class="top-row">
      <h1>AgentHubNext dependency health</h1>
      <div class="meta">{_badge(meta['environment'], 'primary')}<span>{e(_ts(meta['finished']))}</span><span>&middot; {e(duration)}</span>{_app_version(meta.get('app_version'))}
        <button class="btn" id="themeBtn" type="button" onclick="cycleTheme()" title="Theme: auto / light / dark">{_ico('monitor')}<span class="t">Auto</span></button></div>
    </div>
    <div class="toolbar">
      <label class="search">{_ico('search')}<input id="q" type="search" placeholder="Search checks, services, URLs" autocomplete="off" spellcheck="false"><kbd>/</kbd></label>
      <div class="seg" role="group" aria-label="Filter by status">{seg}</div>
      <span class="activef" id="activef" hidden><span></span><button type="button" onclick="setService('')" aria-label="Clear service filter">&times;</button></span>
      <span class="shown" id="shown"></span>
      <div class="tools">
        <button class="btn" type="button" onclick="toggleAll(true)">Expand all</button>
        <button class="btn" type="button" onclick="toggleAll(false)">Collapse all</button>
        <button class="btn primary" type="button" onclick="copyFailures(this)">Copy failures for Teams</button>
      </div>
    </div>
  </header>
  <main class="content">
    <section id="overview">
      <h2>Overview</h2><p class="sub">Windows build of AgentHubNext &middot; environment {e(meta['environment'])} &middot; marker filter: {e(meta['markers'] or 'none')}</p>
      <div class="bento">
        <div class="tile t-verdict">
          <div class="v-head"><span class="v-ico">{_ico(verdict[2])}</span><div><h2>{e(verdict[1])}</h2><p>{e(verdict[3])}</p></div></div>
          {f'<div class="v-causes">{cause_chips}</div>' if cause_chips else ''}
        </div>
        <div class="tile t-ring">{donut}<div class="ring-sub"><b>{n_passed}</b> of <b>{total}</b> checks passed</div></div>
        <div class="chips">{chips}</div>
        <div class="tile t-svcs"><h3>Service health</h3>{_service_grid(records)}<p class="muted small" style="margin:12px 0 0">Click a service to see only the checks that call it.</p></div>
        <div class="tile t-chg"><h3>Changes since the last run</h3>{_changes_tile(records, h)}</div>
        <div class="tile t-lat"><h3>Slowest requests</h3>{_latency_tile(records)}</div>
      </div>
    </section>
    {sections}
    {golden_html}
    <section id="run">
      <h2><span class="h-ico" style="--c:var(--muted)">{_ico('run')}</span>Run details</h2>
      <p class="sub">How this run was made and what it used.</p>
      <div class="grid2">
        <div class="card"><header class="card-h"><h3>Execution</h3></header><div class="card-b"><dl class="facts">
          {_kv('Started', _ts(meta['started']))}{_kv('Finished', _ts(meta['finished']))}{_kv('Duration', duration)}
          {_kv('Environment', meta['environment'])}{_kv('Marker filter', meta['markers'] or 'none')}
          {_kv('Python', meta['python'])}{_kv('Platform', meta['platform'])}
          {_kv('Suite version', meta['suite_version'])}{_kv('pytest exit status', str(meta['exit_status']))}
          {_kv('Log folder', meta.get('log_dir') or '-', mono=True)}
        </dl></div></div>
        <div class="card"><header class="card-h"><h3>Service base URLs</h3></header><div class="card-b p0">
          <table class="tbl"><tbody>{urls}</tbody></table></div></div>
        <div class="card"><header class="card-h"><h3>Remote configuration used</h3></header><div class="card-b p0">
          <table class="tbl"><tbody>{rc_rows}</tbody></table>
          <p class="muted small" style="padding:10px 20px;margin:0">Saved copies: <span class="mono">{e(meta.get('remote_config_dir', ''))}</span></p></div></div>
        <div class="card"><header class="card-h"><h3>Services this configuration uses</h3></header><div class="card-b p0">
          <table class="tbl"><tbody>{usage_rows}</tbody></table>
          <p class="muted small" style="padding:10px 20px;margin:0">Worked out again on every run. Failures of a service marked "not used" are listed under Failed, no effect on the app.</p></div></div>
      </div>
      <details class="card" style="padding:16px 20px"><summary style="font-weight:600">Every request made by every check</summary>
        {all_requests}
      </details>
    </section>
  </main>
  <footer class="foot">AgentHubNext health suite {e(meta['suite_version'])} &middot; credentials are masked to their last four characters &middot; run history in results/history.json</footer>
</div>
<nav class="bnav" aria-label="Sections">{bnav}</nav>
</body></html>"""
    doc = report_theme.apply(doc)
    settings.REPORT_FILE.write_text(doc, encoding="utf-8")
    _save_history(records, meta["environment"], meta["finished"], meta["suite_version"])
    return str(settings.REPORT_FILE)
