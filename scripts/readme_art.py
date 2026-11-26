#!/usr/bin/env python3
"""The README's pictures, drawn as animated SVG from a real run of the engine.

Every part, number and check in these drawings comes from a run on this machine:

  1. four designs are built in a scratch projects folder: one from a recipe (`form new`), one from an exemplar's
     design code as a print design (form/exemplars/planetary_gearbox.py, sliced by your slicer), and two written as
     build123d code the way an agent writes them (scripts/readme_designs/, through create_design, as plain 3D
     models), so the CAD kernel builds the solids and the checks run on them;
  2. the triangle meshes and B-rep edges are read from the engine (`Studio.view`) and projected with the
     viewport's orbit camera (Viewport.qml: orbit angles, 26° field of view);
  3. check names and results, derived values (gear ratios), the assembly joint and its sweep come from the same run;
     the slicer layer is the slicer's G-code, read by form/toolpath.py; the file hashes are SHA-256 of the exported
     files; the terminal lines are what `form state` printed. The gears turn by their own tooth counts.

Colours are Lightdesk's (docs/design/directions/h), the mark comes from LogoPaths.js with its origin in the accent, and
the type is Geist and Geist Mono (SIL OFL 1.1), subset and embedded in each file. GitHub shows an SVG in an <img> without scripts, so all motion is CSS keyframes and
stroke dashes, and every drawing rests on its finished frame when the reader prefers reduced motion.

    .venv/bin/python scripts/readme_art.py              # writes docs/readme/*.svg (dark and light)
    .venv/bin/python scripts/readme_art.py --keep DIR   # reuse (or keep) the scratch projects folder

Needs the engine's extras (build123d) and a slicer Form Studio can drive.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from functools import lru_cache
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "readme"
QML = ROOT / "form" / "app" / "qml" / "Form"
FONTS = ROOT / "form" / "app" / "assets" / "fonts"
sys.path.insert(0, str(ROOT))


# ═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# Theme: read from Theme.qml, so the drawing follows the app
# ═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
def _theme() -> dict:
    src = (QML / "Theme.qml").read_text(encoding="utf-8")
    t = {}
    # a token is one value, or a dark/light pair ("dark ? A : B"): the drawing uses the dark value
    for name, hexv in re.findall(r'property color (\w+): (?:dark \? )?"(#[0-9a-fA-F]{6})"', src):
        t[name] = hexv
    for name, r, g, b, a in re.findall(r"property color (\w+): (?:dark \? )?Qt\.rgba\(([\d.]+), ([\d.]+), ([\d.]+), ([\d.]+)\)", src):
        t[name] = "rgba(%d,%d,%d,%s)" % (round(float(r) * 255), round(float(g) * 255), round(float(b) * 255), a)
    for name, base, a in re.findall(r"property color (\w+): alpha\((\w+), (?:dark \? )?([\d.]+)", src):
        h = t.get(base)
        if h and h.startswith("#"):
            t[name] = "rgba(%d,%d,%d,%s)" % (int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16), a)
    return t


T = _theme()
# Lightdesk, the approved direction (docs/design/directions/h/style.css): a near-black studio, warm key light, and one
# accent, periwinkle, for "this is where you are". Set here so the drawings match the website and the app's new look;
# the mark is the brand's (brand/build.py): a clay F with its origin in the accent.
T.update(plate="#0b0b0c", plate1="#121213", plate2="#19191a", plate3="#232324", plate4="#2f2f31", well="#070708",
         ink="#f4f3f1", ink2="#a9a8a5", ink3="#7d7c78", ink4="#4c4b48", datum="#a9b8ff", datumInk="#0b0b0c",
         blueprint="#a9b8ff", amber="#f2c36b", signal="#ff6f51", clay="#d8d3c8")
T["pass"] = "#86d9a8"
KEY = "#ffe9cf"
MARK_ORIGIN, MARK_ORIGIN_LIGHT = "#a9b8ff", "#3d55d6"   # the mark's origin: periwinkle on the room, its deep shade on paper


def alpha(hexv: str, a: float) -> str:
    h = hexv.lstrip("#")
    return "rgba(%d,%d,%d,%.3g)" % (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), a)


def mix(a: str, b: str, k: float) -> str:
    ha, hb = a.lstrip("#"), b.lstrip("#")
    ca = [int(ha[i:i + 2], 16) for i in (0, 2, 4)]
    cb = [int(hb[i:i + 2], 16) for i in (0, 2, 4)]
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * k) for x, y in zip(ca, cb))


# ═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# Fonts: measured with fontTools, embedded as subset WOFF2 per drawing
# ═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# Geist is the website's copy (site/fonts); Geist Mono and the icons are the app's
FAMILY = {"sans": (ROOT / "site" / "fonts" / "Geist.woff2", "GS"), "mono": ("GeistMono.ttf", "GM"), "icon": ("lucide.ttf", "LU")}


@lru_cache(maxsize=None)
def _metrics(family: str, weight: int):
    from fontTools.ttLib import TTFont
    from fontTools.varLib import instancer
    f = TTFont(FONTS / FAMILY[family][0])
    if "fvar" in f:
        f = instancer.instantiateVariableFont(f, {"wght": weight})
    cmap, hmtx, upm = f.getBestCmap(), f["hmtx"].metrics, f["head"].unitsPerEm
    return cmap, hmtx, upm


def text_w(s: str, size: float, weight: int = 420, family: str = "sans", ls: float = 0.0) -> float:
    cmap, hmtx, upm = _metrics(family, weight if family != "icon" else 400)
    w = 0.0
    for ch in s:
        g = cmap.get(ord(ch))
        w += (hmtx[g][0] if g in hmtx else upm * 0.5) * size / upm + ls
    return w


def font_face(family: str, chars: set) -> str:
    from fontTools import subset
    from fontTools.ttLib import TTFont
    f = TTFont(FONTS / FAMILY[family][0])
    opts = subset.Options()
    opts.flavor = "woff2"
    opts.layout_features = ["kern", "liga", "calt", "tnum"] if family != "icon" else []
    opts.name_IDs = []
    opts.notdef_outline = False
    opts.hinting = False
    sub = subset.Subsetter(opts)
    sub.populate(unicodes=sorted(ord(c) for c in chars | {" "}))
    sub.subset(f)
    buf = io.BytesIO()
    f.flavor = "woff2"
    f.save(buf)
    rng = "font-weight:100 900;" if family != "icon" else ""
    return ("@font-face{font-family:%s;%ssrc:url(data:font/woff2;base64,%s) format('woff2')}"
            % (FAMILY[family][1], rng, base64.b64encode(buf.getvalue()).decode()))


# ═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# SVG builder
# ═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def f1(v: float) -> str:
    s = "%.1f" % v
    return s[:-2] if s.endswith(".0") else s


class Svg:
    """A drawing: elements, the characters each font needs, and the motion (CSS keyframes) on a shared loop."""

    def __init__(self, w: float, h: float, loop: float = 0.0, title: str = ""):
        self.w, self.h, self.loop, self.title = w, h, loop, title
        self.body: list[str] = []
        self.defs: list[str] = []
        self.css: list[str] = []
        self.chars = {k: set() for k in FAMILY}
        self._n = 0

    def id(self, p="a") -> str:
        self._n += 1
        return "%s%d" % (p, self._n)

    def add(self, s: str):
        self.body.append(s)

    # ── motion ──
    def anim(self, frames: list, ease: str = "cubic-bezier(.23,1,.32,1)", origin: str = "", rest: dict | None = None,
             dur: float | None = None, delay: float = 0.0, once: bool = False) -> str:
        """frames: [(seconds, {css props})] on a timeline of `dur` seconds (the drawing's loop by default). Returns
        a class name. Values hold between keys unless the next key differs (then they ease). `rest` is the state
        shown without motion (reduced motion); `once` plays the timeline a single time and holds its end."""
        name = self.id("k")
        dur = dur or self.loop
        fr = sorted(frames, key=lambda f: f[0])
        if fr[0][0] > 0:
            fr.insert(0, (0.0, fr[0][1]))
        if fr[-1][0] < dur:
            fr.append((dur, fr[-1][1]))
        steps = []
        for t, props in fr:
            pct = min(100.0, 100.0 * t / dur)
            body = ";".join("%s:%s" % kv for kv in props.items())
            steps.append("%.3f%%{%s;animation-timing-function:%s}" % (pct, body, ease))
        self.css.append("@keyframes %s{%s}" % (name, "".join(steps)))
        extra = ("transform-box:fill-box;transform-origin:%s;" % origin) if origin else ""
        if rest:
            extra += "".join("%s:%s;" % kv for kv in rest.items())
        timing = "%gs %gs %s both" % (dur, delay, "1" if once else "infinite")
        self.css.append(".%s{%sanimation:%s %s}" % (name, extra, name, timing))
        return name

    # ── text ──
    def text(self, x, y, s, size=13, weight=420, fill=None, family="sans", anchor="start", ls=0.0, cls="", extra="",
             upper=False) -> float:
        if upper:
            s = s.upper()
        self.chars[family].update(s)
        fam = FAMILY[family][1]
        attrs = 'x="%s" y="%s" font-family="%s" font-size="%s"' % (f1(x), f1(y), fam, f1(size) if size % 1 else int(size))
        if family != "icon" and weight != 420:
            attrs += ' font-weight="%d"' % weight
        attrs += ' fill="%s"' % (fill or T["ink"])
        if anchor != "start":
            attrs += ' text-anchor="%s"' % anchor
        if ls:
            attrs += ' letter-spacing="%s"' % f1(ls) if abs(ls) >= 0.1 else ' letter-spacing="%.2f"' % ls
        if cls:
            attrs += ' class="%s"' % cls
        self.add('<text %s%s>%s</text>' % (attrs, extra, esc(s)))
        return text_w(s, size, weight, family, ls)

    def rect(self, x, y, w, h, r=0, fill="none", stroke=None, sw=1, cls="", extra=""):
        a = 'x="%s" y="%s" width="%s" height="%s"' % (f1(x), f1(y), f1(w), f1(h))
        if r:
            a += ' rx="%s"' % f1(r)
        a += ' fill="%s"' % fill
        if stroke:
            a += ' stroke="%s" stroke-width="%s"' % (stroke, f1(sw))
        if cls:
            a += ' class="%s"' % cls
        self.add("<rect %s%s/>" % (a, extra))

    def line(self, x1, y1, x2, y2, stroke, sw=1, cls="", extra=""):
        self.add('<line x1="%s" y1="%s" x2="%s" y2="%s" stroke="%s" stroke-width="%s"%s%s/>'
                 % (f1(x1), f1(y1), f1(x2), f1(y2), stroke, f1(sw), ' class="%s"' % cls if cls else "", extra))

    def circle(self, x, y, r, fill, cls="", extra=""):
        self.add('<circle cx="%s" cy="%s" r="%s" fill="%s"%s%s/>' % (f1(x), f1(y), f1(r), fill, ' class="%s"' % cls if cls else "", extra))

    def g(self, cls="", extra=""):
        self.add("<g%s%s>" % (' class="%s"' % cls if cls else "", extra))

    def end(self):
        self.add("</g>")

    def render(self, desc: str = "") -> str:
        faces = "".join(font_face(fam, ch) for fam, ch in self.chars.items() if ch)
        # .fr repaints the drawing for its first two seconds, so the embedded fonts are used even when nothing else
        # moves (reduced motion): an image is otherwise painted once, possibly before its fonts are decoded
        style = ("<style>%s%s@keyframes fr{0%%{opacity:0}100%%{opacity:.01}}.fr{animation:fr 2s 1}"
                 "@media (prefers-reduced-motion:reduce){*:not(.fr){animation:none!important}}</style>" % (faces, "".join(self.css)))
        style = style.replace("<style>", "<style>text{font-variant-numeric:tabular-nums;white-space:pre}", 1)
        head = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %s %s" width="%s" height="%s" role="img" fill="none" xml:space="preserve">'
                % (f1(self.w), f1(self.h), f1(self.w), f1(self.h)))
        t = "<title>%s</title>" % esc(self.title) if self.title else ""
        d = "<desc>%s</desc>" % esc(desc) if desc else ""
        defs = "<defs>%s</defs>" % "".join(self.defs) if self.defs else ""
        return head + t + d + style + defs + "".join(self.body) + "<rect class=\"fr\" width=\"1\" height=\"1\" fill=\"#808080\" opacity=\"0\"/></svg>\n"


# ═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# The engine: two real designs, built, checked and sliced
# ═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
DESIGNS = {"hinged-box": ("Hinged box", "storage_box", ["lid=2"]),
           "sensor-case": ("Sensor case", "enclosure", [])}      # the design the website's hero builds
# the print design (the checks, slicer and terminal cards): an exemplar's design code, created for printing and sliced
PRINT_ID = "planetary-gearbox"
PRINT_DESIGN = ("Planetary gearbox", "planetary_gearbox",
                "A planetary gearbox to print in one go: a sun, three planets and a ring housing, with a pinned carrier.")
PRINT_PLAN = {"features": [{"id": "ring", "label": "Ring housing", "how": "craft.planetary ring gear with a chamfered rim"},
                           {"id": "flange", "label": "Bolt flange", "how": "three tapered lugs with M4 clearance holes"},
                           {"id": "sun", "label": "Sun gear", "how": "involute gear from the same planetary set"},
                           {"id": "planets", "label": "Planets", "how": "three involute gears in mesh, the backlash as the gap"},
                           {"id": "carrier", "label": "Carrier", "how": "a plate with three pins sized from the planet bores"}],
              "mechanisms": ["sun, planets and ring print in place, in mesh; the carrier prints beside them"],
              "risks": ["three planets need sun + ring teeth divisible by 3"]}
# designs written as build123d code, the way an agent writes them (scripts/readme_designs/), built with create_design
# as plain 3D models: no printer, no slicing
CODE_DESIGNS = {"planetary-gear-stage": ("Planetary gear stage", "planetary.py",
                                         "A planetary gear stage for a 5 mm D shaft: sun, three planets, a ring in a flanged housing."),
                "ergonomic-mouse-shell": ("Ergonomic mouse shell", "mouse_shell.py",
                                          "An ergonomic mouse shell with a thumb scoop, split buttons and a wheel slot.")}
# the staged workflow an agent follows for a complex design: the brief and the feature plan, before the code
PLANS = {"planetary-gear-stage": {
             "features": [{"id": "ring", "label": "Ring gear and housing", "how": "py_gearworks SpurRingGear plus a bolted flange"},
                          {"id": "sun", "label": "Sun gear", "how": "py_gearworks SpurGear with a D bore"},
                          {"id": "planets", "label": "Planet gears", "how": "three SpurGears meshed to the sun at 120 degrees"},
                          {"id": "carrier", "label": "Planet carrier", "how": "a plate with three pins into the planet bores and a hub"}],
             "mechanisms": ["sun, planets and ring mesh with 0.05 mm backlash per gear"],
             "risks": ["three planets need sun + ring teeth divisible by 3",
                       "the ring must be turned so its teeth sit in the planets' gaps (checked by overlap)"]},
         "ergonomic-mouse-shell": {
             "features": [{"id": "body", "label": "Shell", "how": "loft through rounded-rectangle sections, shelled"},
                          {"id": "scoop", "label": "Thumb scoop", "how": "an even-wall dent in the left flank"},
                          {"id": "buttons", "label": "Button split", "how": "a slot cut across the front"},
                          {"id": "wheel", "label": "Wheel slot", "how": "a slot on the centre line"}],
             "risks": ["the scoop must not cut through the wall", "lofted surfaces mesh more coarsely than prismatic ones"]}}


def _b64f(s: str, dt="<f4") -> np.ndarray:
    return np.frombuffer(base64.b64decode(s), dtype=dt)


def engine(data_dir: Path) -> dict:
    os.environ["FORM_DATA"] = str(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    for pid, (name, recipe, params) in DESIGNS.items():
        if not (data_dir / pid).exists():
            print("building %s from the %s recipe…" % (name, recipe), flush=True)
            subprocess.run([sys.executable, "-m", "form", "new", name, recipe, *params], cwd=ROOT, check=True,
                           stdout=subprocess.DEVNULL, env={**os.environ, "FORM_DATA": str(data_dir)})
    for pid, (name, fname, brief) in CODE_DESIGNS.items():
        if not (data_dir / pid).exists():
            print("building %s from its design code…" % name, flush=True)
            env = {**os.environ, "FORM_DATA": str(data_dir)}

            def tool(t, a):
                r = subprocess.run([sys.executable, "-m", "form", "tool", t, json.dumps(a)], cwd=ROOT, check=True,
                                   capture_output=True, text=True, env=env)
                return json.loads(r.stdout)
            bid = tool("design_brief", {"name": name, "goal": brief, "purpose": "model"})["brief"]
            tool("plan_design", {"brief": bid, **PLANS[pid]})
            args = {"name": name, "source": (ROOT / "scripts" / "readme_designs" / fname).read_text(encoding="utf-8"),
                    "brief": brief, "purpose": "model", "process": "cad", "plan": bid}
            subprocess.run([sys.executable, "-m", "form", "tool", "create_design", json.dumps(args)], cwd=ROOT, check=True,
                           stdout=subprocess.DEVNULL, env={**os.environ, "FORM_DATA": str(data_dir)})
    if not (data_dir / PRINT_ID).exists():
        from form import exemplars
        name, exemplar, brief = PRINT_DESIGN
        print("building %s from its design code, for printing…" % name, flush=True)
        env = {**os.environ, "FORM_DATA": str(data_dir)}

        def ptool(t, a):
            r = subprocess.run([sys.executable, "-m", "form", "tool", t, json.dumps(a)], cwd=ROOT, check=True,
                               capture_output=True, text=True, env=env)
            return json.loads(r.stdout)
        bid = ptool("design_brief", {"name": name, "goal": brief, "purpose": "print"})["brief"]
        ptool("plan_design", {"brief": bid, **PRINT_PLAN})
        ptool("create_design", {"name": name, "source": exemplars.get(exemplar)["source"], "brief": brief, "purpose": "print",
                                "plan": bid})
        subprocess.run([sys.executable, "-m", "form", "run", PRINT_ID], cwd=ROOT, check=True, stdout=subprocess.DEVNULL, env=env)
    from form import config, toolpath
    from form.studio import Studio
    st = Studio(config.load())
    out = {}
    for pid in [*DESIGNS, PRINT_ID, *CODE_DESIGNS]:
        state = json.loads(subprocess.run([sys.executable, "-m", "form", "state", pid], cwd=ROOT, check=True,
                                          capture_output=True, text=True, env={**os.environ, "FORM_DATA": str(data_dir)}).stdout)
        p = st.load(pid)
        view = st.view(p, tol=0.25)
        meshes = []
        for m in view["mesh"]:
            pos = _b64f(m["positions"]).reshape(-1, 3).astype(float)
            idx = _b64f(m["indices"], "<u4").reshape(-1, 3) if len(base64.b64decode(m["indices"])) % 12 == 0 else None
            if idx is None or idx.max() >= len(pos):
                idx = _b64f(m["indices"], "<u2").reshape(-1, 3)
            meshes.append({"feature": m["feature"], "part": m.get("part", ""), "tris": pos[idx]})
        edges = _b64f(view["edges"]).reshape(-1, 2, 3).astype(float) if isinstance(view.get("edges"), str) else None
        asm = view.get("assembly")
        part_edges = {}
        if asm:
            for prt in asm["parts"]:
                part_edges[prt["id"]] = _b64f(prt["edges"]).reshape(-1, 2, 3).astype(float)
        tp = None
        if pid == PRINT_ID:
            try:
                sl = st.read(p, "slice", st.keys(p)["slice"]) or {}
                tp = toolpath.for_project(st, p, 1 if sl.get("plates") else None)
            except Exception as e:  # no slicer: the print card is left out
                print("no toolpath for %s: %s" % (pid, e))
        derived = {d["key"]: d for d in (st.head_summary(p).get("derived") or [])}
        try:                                                 # a recipe lists its features in build order
            features = [{"id": f.id, "label": f.label, "role": f.role} for f in st.recipe(p).features]
        except Exception:
            features = []
        out[pid] = {"state": state, "view": view, "meshes": meshes, "edges": edges, "asm": asm, "features": features,
                    "part_edges": part_edges, "toolpath": tp, "derived": derived}
    env = {**os.environ, "FORM_DATA": str(data_dir)}

    def cli(*args) -> str:
        return subprocess.run([sys.executable, "-m", "form", *args], cwd=ROOT, check=True, capture_output=True,
                              text=True, env=env).stdout

    # what the terminal card shows: the CLI's own output, verbatim
    out[PRINT_ID]["state_text"] = cli("state", PRINT_ID)
    out["tools"] = json.loads(cli("tool"))["tools"]
    # the exported files and their SHA-256
    import hashlib
    for pid in (PRINT_ID, "planetary-gear-stage"):
        hashes = []
        for kind, path in out[pid]["state"]["files"].items():
            p = Path(path)
            if p.exists():
                hashes.append((kind, p.name, hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_size))
        out[pid]["hashes"] = hashes
    import importlib
    from form import adapters
    out["slicers"] = [importlib.import_module(m).LABEL for m in adapters.SLICERS.values()]
    return out


def parse_check(s: str) -> dict:
    """'PASS  Thinnest wall: 4.86 mm  [computed]' → status, label, value, evidence"""
    m = re.match(r"(\S+)\s+(.*?)\s+\[(\w+)\]$", s)
    status, rest, ev = m.groups()
    label, _, value = rest.partition(": ")
    return {"status": status, "label": label, "value": value, "evidence": ev}


# ═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# 3D: the viewport's camera, a z-buffer for visibility, painter's order for the SVG
# ═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
class Camera:
    """Viewport.qml's orbit camera. Model space is Z-up millimetres; the scene is Qt Quick 3D's Y-up (x, z, -y)."""

    def __init__(self, az=-34.0, el=28.4, target=(0, 0, 20), dist=420.0, fov=26.0):
        a, e = math.radians(az), math.radians(el)
        tgt = np.array([target[0], target[2], -target[1]], float)
        self.eye = tgt + dist * np.array([math.sin(a) * math.cos(e), math.sin(e), math.cos(a) * math.cos(e)])
        f = tgt - self.eye
        f /= np.linalg.norm(f)
        r = np.cross(f, [0, 1, 0])
        r /= np.linalg.norm(r)
        u = np.cross(r, f)
        self.f, self.r, self.u = f, r, u
        self.k = 1 / math.tan(math.radians(fov) / 2)
        self.ox = self.oy = 0.0
        self.s = 1.0

    def scene(self, p):
        p = np.asarray(p, float)
        return np.stack([p[..., 0], p[..., 2], -p[..., 1]], -1)

    def project(self, p):
        """model points (..., 3) → screen x, y (pixels) and depth (mm along the view)."""
        q = self.scene(p) - self.eye
        z = q @ self.f
        x = (q @ self.r) * self.k / z
        y = -(q @ self.u) * self.k / z
        return np.stack([x * self.s + self.ox, y * self.s + self.oy], -1), z

    def fit(self, pts, box):
        """Scale and place so the projected points fill box (x, y, w, h), centred."""
        self.s, self.ox, self.oy = 1.0, 0.0, 0.0
        xy, _ = self.project(pts)
        lo, hi = xy.reshape(-1, 2).min(0), xy.reshape(-1, 2).max(0)
        bx, by, bw, bh = box
        self.s = min(bw / (hi[0] - lo[0]), bh / (hi[1] - lo[1]))
        c = (lo + hi) / 2 * self.s
        self.ox, self.oy = bx + bw / 2 - c[0], by + bh / 2 - c[1]


CLAY = T["clay"]


def shade(normals: np.ndarray, cam: Camera, base=CLAY) -> list:
    """Clay under the viewport's light: a key from the upper left of the camera, a fill from the sky, ambient."""
    n = cam.scene(normals)
    key = -cam.f * 0.55 + cam.u * 0.62 - cam.r * 0.38
    key /= np.linalg.norm(key)
    sky = np.array([0, 1.0, 0])
    k = np.clip(n @ key, 0, 1)
    s = np.clip(n @ sky, 0, 1)
    lum = 0.58 + 0.32 * k + 0.12 * s
    lum = np.round(lum / 0.018) * 0.018          # tone bands: neighbouring facets of a fillet merge into one shape
    h = base.lstrip("#")
    rgb = np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], float)
    cols = np.clip(rgb[None, :] * lum[:, None] * 0.98, 0, 255)
    return ["#%02x%02x%02x" % tuple(int(round(v)) for v in c) for c in cols]


