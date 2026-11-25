"""Check the built website before it is published. Standard library only.

    python site/build.py && python site/tools/check_site.py

Fails (exit 1) when:
- a page links to a local file that does not exist, or to an #anchor that is not on the page
- an <img> has no alt text, or no width and height (layout shift)
- the exported data (site.json, toolpath.bin) does not match its own layout, or shows a slice the sample does not have
- a page asks another host for a script, a stylesheet, a font or an image
- the first view is heavier than the budget
- the site holds a video, a GIF or an animated image (the app is drawn in code instead)
- a page's navigation bar or footer differs from the shared one in site/tools/chrome.py
"""
from __future__ import annotations

import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlparse

SITE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import chrome  # noqa: E402  the shared nav and footer, and what counts as moving media
BUDGET_FIRST_VIEW = 2_500_000        # bytes, uncompressed: page, CSS, fonts, scripts and the drawn app in the hero
FIRST_VIEW = ["index.html", "css/site.css", "fonts/InstrumentSans.woff2", "fonts/GeistMono.woff2", "fonts/lucide-form.woff2",
              "assets/lockup.svg", "js/main.js", "js/nav.js", "js/theme.js", "js/motion.js", "js/data.js", "js/app.js",
              "js/scene.js", "vendor/three.module.js", "vendor/OrbitControls.js", "assets/data/site.json",
              "assets/data/sample.glb", "assets/data/toolpath.bin"]
# the drawn app loads when it comes near: three.js, the sample project and its toolpath
BUDGET_APP = 2_500_000
APP_VIEW = [f for f in ["js/app.js", "js/scene.js", "vendor/three.module.js", "vendor/OrbitControls.js",
            "assets/data/site.json", "assets/data/sample.glb", "assets/data/toolpath.bin"] if (SITE / f).exists()]


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
    pages += sorted((SITE / "compat").glob("*.html")) + sorted((SITE / "bench").glob("*.html")) + sorted((SITE / "measure").glob("*.html"))
    if not (SITE / "docs" / "index.html").exists():
        errors.append("site/docs is missing: run python site/build.py first")
    # the number of MCP tools on the home page is the one docs/MCP.md states (scripts/gen_mcp_docs.py writes it)
    m = re.search(r"^(\d+) tools\.", (SITE.parent / "docs" / "MCP.md").read_text(encoding="utf-8"), re.M)
    shown = re.search(r'id="why-tools"[^>]*>(\d+)<|data-count="(\d+)" id="why-tools"', (SITE / "index.html").read_text(encoding="utf-8"))
    if m and shown and (shown.group(1) or shown.group(2)) != m.group(1):
        errors.append(f"index.html says {shown.group(1) or shown.group(2)} MCP tools; docs/MCP.md says {m.group(1)}")
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
    sample = site["sample"]
    tp = sample.get("toolpath")
    if bool(tp) != bool(sample.get("slice_meta")) or bool(tp) != (data / "toolpath.bin").exists():
        errors.append("site.json: a toolpath is published only with a slice, and toolpath.bin only with both")
    if tp and sample.get("purpose") != "print":
        errors.append("site.json: the sample has a slice but is not a print design")
    if tp:
        size = (data / "toolpath.bin").stat().st_size
        if size != tp["bytes"]:
            errors.append(f"toolpath.bin: {size} bytes, site.json says {tp['bytes']}")
        widths = {"points": 2, "run_count": 2, "run_type": 1, "layer_runs": 4}
        for name, (off, count) in tp["layout"].items():
            if off + count * widths[name] > size:
                errors.append(f"toolpath.bin: {name} reads past the end of the file")
    for glb in ("sample.glb", "box.glb"):
        head = (data / glb).read_bytes()[:12]
        if head[:4] != b"glTF":
            errors.append(f"{glb}: not a binary glTF file")

    # the app is drawn in code: no video, GIF or animated image anywhere on the site
    for f in SITE.rglob("*"):
        if f.is_file() and ".venv" not in f.parts and chrome.is_moving(f.name, f.read_bytes()[:4096]):
            errors.append(f"{f.relative_to(SITE).as_posix()}: video or animated image; draw the app in code instead")
    for f in pages:
        if re.search(r"<video\b", f.read_text(encoding="utf-8")):
            errors.append(f"{f.relative_to(SITE).as_posix()}: has a <video>; draw the app in code instead")

    # one navigation bar and one footer, the same on every page (site/tools/chrome.py)
    for f in pages:
        rel = f.relative_to(SITE).as_posix()
        text = f.read_text(encoding="utf-8")
        want = chrome.expected(rel)
        if rel.startswith("docs/"):
            want = (chrome.nav("../", "docs"), chrome.foot("../"))
        if want is None:
            errors.append(f"{rel}: not in site/tools/chrome.py STAMPED, so it has no shared nav")
            continue
        for part, name in zip(want, ("nav", "footer")):
            if part not in text:
                errors.append(f"{rel}: the shared {name} is missing or out of date: run python site/build.py")

    weight = sum((SITE / f).stat().st_size for f in FIRST_VIEW)
    if weight > BUDGET_FIRST_VIEW:
        errors.append(f"first view is {weight:,} bytes, over the {BUDGET_FIRST_VIEW:,} budget")
    app = sum((SITE / f).stat().st_size for f in APP_VIEW)
    if app > BUDGET_APP:
        errors.append(f"the drawn app is {app:,} bytes, over the {BUDGET_APP:,} budget")

    for e in errors:
        print("FAIL", e)
    print(f"{len(pages)} pages, {sum(len(p.links) for p in parsed.values())} links, first view {weight:,} bytes uncompressed: "
          + ("ok" if not errors else f"{len(errors)} problem(s)"))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
