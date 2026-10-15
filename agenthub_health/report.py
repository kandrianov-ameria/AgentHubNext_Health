"""
results/result.html - a single self-contained file styled with the Folio design system
(the "HTML redesign in Folio style" archive): cream canvas #faf9f5, warm ink #141413,
coral accent #cc785c, cream sunken surface #efe9de, hairline #e6dfd8, dark footer and code
blocks #181715. Source Serif 4 for headings and figures, Inter for text, JetBrains Mono for
code. Sidebar + topbar shell, flat cards, no shadows, and a dark mode switched with a
data-theme attribute on <html>.

The section and KPI accent colours (#5db872 passed, #c64545 failed, #d4a017 no app effect,
#E3B05A / #e8a55a suite issues, #7FB0D6 known, #d99a80 skipped) come from the redesign,
where they were set inline; here they live at the end of CSS.
"""
from __future__ import annotations

import datetime as dt
import html
from collections import OrderedDict, defaultdict

from . import redact, settings

AREAS = {
    "test_00_setup": "Suite setup",
    "test_01_remote_config": "Remote configuration",
    "test_02_agent_graph": "Agent graph",
    "test_10_aihub_service": "AI-Hub service",
    "test_11_pat_config": "pat-config",
    "test_20_llm_providers": "LLM providers",
    "test_21_speech": "Speech (Deepgram, Whisper)",
    "test_22_segmentation": "Object segmentation",
    "test_30_mav_starkit": "mav-starkit-api",
    "test_31_generation_services": "Generation services",
    "test_40_mcp_servers": "MCP servers",
    "test_50_logs_mapping_seq": "Log upload, device mapping, Seq",
    "test_90_live_generation": "Live generation",
}


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


def _badge(text: str, kind: str) -> str:
    return f'<span class="badge badge-{kind}">{e(text)}</span>'


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


# --- sections --------------------------------------------------------------------

def _failed_section(records, empty: str = "No failed checks.") -> str:
    groups: "OrderedDict[str, list]" = OrderedDict()
    for r in records:
        groups.setdefault(r.failure.get("cause_key", r.nodeid), []).append(r)
    ordered = sorted(groups.values(), key=lambda g: -len(g))
    if not ordered:
        return f'<div class="empty">{e(empty)}</div>'
    cards = []
    for i, group in enumerate(ordered, 1):
        f = group[0].failure
        probe = f.get("probe")
        head_badges = _badge(f"{len(group)} check{'s' if len(group) != 1 else ''}",
                             "warning" if f.get("no_effect_reason") else "danger")
        if probe:
            head_badges += " " + _badge(probe["status"], "neutral")
            if probe["http_status"] is not None:
                head_badges += " " + _badge(f"HTTP {probe['http_status']}", "neutral")
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
        cards.append(f"""
<article class="card cause{' noimpact' if f.get('no_effect_reason') else ''}" id="cause-{'u' if f.get('no_effect_reason') else ''}{i}">
  <header class="card-h">
    <div><div class="eyebrow">Root cause {i}</div><h3>{e(f.get('title', 'Check failed'))}</h3></div>
    <div class="badges">{head_badges}</div>
  </header>
  <div class="card-b">
    <dl class="facts">{facts}</dl>
    <div class="block"><h4>What happened</h4><p>{e(f.get('explanation', ''))}</p></div>
    {f'<div class="block"><h4>Why AgentHubNext is not affected today</h4><p>{e(f["no_effect_reason"])}</p></div>' if f.get('no_effect_reason') else (f'<div class="block"><h4>Effect on AgentHubNext</h4><p>{e(f["impact"])}</p></div>' if f.get('impact') else '')}
    {f'<div class="block"><h4>How to fix</h4><p>{e(f["rotation"])}</p></div>' if f.get('rotation') else ''}
    {''.join(evidence) and f'<details class="block"><summary>Evidence</summary>{"".join(evidence)}</details>'}
    <h4 class="mt">Affected checks</h4>
    <table class="tbl"><thead><tr><th style="width:42%">Check</th><th>Observed</th></tr></thead><tbody>{affected}</tbody></table>
  </div>
</article>""")
    return "".join(cards)


