/* PROTOTYPE LAYER - behaviour. Motion (motion.dev) does all the animation.
   The report's own script keeps doing filtering, copy, theme and scroll-spy;
   this file only adds on top of it and never replaces its functions. */
import { animate, inView, hover, press, scroll, stagger } from "https://cdn.jsdelivr.net/npm/motion@12.23.12/+esm";

const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
const EASE = [0.22, 1, 0.36, 1];
const SPRING = { type: "spring", stiffness: 420, damping: 34 };
const go = (el, kf, opt) => animate(el, kf, reduce ? { duration: 0 } : opt);

/* ---------- staggered reveal on scroll ---------- */
let batch = 0, tick = 0;
const nextDelay = () => {
  if (!tick) tick = requestAnimationFrame(() => { batch = 0; tick = 0; });
  return Math.min(batch++, 14) * 0.04;
};
function reveal(el, delay) {
  if (el.dataset.revealed) return;
  el.dataset.revealed = "1";
  const c = animate(el, { opacity: [0, 1], y: [18, 0], scale: [0.985, 1] },
    { duration: 0.6, delay, ease: EASE });
  c.finished.then(() => { el.removeAttribute("data-reveal"); el.style.opacity = ""; el.style.transform = ""; });
}
if (!reduce) {
  /* verdict, ring and chips are choreographed by the overview block at the end of this file */
  inView("[data-reveal]:not(.t-verdict):not(.t-ring):not(.chip)", (el) => { reveal(el, nextDelay()); }, { amount: 0.1, margin: "0px 0px -4% 0px" });
}

/* ---------- number count-up ---------- */
const counters = [];
$$(".chip .n, .ring-sub b, .l-stats b").forEach((el) => {
  const m = el.textContent.trim().match(/^(\D*?)(\d+(?:[.,]\d+)?)(\D*)$/);
  if (!m) return;
  const dec = (m[2].split(/[.,]/)[1] || "").length;
  counters.push({ el, saved: el.textContent, pre: m[1], suf: m[3], dec, to: parseFloat(m[2].replace(",", ".")) });
});
try {
  if (!reduce) {
    counters.forEach((c) => {
      c.el.textContent = c.pre + (0).toFixed(c.dec) + c.suf;
      inView(c.el, () => {
        animate(0, c.to, { duration: c.el.classList.contains("d-n") ? 1.8 : 1.2, ease: [0.16, 1, 0.3, 1],
          onUpdate: (v) => { c.el.textContent = c.pre + v.toFixed(c.dec) + c.suf; } });
      });
    });
  }
} catch (e) { counters.forEach((c) => { c.el.textContent = c.saved; }); }

/* ---------- latency bars grow ---------- */
if (!reduce) {
  $$(".lat li").forEach((li, i) => {
    const bar = $(".l-b i", li);
    inView(li, () => { animate(bar, { scaleX: [0, 1] }, { duration: 0.9, delay: i * 0.07, ease: [0.16, 1, 0.3, 1] }); });
  });
}

/* ---------- hover lift + press squish ---------- */
if (!reduce) {
  hover(".chip, .svc, .vc", (el) => {
    animate(el, { y: -2 }, SPRING);
    return () => animate(el, { y: 0 }, SPRING);
  });
  press(".chip, .svc, .vc, .btn, .copy, .seg button", (el) => {
    animate(el, { scale: 0.96 }, { duration: 0.12 });
    return () => animate(el, { scale: 1 }, { type: "spring", stiffness: 520, damping: 22 });
  });
}

/* ---------- cursor spotlight ---------- */
let sp = 0;
document.addEventListener("pointermove", (e) => {
  const t = e.target.closest && e.target.closest(".tile, .chip, .svc");
  if (!t || sp) return;
  sp = requestAnimationFrame(() => {
    sp = 0;
    const r = t.getBoundingClientRect();
    t.style.setProperty("--mx", e.clientX - r.left + "px");
    t.style.setProperty("--my", e.clientY - r.top + "px");
  });
}, { passive: true });

/* ---------- scroll progress ---------- */
if (!reduce) {
  const bar = document.createElement("div");
  bar.className = "progress";
  document.body.prepend(bar);
  scroll(animate(bar, { scaleX: [0, 1] }, { ease: "linear" }));
}

