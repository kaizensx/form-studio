"""The website's shared chrome: one navigation bar and one footer for every page. Standard library only.

site/build.py writes them into the generated docs pages and stamps them into the hand-written pages between
<!--nav-->...<!--/nav--> and <!--foot-->...<!--/foot-->, so every page carries the same menu. site/tools/check_site.py
fails when a page's copy differs from what this module produces.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = "https://github.com/kaizensx/form-studio"

# key, label, path from the site root; a list instead of a path is a group (a menu in the bar, a section in the sheet)
LINKS = [
    ("make", "What it makes", "#make"),
    ("how", "How it works", "#how"),
    ("agent", "Your agent", "#agent"),
    ("recipes", "Recipes", "recipes/"),
    ("docs", "Docs", "docs/"),
]

ICONS = """<svg width="0" height="0" style="position:absolute" aria-hidden="true" focusable="false"><defs>
<symbol id="ic-sun" viewBox="0 0 24 24"><circle cx="12" cy="12" r="4"/><path d="M12 2.5v2.2M12 19.3v2.2M2.5 12h2.2M19.3 12h2.2M5.3 5.3l1.6 1.6M17.1 17.1l1.6 1.6M5.3 18.7l1.6-1.6M17.1 6.9l1.6-1.6"/></symbol>
<symbol id="ic-chev" viewBox="0 0 24 24"><path d="M6.5 9.5l5.5 5.5 5.5-5.5"/></symbol>
<symbol id="ic-moon" viewBox="0 0 24 24"><path d="M19.5 14.5A8 8 0 019.5 4.5a8 8 0 1010 10z"/></symbol>
<symbol id="ic-gh" viewBox="0 0 24 24"><path d="M9 19c-4 1.3-4-2-6-2.5m12 4.5v-3.4a3 3 0 00-.8-2.3c2.7-.3 5.5-1.3 5.5-6a4.6 4.6 0 00-1.3-3.2 4.3 4.3 0 00-.1-3.2s-1-.3-3.4 1.3a11.6 11.6 0 00-6 0C6.5 2.6 5.5 2.9 5.5 2.9a4.3 4.3 0 00-.1 3.2A4.6 4.6 0 004 9.3c0 4.6 2.8 5.6 5.5 6a3 3 0 00-.8 2.3V21"/></symbol>
<symbol id="ic-dc" viewBox="0 0 24 24"><path d="M8.5 7.5a12 12 0 017 0M7 17c3 1.3 7 1.3 10 0M8.6 4.8A16 16 0 004.5 6.5C2.8 9.4 2 12.5 2.3 16.2a15.6 15.6 0 004.8 2.3l1.1-1.9M15.4 4.8a16 16 0 014.1 1.7c1.7 2.9 2.5 6 2.2 9.7a15.6 15.6 0 01-4.8 2.3l-1.1-1.9"/><circle cx="9" cy="12.5" r="1.2"/><circle cx="15" cy="12.5" r="1.2"/></symbol>
</defs></svg>"""


MOVING_EXT = (".gif", ".mp4", ".webm", ".mov", ".m4v", ".ogv", ".apng")


def is_moving(name: str, data: bytes) -> bool:
    """True for video, GIF and animated WebP or PNG. The website never shows them: the app is drawn in code."""
    low = name.lower()
    if low.endswith(MOVING_EXT):
        return True
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return b"ANIM" in data[12:4096]
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return b"acTL" in data[:4096]
    return False


def _href(prefix: str, path: str) -> str:
    if path.startswith("#"):
        return f"{prefix or './'}{path}"
    return f"{prefix}{path}"


def nav(prefix: str, current: str = "") -> str:
    """The top bar. prefix leads from the page to the site root ("" at the root, "../" one level down)."""
    cur = ' aria-current="page"'

    def link(key, label, path):
        return f'<li><a href="{_href(prefix, path)}"{cur if key == current else ""}>{label}</a></li>'

    items, sheet = "", ""
    for key, label, path in LINKS:
        if isinstance(path, list):
            inner = "".join(link(*sub) for sub in path)
            here = ' data-current="1"' if any(sub[0] == current for sub in path) else ""
            items += (f'<li class="grp"{here}><button type="button" class="grp-btn" aria-expanded="false" '
                      f'aria-controls="grp-{key}">{label}<svg class="ic chev" aria-hidden="true"><use href="#ic-chev"/></svg></button>'
                      f'<ul class="grp-menu" id="grp-{key}">{inner}</ul></li>')
            sheet += f'<li class="grp-cap"><span>{label}</span><ul>{inner}</ul></li>'
        else:
            items += link(key, label, path)
            sheet += link(key, label, path)
    home = prefix or "./"
    return f"""<!--nav-->
{ICONS}
<a class="skip" href="#main">Skip to content</a>
<header class="nav" id="nav">
  <div class="wrap">
    <a class="brand" href="{home}"><img class="lk-d" src="{prefix}assets/lockup.svg" alt="Form Studio" width="143" height="22"><img class="lk-l" src="{prefix}assets/lockup-light.svg" alt="" width="143" height="22"></a>
    <nav class="nav-links" aria-label="Site"><ul>{items}</ul></nav>
    <div class="end">
      <button class="theme" type="button" id="theme" aria-label="Switch between light and dark"><svg class="ic sun" aria-hidden="true"><use href="#ic-sun"/></svg><svg class="ic moon" aria-hidden="true"><use href="#ic-moon"/></svg></button>
      <a class="gh" href="https://discord.gg/b6ZgyndkmS"><svg class="ic" aria-hidden="true"><use href="#ic-dc"/></svg><span>Discord</span></a>
      <a class="gh" href="{REPO}"><svg class="ic" aria-hidden="true"><use href="#ic-gh"/></svg><span>GitHub</span></a>
      <a class="btn primary small dl-btn" href="{home}#download">Download</a>
      <button class="menu-btn" type="button" id="menu-btn" aria-expanded="false" aria-controls="menu" aria-label="Menu"><i></i><i></i></button>
    </div>
  </div>
  <div class="menu" id="menu" hidden>
    <ul>{sheet}<li><a href="https://discord.gg/b6ZgyndkmS">Discord</a></li><li><a href="{REPO}">GitHub</a></li></ul>
  </div>
  <span class="scrolled-bar" id="scroll-bar" aria-hidden="true"></span>