def rel_path(pts, close=True) -> str:
    """A polyline as one move and relative lines (about a third shorter than absolute coordinates)."""
    q = np.round(np.asarray(pts, float) * 10).astype(int)
    out = ["M%s %s" % (f1(q[0][0] / 10), f1(q[0][1] / 10))]
    prev = q[0]
    segs = []
    for cur in q[1:]:
        dx, dy = cur - prev
        if dx or dy:
            segs.append("%s %s" % (f1(dx / 10), f1(dy / 10)))
        prev = cur
    if segs:
        out.append("l" + " ".join(segs).replace(" -", "-"))
    return "".join(out) + ("z" if close else "")


def _raster(xy, z, W, H, scale=2.0):
    """Depth buffer and owner id at `scale` pixels per SVG pixel."""
    Wp, Hp = int(W * scale) + 2, int(H * scale) + 2
    zb = np.full((Hp, Wp), np.inf)
    ib = np.full((Hp, Wp), -1, np.int32)
    P = xy * scale
    for i in range(len(P)):
        (x0, y0), (x1, y1), (x2, y2) = P[i]
        mnx, mxx = int(max(0, math.floor(min(x0, x1, x2)))), int(min(Wp - 1, math.ceil(max(x0, x1, x2))))
        mny, mxy = int(max(0, math.floor(min(y0, y1, y2)))), int(min(Hp - 1, math.ceil(max(y0, y1, y2))))
        if mnx > mxx or mny > mxy:
            continue
        den = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
        if abs(den) < 1e-9:
            continue
        gx, gy = np.meshgrid(np.arange(mnx, mxx + 1) + 0.5, np.arange(mny, mxy + 1) + 0.5)
        a = ((y1 - y2) * (gx - x2) + (x2 - x1) * (gy - y2)) / den
        b = ((y2 - y0) * (gx - x2) + (x0 - x2) * (gy - y2)) / den
        c = 1 - a - b
        inside = (a >= -1e-6) & (b >= -1e-6) & (c >= -1e-6)
        if not inside.any():
            continue
        zz = a * z[i, 0] + b * z[i, 1] + c * z[i, 2]
        sub = zb[mny:mxy + 1, mnx:mxx + 1]
        win = inside & (zz < sub)
        sub[win] = zz[win]
        ib[mny:mxy + 1, mnx:mxx + 1][win] = i
    return zb, ib


def merged_outline(tris3: np.ndarray, xy: np.ndarray) -> str:
    """Triangles of one colour as their outline: edges two triangles share in opposite directions cancel, the rest
    are chained into closed loops (filled nonzero, so the result covers exactly what the triangles cover)."""
    key = lambda p: (round(p[0], 3), round(p[1], 3), round(p[2], 3))
    pos = {}
    directed = {}
    for t3, t2 in zip(tris3, xy):
        ks = [key(p) for p in t3]
        for k, p in zip(ks, t2):
            pos[k] = p
        for a, b in ((ks[0], ks[1]), (ks[1], ks[2]), (ks[2], ks[0])):
            if a == b:
                continue
            if (b, a) in directed:
                directed[(b, a)] -= 1
                if directed[(b, a)] == 0:
                    del directed[(b, a)]
            else:
                directed[(a, b)] = directed.get((a, b), 0) + 1
    nxt: dict = {}
    for (a, b), n in directed.items():
        for _ in range(n):
            nxt.setdefault(a, []).append(b)
    out = []
    while nxt:
        start = next(iter(nxt))
        loop = [start]
        cur = start
        while True:
            lst = nxt.get(cur)
            if not lst:
                break
            b = lst.pop()
            if not lst:
                del nxt[cur]
            if b == start:
                break
            loop.append(b)
            cur = b
        if len(loop) >= 3:
            pts = np.array([pos[k] for k in loop])
            pts = rdp(np.vstack([pts, pts[:1]]), 0.12)[:-1] if len(pts) > 4 else pts
            out.append(rel_path(pts))
    return "".join(out)