/* ---------- sliding nav pill (shared-layout feel) ---------- */
const nav = $(".nav");
if (nav) {
  const pill = document.createElement("div");
  pill.className = "nav-pill";
  pill.style.opacity = "0";
  nav.prepend(pill);
  let placed = false;
  const place = () => {
    const a = $(".nav a.on", nav);
    if (!a) return;
    pill.style.opacity = "1";
    pill.style.setProperty("--pc", a.style.getPropertyValue("--c") || "var(--text)");
    animate(pill, { y: a.offsetTop, height: a.offsetHeight }, placed ? SPRING : { duration: 0 });
    placed = true;
  };
  $$(".nav a", nav).forEach((a) => new MutationObserver(place).observe(a, { attributes: true, attributeFilter: ["class"] }));
  addEventListener("resize", () => { placed = false; place(); });
}

/* ---------- sliding thumb in the status filter (shadcn Tabs) ---------- */
const seg = $(".seg");
if (seg) {
  seg.classList.add("has-thumb");
  const th = document.createElement("span");
  th.className = "seg-thumb";
  seg.prepend(th);
  let ready = false;
  const place = () => {
    const b = $("button[aria-pressed=true]", seg);
    th.style.opacity = b ? "1" : "0";
    if (!b) return;
    animate(th, { x: b.offsetLeft, width: b.offsetWidth }, ready ? SPRING : { duration: 0 });
    ready = true;
  };
  new MutationObserver(place).observe(seg, { subtree: true, attributes: true, attributeFilter: ["aria-pressed"] });
  place();
  addEventListener("resize", () => { ready = false; place(); });
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => { ready = false; place(); });
}

/* ---------- animate cards back in when a filter un-hides them ---------- */
if (!reduce) {
  const main = $("main.content");
  new MutationObserver((muts) => {
    const els = [];
    muts.forEach((m) => {
      const el = m.target;
      if (m.oldValue !== null && !el.hasAttribute("hidden") && el.matches("details.card, details.group")) els.push(el);
    });
    els.slice(0, 14).forEach((el, i) => {
      el.dataset.revealed = "1";
      el.removeAttribute("data-reveal");
      animate(el, { opacity: [0, 1], y: [10, 0] }, { duration: 0.35, delay: i * 0.03, ease: EASE });
    });
  }).observe(main, { subtree: true, attributes: true, attributeFilter: ["hidden"], attributeOldValue: true });
}

/* ---------- toast ---------- */
let toasts;
function toast(msg, tone) {
  if (!toasts) { toasts = document.createElement("div"); toasts.className = "toasts"; toasts.setAttribute("role", "status"); toasts.setAttribute("aria-live", "polite"); document.body.append(toasts); }
  const el = document.createElement("div");
  el.className = "toast" + (tone === "bad" ? " bad" : "");
  el.append(document.createElement("i"));
  const s = document.createElement("span"); s.textContent = msg; el.append(s);
  toasts.append(el);
  go(el, { opacity: [0, 1], y: [16, 0], scale: [0.96, 1] }, SPRING);
  setTimeout(() => { go(el, { opacity: 0, y: 8 }, { duration: 0.2 }).finished.then(() => el.remove()); }, 2200);
}
document.addEventListener("click", (e) => {
  const b = e.target.closest && e.target.closest(".copy, .btn.primary");
  if (!b) return;
  setTimeout(() => {
    if (b.classList.contains("done")) toast("Copied to clipboard");
    else if (/failed/i.test(b.textContent)) toast("Copy failed - select the text manually", "bad");
  }, 250);
});

/* ---------- command palette (shadcn Command in a Dialog) ---------- */
const isMac = /Mac|iPhone|iPad/.test(navigator.platform);
const COLOR = { failed: "var(--bad)", unused: "var(--warn)", suite: "var(--suite)", known: "var(--info)", passed: "var(--ok)", skipped: "var(--neu)" };
const flashTo = (id) => { history.replaceState(null, "", "#" + id); dispatchEvent(new HashChangeEvent("hashchange")); };

