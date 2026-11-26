"""The "Golden scenarios" section of the report (1.13.0). A section of its own, after Skipped and
before Run details; its cards carry no data-status, so the status filter, the search, the counts and
the Teams copy of the health checks never touch it. Data comes from golden.py."""
from __future__ import annotations

from . import golden

_STATE = {  # readiness -> (label, badge kind, colour variable, icon)
    "ready": ("Ready", "success", "--ok", "check"),
    "degraded": ("Degraded", "warning", "--warn", "alert"),
    "blocked": ("Blocked", "danger", "--bad", "x"),
    "unknown": ("Not verified", "neutral", "--neu", "skip"),
}
_NEED_ICO = {golden.OK: ("check", "--ok"), golden.WARN: ("alert", "--warn"), golden.BAD: ("x", "--bad"),
             golden.UNKNOWN: ("skip", "--neu")}

CSS = r"""
.gsum{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 18px}
.gsum .gc{display:flex;align-items:baseline;gap:8px;padding:10px 14px;border:1px solid var(--line);border-radius:var(--r-l);background:var(--surface);box-shadow:var(--shadow)}
.gsum .gc b{font:650 20px var(--f);color:var(--c)}.gsum .gc span{color:var(--muted)}
.gneeds{list-style:none;margin:6px 0 0;padding:0;display:grid;gap:6px}
.gneeds li{display:grid;grid-template-columns:22px minmax(0,1fr);gap:10px;align-items:start}
.gneeds .gi{width:20px;height:20px;border-radius:6px;display:grid;place-items:center;font-size:12px;color:var(--c);background:color-mix(in srgb,var(--c) 15%,transparent)}
.gneeds .gl{color:var(--text);font-weight:500}.gneeds .gd{color:var(--muted);font-size:13px}
.gans{white-space:pre-wrap;word-break:break-word;background:var(--surface-2);border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin:6px 0 0;color:var(--text)}
details.gold>.card-b .gnote{color:var(--muted);font-size:13px;margin:6px 0 0}
details.gold .st-ico{--st:var(--c)}
"""


def _needs(r) -> str:
    from . import report as R
    items = []
    for n in r.needs:
        ico, col = _NEED_ICO[n.state]
        items.append(f'<li style="--c:var({col})"><span class="gi">{R._ico(ico)}</span>'
                     f'<div><div class="gl">{R.e(n.label)}</div><div class="gd">{R.e(n.detail)}</div></div></li>')
    return f'<ul class="gneeds">{"".join(items)}</ul>'


def _replay(s: dict, rec) -> tuple[str, str]:
    """(badge html, body html) of the replay block of one scenario."""
    from . import report as R
    if "replay" not in s:
        return "", ('<div class="block"><h4>Replay</h4><p class="gnote">No replay: this scenario needs more than one '
                    'model call (tools, browser, generation or devices), so the suite only checks readiness.</p></div>')
    if rec is None:
        return R._badge("replay not run", "neutral"), ('<div class="block"><h4>Replay</h4><p class="gnote">The replay '
                                                      'did not run in this run (marker filter).</p></div>')
    data = golden.REPLAYS.get(s["id"], {})
    if rec.category == "skipped":
        return R._badge("replay skipped", "neutral"), (f'<div class="block"><h4>Replay</h4><p>{R.e(rec.reason)}</p></div>')
    ok = rec.category == "passed"
    head = R._badge("replay passed" if ok else "replay failed", "success" if ok else "danger")
    parts = [f'<div class="block"><h4>Replay</h4><p>Model: {R.e(data.get("provider", "-"))}. Screenshot: '
             f'<span class="mono">{R.e(data.get("asset", "-"))}</span>'
             + (f'. Response time: {R.e(R._ms(data["latency_ms"]))}' if data.get("latency_ms") is not None else "")
             + ".</p></div>"]
    if data.get("answer"):
        parts.append(f'<div class="block"><h4>Answer</h4><div class="gans">{R.e(golden.strip_tags(data["answer"]))}</div></div>')
    if data.get("checks"):
        rows = "".join(
            f'<li style="--c:var({_NEED_ICO[golden.OK if ok_ else golden.BAD][1]})"><span class="gi">'
            f'{R._ico(_NEED_ICO[golden.OK if ok_ else golden.BAD][0])}</span><div><div class="gl">{R.e(label)}</div>'
            f'<div class="gd">{R.e(detail)}</div></div></li>' for label, ok_, detail in data["checks"])
        parts.append(f'<div class="block"><h4>Criteria read from the answer text</h4><ul class="gneeds">{rows}</ul></div>')
    if not ok and rec.failure and not data.get("checks"):
        parts.append(f'<div class="block"><h4>Why it failed</h4><p>{R.e(rec.failure.get("message", ""))}</p></div>')
    if data.get("not_replayed"):
        parts.append(f'<div class="block"><h4>Not covered by the replay</h4><p class="gnote">{R.e(data["not_replayed"])}</p></div>')
    parts.append('<p class="gnote">The model does not answer the same way twice, and the replay differs from the app '
                 '(no tools, a PNG of the page, the spoken text only). Treat a failed criterion as a reason to look, '
                 'not as proof of a regression.</p>')
    return head, "".join(parts)


