"""Build the /docs pages of the FORM website from the repository's markdown.

    python site/build.py            (needs the `markdown` package: pip install markdown)

Reads docs/APP.md, docs/MCP.md, docs/RECIPES.md, docs/NORTH_STAR.md, docs/VERIFICATION.md and CHANGELOG.md,
and writes site/docs/*.html and site/sitemap.xml. The home page (site/index.html) is hand-written and is
not touched. The GitHub Pages workflow runs this before it uploads site/.
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
    ("app", "docs/APP.md", "The desktop app", "Run it, what you see, the keys, what it will not do."),
    ("mcp", "docs/MCP.md", "MCP tools", "Every tool an agent can call, generated from the server itself."),
    ("recipes", "docs/RECIPES.md", "Writing a recipe", "Parameters, features, constraints, fit and tests."),
    ("verification", "docs/VERIFICATION.md", "Verification", "What was tested, on what, and what was not run."),
    ("north-star", "docs/NORTH_STAR.md", "North star", "The brief every contributor works from."),
    ("changelog", "CHANGELOG.md", "Changelog", "What changed in each version."),
]
BY_SOURCE = {src: slug for slug, src, _, _ in PAGES}

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} · FORM docs</title>
<meta name="description" content="{desc}">
<meta name="theme-color" content="#0e1113">
<link rel="canonical" href="{base}docs/{file}">
<meta property="og:type" content="article">
<meta property="og:site_name" content="FORM">
<meta property="og:title" content="{title} · FORM docs">
<meta property="og:description" content="{desc}">
<meta property="og:image" content="{base}assets/og.png">
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="../favicon.ico" sizes="48x48">
<link rel="icon" type="image/png" href="../assets/favicon.png">
<link rel="preload" href="../fonts/InstrumentSans.woff2" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="../css/site.css">
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
<header class="nav scrolled">
  <div class="wrap">
    <a class="mark" href="../" aria-label="FORM, home">FORM</a>
    <ul class="nav-links">
      <li><a href="../#how">How it works</a></li>
      <li><a href="../#app">The app</a></li>
      <li><a href="../#works-with">Works with</a></li>
      <li><a href="../#agents">For agents</a></li>
      <li><a href="./" aria-current="page">Docs</a></li>
      <li><a href="{repo}">GitHub</a></li>
    </ul>
    <a class="nav-docs" href="./" aria-current="page">Docs</a>
    <a class="btn primary small" href="../#get">Download</a>
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
    <a class="mark" href="../">FORM</a>
    <nav aria-label="Footer">
      <a href="./">Docs</a>
      <a href="changelog.html">Changelog</a>
      <a href="{repo}">GitHub</a>
      <a href="{repo}/issues">Issues</a>
      <a href="{repo}/blob/main/LICENSE">MIT licence</a>
    </nav>
    <p>This site sets no cookies and loads no trackers, analytics or third-party fonts. These pages are generated from the markdown in the repository.</p>
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
                return f'src="media/{f.name}"'
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
    urls = ["", "docs/"]
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
    index = (f"<h1>Docs</h1>\n<p>These pages are the repository's own markdown, built with the site. "
             f"If a page and the code disagree, the code is right and the page has a bug: "
             f'<a href="{REPO}/issues">please report it</a>.</p>\n<ul class="docs-index">\n{items}\n</ul>')
    (OUT / "index.html").write_text(PAGE.format(title="Docs", desc="FORM documentation: the app, MCP tools, recipes, verification.",
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