function collect(q) {
  const items = [];
  $$(".nav a[href^='#']").forEach((a) => {
    const id = a.getAttribute("href").slice(1);
    items.push({ g: "Go to", t: $(".l", a).textContent.trim(), sub: "", c: a.style.getPropertyValue("--c"),
      run: () => { const s = document.getElementById(id); if (s.hidden) window.clearFilters(); s.scrollIntoView({ behavior: "smooth", block: "start" }); } });
  });
  $$("details.cause").forEach((d) => {
    items.push({ g: "Root causes", t: $("h3", d).textContent.trim(), sub: ($(".sum b", d) || {}).textContent || "", c: COLOR[d.dataset.status],
      run: () => flashTo(d.id) });
  });
  $$(".svc").forEach((b) => {
    items.push({ g: "Services", t: $(".svc-t", b).textContent.trim(), sub: $(".svc-m", b).textContent.trim(), c: getComputedStyle(b).getPropertyValue("--c"),
      run: () => { window.setService(b.dataset.svc); const c = $("details.card:not([hidden])"); if (c) c.scrollIntoView({ block: "center", behavior: "smooth" }); } });
  });
  $$(".seg button[data-status-btn]").forEach((b) => {
    const s = b.dataset.statusBtn;
    items.push({ g: "Filter", t: "Show " + (s === "all" ? "all checks" : b.firstChild.textContent.trim().toLowerCase()), sub: "", c: COLOR[s] || "var(--text)",
      run: () => window.setStatus(s, false) });
  });
  const act = (t, run, k) => items.push({ g: "Actions", t, sub: "", k, c: "var(--text)", run });
  act("Expand all cards", () => window.toggleAll(true));
  act("Collapse all cards", () => window.toggleAll(false));
  act("Copy failures for Teams", () => { const b = $(".tools .btn.primary"); if (b) b.click(); });
  act("Clear filters and search", () => window.clearFilters());
  act("Cycle theme (auto / light / dark)", () => window.cycleTheme());
  if (q) {
    $$("details.card.check").filter((d) => d.dataset.search.includes(q)).slice(0, 8).forEach((d) => {
      items.push({ g: "Checks", t: $("h3", d).textContent.trim(), sub: ($(".eyebrow", d) || {}).textContent || "", c: COLOR[d.dataset.status],
        run: () => flashTo(d.id) });
    });
  }
  return items;
}
function score(it, toks) {
  const t = it.t.toLowerCase(), h = (it.g + " " + it.t + " " + it.sub).toLowerCase();
  let s = 0;
  for (const k of toks) { const i = h.indexOf(k); if (i < 0) return -1; s += t.includes(k) ? 2 : 1; }
  return s;
}