</header>
<!--/nav-->"""


def foot(prefix: str) -> str:
    home = prefix or "./"
    return f"""<!--foot-->
<footer class="foot">
  <div class="wrap">
    <div class="foot-top">
      <div class="foot-brand">
        <a class="brand" href="{home}"><img class="lk-d" src="{prefix}assets/lockup.svg" alt="Form Studio" width="143" height="22"><img class="lk-l" src="{prefix}assets/lockup-light.svg" alt="" width="143" height="22"></a>
        <p>Describe anything. The open-source AI CAD studio, MIT licence.</p>
      </div>
      <nav aria-label="Product"><span class="cap">Product</span><a href="{home}#make">What it makes</a><a href="{home}#how">How it works</a><a href="{home}#agent">Your agent</a><a href="{prefix}recipes/">Recipes</a><a href="{home}#download">Download</a></nav>
      <nav aria-label="Measured"><span class="cap">Measured</span><a href="{prefix}measure/">How we measure</a><a href="{prefix}bench/">Build timings</a><a href="{prefix}compat/">Slicer compatibility</a></nav>
      <nav aria-label="Docs"><span class="cap">Docs</span><a href="{prefix}docs/features.html">Features</a><a href="{prefix}docs/app.html">The app</a><a href="{prefix}docs/cli.html">Command line</a><a href="{prefix}docs/mcp.html">MCP tools</a><a href="{prefix}docs/changelog.html">Changelog</a></nav>
      <nav aria-label="Community"><span class="cap">Community</span><a href="https://discord.gg/b6ZgyndkmS">Discord</a><a href="{REPO}/discussions">Discussions</a><a href="{REPO}/issues/new?template=3-recipe.yml">Share a recipe</a><a href="{REPO}/issues/new/choose">Report an issue</a><a href="{REPO}/blob/main/CONTRIBUTING.md">Contributing</a></nav>
    </div>
    <p class="foot-note">No cookies, trackers or third-party requests. Form Studio runs on your computer; it never uploads a design and never sends a file to a machine.</p>
  </div>
</footer>
<!--/foot-->"""


# hand-written pages: path from site/, prefix to the root, current nav key
STAMPED = [
    ("index.html", "", ""),
    ("recipes/index.html", "../", "recipes"),
    ("compat/index.html", "../", "compat"),
    ("bench/index.html", "../", "bench"),
    ("measure/index.html", "../", "measure"),
    ("404.html", "", ""),                       # served from any path, with <base href="/form-studio/">
]


def expected(rel: str) -> tuple[str, str] | None:
    for path, prefix, cur in STAMPED:
        if path == rel:
            return nav(prefix, cur), foot(prefix)
    return None


def stamp(site: Path) -> list[str]:
    """Write the shared nav and footer into each hand-written page. Returns the pages it changed."""
    changed = []
    for path, prefix, cur in STAMPED:
        f = site / path
        text = f.read_text(encoding="utf-8")
        new = re.sub(r"<!--nav-->.*?<!--/nav-->", lambda _m: nav(prefix, cur), text, count=1, flags=re.S)
        new = re.sub(r"<!--foot-->.*?<!--/foot-->", lambda _m: foot(prefix), new, count=1, flags=re.S)
        if new != text:
            f.write_text(new, encoding="utf-8")
            changed.append(path)
    return changed
