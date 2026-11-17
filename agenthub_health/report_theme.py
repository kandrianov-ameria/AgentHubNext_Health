"""Visual layer of the report (since 1.7.0): shadcn "zinc" tokens, aurora bento, floating glass
shell, and Motion (motion.dev) animation.

report.py renders the report as before; apply() then adds, on top of that finished HTML:
  * report_assets/proto.css   - a CSS layer loaded after the report's own CSS
  * report_assets/proto.js    - an ES module (Motion from jsDelivr) for reveals, counters, the
                                sliding nav/filter thumbs, the Ctrl+K command palette, toasts and
                                the donut animation (plays on hover of the ring or of a status chip)
  * Geist / Geist Mono from Google Fonts, plus `data-reveal` marks on what animates in on scroll.

The report's own script (filters, copy, theme, scroll-spy) is untouched and keeps working.
If Motion cannot be loaded (offline), a fail-safe removes the `js-motion` class after 2.5 s and the
page falls back to plain CSS, fully visible. Motion is the only script loaded from outside.
"""
import re
from pathlib import Path

ASSETS = Path(__file__).resolve().parent / "report_assets"

_EARLY = (
    '<link href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700'
    '&family=Geist+Mono:wght@400;500;600&display=swap" rel="stylesheet">\n'
    "<script>(function(){var d=document.documentElement;"
    "if(!(window.matchMedia&&matchMedia('(prefers-reduced-motion: reduce)').matches)){"
    "d.classList.add('js-motion');"
    "setTimeout(function(){if(!window.__protoReady){d.classList.remove('js-motion');}},2500);}})();</script>\n"
)

# Elements that fade in on scroll. The attribute goes right after the tag name.
_REVEAL = [
    r'<header class="top"',
    r'<aside class="side"',
    r'<div class="tile ',
    r'<button type="button" class="chip',
    r'<button type="button" class="svc ',
    r'<details class="card',
    r'<details class="group"',
]


def apply(html: str) -> str:
    """Return the report HTML with the visual layer added. Never raises for a missing asset:
    the plain report is returned instead."""
    try:
        css = (ASSETS / "proto.css").read_text(encoding="utf-8")
        js = (ASSETS / "proto.js").read_text(encoding="utf-8")
    except OSError:
        return html
    html = re.sub(r"<title>.*?</title>", lambda m: m.group(0) + "\n" + _EARLY, html, count=1, flags=re.S)
    html = html.replace("</style>", '</style>\n<style id="theme-layer">\n' + css + "\n</style>", 1)
    for p in _REVEAL:
        html = re.sub("<(\\w+)( " + p.split(" ", 1)[1] + ")", r"<\1 data-reveal\2", html)
    html = re.sub(r"(<section[^>]*>\s*)<h2>", r"\1<h2 data-reveal>", html)
    html = re.sub(r'(</h2>\s*)<p class="sub">', r'\1<p class="sub" data-reveal>', html)
    return html.replace("</body>", '<script type="module">\n' + js + "\n</script>\n</body>", 1)