def _suite_section(records, collection_issues) -> str:
    items = []
    for c in collection_issues:
        items.append((c, None))
    for r in records:
        items.append((r.failure, r))
    if not items:
        return '<div class="empty">No suite issues. Every check ran to a verdict.</div>'
    cards = []
    for f, r in items:
        title = e(r.objective) if r else e(f.get("location", "Collection"))
        ident = f'<div class="t-id mono">{e(r.nodeid)} &middot; phase: {e(r.phase)}</div>' if r else ""
        cards.append(f"""
<article class="card issue">
  <header class="card-h"><div><div class="eyebrow">{e(f.get('type', 'Suite issue'))}</div><h3>{title}</h3>{ident}</div>
  <div class="badges">{_badge('suite issue', 'warning')}</div></header>
  <div class="card-b">
    <div class="block"><h4>What this means</h4><p>{e(f.get('meaning', ''))}</p></div>
    <div class="block"><h4>Detail</h4><pre>{e(f.get('message', ''))}</pre></div>
    {f'<dl class="facts">{_kv("Location", f.get("location", ""), mono=True)}</dl>' if f.get('location') and r else ''}
    {f'<div class="block"><h4>How to fix</h4><p>{e(f["remediation"])}</p></div>' if f.get('remediation') else ''}
  </div>
</article>""")
    return "".join(cards)


def _table_by_area(records, extra_col: str | None, extra_fn) -> str:
    if not records:
        return '<div class="empty">None.</div>'
    by_area: dict[str, list] = defaultdict(list)
    for r in records:
        by_area[_area(r.module)].append(r)
    out = []
    for area in sorted(by_area, key=lambda a: list(AREAS.values()).index(a) if a in AREAS.values() else 99):
        rows = []
        for r in by_area[area]:
            lat = ", ".join(f'{p["latency_ms"]} ms' for p in r.probes) or "-"
            extra = f"<td>{extra_fn(r)}</td>" if extra_col else ""
            rows.append(f'<tr><td><div class="t-obj">{e(r.objective)}</div><div class="t-id mono">{e(r.nodeid)}</div></td>'
                        f'{extra}<td class="num">{lat}</td><td class="num">{_dur(r.duration)}</td></tr>')
        head_extra = f"<th>{e(extra_col)}</th>" if extra_col else ""
        out.append(f"""
<div class="card area"><header class="card-h"><h3>{e(area)}</h3><div class="badges">{_badge(len(by_area[area]), 'neutral')}</div></header>
<div class="card-b p0"><table class="tbl"><thead><tr><th>Check</th>{head_extra}<th class="num">Service latency</th><th class="num">Duration</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div></div>""")
    return "".join(out)


# --- page ------------------------------------------------------------------------

