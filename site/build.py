"""Build the /docs pages of the Form Studio website from the repository's markdown.

    python site/build.py            (needs the `markdown` package: pip install markdown)

Reads the markdown listed in PAGES and writes site/docs/*.html, site/sitemap.xml and site/robots.txt. The home
page and the recipe gallery are hand-written and are not touched. The GitHub Pages workflow runs this before it
uploads site/.
"""
from __future__ import annotations

import datetime as _dt
import html
import posixpath
import re
import shutil
import sys
from pathlib import Path

try:
    import markdown
except ImportError:                                    # pragma: no cover
    sys.exit("site/build.py needs the 'markdown' package. Install it with: pip install markdown")

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
OUT = SITE / "docs"
BASE = "https://kaizensx.github.io/form-studio/"
REPO = "https://github.com/kaizensx/form-studio"

# slug, source, nav title, one line for the index
PAGES = [
    ("features", "docs/FEATURES.md", "Features", "Everything Form Studio does, from the first message to the release."),
    ("app", "docs/APP.md", "The desktop app", "Install, the window, the five stages, keys and settings."),
    ("cli", "docs/CLI.md", "Command line", "Every form command, with its arguments."),
    ("mcp", "docs/MCP.md", "MCP tools", "Every tool an agent can call, generated from the server itself."),
    ("recipes", "docs/RECIPES.md", "Writing a recipe", "Parameters, features, constraints, fit and tests."),
    ("architecture", "docs/ARCHITECTURE.md", "Architecture", "The engine, the kernel worker, adapters, staleness and the fit model."),
    ("verification", "docs/VERIFICATION.md", "Compatibility", "Platforms, slicers, agents and programs, and what CI exercises."),
    ("changelog", "CHANGELOG.md", "Changelog", "What changed in each version."),
]
BY_SOURCE = {src: slug for slug, src, _, _ in PAGES}

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} · Form Studio docs</title>
<meta name="description" content="{desc}">
<meta name="theme-color" content="#0e1113" media="(prefers-color-scheme: dark)">
<meta name="theme-color" content="#f5f6f4" media="(prefers-color-scheme: light)">
<link rel="canonical" href="{base}docs/{file}">
<meta property="og:type" content="article">
<meta property="og:site_name" content="Form Studio">
<meta property="og:title" content="{title} · Form Studio docs">
<meta property="og:description" content="{desc}">
<meta property="og:image" content="{base}assets/og.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="../favicon.ico" sizes="48x48">
<link rel="icon" type="image/svg+xml" href="../assets/favicon.svg">
<link rel="icon" type="image/png" href="../assets/favicon.png">
<link rel="apple-touch-icon" href="../assets/apple-touch-icon.png">
<link rel="manifest" href="../manifest.webmanifest">
<link rel="preload" href="../fonts/InstrumentSans.woff2" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="../css/site.css">
<script>document.documentElement.classList.add("js");try{{var t=localStorage.getItem("theme");if(t==="light"||t==="dark")document.documentElement.dataset.theme=t}}catch(e){{}}</script>
<script type="module">import {{ initTheme }} from "../js/theme.js"; initTheme(document.getElementById("theme"));</script>
</head>
<body>
<svg width="0" height="0" style="position:absolute" aria-hidden="true" focusable="false"><defs>
<symbol id="ic-sun" viewBox="0 0 24 24"><circle cx="12" cy="12" r="4"/><path d="M12 2.5v2.2M12 19.3v2.2M2.5 12h2.2M19.3 12h2.2M5.3 5.3l1.6 1.6M17.1 17.1l1.6 1.6M5.3 18.7l1.6-1.6M17.1 6.9l1.6-1.6"/></symbol>
<symbol id="ic-moon" viewBox="0 0 24 24"><path d="M19.5 14.5A8 8 0 019.5 4.5a8 8 0 1010 10z"/></symbol>
<symbol id="ic-gh" viewBox="0 0 24 24"><path d="M9 19c-4 1.3-4-2-6-2.5m12 4.5v-3.4a3 3 0 00-.8-2.3c2.7-.3 5.5-1.3 5.5-6a4.6 4.6 0 00-1.3-3.2 4.3 4.3 0 00-.1-3.2s-1-.3-3.4 1.3a11.6 11.6 0 00-6 0C6.5 2.6 5.5 2.9 5.5 2.9a4.3 4.3 0 00-.1 3.2A4.6 4.6 0 004 9.3c0 4.6 2.8 5.6 5.5 6a3 3 0 00-.8 2.3V21"/></symbol>
</defs></svg>
<a class="skip" href="#main">Skip to content</a>
<header class="nav scrolled">
  <div class="wrap">
    <a class="brand" href="../"><img class="lk-d" src="../assets/lockup.svg" alt="Form Studio" width="143" height="22"><img class="lk-l" src="../assets/lockup-light.svg" alt="" width="143" height="22"></a>
    <ul class="nav-links">
      <li><a href="../#features">Features</a></li>
      <li><a href="../#agents">Agents</a></li>
      <li><a href="../recipes/">Recipes</a></li>
      <li><a href="./" aria-current="page">Docs</a></li>
      <li><a href="../#community">Community</a></li>
    </ul>
    <div class="end">
      <button class="theme" type="button" id="theme" aria-label="Switch between light and dark"><svg class="ic sun" aria-hidden="true"><use href="#ic-sun"/></svg><svg class="ic moon" aria-hidden="true"><use href="#ic-moon"/></svg></button>
      <a class="gh" href="{repo}"><svg class="ic" aria-hidden="true"><use href="#ic-gh"/></svg><span>GitHub</span></a>
      <a class="btn primary small" href="../#download">Download</a>
    </div>
  </div>