def draw_solid(cam: Camera, tris: np.ndarray, W: float, H: float, edges: np.ndarray | None = None,
               colors: list | None = None, edge_ink: str = "rgba(28,30,30,.55)", base: str | None = None) -> tuple[str, str]:
    """Visible triangles as merged flat-shaded paths (painter's order), and the visible B-rep edges as one path."""
    tris = np.asarray(tris, float)
    nrm = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    ln = np.linalg.norm(nrm, axis=1)
    ok = ln > 1e-9
    tris, nrm = tris[ok], nrm[ok] / ln[ok, None]
    if colors is not None:
        colors = [c for c, o in zip(colors, ok) if o]
    # facing the camera
    cen = cam.scene(tris.mean(1))
    facing = np.einsum("ij,ij->i", cam.scene(nrm), cen - cam.eye) < 0
    tris, nrm = tris[facing], nrm[facing]
    if colors is not None:
        colors = [c for c, o in zip(colors, facing) if o]
    cols = shade(nrm, cam, base or CLAY) if colors is None else colors
    xy, z = cam.project(tris)
    sc = 2.0
    zb, ib = _raster(xy, z, W, H, sc)
    seen = np.zeros(len(tris), bool)
    seen[np.unique(ib[ib >= 0])] = True
    vis = np.nonzero(seen)[0]
    # the drawing order comes from what really covers what: for every visible triangle, the triangles that win its
    # pixels (clearly nearer, not just a neighbour sharing an edge) are drawn after it
    after = {int(i): set() for i in vis}
    P = xy * sc
    for i in vis:
        (x0, y0), (x1, y1), (x2, y2) = P[i]
        mnx, mxx = int(max(0, math.floor(min(x0, x1, x2)))), int(min(ib.shape[1] - 1, math.ceil(max(x0, x1, x2))))
        mny, mxy = int(max(0, math.floor(min(y0, y1, y2)))), int(min(ib.shape[0] - 1, math.ceil(max(y0, y1, y2))))
        den = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
        if abs(den) < 1e-9 or mnx > mxx or mny > mxy:
            continue
        gx, gy = np.meshgrid(np.arange(mnx, mxx + 1) + 0.5, np.arange(mny, mxy + 1) + 0.5)
        a = ((y1 - y2) * (gx - x2) + (x2 - x1) * (gy - y2)) / den
        b = ((y2 - y0) * (gx - x2) + (x0 - x2) * (gy - y2)) / den
        c = 1 - a - b
        inside = (a > 0) & (b > 0) & (c > 0)
        if not inside.any():
            continue
        zz = a * z[i, 0] + b * z[i, 1] + c * z[i, 2]
        own = ib[mny:mxy + 1, mnx:mxx + 1]
        dep = zb[mny:mxy + 1, mnx:mxx + 1]
        cover = inside & (own >= 0) & (own != i) & (dep < zz - (0.08 + 0.002 * zz))
        if cover.any():
            for j in np.unique(own[cover]):
                after[int(i)].add(int(j))
    indeg = {i: 0 for i in after}
    for i, js in after.items():
        for j in js:
            if j in indeg:
                indeg[j] += 1
    # Kahn's order, batched by colour so each batch is one path
    ready: dict = {}
    for i, n in indeg.items():
        if n == 0:
            ready.setdefault(cols[i], []).append(i)
    left = set(after)
    batches = []
    cur = None
    while left:
        if not any(ready.values()):
            # a cycle (two faces that each cover a little of the other): release the farthest
            k = max(left, key=lambda i: z[i].mean())
            indeg[k] = 0
            ready.setdefault(cols[k], []).append(k)
        if cur not in ready or not ready[cur]:
            cur = max(ready, key=lambda c_: len(ready[c_]))
        batch, ready[cur] = ready[cur], []
        batch = [i for i in batch if i in left]
        for i in batch:
            left.discard(i)
        for i in batch:
            for j in after[i]:
                if j in left:
                    indeg[j] -= 1
                    if indeg[j] == 0:
                        ready.setdefault(cols[j], []).append(j)
        if batch:
            if batches and batches[-1][0] == cur:
                batches[-1][1].extend(batch)
            else:
                batches.append((cur, batch))
    paths = []
    for c, batch in batches:
        d = merged_outline(tris[batch], xy[batch])
        paths.append('<path d="%s" fill="%s" stroke="%s" stroke-width=".6" stroke-linejoin="round"/>' % (d, c, c))
    epath = ""
    if edges is not None and len(edges):
        exy, ez = cam.project(edges)
        out = []
        sc = 2.0
        for (p0, p1), (z0, z1) in zip(exy, ez):
            L = np.linalg.norm(p1 - p0)
            n = max(2, int(L / 1.5))
            ts = np.linspace(0, 1, n)
            pts = p0[None] + (p1 - p0)[None] * ts[:, None]
            zz = z0 + (z1 - z0) * ts
            px = np.clip((pts * sc).astype(int), 0, [zb.shape[1] - 1, zb.shape[0] - 1])
            best = zb[px[:, 1], px[:, 0]]
            # neighbours too: an edge lies on the border of its faces
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                q = np.clip(px + [dx, dy], 0, [zb.shape[1] - 1, zb.shape[0] - 1])
                best = np.maximum(best, np.where(np.isinf(zb[q[:, 1], q[:, 0]]), best, zb[q[:, 1], q[:, 0]]))
            vis = zz <= best * 1.004 + 0.6
            run = None
            for k in range(n):
                if vis[k] and run is None:
                    run = k
                if (not vis[k] or k == n - 1) and run is not None:
                    e_ = k if vis[k] else k - 1
                    if e_ > run:
                        out.append(rel_path([pts[run], pts[e_]], close=False))
                    run = None
        if out:
            epath = '<path d="%s" stroke="%s" stroke-width=".8" stroke-linecap="round" fill="none"/>' % ("".join(out), edge_ink)
    return "".join(paths), epath


# ═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# App pieces, drawn as in the QML
# ═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
_LP = (QML / "LogoPaths.js").read_text(encoding="utf-8")
LOGO_FORM = re.search(r'var form = "([^"]+)"', _LP).group(1)
LOGO_STUDIO = re.search(r'var studio = "([^"]+)"', _LP).group(1)
LOGO_W = float(re.search(r"width = ([\d.]+)", _LP).group(1))
LOGO_CAP = float(re.search(r"capHeight = ([\d.]+)", _LP).group(1))


def logo(svg: Svg, x, cy, size=14, ink=None, ink2=None, cls="", part=None, word=True, datum=None) -> float:
    """Logo.qml: the F as a coordinate frame (the origin in datum, the arms in clay) and the wordmark outlines,
    left edge at x, centred on cy. Returns the width."""
    u = size / 48
    y = cy - size / 2
    cut = 2 * u if size >= 24 else 0
    clay = part or T["clay"]
    out = ['<g%s>' % (' class="%s"' % cls if cls else "")]
    out.append('<rect x="%s" y="%s" width="%s" height="%s" fill="%s"/>' % (f1(x), f1(y), "%.2f" % (12 * u), "%.2f" % (12 * u), datum or MARK_ORIGIN))
    for rx, ry, rw, rh in ((12 * u + cut, 0, 28 * u - cut, 12 * u), (0, 12 * u + cut, 12 * u, 36 * u - cut), (12 * u, 20 * u, 20 * u, 12 * u)):
        out.append('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" fill="%s"/>' % (x + rx, y + ry, rw, rh, clay))
    w = 40 * u
    if word:
        cap = size / 1.5
        k = cap / LOGO_CAP
        wx, wy = x + 40 * u + 0.42 * size, y + (size - cap) / 2
        out.append('<g transform="translate(%.2f %.2f) scale(%.5f)"><path d="%s" fill="%s"/><path d="%s" fill="%s"/></g>'
                   % (wx, wy, k, LOGO_FORM, ink or T["ink"], LOGO_STUDIO, ink2 or T["ink2"]))
        w += 0.42 * size + LOGO_W * k
    out.append("</g>")
    svg.add("".join(out))
    return w


def rot(axis, ang):
    a = np.asarray(axis, float)
    a /= np.linalg.norm(a)
    c, s = math.cos(ang), math.sin(ang)
    x, y, z = a
    return np.array([[c + x * x * (1 - c), x * y * (1 - c) - z * s, x * z * (1 - c) + y * s],
                     [y * x * (1 - c) + z * s, c + y * y * (1 - c), y * z * (1 - c) - x * s],
                     [z * x * (1 - c) - y * s, z * y * (1 - c) + x * s, c + z * z * (1 - c)]])


def chain(segs: np.ndarray, tol=1e-3) -> list:
    """Consecutive moves that share an end point, as polylines."""
    out, cur = [], None
    for x0, y0, x1, y1 in segs:
        if cur is not None and abs(cur[-1][0] - x0) < tol and abs(cur[-1][1] - y0) < tol:
            cur.append((x1, y1))
        else:
            if cur:
                out.append(cur)
            cur = [(x0, y0), (x1, y1)]
    if cur:
        out.append(cur)
    return out


def rdp(pts: np.ndarray, eps: float) -> np.ndarray:
    if len(pts) < 3:
        return pts
    a, b = pts[0], pts[-1]
    ab = b - a
    L = np.hypot(*ab)
    if L < 1e-9:
        d = np.hypot(*(pts - a).T)
    else:
        d = np.abs(ab[0] * (pts[:, 1] - a[1]) - ab[1] * (pts[:, 0] - a[0])) / L
    i = int(np.argmax(d))
    if d[i] > eps:
        return np.concatenate([rdp(pts[: i + 1], eps)[:-1], rdp(pts[i:], eps)])
    return np.array([a, b])


TYPE_INK = {"Outer wall": T["ink"], "Inner wall": T["ink3"], "Sparse infill": T["amber"], "Internal solid infill": T["blueprint"],
            "Top surface": T["datum"], "Bottom surface": mix(T["datum"], "#000000", 0.42), "Bridge": T["signal"],
            "Overhang wall": T["signal"], "Floating vertical shell": "#ff9678", "Gap infill": T["ink4"]}