CSS = """
:root{--c-primary:#cc785c;--c-primary-dark:#a9583e;--c-primary-soft:#f5e6df;--ring:rgba(204,120,92,.15);
--bg-body:#faf9f5;--bg-card:#faf9f5;--bg-side:#faf9f5;--bg-sunken:#efe9de;--text:#141413;--body:#3d3d3a;--muted:#6c6a64;--line:#e6dfd8;
--ok:#2f7d68;--ok-soft:#dfeee8;--bad:#b0402f;--bad-soft:#f6dfd8;--warn:#94600f;--warn-soft:#f6e8c8;--warn-2:#d9a13b;
--info:#3f6f95;--info-soft:#dde8f0;--neu:#5a5852;--neu-soft:#efe9de;--shadow:none;
--f-body:"Inter",system-ui,-apple-system,"Segoe UI",sans-serif;--f-display:"Source Serif 4","Tiempos Headline",Georgia,serif;
--f-mono:"JetBrains Mono",ui-monospace,Consolas,monospace}
html[data-theme="dark"]{--c-primary:#d98b70;--c-primary-soft:#3a2a24;--bg-body:#181715;--bg-card:#181715;--bg-side:#181715;--bg-sunken:#22201d;
--text:#faf9f5;--body:#d6d2c8;--muted:#a09d96;--line:#33302b;--ok:#6fc0a8;--ok-soft:#1f3a32;--bad:#e58a78;--bad-soft:#412621;
--warn:#e3b05a;--warn-soft:#3f3218;--warn-2:#d9a13b;--info:#7fb0d6;--info-soft:#20303d;--neu:#c9c5ba;--neu-soft:#2a2823}
*{box-sizing:border-box}html,body{margin:0}
body{background:var(--bg-body);color:var(--body);font:15px/1.6 var(--f-body);-webkit-font-smoothing:antialiased}
a{color:var(--c-primary);text-decoration:none}a:hover{color:var(--c-primary-dark)}
.side{position:fixed;inset:0 auto 0 0;width:248px;background:var(--bg-side);border-right:1px solid var(--line);display:flex;flex-direction:column;z-index:3}
.brand{display:flex;align-items:center;gap:10px;height:64px;padding:0 24px;border-bottom:1px solid var(--line);font:400 22px var(--f-display);letter-spacing:-.3px;color:var(--text)}
.brand .logo{width:28px;height:28px;border-radius:50%;background:var(--c-primary);color:#faf9f5;display:grid;place-items:center;font:400 16px var(--f-display)}
.nav{padding:16px 12px;overflow:auto}
.nav .sec{font-size:11px;letter-spacing:1.5px;text-transform:uppercase;color:var(--muted);padding:14px 12px 6px}
.nav a{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:8px 12px;border-radius:8px;color:var(--body);font-weight:500;font-size:14px}
.nav a:hover{background:var(--bg-sunken);color:var(--text)}
.nav a .dot{width:7px;height:7px;border-radius:50%;display:inline-block;margin-right:12px}
.nav a span.l{display:flex;align-items:center}
.cnt{font:500 12px var(--f-mono);color:var(--muted)}
.main{margin-left:248px;min-height:100vh;display:flex;flex-direction:column}
.top{position:sticky;top:0;z-index:2;height:64px;display:flex;align-items:center;justify-content:space-between;gap:16px;padding:0 40px;background:var(--bg-body);border-bottom:1px solid var(--line)}
.top h1{margin:0;font:400 24px var(--f-display);letter-spacing:-.3px;color:var(--text)}
.top .meta{display:flex;align-items:center;gap:12px;color:var(--muted);font-size:13px;flex-wrap:wrap}
.btn{border:1px solid var(--line);background:transparent;color:var(--text);border-radius:8px;padding:7px 14px;font:500 13px var(--f-body);cursor:pointer}
.btn:active{background:var(--bg-sunken)}
.content{padding:48px 40px 64px;display:flex;flex-direction:column;gap:72px;flex:1;max-width:1240px;width:100%}
section,.card{scroll-margin-top:88px}
section>h2{margin:0 0 8px;font:400 36px/1.15 var(--f-display);letter-spacing:-.8px;color:var(--text);display:flex;align-items:center;gap:14px}
section>p.sub{margin:0 0 28px;color:var(--muted);max-width:72ch;text-wrap:pretty}
.kpis{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:12px}
.kpi{background:var(--bg-sunken);border-radius:12px;padding:18px 18px 16px}
.kpi .k{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:1.5px}
.kpi .v{font:400 44px/1 var(--f-display);letter-spacing:-1px;margin-top:14px;color:var(--text)}
.kpi.ok .v{color:var(--ok)}.kpi.bad .v{color:var(--bad)}.kpi.warn .v,.kpi.warn2 .v{color:var(--warn)}.kpi.info .v{color:var(--info)}
.bar{display:flex;height:8px;border-radius:999px;overflow:hidden;background:var(--bg-sunken);margin-top:28px;gap:2px}
.bar i{display:block;height:100%}
.legend{display:flex;gap:20px;flex-wrap:wrap;margin-top:12px;color:var(--muted);font-size:13px}
.legend b{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:8px}
.verdict{border-radius:12px;padding:20px 24px;font:400 22px/1.35 var(--f-display);letter-spacing:-.2px;display:flex;align-items:center;gap:12px;text-wrap:pretty}
.verdict.ok{background:var(--ok-soft);color:var(--ok)}.verdict.bad{background:var(--bad-soft);color:var(--bad)}.verdict.warn{background:var(--warn-soft);color:var(--warn)}
.card{background:var(--bg-card);border:1px solid var(--line);border-radius:12px;margin-bottom:20px;overflow:hidden}
.card-h{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;padding:20px 24px;border-bottom:1px solid var(--line)}
.card-h h3{margin:0;font:400 24px/1.2 var(--f-display);letter-spacing:-.3px;color:var(--text)}
.cause .card-h{background:var(--bad-soft)}.cause.noimpact .card-h{background:var(--warn-soft)}.issue .card-h{background:var(--warn-soft)}
.eyebrow{font-size:11px;letter-spacing:1.5px;text-transform:uppercase;color:var(--muted);margin-bottom:4px}
.card-b{padding:24px}.card-b.p0{padding:0;overflow-x:auto}
.tbl td,.tbl th{padding-left:16px;padding-right:16px}.tbl td:first-child,.tbl th:first-child{padding-left:24px}.tbl td:last-child,.tbl th:last-child{padding-right:24px}
.badges{display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end}
.badge{display:inline-block;font:500 11px var(--f-mono);padding:3px 10px;border-radius:999px;white-space:nowrap;letter-spacing:.2px}
.badge-success{background:var(--ok-soft);color:var(--ok)}.badge-danger{background:var(--bad-soft);color:var(--bad)}
.badge-warning{background:var(--warn-soft);color:var(--warn)}.badge-info{background:var(--info-soft);color:var(--info)}
.badge-neutral{background:var(--neu-soft);color:var(--neu)}.badge-primary{background:var(--c-primary);color:#faf9f5;text-transform:uppercase;letter-spacing:1.5px;font-family:var(--f-body);font-weight:500}
section>h2 .badge{font-size:13px;padding:4px 12px;font-family:var(--f-mono);letter-spacing:0;text-transform:none}
.facts{display:grid;grid-template-columns:140px 1fr;gap:8px 20px;margin:0 0 20px}
.facts dt{color:var(--muted)}.facts dd{margin:0;word-break:break-word;color:var(--text)}
.block{margin-top:18px}.block h4,h4.mt{margin:0 0 6px;font:500 11px var(--f-body);text-transform:uppercase;letter-spacing:1.5px;color:var(--muted)}
h4.mt{margin-top:28px;margin-bottom:10px}.block p{margin:0;max-width:78ch;text-wrap:pretty}
details summary{cursor:pointer;font:500 14px var(--f-body);color:var(--c-primary)}
pre{margin:8px 0 0;padding:16px;background:#181715;color:#e8e4da;border-radius:12px;font:12px/1.6 var(--f-mono);white-space:pre-wrap;word-break:break-word;max-height:320px;overflow:auto}
.ev-label{margin-top:12px;font-size:12px;color:var(--muted)}
.tbl{width:100%;border-collapse:collapse}
.tbl th{text-align:left;font:500 11px var(--f-body);text-transform:uppercase;letter-spacing:1.5px;color:var(--muted);background:var(--bg-sunken);padding:10px 24px;border-bottom:1px solid var(--line)}
.tbl td{padding:12px 24px;border-bottom:1px solid var(--line);vertical-align:top}
.tbl tr:last-child td{border-bottom:none}.tbl .num{text-align:right;white-space:nowrap;font-family:var(--f-mono);font-size:12px}
.card-b>.tbl{border:1px solid var(--line);border-radius:8px;overflow:hidden}
.card-b>.tbl th:first-child,.card-b>.tbl td:first-child{padding-left:16px}
.tbl-compact td,.tbl-compact th{padding:8px 16px}.url{word-break:break-all}
.t-obj{font-weight:500;color:var(--text)}.t-id{color:var(--muted);font-size:11px;margin-top:2px;word-break:break-all}.t-hint{color:var(--info);margin-top:4px}
.mono{font-family:var(--f-mono);font-size:12px}
.empty{background:var(--bg-sunken);border-radius:12px;padding:28px;color:var(--muted);font:400 18px var(--f-display);text-align:center}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:20px}
.foot{padding:32px 40px;color:#a09d96;font-size:13px;background:#181715}
@media (max-width:1100px){.kpis{grid-template-columns:repeat(3,1fr)}.grid2{grid-template-columns:1fr}}
@media (max-width:760px){.side{display:none}.main{margin-left:0}.kpis{grid-template-columns:repeat(2,1fr)}.content{padding:24px 16px;gap:48px}.top{padding:0 16px}.facts{grid-template-columns:1fr}section>h2{font-size:28px}}
@media print{.side,.top .btn{display:none}.main{margin-left:0}}
/* Section accents from the Folio redesign of this report */
.nav a .dot.d-overview{background-color:#3C82DD}.nav a .dot.d-passed{background-color:#5db872}.nav a .dot.d-failed{background-color:#c64545}
.kpi.total .v{color:#a09d96}
.kpi.ok .k,.kpi.ok .v{color:#5db872}.kpi.bad .k,.kpi.bad .v{color:#c64545}
.kpi.warn .k,.kpi.warn .v{color:#d4a017}.kpi.warn2 .k,.kpi.warn2 .v{color:#E3B05A}
.kpi.info .k,.kpi.info .v{color:#7FB0D6}.kpi.skip .k,.kpi.skip .v{color:#d99a80}
#failed>h2{color:#c64545}#unused>h2{color:#d4a017}#suite>h2{color:#e8a55a}#passed>h2{color:#5db872}
#known>h2{color:#7FB0D6}#skipped>h2,#skipped>h2 .badge{color:#d99a80}
"""