</header>
<div class="wrap docs">
  <nav class="docs-nav" aria-label="Docs">
    <span class="cap">Docs</span>
    <ul>
{nav}
    </ul>
    {src}
  </nav>
  <main id="main" class="prose">
{body}
  </main>
</div>
<footer class="foot">
  <div class="wrap">
    <div class="foot-top">
      <div class="foot-brand">
        <a class="brand" href="../"><img class="lk-d" src="../assets/lockup.svg" alt="Form Studio" width="143" height="22"><img class="lk-l" src="../assets/lockup-light.svg" alt="" width="143" height="22"></a>
        <p>Describe a part. Get a file you can print. Open source, MIT licence.</p>
      </div>
      <nav aria-label="Product"><span class="cap">Product</span><a href="../#features">Features</a><a href="../#tour">Tour</a><a href="../#agents">Agents and slicers</a><a href="../recipes/">Recipes</a><a href="../#download">Download</a></nav>
      <nav aria-label="Docs"><span class="cap">Docs</span><a href="features.html">Features</a><a href="app.html">The app</a><a href="cli.html">Command line</a><a href="mcp.html">MCP tools</a><a href="changelog.html">Changelog</a></nav>
      <nav aria-label="Community"><span class="cap">Community</span><a href="{repo}/discussions">Discussions</a><a href="{repo}/issues/new/choose">Report an issue</a><a href="{repo}/blob/main/CONTRIBUTING.md">Contributing</a><a href="{repo}">GitHub</a></nav>
    </div>
    <p class="foot-note">No cookies, trackers or third-party requests. These pages are generated from the repository’s markdown.</p>
  </div>
