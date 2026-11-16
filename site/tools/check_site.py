"""Check the built website before it is published. Standard library only.

    python site/build.py && python site/tools/check_site.py

Fails (exit 1) when:
- a page links to a local file that does not exist, or to an #anchor that is not on the page
- an <img> has no alt text, or no width and height (layout shift)
- parts.json points outside its .bin files
- a page asks another host for a script, a stylesheet, a font or an image
- the first view is heavier than the budget
"""
from __future__ import annotations

import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlparse

SITE = Path(__file__).resolve().parents[1]
BUDGET_FIRST_VIEW = 1_500_000        # bytes, uncompressed: page, CSS, fonts, poster, scripts, three.js, first part
FIRST_VIEW = ["index.html", "css/site.css", "fonts/InstrumentSans.woff2", "fonts/GeistMono.woff2", "assets/hero-poster.webp",
              "js/main.js", "js/hero.js", "js/viewer.js", "vendor/three.module.js", "vendor/OrbitControls.js",
              "assets/parts/parts.json", "assets/parts/dock.bin"]


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self.ids, self.imgs, self.remote = [], set(), [], []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get("id"):
            self.ids.add(a["id"])
        for key in ("href", "src"):
            if a.get(key):
                self.links.append((tag, a[key]))
        if tag == "source" and a.get("srcset"):
            self.links.append((tag, a["srcset"].split()[0]))
        if tag == "img":
            self.imgs.append(a)
        if tag in ("script", "img", "source") or (tag == "link" and a.get("rel") in ("stylesheet", "preload", "icon")):
            url = a.get("src") or a.get("href") or ""
            if re.match(r"^(https?:)?//", url):
                self.remote.append(url)


def main() -> int:
    errors: list[str] = []
    pages = sorted(SITE.glob("*.html")) + sorted((SITE / "docs").glob("*.html"))
    if not (SITE / "docs" / "index.html").exists():
        errors.append("site/docs is missing: run python site/build.py first")
    parsed = {}
    for f in pages:
        p = Page()
        p.feed(f.read_text(encoding="utf-8"))
        parsed[f] = p
    for f, p in parsed.items():
        rel = f.relative_to(SITE).as_posix()
        if rel == "404.html":
            continue                                   # served from any path, with <base href="/form-studio/">
        for tag, url in p.links:
            u = urlparse(url)
            if u.scheme or url.startswith("//"):
                continue
            target = f if not u.path else (f.parent / unquote(u.path)).resolve()
            if target.is_dir():
                target = target / "index.html"
            if not target.exists():
                errors.append(f"{rel}: <{tag}> points at a missing file: {url}")
            elif u.fragment and target in parsed and u.fragment not in parsed[target].ids:
                errors.append(f"{rel}: no element with id '{u.fragment}' for {url}")
        for img in p.imgs:
            src = img.get("src", "?")
            if "alt" not in img:
                errors.append(f"{rel}: image without alt text: {src}")
            if not (img.get("width") and img.get("height")):
                errors.append(f"{rel}: image without width and height: {src}")
        for url in p.remote:
            errors.append(f"{rel}: loads from another host: {url}")

    parts = SITE / "assets" / "parts"
    man = json.loads((parts / "parts.json").read_text(encoding="utf-8"))
    for part in man["parts"]:
        size = (parts / part["bin"]).stat().st_size
        if size != part["bytes"]:
            errors.append(f"{part['bin']}: {size} bytes, parts.json says {part['bytes']}")
        if not 8 <= len(part["steps"]) <= 13:
            errors.append(f"{part['id']}: {len(part['steps'])} builds, expected 8 to 13")
        for st in part["steps"]:
            end = max(st["v"][0] + st["v"][1] * 6, st["i"][0] + st["i"][1] * st["i"][2], st["e"][0] + st["e"][1] * 12)
            if end > size:
                errors.append(f"{part['id']} step {st['value']}: reads past the end of {part['bin']}")

    weight = sum((SITE / f).stat().st_size for f in FIRST_VIEW)
    if weight > BUDGET_FIRST_VIEW:
        errors.append(f"first view is {weight:,} bytes, over the {BUDGET_FIRST_VIEW:,} budget")

    for e in errors:
        print("FAIL", e)
    print(f"{len(pages)} pages, {sum(len(p.links) for p in parsed.values())} links, first view {weight:,} bytes uncompressed: "
          + ("ok" if not errors else f"{len(errors)} problem(s)"))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