JS = """
(function(){var root=document.documentElement,key='agenthub-health-theme';
function set(t){root.setAttribute('data-theme',t);var b=document.getElementById('themeBtn');if(b)b.textContent=t==='dark'?'Light mode':'Dark mode';}
var saved=null;try{saved=localStorage.getItem(key);}catch(e){}
set(saved||(window.matchMedia&&window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'));
window.toggleTheme=function(){var t=root.getAttribute('data-theme')==='dark'?'light':'dark';set(t);try{localStorage.setItem(key,t);}catch(e){}};
window.toggleDetails=function(open){document.querySelectorAll('details').forEach(function(d){d.open=open;});};
})();
"""


def render(records, collection_issues, meta) -> str:
    settings.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    cat = defaultdict(list)
    for r in records:
        cat[r.category].append(r)
    passed, failed, suite, unused = cat["passed"], cat["failed"], cat["suite"], cat["unused"]
    skipped, known, fixed = cat["skipped"], cat["known"], cat["known_fixed"]
    n_suite = len(suite) + len(collection_issues)
    total = len(records)
    root_causes = len({r.failure.get("cause_key", r.nodeid) for r in failed})

    if failed:
        verdict = ("bad", f"{len(failed)} check(s) failed across {root_causes} root cause(s). "
                          "AgentHubNext is affected - see Failed checks.")
    elif unused:
        verdict = ("warn", f"Nothing AgentHubNext uses today has failed. {len(unused)} check(s) failed on "
                           "things the app does not use - see Failed, no effect on the app.")
    elif n_suite:
        verdict = ("warn", f"No dependency failures, but {n_suite} check(s) could not run. "
                           "See Suite issues before trusting this result.")
    else:
        verdict = ("ok", "Every executed check passed.")

    def pct(n):
        return f"{(100 * n / total):.2f}%" if total else "0%"

    bar = "".join(f'<i style="width:{pct(n)};background:var({c})" title="{t}: {n}"></i>' for n, c, t in [
        (len(passed) + len(fixed), "--ok", "Passed"), (len(failed), "--bad", "Failed"),
        (len(unused), "--warn-2", "Failed, no effect on the app"),
        (len(suite), "--warn", "Suite issues"), (len(known), "--info", "Known issues"),
        (len(skipped), "--neu", "Skipped")])

    def nav(anchor, label, n, color, cls=""):
        dot = f'<i class="dot {cls}"></i>' if cls else f'<i class="dot" style="background:var({color})"></i>'
        return (f'<a href="#{anchor}"><span class="l">{dot}{label}</span>'
                f'<span class="cnt">{n}</span></a>')

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

    known_rows = _table_by_area(known + fixed, "Known issue", lambda r: (
        (_badge("fixed - remove xfail", "success") + " " if r.category == "known_fixed" else "") + e(r.reason)))
    skip_rows = _table_by_area(skipped, "Reason", lambda r: e(r.reason))

    doc = f"""<!doctype html>
<html lang="en" data-theme="light"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AgentHubNext Health Report</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500&family=Source+Serif+4:opsz,wght@8..60,400&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>{CSS}</style><script>{JS}</script></head>
<body>
<aside class="side">
  <div class="brand"><span class="logo">A</span>AgentHub Health</div>
  <nav class="nav">
    <div class="sec">Report</div>
    <a href="#overview"><span class="l"><i class="dot d-overview"></i>Overview</span></a>
    {nav('passed', 'Passed checks', len(passed) + len(fixed), '--ok', 'd-passed')}
    {nav('failed', 'Failed checks', len(failed), '--bad', 'd-failed')}
    {nav('unused', 'Failed, no app effect', len(unused), '--warn-2')}
    {nav('suite', 'Suite issues', n_suite, '--warn')}
    {nav('known', 'Known issues', len(known) + len(fixed), '--info')}
    {nav('skipped', 'Skipped', len(skipped), '--neu')}
    <div class="sec">Run</div>
    <a href="#run"><span class="l"><i class="dot" style="background:var(--muted)"></i>Run details</span></a>
  </nav>
</aside>
<div class="main">
  <header class="top">
    <h1>AgentHubNext dependency health</h1>
    <div class="meta">{_badge(meta['environment'], 'primary')}<span>{e(_ts(meta['finished']))}</span><span>&middot; {e(duration)}</span>
      <button class="btn" onclick="toggleDetails(true)">Expand evidence</button>
      <button class="btn" id="themeBtn" onclick="toggleTheme()">Dark mode</button></div>
  </header>
  <main class="content">
    <section id="overview">
      <h2>Overview</h2><p class="sub">Windows build of AgentHubNext &middot; environment {e(meta['environment'])} &middot; marker filter: {e(meta['markers'] or 'none')}</p>
      <div class="verdict {verdict[0]}">{e(verdict[1])}</div>
      <div class="kpis" style="margin-top:16px">
        <div class="kpi neu total"><div class="k">Checks</div><div class="v">{total}</div></div>
        <div class="kpi ok"><div class="k">Passed</div><div class="v">{len(passed) + len(fixed)}</div></div>
        <div class="kpi bad"><div class="k">Failed</div><div class="v">{len(failed)}</div></div>
        <div class="kpi warn"><div class="k">No app effect</div><div class="v">{len(unused)}</div></div>
        <div class="kpi warn2"><div class="k">Suite issues</div><div class="v">{n_suite}</div></div>
        <div class="kpi info"><div class="k">Known issues</div><div class="v">{len(known)}</div></div>
        <div class="kpi neu skip"><div class="k">Skipped</div><div class="v">{len(skipped)}</div></div>
      </div>
      <div class="bar">{bar}</div>
      <div class="legend"><span><b style="background:var(--ok)"></b>Passed</span><span><b style="background:var(--bad)"></b>Failed</span><span><b style="background:var(--warn-2)"></b>Failed, no app effect</span>
        <span><b style="background:var(--warn)"></b>Suite issues</span><span><b style="background:var(--info)"></b>Known issues</span>
        <span><b style="background:var(--neu)"></b>Skipped</span></div>
    </section>

    <section id="failed">
      <h2>Failed checks {_badge(len(failed), 'danger')}</h2>
      <p class="sub">A dependency of AgentHubNext did not behave as the application requires. Checks that failed for the same reason are grouped under one root cause, largest first. Every explanation is derived from the HTTP answer, transport error or configuration value this run observed.</p>
      {_failed_section(failed)}
    </section>

    <section id="unused">
      <h2>Failed, no effect on the app {_badge(len(unused), 'warning')}</h2>
      <p class="sub">These checks failed, but on something AgentHubNext does not use today - an MCP server no agent is assigned, an endpoint no code path calls, or a setting the app ignores. Each card names the reason. They become real failures the moment the app starts using them.</p>
      {_failed_section(unused, "None.")}
    </section>

    <section id="suite">
      <h2>Suite issues {_badge(n_suite, 'warning')}</h2>
      <p class="sub">Problems with the test suite itself: a check could not run, or its code raised an unexpected error. These say nothing about the services - fix them before trusting the rest of the report.</p>
      {_suite_section(suite, collection_issues)}
    </section>

    <section id="passed">
      <h2>Passed checks {_badge(len(passed) + len(fixed), 'success')}</h2>
      <p class="sub">Grouped by area. Service latency is the time each request made by the check took.</p>
      {_table_by_area(passed + fixed, None, None)}
    </section>

    <section id="known">
      <h2>Known issues {_badge(len(known) + len(fixed), 'info')}</h2>
      <p class="sub">Defects already identified in the configuration, tracked as expected failures. A check marked "fixed" now passes and its expected-failure marker can be removed.</p>
      {known_rows}
    </section>

    <section id="skipped">
      <h2>Skipped {_badge(len(skipped), 'neutral')}</h2>
      <p class="sub">Checks that did not apply to this run, with the reason each one names.</p>
      {skip_rows}
    </section>

    <section id="run">
      <h2>Run details</h2>
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
          <p class="sub" style="padding:10px 16px">Saved copies: <span class="mono">{e(meta.get('remote_config_dir', ''))}</span></p></div></div>
        <div class="card"><header class="card-h"><h3>Services this configuration uses</h3></header><div class="card-b p0">
          <table class="tbl"><tbody>{usage_rows}</tbody></table>
          <p class="sub" style="padding:10px 16px">Worked out again on every run. Failures of a service marked "not used" are listed under Failed, no effect on the app.</p></div></div>
      </div>
      <details class="card" style="padding:16px 20px"><summary>Every request made by every check</summary>
        {''.join(f'<div class="t-obj" style="margin-top:14px">{e(r.objective)}</div><div class="t-id mono">{e(r.nodeid)}</div>{_probe_rows(r.probes)}' for r in records if r.probes)}
      </details>
    </section>
  </main>
  <footer class="foot">AgentHubNext health suite {e(meta['suite_version'])} &middot; credentials are masked to their last four characters &middot; styled with the Folio design system.</footer>
</div>
</body></html>"""
    settings.REPORT_FILE.write_text(doc, encoding="utf-8")
    return str(settings.REPORT_FILE)