</footer>
</body>
</html>
"""


def nav(current: str) -> str:
    rows = [("index", "Overview")] + [(slug, title) for slug, _, title, _ in PAGES]
    out = []
    for slug, title in rows:
        href = "./" if slug == "index" else f"{slug}.html"
        cur = ' aria-current="page"' if slug == current else ""
        out.append(f'      <li><a href="{href}"{cur}>{html.escape(title)}</a></li>')
    return "\n".join(out)


def image_size(f: Path) -> tuple[int, int] | None:
    """Width and height of a PNG, GIF or WebP file, from its header (standard library only)."""
    b = f.read_bytes()[:40]
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return int.from_bytes(b[16:20], "big"), int.from_bytes(b[20:24], "big")
    if b[:6] in (b"GIF87a", b"GIF89a"):
        return int.from_bytes(b[6:8], "little"), int.from_bytes(b[8:10], "little")
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        kind = b[12:16]
        if kind == b"VP8X":
            return 1 + int.from_bytes(b[24:27], "little"), 1 + int.from_bytes(b[27:30], "little")
        if kind == b"VP8 ":
            return int.from_bytes(b[26:28], "little") & 0x3FFF, int.from_bytes(b[28:30], "little") & 0x3FFF
        if kind == b"VP8L":
            v = int.from_bytes(b[21:25], "little")
            return (v & 0x3FFF) + 1, ((v >> 14) & 0x3FFF) + 1
    return None


def rewrite(body: str, source: str) -> str:
    """Point relative links at the generated pages or at GitHub, and copy local images next to the pages."""
    here = posixpath.dirname(source)

    def link(m: re.Match) -> str:
        attr, url = m.group(1), m.group(2)
        if re.match(r"^(?:[a-z][a-z0-9+.-]*:|#|//)", url, re.I):
            return m.group(0)
        path, _, frag = url.partition("#")
        target = posixpath.normpath(posixpath.join(here, path)) if path else source
        frag = "#" + frag if frag else ""
        if attr == "src":
            f = ROOT / target
            if f.is_file():
                (OUT / "media").mkdir(parents=True, exist_ok=True)
                shutil.copy(f, OUT / "media" / f.name)
                wh = image_size(f)
                size = f' width="{wh[0]}" height="{wh[1]}"' if wh else ""
                return f'src="media/{f.name}"{size} loading="lazy" decoding="async"'
            return f'src="{REPO}/raw/main/{target}"'
        if target in BY_SOURCE:
            return f'href="{BY_SOURCE[target]}.html{frag}"'
        kind = "tree" if (ROOT / target).is_dir() else "blob"
        return f'href="{REPO}/{kind}/main/{target}{frag}"'

    body = re.sub(r'\b(href|src)="([^"]+)"', link, body)
    body = re.sub(r"<table>", '<div class="tablewrap"><table>', body)
    body = body.replace("</table>", "</table></div>")
    body = re.sub(r'<pre><code class="language-[\w-]+">', '<pre tabindex="0"><code>', body)
    body = body.replace("<pre><code>", '<pre tabindex="0"><code>')
    return body


def render(text: str) -> str:
    md = markdown.Markdown(extensions=["tables", "fenced_code", "sane_lists", "toc"], output_format="html")
    return md.convert(text)


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    urls = ["", "docs/", "recipes/"]
    for slug, source, title, desc in PAGES:
        text = (ROOT / source).read_text(encoding="utf-8")
        body = rewrite(render(text), source)
        src = f'<p class="src">Source: <a href="{REPO}/blob/main/{source}">{source}</a></p>'
        page = PAGE.format(title=html.escape(title), desc=html.escape(desc), file=f"{slug}.html", base=BASE, repo=REPO,
                           nav=nav(slug), src=src, body=body)
        (OUT / f"{slug}.html").write_text(page, encoding="utf-8")
        urls.append(f"docs/{slug}.html")
        print("docs", slug, "<-", source)

    items = "\n".join(f'<li><a href="{slug}.html"><b>{html.escape(title)}</b><span>{html.escape(desc)}</span></a></li>'
                      for slug, _, title, desc in PAGES)
    index = (f"<h1>Documentation</h1>\n<p class=\"lede\">How to use Form Studio, from the desktop app to the command line and the "
             f'MCP server, and how to extend it with recipes. Spotted something wrong? <a href="{REPO}/issues/new?template=6-docs.yml">Tell us</a>.</p>\n'
             f'<ul class="docs-index">\n{items}\n</ul>')
    (OUT / "index.html").write_text(PAGE.format(title="Docs", desc="Form Studio documentation: features, the desktop app, the command line, MCP tools, recipes, architecture and compatibility.",
                                                file="", base=BASE, repo=REPO, nav=nav("index"), src="", body=index), encoding="utf-8")

    today = _dt.date.today().isoformat()
    sm = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    sm += [f"  <url><loc>{BASE}{u}</loc><lastmod>{today}</lastmod></url>" for u in urls]
    sm.append("</urlset>")
    (SITE / "sitemap.xml").write_text("\n".join(sm) + "\n", encoding="utf-8")
    (SITE / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {BASE}sitemap.xml\n", encoding="utf-8")
    print("wrote", OUT, "and sitemap.xml")
    return 0


if __name__ == "__main__":
    sys.exit(main())