let overlay, dlg, input, list, sel = 0, shown = [], opener = null;
function buildPalette() {
  overlay = document.createElement("div");
  overlay.className = "cmdk-overlay";
  overlay.innerHTML =
    '<div class="cmdk" role="dialog" aria-modal="true" aria-label="Command menu">' +
    '<div class="cmdk-in"><svg class="i" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>' +
    '<input type="text" role="combobox" aria-expanded="true" aria-controls="cmdk-list" aria-autocomplete="list" placeholder="Search checks, root causes, services, actions" autocomplete="off" spellcheck="false"></div>' +
    '<div class="cmdk-list" id="cmdk-list" role="listbox"></div>' +
    '<div class="cmdk-foot"><span>&uarr;&darr; navigate</span><span>&crarr; select</span><span>esc close</span></div></div>';
  document.body.append(overlay);
  dlg = $(".cmdk", overlay); input = $("input", overlay); list = $(".cmdk-list", overlay);
  overlay.addEventListener("mousedown", (e) => { if (e.target === overlay) closePalette(); });
  input.addEventListener("input", render);
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); move(1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); move(-1); }
    else if (e.key === "Enter") { e.preventDefault(); choose(sel); }
    else if (e.key === "Escape") { e.preventDefault(); closePalette(); }
    else if (e.key === "Tab") { e.preventDefault(); }
  });
}
function render() {
  const q = input.value.trim().toLowerCase(), toks = q.split(/\s+/).filter(Boolean);
  let items = collect(q);
  const RANK = { "Root causes": 0, Services: 1, "Go to": 2, Checks: 3, Filter: 4, Actions: 5 };
  if (toks.length) items = items.map((it) => [it, score(it, toks)]).filter((x) => x[1] >= 0)
    .sort((a, b) => (RANK[a[0].g] - RANK[b[0].g]) || (b[1] - a[1])).map((x) => x[0]);
  else items = items.filter((it) => it.g !== "Filter");
  shown = items.slice(0, 40);
  list.textContent = "";
  if (!shown.length) { const e = document.createElement("div"); e.className = "cmdk-empty"; e.textContent = "No results."; list.append(e); return; }
  let last = "";
  shown.forEach((it, i) => {
    if (it.g !== last) { const g = document.createElement("div"); g.className = "cmdk-g"; g.textContent = it.g; list.append(g); last = it.g; }
    const b = document.createElement("button");
    b.type = "button"; b.className = "cmdk-i"; b.id = "cmdk-o" + i; b.setAttribute("role", "option"); b.tabIndex = -1;
    b.style.setProperty("--c", it.c || "var(--muted)");
    const dot = document.createElement("span"); dot.className = "cmdk-dot";
    const t = document.createElement("span"); t.className = "cmdk-t"; t.textContent = it.t;
    if (it.sub) { const s = document.createElement("small"); s.textContent = it.sub; t.append(s); }
    b.append(dot, t);
    b.addEventListener("mousemove", () => { if (sel !== i) { sel = i; mark(false); } });
    b.addEventListener("click", () => choose(i));
    list.append(b);
  });
  sel = 0; mark(false);
}
function mark(scrollIt) {
  $$(".cmdk-i", list).forEach((b, i) => b.setAttribute("aria-selected", String(i === sel)));
  const cur = $("#cmdk-o" + sel, list);
  input.setAttribute("aria-activedescendant", cur ? cur.id : "");
  if (cur && scrollIt) cur.scrollIntoView({ block: "nearest" });
}
function move(d) { if (!shown.length) return; sel = (sel + d + shown.length) % shown.length; mark(true); }
function choose(i) { const it = shown[i]; if (!it) return; closePalette(); setTimeout(it.run, 60); }
function openPalette() {
  if (!overlay) buildPalette();
  if (overlay.classList.contains("open")) return;
  opener = document.activeElement;
  input.value = ""; render();
  overlay.classList.add("open");
  go(overlay, { opacity: [0, 1] }, { duration: 0.16 });
  go(dlg, { opacity: [0, 1], scale: [0.96, 1], y: [-10, 0] }, { type: "spring", stiffness: 520, damping: 34 });
  input.focus();
}
function closePalette() {
  if (!overlay || !overlay.classList.contains("open")) return;
  const c = go(dlg, { opacity: 0, scale: 0.98, y: -6 }, { duration: 0.11 });
  go(overlay, { opacity: 0 }, { duration: 0.12 }).finished.then(() => {
    overlay.classList.remove("open");
    if (opener && opener.focus) opener.focus();
  });
  return c;
}
/* capture phase on window so it runs before the report's own Ctrl+K handler */
addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
    e.preventDefault(); e.stopImmediatePropagation();
    overlay && overlay.classList.contains("open") ? closePalette() : openPalette();
  }
}, true);

const tools = $(".tools");
if (tools) {
  const b = document.createElement("button");
  b.type = "button"; b.className = "btn cmdk-btn"; b.title = "Command menu"; b.setAttribute("aria-haspopup", "dialog");
  b.innerHTML = '<svg class="i" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg><span class="t">Command</span><kbd>' + (isMac ? "&#8984;K" : "Ctrl K") + "</kbd>";
  b.addEventListener("click", openPalette);
  tools.prepend(b);
}

/* ---------- donut: "circular progress bar" effect, plays on hover ----------
   Like the Lottie: a hair-line track, then thick glowing arcs drawn clockwise over it from
   12 o'clock. Every segment (passed, no effect, known, skipped ...) is drawn in turn, so the
   whole ring is covered. The centre number counts up with the passed arc. At rest the ring
   is complete; moving the cursor onto it replays the draw. */