def _card(r, rec) -> str:
    from . import report as R
    s = r.scenario
    label, kind, col, ico = _STATE[r.state]
    rbadge, rbody = _replay(s, rec)
    blockers = [n for n in r.needs if n.state in (golden.BAD, golden.WARN)]
    line = ("; ".join(f"{n.label}: {n.detail}" for n in blockers[:2]) if blockers
            else "Everything this scenario needs from the services and the configuration is in place."
            if r.state == "ready" else "Some of what it needs was not checked in this run.")
    return f"""
<details class="card gold" id="golden-{R.e(s['id'])}" style="--c:var({col})">
  <summary class="card-h">{R._chev()}<span class="st-ico">{R._ico(ico)}</span>
    <div class="hm"><div class="eyebrow">{R.e(s['id'])} &middot; {R.e(s['category'])} &middot; {R.e(s['route'])}</div>
      <h3>{R.e(s['request'])}</h3><div class="sum">{R.e(R._clip(line, 200))}</div></div>
    <div class="badges">{R._badge(label, kind)} {rbadge}</div>
  </summary>
  <div class="card-b">
    <dl class="facts">{R._kv('Pointing', s.get('pointing') or '')}{R._kv('Language', s.get('language') or '')}{R._kv('Expected tools / agents', s.get('expected_tools') or '')}{R._kv('Pass criteria (workbook)', s.get('pass_criteria') or '')}</dl>
    <div class="block"><h4>What it needs, checked in this run</h4>{_needs(r)}</div>
    {rbody}
    <div class="block"><h4>Not checked by the suite</h4><p class="gnote">{R.e(s.get('manual', ''))} Voice capture, the pointing
    overlay, the screenshot and the time to a usable answer on the device stay in the manual run (Run Log sheet).</p></div>
  </div>
</details>"""


def section(rows: list, replay_records: list) -> str:
    """The whole section. rows: golden.evaluate(); replay_records: the golden-marked records."""
    from . import report as R
    by_id = {}
    for rec in replay_records:
        for r in rows:
            if rec.nodeid.endswith(f"[{r.scenario['id']}]"):
                by_id[r.scenario["id"]] = rec
    n = golden.summarise(rows)
    replays = [by_id[s] for s in by_id]
    rp_ok = sum(1 for x in replays if x.category == "passed")
    rp_bad = sum(1 for x in replays if x.category in ("failed", "unused", "suite"))
    chips = "".join(f'<div class="gc" style="--c:var({_STATE[k][2]})"><b>{n[k]}</b><span>{_STATE[k][0]}</span></div>'
                    for k in ("ready", "degraded", "blocked", "unknown"))
    chips += (f'<div class="gc" style="--c:var(--info)"><b>{rp_ok}/{len(replays)}</b><span>replays passed'
              f'{f", {rp_bad} failed" if rp_bad else ""}</span></div>') if replays else ""
    worst = "blocked" if n["blocked"] else "degraded" if n["degraded"] else "unknown" if n["unknown"] else "ready"
    cards = "".join(_card(r, by_id.get(r.scenario["id"])) for r in rows)
    return f"""
    <section id="golden">
      <h2><span class="h-ico" style="--c:var({_STATE[worst][2]})">{R._ico(_STATE[worst][3])}</span>Golden scenarios
        <span class="badge badge-{_STATE[worst][1]}">{len(rows)}</span></h2>
      <p class="sub">The 13 golden scenarios of the workbook, as far as this suite can see them. A scenario is a whole user
      journey; the suite checks what it needs from the services and the configuration (readiness, worked out from the checks
      above, no extra requests) and, for three scenarios that are one model call over a screenshot, replays it. This section
      is separate: it does not change the verdict, the counts or the history above.</p>
      <div class="gsum">{chips}</div>
      {cards}
    </section>"""
