"""Check the built website before it is published. Standard library only.

    python site/build.py && python site/tools/check_site.py

Fails (exit 1) when:
- a page links to a local file that does not exist, or to an #anchor that is not on the page
- an <img> has no alt text, or no width and height (layout shift)
- the exported data (site.json, toolpath.bin) does not match its own layout
- a page asks another host for a script, a stylesheet, a font or an image
- the first view is heavier than the budget
- recipes/index.json is missing, or names a preview that is not published
"""
from __future__ import annotations

import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlparse

SITE = Path(__file__).resolve().parents[1]
BUDGET_FIRST_VIEW = 2_500_000        # bytes, uncompressed: page, CSS, fonts, scripts, three.js, the dock and its toolpath
FIRST_VIEW = ["index.html", "css/site.css", "fonts/InstrumentSans.woff2", "fonts/GeistMono.woff2", "fonts/lucide-form.woff2",
              "assets/lockup.svg", "js/main.js", "js/theme.js", "js/recipes.js", "js/data.js", "js/app.js", "js/scene.js", "js/demos.js",
              "vendor/three.module.js", "vendor/OrbitControls.js",
              "assets/data/site.json", "assets/data/dock.glb", "assets/data/toolpath.bin"]


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
    pages = sorted(SITE.glob("*.html")) + sorted((SITE / "docs").glob("*.html")) + sorted((SITE / "recipes").glob("*.html"))
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

    data = SITE / "assets" / "data"
    site = json.loads((data / "site.json").read_text(encoding="utf-8"))
    tp = site["dock"]["toolpath"]
    size = (data / "toolpath.bin").stat().st_size
    if size != tp["bytes"]:
        errors.append(f"toolpath.bin: {size} bytes, site.json says {tp['bytes']}")
    widths = {"points": 2, "run_count": 2, "run_type": 1, "layer_runs": 4}
    for name, (off, count) in tp["layout"].items():
        if off + count * widths[name] > size:
            errors.append(f"toolpath.bin: {name} reads past the end of the file")
    for glb in ("dock.glb", "box.glb"):
        head = (data / glb).read_bytes()[:12]
        if head[:4] != b"glTF":
            errors.append(f"{glb}: not a binary glTF file")

    idx = SITE / "recipes" / "index.json"
    if not idx.is_file():
        errors.append("recipes/index.json is missing: run python site/tools/build_recipe_index.py")
    else:
        d = json.loads(idx.read_text(encoding="utf-8"))
        if d.get("version") != 1 or not d.get("recipes"):
            errors.append("recipes/index.json: expected version 1 and at least one recipe")
        for r in d.get("recipes", []):
            if r.get("preview"):
                local = SITE / "recipes" / "previews" / r["preview"].rsplit("/", 1)[-1]
                if not local.is_file():
                    errors.append(f"recipes/index.json: {r['id']} preview is not in site/recipes/previews")

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