(() => {
  const svg = $(".donut");
  if (!svg || reduce) return;
  const segs = $$(".seg-c", svg), dn = $(".d-n", svg);
  const C = parseFloat(svg.style.getPropertyValue("--C")) || 339.29;
  const info = segs.map((s) => ({
    s, L: parseFloat(s.style.getPropertyValue("--len")) || 0,
    start: -(parseFloat(s.style.getPropertyValue("--off")) || 0),
  }));
  segs.forEach((s) => s.style.setProperty("--g", s.style.stroke));
  const m = dn && dn.textContent.trim().match(/^(\d+(?:\.\d+)?)(.*)$/);
  const target = m ? parseFloat(m[1]) : null, suf = m ? m[2] : "";
  const main = info[0];
  let playing = false;
  svg.style.cursor = "pointer";
  svg.setAttribute("title", "Hover to replay");
  function frame(p) {
    const D = p * C;
    info.forEach((i) => {
      const len = Math.min(i.L, D - i.start);
      i.s.style.opacity = len > 0 ? 1 : 0;
      i.s.style.strokeDasharray = Math.max(0.01, len) + " " + C;
    });
    if (target !== null && main) dn.textContent = Math.round(target * Math.min(1, D / main.L)) + suf;
  }
  /* hovering a status chip plays the same draw, then keeps only that category's segment.
     A category with no segment on the ring (count 0) just plays the full default draw. */
  const MAP = { ok: "passed", bad: "failed", warn: "unused", suite: "suite", info: "known", neu: "skipped" };
  info.forEach((i) => { i.status = MAP[(i.s.style.stroke.match(/--(\w+)/) || [])[1]]; });
  const dl = $(".d-l", svg), dlOrig = dl ? dl.textContent : "";
  let hovered = null, focused = false;
  const swap = (n, l) => { dn.textContent = n; if (dl) dl.textContent = l; go([dn, dl].filter(Boolean), { opacity: [0, 1] }, { duration: 0.25 }); };
  function focusOn(status) {
    const chip = $('.chip[data-status-btn="' + status + '"]');
    if (!chip) return;
    focused = true;
    info.forEach((i) => { if (i.status !== status) animate(i.s, { opacity: 0 }, { duration: 0.4 }); });
    const n = $(".n", chip), c = counters.find((x) => x.el === n);
    swap(String(c ? c.to : parseInt(n.textContent, 10)), $(".l", chip).textContent.toLowerCase());
  }
  function release() {
    if (!focused) return;
    focused = false;
    info.forEach((i) => { animate(i.s, { opacity: 1 }, { duration: 0.35 }).finished.then(() => { if (!focused) i.s.style.opacity = ""; }); });
    if (target !== null) swap(m[0], dlOrig);
  }
  function play() {
    if (playing) return;
    release();
    playing = true;
    frame(0);
    animate(0, 1, { duration: 2.6, ease: [0.45, 0, 0.2, 1], onUpdate: frame }).finished.then(() => {
      info.forEach((i) => { i.s.style.opacity = ""; i.s.style.strokeDasharray = ""; });
      if (target !== null) dn.textContent = m[0];
      if (dl) dl.textContent = dlOrig;
      playing = false;
      if (hovered && info.some((i) => i.status === hovered)) focusOn(hovered);
    });
  }
  svg.addEventListener("pointerenter", play);
  $$(".chip[data-status-btn]").forEach((chip) => {
    chip.addEventListener("pointerenter", () => { hovered = chip.dataset.statusBtn; play(); });
    chip.addEventListener("pointerleave", () => { hovered = null; release(); });
  });
})();

/* ---------- overview choreography v2 ----------
   One sequence instead of independent reveals: verdict tile -> its icon pops (spring) and the
   headline blurs in -> ring tile -> chips fly in one by one, each with a share meter that grows
   along its bottom edge (width = share of all checks). A red verdict shakes its icon once.
   Verdict and ring tiles tilt a few degrees toward the cursor and spring back.
   Shift+R replays the whole sequence (prototype only, for judging the timing). */