def fmt_min(m: float) -> str:
    m = int(round(m))
    return "%d h %d min" % (m // 60, m % 60) if m >= 60 else "%d min" % m


def wrap(s: str, width: float, size=13, weight=420) -> list:
    out, cur = [], ""
    for word in s.split(" "):
        t = (cur + " " + word).strip()
        if text_w(t, size, weight) > width and cur:
            out.append(cur)
            cur = word
        else:
            cur = t
    if cur:
        out.append(cur)
    return out


def elide(s: str, width: float, size=13, weight=420, family="sans") -> str:
    if text_w(s, size, weight, family) <= width:
        return s
    while s and text_w(s + "…", size, weight, family) > width:
        s = s[:-1]
    return s.rstrip() + "…"


# ═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# The page's palette: Theme.qml for GitHub's dark theme, the same roles set dark-on-light for the light theme
# ═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
def P(light: bool) -> dict:
    if light:
        return dict(panel="#f8f7f4", panel2="#e6e3de", well="#ffffff", ink="#161616", ink2="#5d5c59", ink3="#7a7975",
                    ink4="#b5b2ac", datum="#3d55d6", tint=T["datum"], mark=MARK_ORIGIN_LIGHT, tintInk=T["datumInk"], clay="#d6d0c3",
                    edge="rgba(22,22,22,.62)", grid="rgba(22,22,22,.10)", amber="#a86a00", pass_="#1f8a52",
                    signal="#c8452b", blueprint="#3d55d6", shadow="rgba(60,50,40,.16)", logo_part="#161616",
                    glass="rgba(255,255,255,.62)", glass2="rgba(255,255,255,.95)", glass_edge="rgba(255,255,255,.9)",
                    well_glass="rgba(255,255,255,.82)", room=("#e6e3de", "#efede9", "#f6f5f2", "#e4e1dc"), key="#ffffff", key_a=0.95,
                    dim_bg="rgba(255,255,255,.92)", dim_ink="#2b3fb0", send="#161616", send_ink="#ffffff", track="rgba(22,22,22,.13)")
    return dict(panel="#121213", panel2="#19191a", well="#070708", ink=T["ink"], ink2=T["ink2"], ink3=T["ink3"],
                ink4=T["ink4"], datum=T["datum"], tint=T["datum"], mark=MARK_ORIGIN, tintInk=T["datumInk"], clay=T["clay"],
                edge="rgba(16,16,16,.62)", grid="rgba(255,255,255,.09)", amber=T["amber"], pass_=T["pass"],
                signal=T["signal"], blueprint=T["blueprint"], shadow="rgba(0,0,0,.45)", logo_part=T["clay"],
                glass="rgba(255,255,255,.07)", glass2="rgba(255,255,255,.14)", glass_edge="rgba(255,255,255,.11)",
                well_glass="rgba(11,11,12,.66)", room=("#0a0a0b", "#131314", "#1b1b1c", "#0d0d0e"), key=KEY, key_a=0.24,
                dim_bg="rgba(14,15,20,.86)", dim_ink="#dfe5ff", send="#f4f3f1", send_ink="#0b0b0c", track="rgba(255,255,255,.13)")


def ev_ink(p: dict, ev: str) -> str:
    return {"computed": p["datum"], "specified": p["datum"], "heuristic": p["ink2"], "model": p["amber"],
            "modelled": p["amber"], "simulated": p["amber"], "assumed": p["amber"]}.get(ev, p["ink2"])


def stand_facts(d) -> dict:
    s = d["state"]
    sl = s["slice_simulated"]
    checks = [parse_check(c) for c in s["checks"]]
    v = d["view"]
    lo, hi = np.array(v["bbox"][0]), np.array(v["bbox"][1])
    ev = {}
    for c in checks:
        ev[c["evidence"]] = ev.get(c["evidence"], 0) + 1
    return {"name": s["name"], "rev": "r%02d" % s["head"], "checks": checks, "evidence": ev,
            "time": fmt_min(sl["time_min"]), "grams": "%.1f g" % sl["filament_g"], "layers": sl["layers"],
            "presets": sl["presets"], "size": " × ".join("%.1f" % x for x in hi - lo)}


def all_tris(d) -> np.ndarray:
    return np.concatenate([m["tris"] for m in d["meshes"]])


def wire(cam: Camera, edges: np.ndarray) -> str:
    """Every B-rep edge, bottom to top, as one path: drawn with a dash it is plotted edge by edge."""
    order = np.argsort(edges[:, :, 2].min(1) + 0.02 * edges[:, :, 0].min(1))
    xy, _ = cam.project(edges[order])
    return "".join("M%s %sL%s %s" % (f1(a[0]), f1(a[1]), f1(b[0]), f1(b[1])) for a, b in xy)


def draw_dash(svg: Svg, d: str, stroke: str, sw: float, t0: float, t1: float, dur: float, hold: float | None = None,
              once: bool = False, ease="cubic-bezier(.45,.05,.25,1)", extra="", cap="round") -> str:
    """A path that draws itself from t0 to t1 (a stroke dash over its normalised length)."""
    fr = [(0, {"stroke-dashoffset": "1"}), (t0, {"stroke-dashoffset": "1"}), (t1, {"stroke-dashoffset": "0"})]
    if hold is not None:
        fr += [(hold, {"stroke-dashoffset": "0"}), (hold + 1e-3, {"stroke-dashoffset": "1"})]
    cls = svg.anim(fr, ease=ease, rest={"stroke-dashoffset": "0"}, dur=dur, once=once)
    svg.add('<path d="%s" pathLength="1" stroke-dasharray="1 1" stroke="%s" stroke-width="%s" stroke-linecap="%s" '
            'stroke-linejoin="round" fill="none" class="%s"%s/>' % (d, stroke, f1(sw), cap, cls, extra))
    return cls


def window_classes(svg: Svg, intervals_per_frame: list, dur: float, delay: float = 0.0, once=False) -> list:
    """One class per frame: visible only inside its intervals (frame 0 is the one shown without motion)."""
    out = []
    for k, iv in enumerate(intervals_per_frame):
        fr = [(0, {"opacity": "0"})]
        for s, e in iv:
            if s <= 0:
                fr = [(0, {"opacity": "1"})]
            else:
                fr += [(s - 1e-3, {"opacity": "0"}), (s, {"opacity": "1"})]
            if e < dur:
                fr += [(e, {"opacity": "1"}), (e + 1e-3, {"opacity": "0"})]
            else:
                fr += [(dur, {"opacity": "1"})]
        out.append(svg.anim(fr, ease="linear", rest={"opacity": "1" if k == 0 else "0"}, dur=dur, delay=delay, once=once))
    return out


def frame_intervals(index_at, n: int, dur: float, dt=1 / 120) -> list:
    iv = [[] for _ in range(n)]
    t, cur, start = 0.0, index_at(0.0), 0.0
    while t < dur - 1e-9:
        t = min(dur, t + dt)
        k = index_at(t) if t < dur - 1e-9 else None
        if k != cur:
            iv[cur].append((start, t))
            cur, start = k, t
    return iv


def rings(svg: Svg, cam: Camera, c, radii, ink: str, cls=""):
    out = []
    for r in radii:
        a = np.linspace(0, 2 * math.pi, 97)
        P3 = np.stack([c[0] + r * np.cos(a), c[1] + r * np.sin(a), np.zeros_like(a)], 1)
        xy, _ = cam.project(P3)
        out.append("M" + "L".join("%s %s" % (f1(x), f1(y)) for x, y in xy) + "Z")
    svg.add('<path d="%s" stroke="%s" stroke-width="1" fill="none"%s/>' % ("".join(out), ink, ' class="%s"' % cls if cls else ""))


def soft_shadow(svg: Svg, cam: Camera, c, rx, ry, ink):
    g = svg.id("sg")
    svg.defs.append('<radialGradient id="%s"><stop offset="0" stop-color="%s"/><stop offset="1" stop-color="%s" stop-opacity="0"/></radialGradient>'
                    % (g, ink, ink))
    xy, _ = cam.project(np.array([[c[0], c[1], 0.0]]))
    svg.add('<ellipse cx="%s" cy="%s" rx="%s" ry="%s" fill="url(#%s)"/>' % (f1(xy[0][0]), f1(xy[0][1]), f1(rx), f1(ry), g))


def spin_about(c):
    return lambda pts, deg: (np.asarray(pts).reshape(-1, 3) - c) @ rot([0, 0, 1], math.radians(deg)).T + c


def px_per_mm(cam: Camera, dist: float) -> float:
    return cam.s * cam.k / dist


def model_facts(d) -> dict:
    """A design built as a plain 3D model: name, size, the checks that apply and how many pass, derived values."""
    s = d["state"]
    checks = [parse_check(c) for c in s["checks"]]
    applies = [c for c in checks if c["status"] != "N/A"]
    v = d["view"]
    lo, hi = np.array(v["bbox"][0]), np.array(v["bbox"][1])
    parts = next((c["value"].split()[0] for c in checks if "valid part" in c["label"]), "1")
    return {"name": s["name"], "rev": "r%02d" % s["head"], "checks": checks, "applies": applies,
            "passed": sum(1 for c in applies if c["status"] == "PASS"), "size": " × ".join("%.1f" % x for x in hi - lo),
            "derived": d.get("derived", {}), "parts": parts}


def ratio(x: float) -> str:
    return "1 : %s" % f1(x)


def drawn_part(svg: Svg, p, d, box, az, el, t_draw0, t_draw1, t_fill0, t_fill1, dist=440, rings_=True):
    """A part drawing itself: its B-rep edges plotted, then its shaded faces filling in; it rests filled."""
    tris = all_tris(d).reshape(-1, 3)
    edges = d["edges"]
    lo, hi = tris.min(0), tris.max(0)
    c = (lo + hi) / 2
    cam = Camera(az=az, el=el, target=(c[0], c[1], (lo[2] + hi[2]) / 2), dist=dist)
    cam.fit(tris, box)
    rad = float(np.linalg.norm((hi - lo)[:2])) / 2
    k_ = px_per_mm(cam, dist)
    soft_shadow(svg, cam, (c[0], c[1], lo[2]), rad * k_ * 1.05, rad * k_ * 0.34, p["shadow"])
    if rings_:
        rc = svg.anim([(0, {"opacity": "0"}), (0.3, {"opacity": "0"}), (1.2, {"opacity": "1"})], dur=1.2, once=True)
        out = []
        for r in (rad * 1.15, rad * 1.5):
            a = np.linspace(0, 2 * math.pi, 97)
            xy, _ = cam.project(np.stack([c[0] + r * np.cos(a), c[1] + r * np.sin(a), np.full_like(a, lo[2])], 1))
            out.append("M" + "L".join("%s %s" % (f1(x), f1(y)) for x, y in xy) + "Z")
        svg.add('<path d="%s" stroke="%s" stroke-width="1" fill="none" class="%s"/>' % ("".join(out), p["grid"], rc))
    fills, ed = draw_solid(cam, tris.reshape(-1, 3, 3), svg.w, svg.h, edges, edge_ink=p["edge"], base=p["clay"])
    fill_in = svg.anim([(0, {"opacity": "0"}), (t_fill0, {"opacity": "0"}), (t_fill1, {"opacity": "1"})], dur=t_fill1, once=True)
    svg.add('<g class="%s">%s%s</g>' % (fill_in, fills, ed))
    wire_out = svg.anim([(0, {"opacity": "1"}), (t_fill0 + 0.2, {"opacity": "1"}), (t_fill1 + 0.3, {"opacity": "0"})],
                        dur=t_fill1 + 0.3, once=True, rest={"opacity": "0"})
    svg.add('<g class="%s">' % wire_out)
    draw_dash(svg, wire(cam, edges), p["datum"], 1.1, t_draw0, t_draw1, t_draw1, once=True)
    svg.add("</g>")
    return cam


# ═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# The opening poster: the promise, and two very different designs drawing themselves as edges, then filling in
# ═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
def hero(data, light: bool):
    p = P(light)
    gear, shell = data["planetary-gear-stage"], data["ergonomic-mouse-shell"]
    G, M = model_facts(gear), model_facts(shell)
    W, H = 828, 660
    svg = Svg(W, H, 8.0, "Form Studio")
    svg.rect(0, 0, W, H, 28, fill=p["panel"])
    logo(svg, 40, 52, size=22, ink=p["ink"], ink2=p["ink2"], part=p["logo_part"], datum=p["mark"])
    svg.text(W - 40, 59, "Open source  ·  macOS, Windows, Linux", 14, 520, p["ink3"], anchor="end")
    h1 = svg.anim([(0, {"opacity": "0", "transform": "translateY(14px)"}), (0.15, {"opacity": "0", "transform": "translateY(14px)"}),
                   (0.95, {"opacity": "1", "transform": "translateY(0px)"})], dur=1.0, once=True)
    svg.text(W / 2, 162, "Describe anything.", 76, 640, p["ink"], anchor="middle", ls=-2.8, cls=h1)
    h2 = svg.anim([(0, {"opacity": "0", "transform": "translateY(10px)"}), (0.35, {"opacity": "0", "transform": "translateY(10px)"}),
                   (1.15, {"opacity": "1", "transform": "translateY(0px)"})], dur=1.2, once=True)
    svg.text(W / 2, 208, "An engineer-grade agent builds it as real, editable CAD.", 21, 450, p["ink2"], anchor="middle", cls=h2)
    drawn_part(svg, p, gear, (56, 258, 400, 290), -30, 34, 0.5, 3.0, 2.7, 3.6)
    drawn_part(svg, p, shell, (500, 290, 272, 236), -142, 24, 1.1, 3.4, 3.1, 4.0, rings_=False)
    cap = svg.anim([(0, {"opacity": "0"}), (3.4, {"opacity": "0"}), (4.2, {"opacity": "1"})], dur=4.2, once=True)
    svg.g(cap)
    rc = G["derived"].get("ratio_carrier")
    g_sub = "%s parts · %s · %s mm" % (G["parts"], ratio(rc["value"]), G["size"]) if rc else "%s parts · %s mm" % (G["parts"], G["size"])
    for x, name, sub in ((256, G["name"], g_sub), (636, M["name"], "lofted shell · %s mm" % M["size"])):
        svg.text(x, H - 62, name, 15, 600, p["ink"], anchor="middle")
        svg.text(x, H - 40, sub, 13, 450, p["ink3"], anchor="middle")
    svg.end()
    desc = ("Form Studio. Describe anything. An engineer-grade agent builds it as real, editable CAD. Two designs written as "
            "build123d code and built by the CAD kernel draw themselves as their B-rep edges and fill in: a %s (%s) and an "
            "%s (%s mm)." % (G["name"].lower(), g_sub, M["name"].lower(), M["size"]))
    return [("hero", svg.render(desc))]


# ═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# The workspace mid-build, as Lightdesk draws it (docs/design/directions/h): the part in a pool of light with its
# size on dimension lines, the features as a program listing whose gutter is lit down to the line that is running,
# a lower-third title for that feature, and one bar under the part. The features, their names, their order and
# their faces are the design's own (the recipe and Studio.view); the drawing stops the build at one of them.
# ═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
BUILDING_ID = "sensor-case"


def build_order(d) -> list:
    """[(feature id, label, triangles)] in the order the engine's view lists them, for the features that own faces."""
    by = {}
    for m in d["meshes"]:
        by.setdefault(m["feature"], []).append(m["tris"])
    feats = d.get("features") or d["view"].get("features") or []
    order = [f["id"] for f in feats if f["id"] in by] + [k for k in by if k not in {f["id"] for f in feats}]
    label = {f["id"]: f.get("label") or f["id"] for f in feats}
    return [(k, label.get(k, k.replace("_", " ").capitalize()), np.concatenate(by[k])) for k in order]


def building(data, light: bool):
    p = P(light)
    d = data[BUILDING_ID]
    M = model_facts(d)
    feats = build_order(d)
    listing = d.get("features") or [{"id": k, "label": lab, "role": ""} for k, lab, _ in feats]
    n = len(feats)
    at = max(2, min(n - 1, round(n * 0.5)))             # the line running: half way down the program
    fid, name = feats[at - 1][0], feats[at - 1][1]
    line_of = {f["id"]: i for i, f in enumerate(listing)}
    W, H = 828, 520
    PW, PX, PY = 240, W - 16 - 240, 62                  # the program pane
    CX = (16 + PX - 12) / 2                             # the centre of the room left of it
    loop = 6.0
    acc, glass, glass2, edge = p["datum"], p["glass"], p["glass2"], p["glass_edge"]
    svg = Svg(W, H, loop, "Form Studio, building")
    # the room: a sweep of floor and the key light pooled under the part
    svg.defs.append('<linearGradient id="rm" x1="0" y1="0" x2="0" y2="1">%s</linearGradient>'
                    % "".join('<stop offset="%s" stop-color="%s"/>' % (o, c) for o, c in zip((0, .38, .6, 1), p["room"])))
    svg.defs.append('<radialGradient id="pl"><stop offset="0" stop-color="%s" stop-opacity="%s"/><stop offset=".55" stop-color="%s" stop-opacity="%s"/>'
                    '<stop offset="1" stop-color="%s" stop-opacity="0"/></radialGradient>' % (p["key"], p["key_a"], p["key"], p["key_a"] * 0.3, p["key"]))
    svg.defs.append('<clipPath id="win"><rect x="0.5" y="0.5" width="%s" height="%s" rx="22"/></clipPath>' % (W - 1, H - 1))
    svg.add('<g clip-path="url(#win)"><rect width="%s" height="%s" fill="url(#rm)"/><ellipse cx="%s" cy="232" rx="300" ry="150" fill="url(#pl)"/></g>' % (W, H, f1(CX)))
    svg.rect(0.5, 0.5, W - 1, H - 1, 22, stroke=edge)
    pulse = svg.anim([(0, {"opacity": "1"}), (loop / 2, {"opacity": ".35"}), (loop, {"opacity": "1"})], ease="ease-in-out")

    def pane(x, y, w, h, r, fill=None):
        svg.rect(x, y, w, h, r, fill=fill or glass, stroke=edge)

    # title capsule: the mark, the design, its revision and state
    nm_w = text_w(M["name"], 13, 600)
    rv = "r%02d" % d["state"]["head"]
    tag_w = text_w("UNRELEASED", 8.5, 500, "mono", 0.8) + 12
    cap_w = 14 + 16 + 9 + nm_w + 8 + text_w(rv, 10.5, 450, "mono") + 9 + tag_w + 10
    pane(16, 14, cap_w, 32, 16)
    logo(svg, 28, 30, size=14, part=p["logo_part"], datum=p["mark"], word=False)
    x = 28 + 14 * 40 / 48 + 9
    x += svg.text(x, 34.5, M["name"], 13, 600, p["ink"], ls=-0.1) + 8
    x += svg.text(x, 34, rv, 10.5, 450, p["ink2"], family="mono") + 9
    svg.rect(x, 21.5, tag_w, 17, 8.5, fill=glass2)
    svg.text(x + tag_w / 2, 33, "UNRELEASED", 8.5, 500, p["ink2"], family="mono", anchor="middle", ls=0.8)
    # stages: the one in front on raised glass, its count in the accent
    stages = [("Describe", ""), ("Design", "%d of %d" % (at, n)), ("Review", ""), ("Make", "")]
    sw_ = 74
    sx = max(CX - sw_ * len(stages) / 2, 16 + cap_w + 18)
    pane(sx - 4, 10, sw_ * len(stages) + 8, 40, 20)
    for i, (s, sub) in enumerate(stages):
        cx = sx + i * sw_ + sw_ / 2
        if sub:
            svg.rect(sx + i * sw_, 14, sw_, 32, 16, fill=glass2)
            svg.text(cx, 29, s, 11.5, 600, p["ink"], anchor="middle")
            svg.text(cx, 40.5, sub, 9, 450, acc, anchor="middle")
        else:
            svg.text(cx, 34, s, 11.5, 600, p["ink2"], anchor="middle")

    # the program: the features in build order; the gutter is lit down to the line that is running
    rows, rh = len(listing), 25.0
    pane(PX, PY, PW, 38 + rows * rh + 8, 20)
    svg.text(PX + 16, PY + 24, "Program", 12.5, 600, p["ink"])
    svg.text(PX + 16 + text_w("Program", 12.5, 600) + 7, PY + 24, str(rows), 10, 450, p["ink3"], family="mono")
    cnt = ("%d of %d" % (at, n)).upper()
    svg.text(PX + PW - 16, PY + 23.5, cnt, 9, 500, acc, family="mono", anchor="end", ls=1.2)
    svg.circle(PX + PW - 16 - text_w(cnt, 9, 500, "mono", 1.2) - 9, PY + 20.5, 2.6, acc, cls=pulse)
    gx, gy = PX + 33, PY + 38
    svg.line(gx, gy, gx, gy + rows * rh, p["grid"])
    now_row = line_of.get(fid, at - 1)
    g0, g1 = max(0.0, (now_row - 1) * rh + rh / 2), now_row * rh + rh / 2
    lit = svg.anim([(0, {"transform": "scaleY(%.4f)" % (g0 / g1)}), (0.5, {"transform": "scaleY(%.4f)" % (g0 / g1)}), (0.9, {"transform": "scaleY(1)"}),
                    (loop - 0.7, {"transform": "scaleY(1)"}), (loop, {"transform": "scaleY(%.4f)" % (g0 / g1)})], origin="center top", rest={"transform": "scaleY(1)"})
    svg.rect(gx - 1, gy, 2, g1, 1, fill=acc, cls=lit)
    built = {k for k, _, _ in feats[:at - 1]}
    for i, f in enumerate(listing):
        y = gy + i * rh
        now, done, off = f["id"] == fid, f["id"] in built, f["id"] not in {k for k, _, _ in feats}
        if now:
            svg.rect(PX + 5, y + 0.5, PW - 10, rh - 1, 8, fill=glass2)
        ink = p["ink"] if now else p["ink2"] if done else p["ink3"]
        svg.text(PX + 25, y + 16.5, "%02d" % (i + 1), 9.5, 450, acc if now else p["ink3"], family="mono", anchor="end")
        if done:
            svg.add('<path d="%s" stroke="%s" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>' % (check_mark(gx + 12, y + rh / 2, 0.6), p["pass_"]))
        elif now:
            svg.add('<path d="M%s %sl6 3.6-6 3.6z" stroke="%s" stroke-width="1.3" stroke-linejoin="round" class="%s"/>' % (f1(gx + 9.5), f1(y + rh / 2 - 3.6), acc, pulse))
        kw = "BUILDING" if now else "OFF" if off else (f.get("role") or "").upper()
        kw_w = text_w(kw, 7.5, 500, "mono", 0.7)
        svg.text(PX + 52, y + 16.5, elide(f["label"], PW - 52 - 14 - kw_w - 8, 12, 600 if now else 500), 12, 600 if now else 500, ink)
        svg.text(PX + PW - 14, y + 15.5, kw, 7.5, 500, acc if now else p["ink3"], family="mono", anchor="end", ls=0.7,
                 extra="" if now else ' opacity=".7"')

    # the part: what is built so far solid, the feature arriving lit, the rest of the design a faint plot
    every = all_tris(d).reshape(-1, 3)
    lo, hi = every.min(0), every.max(0)
    c = (lo + hi) / 2
    cam = Camera(az=-27, el=31, target=(c[0], c[1], c[2]), dist=470)
    cam.fit(every, (60, 72, PX - 12 - 60 - 30, 250))
    made = np.concatenate([t for _, _, t in feats[:at]]).reshape(-1, 3)
    mlo, mhi = made.min(0), made.max(0)
    mc, kpx = (mlo + mhi) / 2, px_per_mm(cam, 470)
    soft_shadow(svg, cam, (mc[0] + 6, mc[1] - 4, 0), (mhi[0] - mlo[0]) * kpx * 0.86, (mhi[1] - mlo[1]) * kpx * 0.5, p["shadow"])
    if d["edges"] is not None:
        svg.add('<path d="%s" stroke="%s" stroke-width="0.8" opacity="%s"/>' % (wire(cam, d["edges"]), p["ink3"], "0.3" if not light else "0.36"))
    fills, _ed = draw_solid(cam, np.concatenate([t for _, _, t in feats[:at - 1]]), svg.w, svg.h, None, base=p["clay"])
    svg.add("<g>%s</g>" % fills)
    arrive = svg.anim([(0, {"opacity": "0"}), (0.5, {"opacity": "0"}), (1.3, {"opacity": "1"}), (loop - 0.7, {"opacity": "1"}), (loop, {"opacity": "0"})],
                      rest={"opacity": "1"})
    fills, _ed = draw_solid(cam, feats[at - 1][2], svg.w, svg.h, None, base=mix(p["clay"], p["key"], 0.55))
    svg.add('<g class="%s">%s</g>' % (arrive, fills))
    # the size so far, on the part: three dimension lines from the built solid's own bounding box
    m = 9.0
    for a, b, val in (((mlo[0] - m, mhi[1], 0), (mlo[0] - m, mhi[1], mhi[2]), mhi[2] - mlo[2]),
                      ((mlo[0] - m, mhi[1], 0), (mlo[0] - m, mlo[1], 0), mhi[1] - mlo[1]),
                      ((mlo[0], mlo[1] - m, 0), (mhi[0], mlo[1] - m, 0), mhi[0] - mlo[0])):
        (ax, ay), (bx, by) = cam.project(np.array([a, b], float))[0]
        svg.line(ax, ay, bx, by, acc, 1.1)
        svg.circle(ax, ay, 2.2, acc)
        svg.circle(bx, by, 2.2, acc)
        t = "%.1f" % val
        tw = text_w(t, 9.5, 500, "mono") + 12
        svg.rect((ax + bx) / 2 - tw / 2, (ay + by) / 2 - 8.5, tw, 17, 8.5, fill=p["dim_bg"], stroke=alpha(acc, 0.4) if acc.startswith("#") else acc)
        svg.text((ax + bx) / 2, (ay + by) / 2 + 3.4, t, 9.5, 500, p["dim_ink"], family="mono", anchor="middle")

    # the cue: a lower-third title for the feature being built, and the build as twelve segments
    ty = 356
    over = "BUILDING"
    ow = text_w(over, 9, 500, "mono", 1.5)
    of_ = ("%d of %d" % (at, n)).upper()
    tot = 12 + ow + 9 + text_w(of_, 9, 500, "mono", 1.5)
    ox = CX - tot / 2
    svg.circle(ox + 3, ty - 3, 2.8, acc, cls=pulse)
    svg.text(ox + 12, ty, over, 9, 500, acc, family="mono", ls=1.5)
    svg.text(ox + 12 + ow + 9, ty, of_, 9, 500, p["ink2"], family="mono", ls=1.5)
    no = "%02d" % (now_row + 1)
    nw, tw = text_w(no, 13, 500, "mono"), text_w(name, 38, 600, ls=-1.4)
    tx = CX - (nw + 9 + tw) / 2
    rise = svg.anim([(0, {"opacity": "0", "transform": "translateY(8px)"}), (0.5, {"opacity": "0", "transform": "translateY(8px)"}),
                     (1.0, {"opacity": "1", "transform": "translateY(0px)"}), (loop - 0.7, {"opacity": "1", "transform": "translateY(0px)"}),
                     (loop, {"opacity": "0", "transform": "translateY(0px)"})], rest={"opacity": "1"})
    svg.g(rise)
    svg.text(tx, ty + 30, no, 13, 500, acc, family="mono")
    svg.text(tx + nw + 9, ty + 44, name, 38, 600, p["ink"], ls=-1.4)
    svg.end()
    tw_all, gap = 372.0, 4.0
    seg = (tw_all - gap * (n - 1)) / n
    fill_now = svg.anim([(0, {"transform": "scaleX(0)"}), (0.5, {"transform": "scaleX(0)"}), (1.7, {"transform": "scaleX(.55)"}),
                         (loop - 0.7, {"transform": "scaleX(.55)"}), (loop, {"transform": "scaleX(0)"})], origin="left center", rest={"transform": "scaleX(.55)"})
    for i in range(n):
        x0 = CX - tw_all / 2 + i * (seg + gap)
        svg.rect(x0, ty + 60, seg, 4, 2, fill=p["ink"] if i < at - 1 else p["track"])
        if i == at - 1:
            svg.rect(x0, ty + 60, seg, 4, 2, fill=acc, cls=fill_now)
    if at > 1:
        pv = feats[at - 2]
        x = CX - tw_all / 2
        x += svg.text(x, ty + 82, "built", 10.5, 450, p["ink3"]) + 7
        x += svg.text(x, ty + 82, "%02d" % (line_of.get(pv[0], at - 2) + 1), 9.5, 500, p["ink2"], family="mono") + 7
        svg.text(x, ty + 82, pv[1], 10.5, 450, p["ink3"])
    if at < n:
        nx = feats[at]
        x = CX + tw_all / 2
        x -= svg.text(x, ty + 82, nx[1], 10.5, 450, p["ink3"], anchor="end") + 7
        x -= svg.text(x, ty + 82, "%02d" % (line_of.get(nx[0], at) + 1), 9.5, 500, p["ink2"], family="mono", anchor="end") + 7
        svg.text(x, ty + 82, "next", 10.5, 450, p["ink3"], anchor="end")

    # the bar: one prompt under the part
    bw_, by_ = 372.0, H - 16 - 40
    pane(CX - bw_ / 2, by_, bw_, 40, 20)
    svg.rect(CX - bw_ / 2 + 5, by_ + 5, bw_ - 10, 30, 15, fill=p["well_glass"])
    svg.text(CX - bw_ / 2 + 18, by_ + 25.5, "›", 16, 500, acc, family="mono")
    svg.rect(CX - bw_ / 2 + 32, by_ + 13, 6, 14, 1.5, fill=acc, cls=pulse)
    svg.text(CX - bw_ / 2 + 46, by_ + 24.5, "Ask about %s, or describe a change…" % M["name"], 12, 450, p["ink3"])
    svg.circle(CX + bw_ / 2 - 20, by_ + 20, 12, p["send"])
    svg.add('<path d="M%s %sv4a2 2 0 01-2 2h-6m2.6-2.6l-2.6 2.6 2.6 2.6" stroke="%s" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>'
            % (f1(CX + bw_ / 2 - 15.5), f1(by_ + 15), p["send_ink"]))
    svg.text(W - 26, H - 23, "build123d on OpenCascade", 10.5, 450, p["ink3"], anchor="end")
    desc = ("The Form Studio workspace while a design builds: %s, line %d of the program, %s, being built. The part stands in a pool of "
            "light with its size so far on dimension lines, the features built so far are solid and the rest of the design is a faint plot. "
            "The program lists the features in build order: %s."
            % (M["name"].lower(), now_row + 1, name, ", ".join(f["label"] for f in listing)))
    return [("building", svg.render(desc))]


# ═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# Small motion helpers shared by the strips and cards
# ═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
def counter(svg: Svg, x, y, values: list, times: list, size, weight, fill, dur, once=True, anchor="start", ls=0.0):
    """A number counting up: each value shown from its time until the next; the last one is the resting state."""
    n = len(values)
    for i, v in enumerate(values):
        t0 = times[i]
        t1 = times[i + 1] if i + 1 < n else None
        fr = [(0, {"opacity": "1" if i == 0 else "0"})]
        if i:
            fr += [(t0 - 1e-3, {"opacity": "0"}), (t0, {"opacity": "1"})]
        if t1 is not None:
            fr += [(t1 - 1e-3, {"opacity": "1"}), (t1, {"opacity": "0"})]
        cls = svg.anim(fr, ease="linear", rest={"opacity": "1" if i == n - 1 else "0"}, dur=dur, once=once)
        svg.text(x, y, str(v), size, weight, fill, anchor=anchor, ls=ls, cls=cls)


def cycle(svg: Svg, t_in: float, t_out: float, fade=0.4, rise=8.0, scale=0.0) -> str:
    """In at t_in, out at t_out, on the drawing's loop; resting visible."""
    hid = {"opacity": "0"}
    vis = {"opacity": "1"}
    if rise:
        hid["transform"] = "translateY(%gpx)" % rise
        vis["transform"] = "translateY(0px)"
    if scale:
        hid["transform"] = "scale(%g)" % scale
        vis["transform"] = "scale(1)"
    fr = [(0, hid), (t_in, hid), (t_in + fade, vis), (t_out, vis), (min(svg.loop, t_out + 0.3), {"opacity": "0"})]
    return svg.anim(fr, origin="center" if scale else "")


def typing(svg: Svg, x, y, s, size, weight, fill, t0, t1, t_out, bg, caret, family="sans"):
    """Text typed in: a cover the colour of the field steps off it one character at a time, the caret riding its edge."""
    w = svg.text(x, y, s, size, weight, fill, family=family)
    n = max(1, len(s))
    cls = svg.anim([(0, {"transform": "translateX(0px)"}), (t0, {"transform": "translateX(0px)"}),
                    (t1, {"transform": "translateX(%spx)" % f1(w + 3)}), (t_out, {"transform": "translateX(%spx)" % f1(w + 3)}),
                    (t_out + 1e-3, {"transform": "translateX(0px)"})], ease="steps(%d,end)" % n,
                   rest={"transform": "translateX(%spx)" % f1(w + 3)})
    car = svg.anim([(0, {"opacity": "0"}), (t0 - 0.2, {"opacity": "0"}), (t0 - 0.19, {"opacity": "1"}), (t1 + 0.25, {"opacity": "1"}),
                    (t1 + 0.26, {"opacity": "0"})], ease="linear", rest={"opacity": "0"})
    clip = svg.id("tc")
    svg.defs.append('<clipPath id="%s"><rect x="%s" y="%s" width="%s" height="%s"/></clipPath>'
                    % (clip, f1(x - 2), f1(y - size * 1.1), f1(w + 6), f1(size * 1.6)))
    svg.add('<g clip-path="url(#%s)"><g class="%s"><rect x="%s" y="%s" width="%s" height="%s" fill="%s"/><rect class="%s" x="%s" y="%s" '
            'width="1.6" height="%s" fill="%s"/></g></g>'
            % (clip, cls, f1(x - 1), f1(y - size * 1.05), f1(w + 8), f1(size * 1.45), bg, car, f1(x - 1), f1(y - size * 0.92),
               f1(size * 1.2), caret))
    return w


def check_mark(cx, cy, s=1.0) -> str:
    return "M%s %sl%s %sl%s %s" % (f1(cx - 4.2 * s), f1(cy + 0.2 * s), f1(2.9 * s), f1(2.9 * s), f1(5.6 * s), f1(-6.2 * s))


def type_ink(p: dict, light: bool) -> dict:
    if not light:
        return TYPE_INK
    return {"Outer wall": p["ink"], "Inner wall": p["ink3"], "Sparse infill": p["amber"], "Internal solid infill": p["blueprint"],
            "Top surface": p["datum"], "Bottom surface": mix(p["datum"], "#ffffff", 0.35), "Bridge": p["signal"],
            "Overhang wall": p["signal"], "Floating vertical shell": "#d0603f", "Gap infill": p["ink4"]}


# ═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# How it works: four beats in two pictures (side by side on a wide page, stacked on a phone), one shared clock
# ═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
BEAT_LOOP = 12.0
BEATS = [("Describe", "Words, a photo, a sketch, a part or a link."),
         ("Build", "Your agent writes real build123d CAD. It grows in front of you."),
         ("Review", "Every revision is checked on the solid itself."),
         ("Make", "STEP for CAD and CNC, meshes for renders, your slicer if you print.")]


def beat_window(j):
    return 0.4 + 2.7 * j, 0.4 + 2.7 * (j + 1)


def beat_describe(svg, p, x, y, w, h, t0, t1, t_out):
    svg.rect(x, y + 12, w, 100, 14, fill=p["well"])
    lines = ["A planetary stage,", "1:5, on a 5 mm shaft"]
    mid = t0 + (t1 - t0) * 0.5
    typing(svg, x + 13, y + 44, lines[0], 13.5, 450, p["ink"], t0 + 0.1, mid - 0.15, t_out, p["well"], p["datum"])
    typing(svg, x + 13, y + 65, lines[1], 13.5, 450, p["ink"], mid, t1 - 0.6, t_out, p["well"], p["datum"])
    send = svg.anim([(0, {"opacity": ".25"}), (t1 - 0.5, {"opacity": ".25"}), (t1 - 0.3, {"opacity": "1"}), (t_out, {"opacity": "1"}),
                     (t_out + 0.3, {"opacity": ".25"})], rest={"opacity": "1"})
    cx, cy = x + w - 24, y + 89
    svg.add('<g class="%s"><circle cx="%s" cy="%s" r="12" fill="%s"/><path d="M%s %sv-10M%s %sl4.5-4.5 4.5 4.5" stroke="%s" stroke-width="1.8" '
            'stroke-linecap="round" stroke-linejoin="round"/></g>' % (send, f1(cx), f1(cy), p["tint"], f1(cx), f1(cy + 5), f1(cx - 4.5),
                                                                    f1(cy - 0.5), p["tintInk"]))


def beat_build(svg, p, d, x, y, w, h, t0, t1, t_out):
    tris = all_tris(d).reshape(-1, 3)
    cam = Camera(az=-36, el=21, target=tris.mean(0), dist=440)
    cam.fit(tris, (x + 6, y + 6, w - 12, h - 12))
    fills, ed = draw_solid(cam, tris.reshape(-1, 3, 3), svg.w, svg.h, d["edges"], edge_ink=p["edge"], base=p["clay"])
    f_in = svg.anim([(0, {"opacity": "0"}), (t1 - 0.9, {"opacity": "0"}), (t1 - 0.2, {"opacity": "1"}), (t_out, {"opacity": "1"}),
                     (t_out + 0.3, {"opacity": "0"})], rest={"opacity": "1"})
    svg.add('<g class="%s">%s%s</g>' % (f_in, fills, ed))
    w_out = svg.anim([(0, {"opacity": "1"}), (t1 - 0.6, {"opacity": "1"}), (t1, {"opacity": "0"}), (BEAT_LOOP - 0.01, {"opacity": "0"}),
                      (BEAT_LOOP, {"opacity": "1"})], rest={"opacity": "0"})
    svg.add('<g class="%s">' % w_out)
    draw_dash(svg, wire(cam, d["edges"]), p["datum"], 1.0, t0 + 0.05, t1 - 0.6, BEAT_LOOP)
    svg.add("</g>")


def beat_prove(svg, p, G, x, y, w, h, t0, t1, t_out):
    fit = [c for c in G["applies"] if c["status"] == "PASS"]
    rows = []
    for c in fit:
        full = "%s: %s" % (c["label"], c["value"])
        for s_ in (full, c["label"]):
            if text_w(s_, 12.5, 480) <= w - 24:
                rows.append(s_)
                break
        if len(rows) == 4:
            break
    for i, s_ in enumerate(rows):
        ry = y + 16 + i * 26
        ti = t0 + 0.25 + i * (t1 - t0 - 0.8) / len(rows)
        g = cycle(svg, ti - 0.15, t_out, fade=0.25, rise=4)
        svg.g(g)
        svg.circle(x + 9, ry, 9, alpha(p["pass_"], 0.16))
        svg.text(x + 26, ry + 4.4, s_, 12.5, 480, p["ink"])
        svg.end()
        draw_dash(svg, check_mark(x + 9, ry, 0.95), p["pass_"], 1.8, ti, ti + 0.3, BEAT_LOOP, hold=t_out + 0.3)
    g = cycle(svg, t1 - 0.5, t_out, fade=0.3, rise=4)
    svg.text(x, y + h - 4, "%d of %d checks pass" % (G["passed"], len(G["applies"])), 12.5, 520, p["pass_"], cls=g)


def beat_make(svg, p, d, x, y, w, h, t0, t1, t_out):
    lab = {"step": "STEP", "stl": "STL", "3mf": "3MF", "obj": "OBJ", "glb": "GLB"}
    use = {"step": "CAD, CNC", "stl": "meshes", "3mf": "slicers", "obj": "renders", "glb": "the web"}
    rows = sorted([r for r in d["hashes"] if r[0] in lab], key=lambda r: list(lab).index(r[0]))[:4]
    for i, (kind, name, hx, size) in enumerate(rows):
        ry = y + 16 + i * 26
        ti = t0 + 0.2 + i * (t1 - t0 - 0.8) / len(rows)
        g = cycle(svg, ti, t_out, fade=0.25, rise=4)
        svg.g(g)
        svg.rect(x, ry - 11, 46, 22, 6, fill=p["panel2"])
        svg.text(x + 23, ry + 4.4, lab[kind], 11.5, 640, p["datum"], anchor="middle", family="mono")
        svg.text(x + 56, ry + 4.4, use[kind], 12.5, 480, p["ink"])
        svg.end()
    g = cycle(svg, t1 - 0.5, t_out, fade=0.3, rise=4)
    svg.text(x, y + h - 4, "3MF and G-code if you print", 12.5, 520, p["ink3"], cls=g)


def steps(data, light: bool):
    p = P(light)
    d = data["planetary-gear-stage"]
    G = model_facts(d)
    out = []
    for half in (0, 1):
        svg = Svg(414, 368, BEAT_LOOP, "How it works")
        for k in (0, 1):
            j = half * 2 + k
            x = 3 + k * 209
            svg.rect(x, 0, 199, 368, 22, fill=p["panel"])
            t0, t1 = beat_window(j)
            t_out = BEAT_LOOP - 0.5
            svg.text(x + 20, 58, str(j + 1), 40, 600, p["ink4"], ls=-1)
            lit = svg.anim([(0, {"opacity": "0"}), (t0, {"opacity": "0"}), (t0 + 0.25, {"opacity": "1"}), (t_out, {"opacity": "1"}),
                            (t_out + 0.3, {"opacity": "0"})], rest={"opacity": "1"})
            svg.text(x + 20, 58, str(j + 1), 40, 600, p["datum"], ls=-1, cls=lit)
            mx, my, mw, mh = x + 20, 82, 159, 136
            if j == 0:
                beat_describe(svg, p, mx, my, mw, mh, t0, t1, t_out)
            elif j == 1:
                beat_build(svg, p, d, mx, my, mw, mh, t0, t1, t_out)
            elif j == 2:
                beat_prove(svg, p, G, mx, my, mw, mh, t0, t1, t_out)
            else:
                beat_make(svg, p, d, mx, my, mw, mh, t0, t1, t_out)
            title, line = BEATS[j]
            svg.text(x + 20, 266, title, 26, 640, p["ink"], ls=-0.6)
            for i, ln in enumerate(wrap(line, 160, 15.5, 440)):
                svg.text(x + 20, 294 + i * 21.5, ln, 15.5, 440, p["ink2"])
        a, b = BEATS[half * 2][0], BEATS[half * 2 + 1][0]
        desc = "%d %s, %d %s: %s %s" % (half * 2 + 1, a, half * 2 + 2, b, BEATS[half * 2][1], BEATS[half * 2 + 1][1])
        out.append(("steps-%d" % (half + 1), svg.render(desc)))
    return out


# ═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# The numbers, in two pictures
# ═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
def numbers(data, light: bool):
    p = P(light)
    n_tools = len(data["tools"])
    n_agents = len(AGENT_APPS) + len(MODEL_APIS) + len(LOCAL)
    items = [(n_tools, "MCP tools for any agent"), (n_agents, "agent apps, model APIs and local models"),
             (3, "platforms: macOS, Windows and Linux"), (0, "uploads of your files by Form Studio on its own")]
    out = []
    for half in (0, 1):
        svg = Svg(414, 178, 4.0, "Form Studio in numbers")
        for k in (0, 1):
            n, label = items[half * 2 + k]
            x = 3 + k * 207 + 20
            svg.rect(x, 26, 10, 10, fill=p["datum"])
            steps_ = 9 if n > 9 else max(1, n)
            vals = sorted(set([round(n * i / steps_) for i in range(steps_ + 1)]))
            times = [0.25 + 0.9 * i / max(1, len(vals) - 1) for i in range(len(vals))]
            times[0] = 0.0
            counter(svg, x - 3, 112, vals, times, 78, 600, p["ink"], 1.3, ls=-3)
            for i, ln in enumerate(wrap(label, 170, 16, 450)):
                svg.text(x, 142 + i * 22, ln, 16, 450, p["ink2"])
        desc = "; ".join("%d %s" % it for it in items[half * 2: half * 2 + 2])
        out.append(("numbers-%d" % (half + 1), svg.render(desc)))
    return out


# ═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# Features: one idea per card, two to a row on a wide page
# ═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
CARD_W, CARD_H = 414, 436


def card(title: str, light: bool, loop: float):
    p = P(light)
    svg = Svg(CARD_W, CARD_H, loop, title)
    svg.rect(3, 0, CARD_W - 6, CARD_H, 24, fill=p["panel"])
    return svg, p


def card_words(svg: Svg, p, title: str, sentence: str):
    svg.text(27, 326, title, 27, 640, p["ink"], ls=-0.7)
    for i, ln in enumerate(wrap(sentence, 358, 16, 440)):
        svg.text(27, 358 + i * 23, ln, 16, 440, p["ink2"])


def f_start(data, light):
    title = "Start from anything"
    svg, p = card(title, light, 10.0)
    chips = ["“a hook for my desk”", "photo.jpg", "sketch, in mm", "bracket.step", "part.stl", "drawing.pdf", "a link"]
    x, y = 27, 34
    for i, c in enumerate(chips):
        w = text_w(c, 14, 520) + 30
        if x + w > 387:
            x, y = 27, y + 44
        g = cycle(svg, 0.1 + 0.12 * i, 9.6, fade=0.35, rise=10)
        svg.g(g)
        svg.rect(x, y, w, 34, 17, fill=p["panel2"])
        svg.text(x + 15, y + 22, c, 14, 520, p["ink"])
        svg.end()
        x += w + 8
    fy = 196
    svg.rect(27, fy, 360, 62, 18, fill=p["well"])
    ph = svg.anim([(0, {"opacity": "1"}), (2.0, {"opacity": "1"}), (2.3, {"opacity": "0"}), (9.4, {"opacity": "0"}), (9.7, {"opacity": "1"})],
                  rest={"opacity": "0"})
    svg.text(47, fy + 36, "What are we making?", 15, 450, p["ink3"], cls=ph)
    typing(svg, 47, fy + 36, "A hook for my desk, sized from photo.jpg", 14, 450, p["ink"], 2.3, 4.4, 9.4, p["well"], p["datum"])
    send = svg.anim([(0, {"opacity": ".3"}), (4.5, {"opacity": ".3"}), (4.7, {"opacity": "1"}), (9.4, {"opacity": "1"}), (9.7, {"opacity": ".3"})],
                    rest={"opacity": "1"})
    cx, cy = 387 - 31, fy + 31
    svg.add('<g class="%s"><circle cx="%s" cy="%s" r="16" fill="%s"/><path d="M%s %sv-12M%s %sl5.5-5.5 5.5 5.5" stroke="%s" stroke-width="2" '
            'stroke-linecap="round" stroke-linejoin="round"/></g>' % (send, f1(cx), f1(cy), p["tint"], f1(cx), f1(cy + 6), f1(cx - 5.5),
                                                                    f1(cy - 0.5), p["tintInk"]))
    card_words(svg, p, title, "Words, a photo with a coin for scale, a sketch with real dimensions, a STEP, STL or 3MF part, a PDF drawing or a link.")
    return svg.render("%s: words, photos, sketches, STEP, STL and 3MF parts, PDF drawings and links in one composer." % title)


def gear_split(d) -> dict:
    """The planetary stage's triangles and B-rep edges by part, sorted by where they sit: the carrier below the gears
    (and its pins in the planet bores), the sun at the middle, a planet around each planet centre, the ring outside."""
    v = d["view"]["values"]
    m, zs, zp = v["module"], v["z_sun"], v["z_planet"]
    cd = d["derived"]["centre_distance"]["value"]
    centres = [np.array([cd * math.cos(2 * math.pi * k / 3), cd * math.sin(2 * math.pi * k / 3)]) for k in range(3)]
    tris = all_tris(d)
    z_top = float(tris[:, :, 2].max())
    z_gear = z_top - v["face"]

    def owner(pts):
        """pts (n, k, 3) → part name per row, from the centroid."""
        c = pts.mean(1)
        r = np.hypot(c[:, 0], c[:, 1])
        out = np.full(len(c), "ring", dtype=object)
        out[r < m * (zs + 2) / 2 + 0.6] = "sun"
        for k, ce in enumerate(centres):
            dk = np.hypot(c[:, 0] - ce[0], c[:, 1] - ce[1])
            out[dk < m * (zp + 2) / 2 + 0.6] = "planet%d" % k
            out[dk < v["bore"] / 2 - 0.02] = "carrier"
        out[c[:, 2] < z_gear - 1e-3] = "carrier"
        return out

    to, eo = owner(tris), owner(d["edges"])
    names = ["carrier", "ring", "sun", "planet0", "planet1", "planet2"]
    return {n: (tris[to == n], d["edges"][eo == n]) for n in names}, centres, z_top


def f_gears(data, light):
    title = "Mechanisms that mesh"
    d = data["planetary-gear-stage"]
    G = model_facts(d)
    v = d["view"]["values"]
    zs, zp = int(v["z_sun"]), int(v["z_planet"])
    zr = int(G["derived"]["z_ring"]["value"])
    loop = 24.0                                   # one turn of the sun; every part looks the same again after it
    svg, p = card(title, light, loop)
    parts, centres, z_top = gear_split(d)
    cam = Camera(az=0, el=89.9, target=(0, 0, z_top), dist=6000, fov=1.2)
    every = np.concatenate([t for t, _ in parts.values()]).reshape(-1, 3)
    cam.fit(every, (166, 24, 222, 222))
    tone = {"carrier": mix(p["clay"], p["panel"], 0.55), "ring": p["clay"], "sun": p["tint"],
            "planet0": mix(p["clay"], "#ffffff" if not light else "#000000", 0.08)}
    tone["planet1"] = tone["planet2"] = tone["planet0"]
    # carrier held: the sun turns once, each planet -zs/zp of a turn on its own pin, the ring -zs/zr
    turns = {"carrier": 0.0, "sun": 1.0, "ring": -zs / zr, "planet0": -zs / zp, "planet1": -zs / zp, "planet2": -zs / zp}
    for name in ("carrier", "ring", "sun", "planet0", "planet1", "planet2"):
        tris, edges = parts[name]
        if not len(tris):
            continue
        cxy = (0.0, 0.0) if not name.startswith("planet") else tuple(centres[int(name[-1])])
        (ox, oy), = cam.project(np.array([[cxy[0], cxy[1], z_top]]))[0]
        fills, ed = draw_solid(cam, tris, svg.w, svg.h, edges, edge_ink=p["edge"], base=tone[name])
        deg = 360.0 * turns[name]
        if deg:
            k = svg.id("k")
            svg.css.append("@keyframes %s{from{transform:rotate(0deg)}to{transform:rotate(%sdeg)}}" % (k, f1(-deg)))
            svg.css.append(".%s{transform-box:view-box;transform-origin:%spx %spx;animation:%s %gs linear infinite}"
                           % (k, f1(ox), f1(oy), k, loop))
            svg.add('<g class="%s">%s%s</g>' % (k, fills, ed))
        else:
            svg.add("<g>%s%s</g>" % (fills, ed))
    svg.text(27, 40, "Carrier held", 13, 600, p["ink"])
    svg.text(27, 60, "sun %d · planets %d · ring %d" % (zs, zp, zr), 12.5, 450, p["ink3"])
    rc, rs = G["derived"]["ratio_carrier"]["value"], G["derived"]["ratio_star"]["value"]
    svg.text(27, 268, "%s with the ring held · %s reversed with the carrier held" % (ratio(rc), ratio(rs)), 12.5, 450, p["ink3"])
    card_words(svg, p, title, "Involute gears from the parts library, meshed by the agent and turned here by their own tooth counts.")
    return svg.render("%s: the %s seen from above, turning with the carrier held: sun %d, planets %d, ring %d teeth; %s with the "
                      "ring held, %s reversed with the carrier held." % (title, G["name"].lower(), zs, zp, zr, ratio(rc), ratio(rs)))


def f_shape(data, light):
    title = "Shapes, not just boxes"
    d = data["ergonomic-mouse-shell"]
    M = model_facts(d)
    loop = 10.0
    svg, p = card(title, light, loop)
    drawn_part(svg, p, d, (47, 30, 320, 222), -142, 26, 0.4, 3.2, 2.9, 3.8, rings_=False)
    wall = d["view"]["values"].get("wall")
    svg.text(27, 268, "%s · %s mm%s" % (M["name"], M["size"], " · %s mm wall" % f1(wall) if wall else ""), 12.5, 450, p["ink3"])
    card_words(svg, p, title, "Lofted surfaces, scoops and splits, written as code and built as solids you can still edit.")
    return svg.render("%s: an %s, %s mm, lofted through rounded sections and hollowed to an even wall, with a thumb scoop, "
                      "split buttons and a wheel slot." % (title, M["name"].lower(), M["size"]))


AGENT_APPS = ["Claude Code", "Codex", "Gemini CLI", "Cursor CLI", "OpenCode", "Qwen Code", "GitHub Copilot CLI"]
MODEL_APIS = ["Anthropic", "OpenAI", "Gemini", "OpenRouter", "Mistral", "xAI", "DeepSeek", "Groq"]
LOCAL = ["Ollama", "LM Studio", "llama.cpp"]


def f_talk(data, light):
    title = "Talk to any model"
    picks = [(0, 0), (1, 0), (2, 0), (0, 1), (1, 2), (2, 1), (0, 6), (1, 4)]
    step = 1.15
    svg, p = card(title, light, step * len(picks))
    cols = [("Agent apps", AGENT_APPS), ("Model APIs", MODEL_APIS), ("Local", LOCAL)]
    cx_, x0, y0, rh = [0, 144, 272], 27, 74, 23
    hl = alpha(p["tint"], 0.16) if not light else alpha(p["datum"], 0.12)
    fr = []
    for i, (c, r) in enumerate(picks):
        t = i * step
        tr = {"transform": "translate(%spx,%spx)" % (f1(cx_[c]), f1(r * rh))}
        fr += [(t + (0.32 if i else 0), tr), (t + step, tr)]
    fr.append((svg.loop - 0.001, fr[-1][1]))
    mv = svg.anim([(0, fr[0][1])] + fr, ease="cubic-bezier(.65,0,.35,1)")
    svg.rect(x0 - 8, y0 - 16, 124, 23, 7, fill=hl, cls=mv)
    for ci, (head, names) in enumerate(cols):
        svg.text(x0 + cx_[ci], 44, head, 13, 620, p["ink"])
        for ri, n in enumerate(names):
            svg.text(x0 + cx_[ci], y0 + ri * rh, n, 13.5, 450, p["ink2"])
    card_words(svg, p, title, "Agent apps, model APIs or local models. Every conversation keeps its own agent and model, and its design.")
    return svg.render("%s: agent apps %s; model APIs %s; local models %s." % (title, ", ".join(AGENT_APPS), ", ".join(MODEL_APIS), ", ".join(LOCAL)))


def arc_path(cx, cy, r, a0, a1) -> str:
    x0, y0 = cx + r * math.sin(a0), cy - r * math.cos(a0)
    x1, y1 = cx + r * math.sin(a1), cy - r * math.cos(a1)
    return "M%s %sA%s %s 0 %d 1 %s %s" % (f1(x0), f1(y0), f1(r), f1(r), 1 if a1 - a0 > math.pi else 0, f1(x1), f1(y1))


def f_proved(data, light):
    title = "Proved on the solid"
    d = data[PRINT_ID]
    F = stand_facts(d)
    loop = 10.0
    svg, p = card(title, light, loop)
    checks = F["checks"]
    n = len(checks)
    cx, cy, r = 118, 146, 78
    svg.add('<circle cx="%s" cy="%s" r="%s" stroke="%s" stroke-width="16"/>' % (cx, cy, r, p["panel2"]))
    gap = math.radians(3.2)
    seg = 2 * math.pi / n
    t0, dt = 0.4, 0.2
    for i, c in enumerate(checks):
        a0, a1 = i * seg + gap / 2, (i + 1) * seg - gap / 2
        ink = ev_ink(p, c["evidence"]) if c["status"] == "PASS" else p["signal"]
        draw_dash(svg, arc_path(cx, cy, r, a0, a1), ink, 16, t0 + i * dt, t0 + i * dt + 0.28, loop, hold=loop - 0.05,
                  ease="cubic-bezier(.23,1,.32,1)", cap="butt")
    passed = sum(1 for c in checks if c["status"] == "PASS")
    counter(svg, cx, cy + 14, list(range(passed + 1)), [0.0] + [t0 + i * dt + 0.28 for i in range(passed)], 46, 620, p["ink"], loop,
            once=False, anchor="middle", ls=-1.5)
    svg.text(cx, cy + 38, "checks pass", 13, 500, p["ink3"], anchor="middle")
    lx = 232
    order = [e for e in ("computed", "heuristic", "model", "simulated", "measured") if e in F["evidence"]]
    notes = {"computed": "from the solid or the mesh", "heuristic": "a rule of thumb, stated", "model": "a stated model, not a test"}
    for k, e in enumerate(order):
        yy = 92 + k * 54
        g = cycle(svg, t0 + n * dt + 0.1 + 0.15 * k, 9.6, fade=0.35, rise=6)
        svg.g(g)
        svg.rect(lx, yy - 10, 10, 10, 3, fill=ev_ink(p, e))
        svg.text(lx + 18, yy, "%d %s" % (F["evidence"][e], e), 15, 600, p["ink"])
        svg.text(lx + 18, yy + 20, notes.get(e, ""), 12.5, 450, p["ink3"])
        svg.end()
    card_words(svg, p, title, "Every revision is checked on the B-rep and its mesh, and every number says how it is known.")
    desc = "%s: %s; %s." % (title, ", ".join("%s %s" % (c["label"].lower(), c["value"]) for c in checks),
                            ", ".join("%d %s" % (F["evidence"][e], e) for e in order))
    return svg.render(desc)


def f_move(data, light):
    title = "Assemblies that move"
    d = data["hinged-box"]
    asm = d["asm"]
    joint = asm["joints"][0]
    lid = next(pp for pp in asm["parts"] if pp["id"] == joint["part"])
    M = np.array(lid["placement"]["m"])
    lo_deg, hi_deg = joint["range"]
    check = next(parse_check(c) for c in d["state"]["checks"] if joint["label"] in c and "moves" in c)
    body_t = np.concatenate([m["tris"] for m in d["meshes"] if m["part"] != lid["id"]])
    lid_t = np.concatenate([m["tris"] for m in d["meshes"] if m["part"] == lid["id"]])
    lid_a = lid_t @ M[:, :3].T + M[:, 3]
    be = d["part_edges"].get("body")
    le = d["part_edges"].get(lid["id"])
    le_a = le @ M[:, :3].T + M[:, 3]
    o = np.array(joint["origin"])
    N = 12
    angles = [lo_deg + (hi_deg - lo_deg) * (1 - math.cos(math.pi * i / (N - 1))) / 2 for i in range(N)]
    loop = 8.0
    svg, p = card(title, light, loop)
    allp = [body_t.reshape(-1, 3)]
    for a in (angles[0], angles[-1]):
        R = rot(joint["axis"], math.radians(a))
        allp.append((lid_a.reshape(-1, 3) - o) @ R.T + o)
    allp = np.concatenate(allp)
    lo, hi = allp.min(0), allp.max(0)
    cam = Camera(az=-40, el=24, target=(lo + hi) / 2, dist=420)
    cam.fit(allp, (57, 22, 310, 228))
    c0 = (lo + hi) / 2
    rad = float(np.linalg.norm((hi - lo)[:2])) / 2
    k_ = px_per_mm(cam, 420)
    soft_shadow(svg, cam, (c0[0], c0[1], 0), rad * k_ * 0.95, rad * k_ * 0.34, p["shadow"])
    rings(svg, cam, (c0[0], c0[1], 0), [rad * 1.05, rad * 1.4], p["grid"])
    hold0, move, hold1 = 0.8, 2.4, 0.8
    st = move / (N - 1)
    seq, t = [], hold0
    seq.append((0, 0.0, hold0))
    for i in range(1, N):
        seq.append((i, t, t + st))
        t += st
    seq[-1] = (N - 1, seq[-1][1], t + hold1)
    t += hold1
    for i in range(N - 2, -1, -1):
        seq.append((i, t, t + st))
        t += st
    seq[-1] = (0, seq[-1][1], loop)
    iv = [[(s, e) for j, s, e in seq if j == i] for i in range(N)]
    classes = window_classes(svg, iv, loop)
    for i, a in enumerate(angles):
        R = rot(joint["axis"], math.radians(a))
        tris = np.concatenate([body_t, (lid_a - o) @ R.T + o])
        ed = np.concatenate([be, (le_a - o) @ R.T + o])
        fills, edges = draw_solid(cam, tris, svg.w, svg.h, ed, edge_ink=p["edge"], base=p["clay"])
        svg.add('<g class="%s">%s%s' % (classes[i], fills, edges))
        svg.text(27, 46, "%d°" % round(a), 22, 620, p["datum"])
        svg.add("</g>")
    svg.text(27, 66, joint["label"], 13, 500, p["ink3"])
    svg.text(27, 268, "%s · %s" % (check["label"], check["value"]), 13, 500, p["ink2"])
    card_words(svg, p, title, "Joints are swept through their whole range and checked for collisions, assembled, exploded or laid out to print.")
    desc = ("%s: the %s's lid swings on the %s from %d to %d degrees; %s, %s." %
            (title, d["state"]["name"].lower(), joint["label"].lower(), lo_deg, hi_deg, check["label"].lower(), check["value"]))
    return svg.render(desc)


def f_slicer(data, light):
    title = "Your slicer, if you print"
    d = data[PRINT_ID]
    tp = d["toolpath"]
    loop = 10.0
    svg, p = card(title, light, loop)
    L = tp.layers
    # the layer with the most infill to see: sparse infill, while solid fills (drawn as a block at this size) stay small
    solid = {tp.types.index(t) for t in ("Bridge", "Top surface", "Bottom surface", "Internal solid infill") if t in tp.types}
    sparse = tp.types.index("Sparse infill")
    best, bl = -1.0, L // 3
    for l in range(1, L - 1):
        s0, s1 = tp.start[l], tp.start[l + 1]
        sg, ty = tp.seg[s0:s1], tp.seg_type[s0:s1]
        ln = np.hypot(sg[:, 2] - sg[:, 0], sg[:, 3] - sg[:, 1])
        if sum(float(ln[ty == t].sum()) for t in solid) > 400:
            continue
        score = float(ln[ty == sparse].sum()) + 50 * len(set(ty.tolist()))
        if score > best:
            best, bl = score, l
    s0, s1 = tp.start[bl], tp.start[bl + 1]
    pts = tp.seg[s0:s1].reshape(-1, 2)
    swap = np.ptp(pts[:, 1]) > np.ptp(pts[:, 0])         # the long side across the card
    if swap:
        pts = pts[:, ::-1]
    (bx0, by0), (bx1, by1) = pts.min(0), pts.max(0)
    # plan view from above
    s = min(352 / (bx1 - bx0), 196 / (by1 - by0))
    ox = 27 + (360 - (bx1 - bx0) * s) / 2 - bx0 * s
    oy = 50 + (200 + (by1 - by0) * s) / 2 + by0 * s
    ink = type_ink(p, light)
    by_type = {}
    for (x0, y0, x1, y1), ty in zip(tp.seg[s0:s1], tp.seg_type[s0:s1]):
        by_type.setdefault(int(ty), []).append((x0, y0, x1, y1))
    order = sorted(by_type, key=lambda t_: ["Outer wall", "Inner wall", "Gap infill", "Sparse infill", "Internal solid infill",
                                            "Bridge", "Top surface", "Bottom surface", "Floating vertical shell"].index(tp.types[t_])
                   if tp.types[t_] in TYPE_INK else 99)
    t0 = 0.3
    span = 6.2 / max(1, len(order))
    for i, ty in enumerate(order):
        dd = []
        for pl in chain(np.array(by_type[ty])):
            xy = np.array([[ox + b * s, oy - a * s] if swap else [ox + a * s, oy - b * s] for a, b in pl])
            xy = rdp(xy, 0.2)
            dd.append(rel_path(xy, close=False))
        draw_dash(svg, "".join(dd), ink.get(tp.types[ty], p["ink2"]), 1.0, t0 + i * span, t0 + (i + 1) * span, loop, hold=9.4,
                  ease="linear")
    name = d["state"]["slice_simulated"]
    svg.text(27, 34, "Layer %d of %d" % (bl + 1, L), 13, 600, p["ink"])
    svg.text(27 + text_w("Layer %d of %d" % (bl + 1, L), 13, 600) + 8, 34, "z %.2f mm · from the G-code" % tp.z[bl], 13, 450, p["ink3"])
    x = 27
    for ty in order:
        nm = tp.types[ty]
        wd = 13 + text_w(nm, 11.5, 450)
        if x + wd > 387:
            break
        svg.rect(x, 260, 8, 8, 2, fill=ink.get(nm, p["ink2"]))
        svg.text(x + 13, 268, nm, 11.5, 450, p["ink3"])
        x += wd + 14
    sl = data["slicers"]
    card_words(svg, p, title, "Printing is optional. %s and %s slice a print design with your printer's own presets." % (", ".join(sl[:-1]), sl[-1]))
    desc = ("%s: layer %d of %d of the %s, drawn line type by line type from the slicer's G-code; slicers: %s." %
            (title, bl + 1, L, d["state"]["name"].lower(), ", ".join(sl)))
    return svg.render(desc)


def f_release(data, light):
    title = "Release what you approved"
    d = data["planetary-gear-stage"]
    loop = 10.0
    svg, p = card(title, light, loop)
    lab = {"step": "STEP", "stl": "STL", "3mf": "3MF", "obj": "OBJ", "glb": "GLB", "gcode": "G-code"}
    rows = sorted(d["hashes"], key=lambda h: list(lab).index(h[0]) if h[0] in lab else 99)
    for i, (kind, name, hx, size) in enumerate(rows[:6]):
        y = 42 + i * 35
        g = cycle(svg, 0.3 + 0.18 * i, 9.3, fade=0.35, rise=6)
        svg.g(g)
        svg.text(27, y, lab.get(kind, kind.upper()), 14, 640, p["ink"])
        svg.text(100, y, "%.0f kB" % (size / 1000) if size < 1e6 else "%.1f MB" % (size / 1e6), 12.5, 450, p["ink3"])
        svg.text(387, y, hx[:8] + "…" + hx[-8:], 12.5, 450, p["ink2"], family="mono", anchor="end")
        svg.end()
        draw_dash(svg, check_mark(244, y - 4.5, 0.75), p["datum"], 1.6, 1.6 + 0.12 * i, 1.9 + 0.12 * i, loop, hold=9.3)
    svg.text(27, 268, "SHA-256 of %s %s's files, as exported" % (d["state"]["name"], "r%02d" % d["state"]["head"]), 12.5, 450, p["ink3"])
    card_words(svg, p, title, "Only a person approves a release. Its files are frozen with SHA-256 hashes and a report of every check.")
    desc = "%s: %s." % (title, "; ".join("%s %s sha256 %s" % (lab.get(k, k), n, h) for k, n, h, _ in rows[:6]))
    return svg.render(desc)


def f_headless(data, light):
    title = "Everything headless"
    d = data[PRINT_ID]
    loop = 10.0
    svg, p = card(title, light, loop)
    svg.rect(27, 20, 360, 258, 16, fill=p["well"])
    cmd = "form state " + PRINT_ID
    lines = d["state_text"].splitlines()
    want = ['"name": ', '"module": ', "Thinnest wall", '"time_min": ', '"filament_g": ']
    shown, last = [], None
    for i, ln in enumerate(lines):
        if any(w_ in ln for w_ in want) and not (want[0] in ln and shown and '"name"' in shown[0][1]):
            if last is not None and i != last + 1:
                shown.append((None, "…"))
            shown.append((i, ln.rstrip()))
            last = i
            if '"filament_g"' in ln:
                break
    shown = [(None, "{")] + shown + [(None, "…")]
    fs = 11.5
    x0, y0, lh = 43, 50, 19.5
    svg.text(x0, y0, "$", fs, 500, p["datum"], family="mono")
    typing(svg, x0 + text_w("$ ", fs, 500, "mono"), y0, cmd, fs, 450, p["ink"], 0.4, 1.6, 9.3, p["well"], p["datum"], family="mono")
    for k, (_, ln) in enumerate(shown):
        y = y0 + (k + 1) * lh
        g = cycle(svg, 1.9 + 0.09 * k, 9.3, fade=0.15, rise=0)
        ln = ln.replace("\t", " ")
        ink = p["ink3"] if ln.strip() in ("{", "…") else p["ink2"]
        svg.text(x0, y, elide(ln, 330, fs, 450, "mono"), fs, 450, ink, family="mono", cls=g)
    y = y0 + (len(shown) + 1) * lh
    if y < 268:
        g = cycle(svg, 1.9 + 0.09 * len(shown) + 0.2, 9.3, fade=0.15, rise=0)
        svg.text(x0, y, "$", fs, 500, p["datum"], family="mono", cls=g)
    card_words(svg, p, title, "Every action is a form command that prints JSON, and every agent tool is one of %d MCP tools." % len(data["tools"]))
    return svg.render("%s: $ %s prints the design as JSON: %s." % (title, cmd, " ".join(l.strip() for _, l in shown)))


FEATURES = [("start", f_start), ("shape", f_shape), ("gears", f_gears), ("move", f_move), ("proved", f_proved),
            ("release", f_release), ("slicer", f_slicer), ("talk", f_talk), ("headless", f_headless)]


def features(data, light: bool):
    return [("feature-%s" % n, fn(data, light)) for n, fn in FEATURES]


# ═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# Download buttons: one picture each, the same on light and dark pages (a link around a <picture> loses its dark
# source on GitHub), so each is a self-contained pill with its own edge
# ═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
DOWNLOADS = [("macos-arm64", "macOS", "Apple silicon"), ("macos-x64", "macOS", "Intel"),
             ("windows-x64", "Windows", "x64"), ("linux-x64", "Linux", "x64")]


def downloads(data, light: bool):
    out = []
    for i, (slug, os_, sub) in enumerate(DOWNLOADS):
        primary = i == 0
        W, H = 168, 56
        svg = Svg(W, H, 1.0, "Download for %s, %s" % (os_, sub))
        fill = T["ink"] if primary else "#19191a"
        ink = "#0b0b0c" if primary else T["ink"]
        ink2 = "rgba(11,11,12,.66)" if primary else T["ink2"]
        svg.rect(0.5, 0.5, W - 1, H - 1, 27.5, fill=fill, stroke="rgba(11,11,12,.14)" if primary else "rgba(255,255,255,.14)")
        svg.text(24, 26, os_, 16, 640, ink, ls=-0.2)
        svg.text(24, 42, sub, 12, 480, ink2)
        cx, cy = W - 29, H / 2
        svg.circle(cx, cy, 18, "#0b0b0c" if primary else "rgba(255,255,255,.14)")
        svg.add('<path d="M%s %sv11M%s %sl5 5 5-5" stroke="%s" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'
                % (f1(cx), f1(cy - 6.5), f1(cx - 5), f1(cy - 0.5), T["ink"]))
        out.append(("download-%s" % slug, svg.render("Download Form Studio for %s, %s" % (os_, sub))))
    return out


downloads.neutral = True
SCENES = {"hero": hero, "building": building, "steps": steps, "numbers": numbers, "features": features, "downloads": downloads}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--keep", type=Path, help="projects folder to build into and reuse")
    ap.add_argument("--only", help="comma-separated drawings to write")
    ap.add_argument("--fresh", action="store_true", help="read the engine again even when --keep has a cache")
    a = ap.parse_args()
    data_dir = a.keep or Path(tempfile.mkdtemp(prefix="form-readme-"))
    cache = data_dir / ".readme-art.pkl"
    import pickle
    if a.keep and cache.exists() and not a.fresh:
        data = pickle.loads(cache.read_bytes())
    else:
        data = engine(data_dir)
        if a.keep:
            cache.write_bytes(pickle.dumps(data))
    OUT.mkdir(parents=True, exist_ok=True)
    for name, fn in SCENES.items():
        if a.only and name not in a.only.split(","):
            continue
        neutral = getattr(fn, "neutral", False)
        for light in ((False,) if neutral else (False, True)):
            for fname, svg_text in fn(data, light):
                path = OUT / ("%s.svg" % fname if neutral else "%s-%s.svg" % (fname, "light" if light else "dark"))
                path.write_text(svg_text, encoding="utf-8")
                print("%-34s %7.1f kB" % (path.relative_to(ROOT), path.stat().st_size / 1024))


if __name__ == "__main__":
    main()