(() => {
  const bento = $(".bento");
  if (!bento || reduce) return;
  const verdict = $(".t-verdict", bento), ring = $(".t-ring", bento);
  const chips = $$(".chip", bento);
  const cnt = (chip) => counters.find((c) => c.el === $(".n", chip));
  const total = chips.reduce((a, c) => a + (cnt(c) ? cnt(c).to : 0), 0) || 1;
  const meters = chips.map((chip) => {
    const c = cnt(chip);
    if (!c || !c.to) return null;
    const m = document.createElement("i");
    m.className = "meter";
    m.style.width = Math.max(6, (c.to / total) * 100) + "%";
    chip.append(m);
    return m;
  });
  const clean = (el) => { el.removeAttribute("data-reveal"); el.dataset.revealed = "1"; el.style.opacity = ""; el.style.transform = ""; };
  const BAD = document.documentElement.dataset.verdict === "bad";

  function play(replay) {
    const ico = $(".v-ico", verdict), h = $(".v-head h2", verdict), p = $(".v-head p", verdict);
    [verdict, ring].forEach((el, i) => el && animate(el, { opacity: [0, 1], y: [26, 0], scale: [0.97, 1] },
      { duration: 0.75, delay: i * 0.14, ease: EASE }).finished.then(() => clean(el)));
    if (ico) {
      animate(ico, { opacity: [0, 1], scale: [0.3, 1], rotate: [-28, 0] },
        { type: "spring", stiffness: 340, damping: 15, delay: 0.28 });
      if (BAD) animate(ico, { x: [0, -7, 7, -5, 5, 0] }, { duration: 0.5, delay: 0.85 });
    }
    if (h && p) animate([h, p], { opacity: [0, 1], y: [12, 0], filter: ["blur(8px)", "blur(0px)"] },
      { duration: 0.65, delay: stagger(0.09, { startDelay: 0.38 }), ease: EASE });
    chips.forEach((chip, i) => {
      animate(chip, { opacity: [0, 1], y: [18, 0], scale: [0.92, 1] },
        { duration: 0.55, delay: 0.5 + i * 0.07, ease: EASE }).finished.then(() => clean(chip));
      if (meters[i]) animate(meters[i], { scaleX: [0, 1] }, { duration: 1, delay: 0.75 + i * 0.07, ease: [0.16, 1, 0.3, 1] });
      const c = cnt(chip);
      if (replay && c) animate(0, c.to, { duration: 1.2, delay: 0.5 + i * 0.07, ease: [0.16, 1, 0.3, 1],
        onUpdate: (v) => { c.el.textContent = c.pre + v.toFixed(c.dec) + c.suf; } });
    });
  }
  inView(bento, () => { play(false); }, { amount: 0.25 });
  addEventListener("keydown", (e) => {
    if (e.shiftKey && e.key === "R" && !/^(INPUT|TEXTAREA)$/.test((e.target || {}).tagName)) {
      bento.scrollIntoView({ block: "center" });
      play(true);
    }
  });

  [verdict, ring].forEach((el) => {
    if (!el) return;
    el.addEventListener("pointermove", (e) => {
      const r = el.getBoundingClientRect();
      const px = (e.clientX - r.left) / r.width - 0.5, py = (e.clientY - r.top) / r.height - 0.5;
      animate(el, { rotateY: px * 7, rotateX: -py * 7, transformPerspective: 900 }, { duration: 0.3, ease: "easeOut" });
    }, { passive: true });
    el.addEventListener("pointerleave", () => { animate(el, { rotateX: 0, rotateY: 0 }, SPRING); });
  });
})();

/* ---------- section heading text: variable font weight shift ----------
   (reference: codefronts.com "Variable Font Weight Shift"). The weight itself is CSS-only (proto.css).
   Here each heading's own text is wrapped in one span carrying data-text, so a hidden bold twin
   (::after) can reserve the widest width and the heading never reflows while the weight changes. */
$$("main.content > section > h2").forEach((h) => {
  Array.from(h.childNodes).forEach((n) => {
    if (n.nodeType !== 3 || !n.textContent.trim()) return;
    const t = n.textContent.trim();
    const wrap = document.createElement("span");
    wrap.className = "h-t";
    wrap.dataset.text = t;
    wrap.textContent = t;
    n.replaceWith(wrap);
  });
});

window.__protoReady = true;
