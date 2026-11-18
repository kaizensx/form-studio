#!/usr/bin/env python3
"""The README's pictures: Form Studio drawn 1:1 as animated SVG, from real engine output.

Every part, number and check in these drawings comes from a real run of the engine on this machine:

  1. two designs are built from their recipes in a scratch projects folder (`form new`), so the CAD kernel builds
     the solids, the checks run on them and your slicer slices them;
  2. the triangle meshes and B-rep edges the app's viewport draws are read from the engine (`Studio.view`) and
     projected with the viewport's own camera (Viewport.qml: orbit angles, 26° field of view, framing);
  3. the check results, slice estimate and assembly joint come from the same run; the print playback is the
     slicer's G-code, read by form/toolpath.py.

The app's chrome is drawn from the QML Theme (colours are read from Theme.qml), its fonts (Instrument Sans, Geist
Mono and the Lucide icons, subset and embedded) and the layout of Home.qml, Workspace.qml, Talk.qml and Prove.qml.
GitHub shows an SVG in an <img> without scripts, so all motion is CSS keyframes and SMIL.

    .venv/bin/python scripts/readme_art.py              # writes docs/readme/*.svg (dark and light)
    .venv/bin/python scripts/readme_art.py --keep DIR   # reuse (or keep) the scratch projects folder

Needs the engine's extras (build123d) and, for the slice and print playback, a slicer Form Studio can drive.
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
    for name, hexv in re.findall(r'property color (\w+): "(#[0-9a-fA-F]{6})"', src):
        t[name] = hexv
    for name, r, g, b, a in re.findall(r"property color (\w+): Qt\.rgba\(([\d.]+), ([\d.]+), ([\d.]+), ([\d.]+)\)", src):
        t[name] = "rgba(%d,%d,%d,%s)" % (round(float(r) * 255), round(float(g) * 255), round(float(b) * 255), a)
    return t


T = _theme()


def alpha(hexv: str, a: float) -> str:
    h = hexv.lstrip("#")
    return "rgba(%d,%d,%d,%.3g)" % (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), a)


def mix(a: str, b: str, k: float) -> str:
    ha, hb = a.lstrip("#"), b.lstrip("#")
    ca = [int(ha[i:i + 2], 16) for i in (0, 2, 4)]
    cb = [int(hb[i:i + 2], 16) for i in (0, 2, 4)]
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * k) for x, y in zip(ca, cb))


EVIDENCE = {"computed": T["datum"], "specified": T["datum"], "heuristic": T["ink2"], "model": T["amber"],
            "modelled": T["amber"], "simulated": T["amber"], "assumed": T["amber"], "PASS": T["pass"]}

ICON = {}
for _n, _c in re.findall(r'"(\w+)": "\\u([0-9a-f]{4})"', (QML / "Icons.qml").read_text(encoding="utf-8")):
    ICON[_n] = chr(int(_c, 16))


# ═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# Fonts: measured with fontTools, embedded as subset WOFF2 per drawing
# ═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
FAMILY = {"sans": ("InstrumentSans.ttf", "IS"), "mono": ("GeistMono.ttf", "GM"), "icon": ("lucide.ttf", "LU")}


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
    def anim(self, frames: list, ease: str = "cubic-bezier(.23,1,.32,1)", origin: str = "") -> str:
        """frames: [(seconds, {css props})]. Returns a class name. Values hold between keys unless the next key
        differs (then they ease). The loop restarts at 0."""
        name = self.id("k")
        fr = sorted(frames, key=lambda f: f[0])
        if fr[0][0] > 0:
            fr.insert(0, (0.0, fr[0][1]))
        if fr[-1][0] < self.loop:
            fr.append((self.loop, fr[-1][1]))
        steps = []
        for t, props in fr:
            pct = 100.0 * t / self.loop
            body = ";".join("%s:%s" % kv for kv in props.items())
            steps.append("%.3f%%{%s;animation-timing-function:%s}" % (pct, body, ease))
        self.css.append("@keyframes %s{%s}" % (name, "".join(steps)))
        extra = ("transform-box:fill-box;transform-origin:%s;" % origin) if origin else ""
        self.css.append(".%s{animation:%s %gs infinite;%s}" % (name, name, self.loop, extra))
        return name

    def show(self, t_in: float, t_out: float | None = None, fade: float = 0.24, rise: float = 0.0, scale: float = 0.0) -> str:
        """Visible from t_in (fading and rising in) until t_out (fading out). Returns a class."""
        hid = {"opacity": "0"}
        vis = {"opacity": "1"}
        if rise:
            hid["transform"] = "translateY(%gpx)" % rise
            vis["transform"] = "translateY(0px)"
        if scale:
            hid["transform"] = "scale(%g)" % scale
            vis["transform"] = "scale(1)"
        fr = [(0, hid), (max(0.0, t_in), hid), (t_in + fade, vis)]
        if t_out is not None:
            fr += [(t_out, vis), (min(self.loop, t_out + fade * 0.7), hid)]
        return self.anim(fr, origin="center" if scale else "")

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

    def icon(self, x, y, name, size=14, fill=None, cls=""):
        """Lucide glyph centred on (x, y)."""
        self.text(x - size / 2, y + size / 2, ICON[name], size=size, family="icon", fill=fill or T["ink2"], cls=cls)

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
        style = "<style>%s%s@media (prefers-reduced-motion:reduce){*{animation:none!important}}</style>" % (faces, "".join(self.css))
        head = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %s %s" width="%s" height="%s" role="img" fill="none">'
                % (f1(self.w), f1(self.h), f1(self.w), f1(self.h)))
        t = "<title>%s</title>" % esc(self.title) if self.title else ""
        d = "<desc>%s</desc>" % esc(desc) if desc else ""
        defs = "<defs>%s</defs>" % "".join(self.defs) if self.defs else ""
        return head + t + d + style + defs + "".join(self.body) + "</svg>\n"


# ═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# The engine: two real designs, built, checked and sliced
# ═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
DESIGNS = {"desk-phone-stand": ("Desk phone stand", "device_stand", []),
           "hinged-box": ("Hinged box", "storage_box", ["lid=2"])}


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
    from form import config, toolpath
    from form.studio import Studio
    st = Studio(config.load())
    out = {}
    for pid in DESIGNS:
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
        try:
            tp = toolpath.for_project(st, p)
        except Exception as e:  # no slicer: the print card is left out
            print("no toolpath for %s: %s" % (pid, e))
        out[pid] = {"state": state, "view": view, "meshes": meshes, "edges": edges, "asm": asm,
                    "part_edges": part_edges, "toolpath": tp}
    return out


def mesh_edges(d):
    """The B-rep edges in the frame the meshes are in (an assembly's parts carry their own)."""
    if d["edges"] is not None:
        return d["edges"]
    if d["part_edges"]:
        return np.concatenate(list(d["part_edges"].values()))
    return None


def parse_check(s: str) -> dict:
    """'PASS  Thinnest wall: 4.86 mm  [computed]' → status, label, value, evidence"""
    m = re.match(r"(\w+)\s+(.*?)\s+\[(\w+)\]$", s)
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
    lum = 0.50 + 0.34 * k + 0.12 * s
    h = base.lstrip("#")
    rgb = np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], float)
    cols = np.clip(rgb[None, :] * lum[:, None] * 0.98, 0, 255)
    q = np.round(cols / 3) * 3
    return ["#%02x%02x%02x" % tuple(int(v) for v in c) for c in q]


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


def draw_solid(cam: Camera, tris: np.ndarray, W: float, H: float, edges: np.ndarray | None = None,
               colors: list | None = None, edge_ink: str = "rgba(28,30,30,.55)") -> tuple[str, str]:
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
    cols = shade(nrm, cam) if colors is None else colors
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
        d = "".join("M%s %sL%s %sL%s %sZ" % (f1(xy[i][0][0]), f1(xy[i][0][1]), f1(xy[i][1][0]), f1(xy[i][1][1]),
                                              f1(xy[i][2][0]), f1(xy[i][2][1])) for i in batch)
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
                        out.append("M%s %sL%s %s" % (f1(pts[run][0]), f1(pts[run][1]), f1(pts[e_][0]), f1(pts[e_][1])))
                    run = None
        if out:
            epath = '<path d="%s" stroke="%s" stroke-width=".8" stroke-linecap="round" fill="none"/>' % ("".join(out), edge_ink)
    return "".join(paths), epath


def draw_plate(svg: Svg, cam: Camera, size=(180, 180), center=(0, 0), fade_id: str = "", grid=10,
               plate_fill="#252b2f", grid_ink="#1a1f22"):
    """The build plate: a graphite slab with a 10 mm grid, fading into the bench."""
    w, h = size
    cx, cy = center
    corners = np.array([[cx - w / 2, cy - h / 2, 0], [cx + w / 2, cy - h / 2, 0], [cx + w / 2, cy + h / 2, 0], [cx - w / 2, cy + h / 2, 0]])
    xy, _ = cam.project(corners)
    d = "M" + "L".join("%s %s" % (f1(x), f1(y)) for x, y in xy) + "Z"
    lines = []
    for gx in np.arange(cx - w / 2, cx + w / 2 + 0.01, grid):
        a, _ = cam.project(np.array([[gx, cy - h / 2, 0], [gx, cy + h / 2, 0]]))
        lines.append("M%s %sL%s %s" % (f1(a[0][0]), f1(a[0][1]), f1(a[1][0]), f1(a[1][1])))
    for gy in np.arange(cy - h / 2, cy + h / 2 + 0.01, grid):
        a, _ = cam.project(np.array([[cx - w / 2, gy, 0], [cx + w / 2, gy, 0]]))
        lines.append("M%s %sL%s %s" % (f1(a[0][0]), f1(a[0][1]), f1(a[1][0]), f1(a[1][1])))
    mask = ' mask="url(#%s)"' % fade_id if fade_id else ""
    svg.add('<g%s><path d="%s" fill="%s"/><path d="%s" stroke="%s" stroke-width="1"/>'
            '<path d="%s" stroke="#2f363b" stroke-width="1"/></g>' % (mask, d, plate_fill, "".join(lines), grid_ink, d))


# ═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# App pieces, drawn as in the QML
# ═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
_LP = (QML / "LogoPaths.js").read_text(encoding="utf-8")
LOGO_FORM = re.search(r'var form = "([^"]+)"', _LP).group(1)
LOGO_STUDIO = re.search(r'var studio = "([^"]+)"', _LP).group(1)
LOGO_W = float(re.search(r"width = ([\d.]+)", _LP).group(1))
LOGO_CAP = float(re.search(r"capHeight = ([\d.]+)", _LP).group(1))


def logo(svg: Svg, x, cy, size=14, ink=None, ink2=None, cls="", part=None, word=True) -> float:
    """Logo.qml: the F as a coordinate frame (the origin in datum, the arms in clay) and the wordmark outlines,
    left edge at x, centred on cy. Returns the width."""
    u = size / 48
    y = cy - size / 2
    cut = 2 * u if size >= 24 else 0
    clay = part or T["clay"]
    out = ['<g%s>' % (' class="%s"' % cls if cls else "")]
    out.append('<rect x="%s" y="%s" width="%s" height="%s" fill="%s"/>' % (f1(x), f1(y), "%.2f" % (12 * u), "%.2f" % (12 * u), T["datum"]))
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


def tag(svg: Svg, x, y, text, kind=None) -> float:
    """Tag.qml: 17 px, the evidence colour at 11 % behind its own colour, caps."""
    tint = EVIDENCE.get(kind or text, T["ink2"])
    w = text_w(text.upper(), 10, 620, ls=0.6) + 12
    svg.rect(x, y, w, 17, 4, fill=alpha(tint, 0.11) if tint.startswith("#") else tint)
    svg.text(x + w / 2, y + 12.2, text, 10, 620, tint, anchor="middle", ls=0.6, upper=True)
    return w


def btn(svg: Svg, x, y, text, icon=None, h=28, quiet=True, fill=None, ink=None, size=13, weight=520, cls="", small=False) -> float:
    """Btn.qml: icon then words, 13 px (12 when small), medium weight."""
    if small:
        size, h = 12, 24
    gap = 5 if small else 6
    isz = 13 if small else 14
    w = (text_w(text, size, weight) if text else 0) + ((isz + gap) if icon and text else isz if icon else 0) + ((16 if small else 22) if text else (8 if small else 12))
    if cls:
        svg.g(cls)
    if not quiet:
        svg.rect(x, y, w, h, 6, fill=fill or T["plate3"], stroke=T["rule2"])
    ix = x + ((8 if small else 11) if text else (4 if small else 6))
    if icon:
        svg.icon(ix + isz / 2, y + h / 2, icon, isz, ink or T["ink2"])
        ix += isz + gap
    if text:
        svg.text(ix, y + h / 2 + size * 0.36, text, size, weight, ink or T["ink"])
    if cls:
        svg.end()
    return w


def window(svg: Svg, x, y, w, h, light: bool, r=12):
    """The window: rounded, a hairline edge and a soft shadow that suits the page behind it."""
    fid = svg.id("sh")
    if light:
        svg.defs.append('<filter id="%s" x="-10%%" y="-10%%" width="120%%" height="130%%"><feGaussianBlur in="SourceAlpha" stdDeviation="14"/>'
                        '<feOffset dy="10"/><feComponentTransfer><feFuncA type="linear" slope=".22"/></feComponentTransfer>'
                        '<feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge></filter>' % fid)
    else:
        svg.defs.append('<filter id="%s" x="-10%%" y="-10%%" width="120%%" height="130%%"><feGaussianBlur in="SourceAlpha" stdDeviation="16"/>'
                        '<feOffset dy="12"/><feComponentTransfer><feFuncA type="linear" slope=".6"/></feComponentTransfer>'
                        '<feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge></filter>' % fid)
    svg.rect(x, y, w, h, r, fill=T["plate"], extra=' filter="url(#%s)"' % fid)
    cid = svg.id("clip")
    svg.defs.append('<clipPath id="%s"><rect x="%s" y="%s" width="%s" height="%s" rx="%s"/></clipPath>' % (cid, f1(x), f1(y), f1(w), f1(h), r))
    return cid


def window_edge(svg: Svg, x, y, w, h, light: bool, r=12):
    svg.rect(x + 0.5, y + 0.5, w - 1, h - 1, r, stroke="rgba(0,0,0,.18)" if light else "rgba(255,255,255,.10)")


def traffic(svg: Svg, x, y):
    for i, c in enumerate(("#ff5f57", "#febc2e", "#28c840")):
        svg.circle(x + i * 20, y, 6, c)


# ═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# The hero: Home, a request typed into the composer, then the workspace building, checking and slicing it
# ═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
REQUEST = "A stand for my phone on the desk, leaning back 20°, with a slot for the charging cable"


def topbar_home(svg: Svg, W, printer: str):
    svg.rect(0, 0, W, 44, fill=T["plate1"])
    svg.rect(0, 43, W, 1, fill=T["rule"])
    traffic(svg, 20, 22)
    logo(svg, 90, 22)
    # right: setup notice, printer, search, settings
    x = W - 23
    svg.icon(x, 22, "settings", 15, T["ink2"])
    x -= 23 + 170
    svg.rect(x, 9, 170, 26, 6, fill=T["well"], stroke=T["rule2"])
    svg.icon(x + 15, 22, "search", 13, T["ink3"])
    svg.text(x + 29, 26.5, "Search", 13, 420, T["ink3"])
    svg.text(x + 158, 26.5, "⌘K", 11, 420, T["ink3"], anchor="end")
    pw = text_w(printer, 12, 420)
    x -= 14 + pw
    svg.text(x, 26, printer, 12, 420, T["ink2"])
    svg.icon(x - 13, 22, "printer", 13, T["ink3"])
    return x - 13


def composer(svg: Svg, x, y, w, typing: tuple | None):
    """StartComposer.qml: a plate with the words, the four ways to add something, and Design it."""
    h = 148
    sid = svg.id("csh")
    svg.defs.append('<filter id="%s" x="-20%%" y="-30%%" width="140%%" height="170%%"><feGaussianBlur in="SourceAlpha" stdDeviation="17"/>'
                    '<feOffset dy="18"/><feComponentTransfer><feFuncA type="linear" slope=".55"/></feComponentTransfer>'
                    '<feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge></filter>' % sid)
    svg.rect(x, y, w, h, 22, fill=alpha(T["plate1"], 0.94), stroke=T["rule2"], extra=' filter="url(#%s)"' % sid)
    if typing:
        t0, t1, t_send = typing
        focus = svg.anim([(0, {"opacity": "0"}), (t0 - 0.3, {"opacity": "0"}), (t0, {"opacity": "1"}), (t_send + 0.3, {"opacity": "1"}), (t_send + 0.5, {"opacity": "0"})])
        svg.rect(x - 4, y - 4, w + 8, h + 8, 26, stroke=alpha(T["datum"], 0.1), sw=4, cls=focus)
        svg.rect(x + 0.5, y + 0.5, w - 1, h - 1, 21.5, stroke=alpha(T["datum"], 0.5), cls=focus)
    tx, ty = x + 22, y + 30
    ph = "Describe it, or drop a photo, a sketch, a part or a link…"
    if typing:
        t0, t1, t_send = typing
        hide = svg.anim([(0, {"opacity": "1"}), (t0 + 0.05, {"opacity": "1"}), (t0 + 0.06, {"opacity": "0"}), (svg.loop - 0.01, {"opacity": "0"})], ease="steps(1)")
        svg.text(tx, ty + 5, ph, 16, 420, T["ink4"], cls=hide)
        # the words, revealed character by character (SMIL: discrete widths at each character's advance)
        n = len(REQUEST)
        xs = [0.0]
        for i in range(n):
            xs.append(text_w(REQUEST[: i + 1], 16, 420))
        times = [t0 + (t1 - t0) * i / n for i in range(n + 1)]
        # a slightly human rhythm: pauses after commas
        cid = svg.id("type")
        T_ = svg.loop
        kt = [0.0] + [t / T_ for t in times] + [(t_send + 0.6) / T_, (t_send + 0.6) / T_ + 1e-4, 1.0]
        vals = [0.0] + xs + [xs[-1], 0.0, 0.0]
        svg.defs.append('<clipPath id="%s"><rect x="%s" y="%s" width="0" height="30">'
                        '<animate attributeName="width" dur="%gs" repeatCount="indefinite" calcMode="discrete" keyTimes="%s" values="%s"/>'
                        '</rect></clipPath>' % (cid, f1(tx - 1), f1(ty - 14), T_, ";".join("%.5f" % k for k in kt),
                                                ";".join(f1(v + 1) for v in vals)))
        svg.add('<g clip-path="url(#%s)">' % cid)
        svg.text(tx, ty + 5, REQUEST, 16, 420, T["ink"])
        svg.add("</g>")
        # caret
        cvals = [0.0] + xs + [xs[-1], 0.0, 0.0]
        caret_vis = svg.anim([(0, {"opacity": "0"}), (t0 - 0.01, {"opacity": "0"}), (t0, {"opacity": "1"}), (t_send, {"opacity": "1"}), (t_send + 0.01, {"opacity": "0"})], ease="steps(1)")
        svg.add('<rect x="%s" y="%s" width="1.5" height="19" fill="%s" class="%s"><animate attributeName="x" dur="%gs" repeatCount="indefinite" '
                'calcMode="discrete" keyTimes="%s" values="%s"/></rect>'
                % (f1(tx), f1(ty - 10), T["datum"], caret_vis, T_, ";".join("%.5f" % k for k in kt), ";".join(f1(tx + v + 1) for v in cvals)))
    else:
        svg.text(tx, ty + 5, ph, 16, 420, T["ink4"])
    # bottom row
    by = y + h - 30
    bx = x + 14
    for ic, label in (("paperclip", "Photo or file"), ("pen_tool", "Sketch"), ("link", "Link")):
        bx += btn(svg, bx, by - 14, label, ic) + 4
    svg.icon(bx + 10, by, "mic", 14, T["ink2"])
    # Design it: quiet while empty, datum once there are words
    gw = text_w("Design it", 13, 620) + 44 + 24
    gx, gy = x + w - 14 - gw, by - 19
    svg.rect(gx, gy, gw, 38, 19, fill=T["plate2"])
    svg.text(gx + 22, gy + 23.5, "Design it", 13, 620, T["ink4"])
    svg.icon(gx + gw - 26, gy + 19, "arrow_right", 13, T["ink4"])
    if typing:
        t0, t1, t_send = typing
        on = svg.anim([(0, {"opacity": "0", "transform": "scale(1)"}), (t0 + 0.08, {"opacity": "0", "transform": "scale(1)"}),
                       (t0 + 0.26, {"opacity": "1", "transform": "scale(1)"}), (t_send - 0.12, {"opacity": "1", "transform": "scale(1)"}),
                       (t_send, {"opacity": "1", "transform": "scale(.96)"}), (t_send + 0.14, {"opacity": "1", "transform": "scale(1)"}),
                       (t_send + 0.5, {"opacity": "1", "transform": "scale(1)"}), (t_send + 0.7, {"opacity": "0", "transform": "scale(1)"})], origin="center")
        svg.g(on)
        svg.rect(gx, gy, gw, 38, 19, fill=T["datum"])
        svg.text(gx + 22, gy + 23.5, "Design it", 13, 620, T["datumInk"])
        svg.icon(gx + gw - 26, gy + 19, "arrow_right", 13, T["datumInk"])
        svg.end()
    return h


def seg(svg: Svg, x, y, items, on=0, h=30, size=13) -> float:
    """Seg.qml: a well with the chosen option raised."""
    ws = [text_w(t, size, 520) + 20 for t in items]
    W = sum(ws) + 6
    svg.rect(x, y, W, h, 7, fill=T["well"], stroke=T["rule"])
    cx = x + 3
    for i, (t, w) in enumerate(zip(items, ws)):
        if i == on:
            svg.rect(cx, y + 3, w, h - 6, 5, fill=T["plate3"])
        svg.text(cx + w / 2, y + h / 2 + 4.6, t, size, 520, T["ink"] if i == on else T["ink3"], anchor="middle")
        cx += w
    return W


def home_scene(svg: Svg, W, H, data, typing):
    stand, box = data["desk-phone-stand"], data["hinged-box"]
    printer = stand["state"]["slice_simulated"]["presets"].split(" / ")[0]
    svg.rect(0, 0, W, H, fill=T["plate"])
    # the bench: a build plate in perspective behind the hero, darkened toward the edges (Home.qml)
    cam = Camera(az=-34, el=28.4, target=(0, 0, 0), dist=300)
    pts = np.array([[-130, -130, 0], [130, -130, 0], [130, 130, 0], [-130, 130, 0]], float)
    cam.fit(pts, (-40, 230, W + 80, 700))
    fid = svg.id("fade")
    svg.defs.append('<radialGradient id="%sg" cx=".5" cy=".42" r=".62"><stop offset="0" stop-color="#fff" stop-opacity=".9"/>'
                    '<stop offset=".7" stop-color="#fff" stop-opacity=".35"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></radialGradient>'
                    '<mask id="%s"><rect width="%s" height="%s" fill="url(#%sg)"/></mask>' % (fid, fid, W, H, fid))
    draw_plate(svg, cam, (260, 260), fade_id=fid, grid=10, plate_fill="#22282b", grid_ink="#161a1c")
    vg = svg.id("vg")
    svg.defs.append('<linearGradient id="%s" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="%s" stop-opacity=".85"/>'
                    '<stop offset=".32" stop-color="%s" stop-opacity=".25"/><stop offset=".62" stop-color="%s" stop-opacity=".55"/>'
                    '<stop offset="1" stop-color="%s"/></linearGradient>' % (vg, T["plate"], T["plate"], T["plate"], T["plate"]))
    svg.rect(0, 44, W, 640, fill="url(#%s)" % vg)
    # the scan line crossing the bench now and then
    sg = svg.id("scan")
    svg.defs.append('<linearGradient id="%s" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="%s" stop-opacity="0"/>'
                    '<stop offset=".5" stop-color="%s" stop-opacity=".05"/><stop offset="1" stop-color="%s" stop-opacity="0"/></linearGradient>'
                    % (sg, T["datum"], T["datum"], T["datum"]))
    sc = svg.anim([(0, {"transform": "translateY(160px)", "opacity": "0"}), (0.8, {"transform": "translateY(160px)", "opacity": "0"}),
                   (2.0, {"opacity": "1"}), (4.6, {"opacity": "1"}), (6.0, {"transform": "translateY(560px)", "opacity": "0"})], ease="ease-in-out")
    svg.rect(0, 0, W, 120, fill="url(#%s)" % sg, cls=sc)
    topbar_home(svg, W, printer)
    # setup notice (amber) sits left of the printer in the real bar; left out: it depends on the machine
    cx = W / 2
    svg.text(cx, 143, "GOOD AFTERNOON", 10, 620, T["datum"], anchor="middle", ls=1.6)
    svg.text(cx, 217, "What are we making?", 52, 620, T["ink"], anchor="middle", ls=-2.0)
    svg.text(cx, 258, "Describe it, drop a photo or a part, sketch it, or paste a link. It becomes real CAD,", 15, 420, T["ink2"], anchor="middle")
    svg.text(cx, 284.5, "checked and sliced for your printer.", 15, 420, T["ink2"], anchor="middle")
    cw = 820
    composer(svg, cx - cw / 2, 328, cw, typing)
    # under the composer
    items_y = 491
    parts = []
    sw = text_w("For my printer", 12, 520) + text_w("Just a 3D model", 12, 520) + 44 + 6
    pw = text_w(printer, 12, 520) + 34
    agent = "Claude Code · Default"
    aw = text_w(agent, 12, 520) + 34
    bw = text_w("Start blank", 12, 520) + 34
    total = sw + 6 + pw + 6 + aw + 6 + 9 + 6 + bw
    x = cx - total / 2
    seg(svg, x, items_y, ["For my printer", "Just a 3D model"], size=12)
    x += sw + 6
    x += btn(svg, x, items_y + 3, printer, "printer", small=True) + 6
    x += btn(svg, x, items_y + 3, agent, "sparkles", small=True) + 6
    svg.rect(x + 4, items_y + 7, 1, 16, fill=T["rule2"])
    x += 15
    btn(svg, x, items_y + 3, "Start blank", "square_dashed", small=True)
    svg.text(cx, 546, "Continue “Hinged box” · r01 · just now  →", 11, 420, T["ink3"], anchor="middle")
    # designs
    svg.text(120, 692, "Designs", 18, 620, T["ink"], ls=-0.2)
    svg.text(120 + text_w("Designs", 18, 620, ls=-0.2) + 12, 692, "2", 12, 420, T["ink3"], family="mono")
    rx = W - 120
    svg.icon(rx - 12, 687, "folder_open", 14, T["ink2"])
    w = text_w("Import…", 13, 520)
    svg.text(rx - 40 - w, 692, "Import…", 13, 520, T["ink"])
    svg.icon(rx - 40 - w - 14, 687, "import", 14, T["ink2"])
    cwid = (W - 240 - 3 * 16) / 4
    for i, (pid, d) in enumerate((("hinged-box", box), ("desk-phone-stand", stand))):
        x0 = 120 + i * (cwid + 16)
        y0 = 718
        ch = round(cwid * 0.74) + 62
        clip = svg.id("cc")
        svg.defs.append('<clipPath id="%s"><rect x="%s" y="%s" width="%s" height="%s" rx="16"/></clipPath>' % (clip, f1(x0), f1(y0), f1(cwid), ch))
        svg.add('<g clip-path="url(#%s)">' % clip)
        bg = svg.id("cg")
        svg.defs.append('<linearGradient id="%s" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2a3034"/><stop offset="1" stop-color="#1b2023"/></linearGradient>' % bg)
        svg.rect(x0, y0, cwid, ch, fill="url(#%s)" % bg)
        mini(svg, d, (x0, y0, cwid, ch - 62))
        svg.add("</g>")
        svg.rect(x0 + 0.5, y0 + 0.5, cwid - 1, ch - 1, 16, stroke=T["rule"])
    return cam


def mini(svg: Svg, d, box):
    """A design card's live part on its plate (MiniView)."""
    x0, y0, w, h = box
    tris = np.concatenate([m["tris"] for m in d["meshes"]])
    lo, hi = tris.reshape(-1, 3).min(0), tris.reshape(-1, 3).max(0)
    c = (lo + hi) / 2
    cam = Camera(az=-34, el=28.4, target=c, dist=400)
    plate = np.array([[c[0] - 90, c[1] - 90, 0], [c[0] + 90, c[1] + 90, 0], [c[0] - 90, c[1] + 90, 0], [c[0] + 90, c[1] - 90, 0]])
    cam.fit(plate, (x0 + 0.16 * w, y0 + 0.36 * h, 0.70 * w, 0.51 * h))
    fid = svg.id("mf")
    svg.defs.append('<radialGradient id="%sg" cx=".5" cy=".55" r=".55"><stop offset="0" stop-color="#fff" stop-opacity=".9"/>'
                    '<stop offset="1" stop-color="#fff" stop-opacity="0"/></radialGradient><mask id="%s"><rect x="%s" y="%s" width="%s" height="%s" fill="url(#%sg)"/></mask>'
                    % (fid, fid, f1(x0), f1(y0), f1(w), f1(h), fid))
    draw_plate(svg, cam, (180, 180), center=(c[0], c[1]), fade_id=fid, plate_fill="#30373b", grid_ink="#1d2225")
    fills, edges = draw_solid(cam, tris, svg.w, svg.h, mesh_edges(d))
    svg.add(fills + edges)


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


def fmt_min(m: float) -> str:
    m = int(round(m))
    return "%d h %d min" % (m // 60, m % 60) if m >= 60 else "%d min" % m


def stand_facts(d) -> dict:
    s = d["state"]
    sl = s["slice_simulated"]
    checks = [parse_check(c) for c in s["checks"]]
    v = d["view"]
    lo, hi = np.array(v["bbox"][0]), np.array(v["bbox"][1])
    size = hi - lo
    ev = {}
    for c in checks:
        ev[c["evidence"]] = ev.get(c["evidence"], 0) + 1
    mix_ = " · ".join("%d %s" % (n, e) for e, n in ev.items())
    return {"name": s["name"], "rev": "r%02d" % s["head"], "checks": checks, "mix": mix_,
            "time": fmt_min(sl["time_min"]), "grams": "%.1f g" % sl["filament_g"], "layers": str(sl["layers"]),
            "slicer": sl["slicer"], "presets": sl["presets"], "faces": v["faces"],
            "size": " × ".join("%.1f" % x for x in size), "volume": "%.1f cm³" % (v["volume_mm3"] / 1000),
            "dims": size, "printer": sl["presets"].split(" / ")[0],
            "zmax": "%.1f" % hi[2], "recipe": s["recipe"], "next": s.get("next_best_actions", []),
            "params": s["parameters"]}


def workspace_scene(svg: Svg, W, H, d, t0: float, end: float):
    """Workspace.qml with the conversation, the viewport and the Prove stage, filling in as the engine answers."""
    F = stand_facts(d)
    ok = [c for c in F["checks"] if c["status"] == "PASS"]
    svg.rect(0, 0, W, H, fill=T["plate"])
    # ── viewport: the bench and the part ──
    vx0, vx1 = 340, 1040
    bg = svg.id("vpg")
    svg.defs.append('<radialGradient id="%s" cx=".5" cy=".3" r=".8"><stop offset="0" stop-color="#22272a"/><stop offset="1" stop-color="#141719"/></radialGradient>' % bg)
    svg.rect(vx0, 44, vx1 - vx0, H - 44, fill="url(#%s)" % bg)
    tris = np.concatenate([m["tris"] for m in d["meshes"]])
    lo, hi = tris.reshape(-1, 3).min(0), tris.reshape(-1, 3).max(0)
    c = (lo + hi) / 2
    rad = max(np.linalg.norm(hi - lo) / 2, 12)
    cam = Camera(az=-34, el=28.4, target=c, dist=rad / math.sin(math.radians(13)) * 1.5)
    cam.fit(tris.reshape(-1, 3), (513, 322, 396, 414))
    clipv = svg.id("vc")
    svg.defs.append('<clipPath id="%s"><rect x="%s" y="44" width="%s" height="%s"/></clipPath>' % (clipv, vx0, vx1 - vx0, H - 44))
    svg.add('<g clip-path="url(#%s)">' % clipv)
    pf = svg.id("pf")
    svg.defs.append('<radialGradient id="%sg" cx=".52" cy=".62" r=".6"><stop offset="0" stop-color="#fff" stop-opacity="1"/>'
                    '<stop offset=".75" stop-color="#fff" stop-opacity=".6"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></radialGradient>'
                    '<mask id="%s"><rect x="%s" y="44" width="%s" height="%s" fill="url(#%sg)"/></mask>' % (pf, pf, vx0, vx1 - vx0, H - 44, pf))
    draw_plate(svg, cam, (180, 180), fade_id=pf, plate_fill="#2a3034", grid_ink="#1b2023")
    fills, edges = draw_solid(cam, tris, W, H, d["edges"])
    # the build grows up from the plate, feature by feature, in build order: a rising cut with the datum line on it
    xy, _ = cam.project(tris.reshape(-1, 3))
    top, bot = xy[:, 1].min() - 6, xy[:, 1].max() + 6
    bid = svg.id("build")
    T_ = svg.loop
    g0, g1 = t0 + 0.5, t0 + 2.3
    kt = [0, g0 / T_, g1 / T_, (end - 0.01) / T_, end / T_, 1]
    hv = [0, 0, bot - top, bot - top, 0, 0]
    yv = [bot, bot, top, top, bot, bot]
    svg.defs.append('<clipPath id="%s"><rect x="%s" y="%s" width="%s" height="0">'
                    '<animate attributeName="height" dur="%gs" repeatCount="indefinite" keyTimes="%s" values="%s" calcMode="spline" keySplines="%s"/>'
                    '<animate attributeName="y" dur="%gs" repeatCount="indefinite" keyTimes="%s" values="%s" calcMode="spline" keySplines="%s"/>'
                    '</rect></clipPath>'
                    % (bid, vx0, f1(bot), vx1 - vx0, T_, ";".join("%.4f" % k for k in kt), ";".join(f1(v) for v in hv),
                       ";".join(["0 0 1 1", ".3 .7 .2 1", "0 0 1 1", "0 0 1 1", "0 0 1 1"]),
                       T_, ";".join("%.4f" % k for k in kt), ";".join(f1(v) for v in yv),
                       ";".join(["0 0 1 1", ".3 .7 .2 1", "0 0 1 1", "0 0 1 1", "0 0 1 1"])))
    svg.add('<g clip-path="url(#%s)">%s%s</g>' % (bid, fills, edges))
    # the cut line, glowing while it rises
    scan = svg.anim([(0, {"transform": "translateY(%gpx)" % (bot - top), "opacity": "0"}), (g0, {"transform": "translateY(%gpx)" % (bot - top), "opacity": "0"}),
                     (g0 + 0.1, {"opacity": "1"}), (g1 - 0.1, {"transform": "translateY(0px)", "opacity": "1"}), (g1 + 0.3, {"transform": "translateY(0px)", "opacity": "0"})],
                    ease="cubic-bezier(.3,.7,.2,1)")
    sx0, sx1 = xy[:, 0].min() - 30, xy[:, 0].max() + 30
    lg = svg.id("sl")
    svg.defs.append('<linearGradient id="%s" x1="0" x2="1"><stop offset="0" stop-color="%s" stop-opacity="0"/><stop offset=".2" stop-color="%s"/>'
                    '<stop offset=".8" stop-color="%s"/><stop offset="1" stop-color="%s" stop-opacity="0"/></linearGradient>' % (lg, T["datum"], T["datum"], T["datum"], T["datum"]))
    svg.add('<g class="%s"><rect x="%s" y="%s" width="%s" height="1.5" fill="url(#%s)"/><rect x="%s" y="%s" width="%s" height="26" fill="url(#%s)" opacity=".07"/></g>'
            % (scan, f1(sx0), f1(top), f1(sx1 - sx0), lg, f1(sx0), f1(top), f1(sx1 - sx0), lg))
    # overall dimensions (Store.dims): three mint lines with their values, from the solid's box
    dims = svg.show(g1 + 0.1, end - 0.3)
    svg.g(dims)
    L, Hh, D = F["dims"]
    blo, bhi = np.array(d["view"]["bbox"][0]), np.array(d["view"]["bbox"][1])
    off = 9
    lines = [((blo[0] - off, blo[1], 0), (blo[0] - off, blo[1], bhi[2]), "%.1f" % bhi[2] if False else "%.1f" % (bhi[2] - blo[2])),
             ((blo[0] - off, blo[1], 0), (blo[0] - off, bhi[1], 0), "%.1f" % (bhi[1] - blo[1])),
             ((blo[0], blo[1] - off, 0), (bhi[0], blo[1] - off, 0), "%.1f" % (bhi[0] - blo[0]))]
    # Viewport.qml stands the height on the corner nearest the camera's left; the depth runs along it, the width across the front
    lines[0] = ((blo[0] - off, bhi[1] - 0, 0), (blo[0] - off, bhi[1], bhi[2]), "%.1f" % (bhi[2] - blo[2]))
    lines[1] = ((blo[0] - off, blo[1], 0), (blo[0] - off, bhi[1], 0), "%.1f" % (bhi[1] - blo[1]))
    lines[2] = ((blo[0], blo[1] - off, 0), (bhi[0], blo[1] - off, 0), "%.1f" % (bhi[0] - blo[0]))
    for a, b, label in lines:
        (p, q), _ = cam.project(np.array([a, b]))
        svg.line(p[0], p[1], q[0], q[1], alpha(T["datum"], 0.55), 1)
        mx, my = (p + q) / 2
        w = text_w(label, 12, 520, "mono") + 10
        svg.rect(mx - w / 2, my - 10, w, 20, 5, fill=alpha(T["plate"], 0.92), stroke=alpha(T["datum"], 0.45))
        svg.text(mx, my + 4.3, label, 12, 520, T["ink"], family="mono", anchor="middle")
    svg.end()
    svg.add("</g>")
    # rail
    svg.rect(352, 58, 40, 365, 9, fill=alpha(T["plate1"], 0.92), stroke=T["rule"])
    ys = [75, 106, 137, 168, 199, 230, 271, 302, 343, 374, 405]
    icons = ["mouse_pointer_2", "pencil_ruler", "map_pin", "scissors", "scan_line", "history", "layers", "camera", "maximize_2", "ruler", "box"]
    for yy, ic in zip(ys, icons):
        if ic == "mouse_pointer_2":
            svg.rect(356, yy - 14, 32, 28, 6, fill=T["washOn"])
        svg.icon(372, yy, ic, 15, T["datum"] if ic == "mouse_pointer_2" else T["ink2"])
    svg.rect(358, 250, 28, 1, fill=T["rule2"])
    svg.rect(358, 322, 28, 1, fill=T["rule2"])
    # view switch
    vs = ["Iso", "Front", "Side", "Top", "Under"]
    ws = [text_w(v, 12, 520) + 16 for v in vs]
    x = 1027 - sum(ws) - 4
    svg.rect(x, 58, sum(ws) + 4, 26, 6, fill=alpha(T["plate1"], 0.92), stroke=T["rule"])
    x += 2
    for i, (v, w) in enumerate(zip(vs, ws)):
        if i == 0:
            svg.rect(x, 60, w, 22, 5, fill=T["plate3"])
        svg.text(x + w / 2, 75.2, v, 12, 520, T["ink"] if i == 0 else T["ink2"], anchor="middle")
        x += w
    # size line
    sz = svg.show(g1 + 0.1, end - 0.3)
    svg.g(sz)
    x = svg.text(356, 851, "%s mm" % F["size"], 12, 420, T["ink2"], family="mono")
    svg.text(356 + x + 8, 851, "· %s ·" % F["volume"], 12, 420, T["ink2"], family="mono")
    x2 = text_w("· %s ·" % F["volume"], 12, 420, "mono")
    svg.text(356 + x + 16 + x2, 851, "plate 180 × 180", 12, 420, T["ink3"])
    svg.end()
    # pipeline strip: each step lights as the engine finishes it
    svg.rect(353, 866, 674, 48, 9, fill=alpha(T["plate1"], 0.92), stroke=T["rule"])
    steps = [("Parameters", F["rev"], t0 + 0.4), ("Solid", "%d faces" % F["faces"], g1), ("Exports", ".step .stl .obj .glb", g1 + 0.5),
             ("Checks", "%d pass" % len(ok), t0 + 3.2 + 0.16 * len(ok)), ("Slice", F["time"], t0 + 5.5), ("Release", "ready", t0 + 5.9)]
    xs = [369, 471, 549, 704, 787, 876]
    for (label, sub, tt), x in zip(steps, xs):
        svg.circle(x, 880, 3, T["ink4"])
        svg.circle(x, 880, 3, T["datum"] if label != "Release" else T["ink3"], cls=svg.show(tt, end - 0.2, 0.12))
        svg.text(x + 9, 884.3, label, 12, 620, T["ink"])
        svg.text(x - 1, 904, sub, 11, 420, T["ink2"], family="mono", cls=svg.show(tt, end - 0.2, 0.18))
    for x in xs[1:]:
        svg.rect(x - 16, 883, 6, 1, fill=T["ink4"])
    svg.text(952, 892, "AUTO", 10, 620, T["ink3"], ls=0.9)
    svg.rect(991, 881, 27, 16, 8, fill=T["datum"])
    svg.circle(1010, 889, 6, T["datumInk"])

    # ── top bar ──
    svg.rect(0, 0, W, 44, fill=T["plate1"])
    svg.rect(0, 43, W, 1, fill=T["rule"])
    traffic(svg, 20, 22)
    svg.icon(94, 22, "panel_left_close", 15, T["ink2"])
    logo(svg, 124, 22, ink=T["ink2"], ink2=T["ink3"])
    svg.text(228, 27, "/", 13, 420, T["ink4"])
    w = svg.text(242, 27, F["name"], 13, 620, T["ink"])
    w2 = svg.text(242 + w + 10, 27, F["rev"], 13, 420, T["ink2"], family="mono")
    tag(svg, 242 + w + 20 + w2, 13.5, "UNRELEASED", "x")
    x = W - 23
    svg.icon(x, 22, "settings", 15, T["ink2"])
    x -= 23 + 170
    svg.rect(x, 9, 170, 26, 6, fill=T["well"], stroke=T["rule2"])
    svg.icon(x + 15, 22, "search", 13, T["ink3"])
    svg.text(x + 29, 26.5, "Search", 13, 420, T["ink3"])
    svg.text(x + 158, 26.5, "⌘K", 11, 420, T["ink3"], anchor="end")
    pw = text_w(F["printer"], 12, 420)
    x -= 14 + pw
    svg.text(x, 26, F["printer"], 12, 420, T["ink2"])
    svg.icon(x - 13, 22, "printer", 13, T["ink3"])

    # ── the conversation ──
    svg.rect(0, 44, 340, H - 44, fill=T["plate1"])
    svg.rect(340, 44, 1, H - 44, fill=T["rule"])
    svg.circle(19, 62, 3, T["datum"])
    nm = elide(REQUEST, 250, 13, 620)
    w = svg.text(31, 66.6, nm, 13, 620, T["ink"])
    svg.icon(31 + w + 10, 62, "chevron_down", 12, T["ink3"])
    svg.icon(318, 62, "message_square_plus", 14, T["ink3"])
    svg.rect(0, 84, 340, 1, fill=T["rule"])
    # the request, as you sent it
    bw = 340 - 16 - 56
    lines_ = wrap(REQUEST, bw - 28, 13)
    bh = 20 + len(lines_) * 19
    u = svg.show(t0 + 0.05, end, rise=8)
    svg.g(u)
    svg.rect(340 - 16 - bw, 102, bw, bh, 14, fill=T["plate2"], stroke=T["rule"])
    for i, ln in enumerate(lines_):
        svg.text(340 - 16 - bw + 14, 102 + 24 + i * 19, ln, 13, 420, T["ink"])
    svg.end()
    y = 102 + bh + 22
    # the agent's tool calls (TalkSteps.qml), then what it says
    rows = [("cuboid", "Started a design from the %s recipe" % F["recipe"], "create_project", t0 + 0.6),
            ("eye", "Looked at the iso view", "render", g1 + 0.2),
            ("play", "Ran the pipeline", "run_pipeline", g1 + 0.6)]
    hdr = svg.show(t0 + 0.4, end, rise=4)
    svg.g(hdr)
    svg.icon(23, y, "chevron_right", 13, T["ink3"])
    svg.text(37, y + 4, "4 steps", 11, 550, T["ink2"])
    svg.text(37 + text_w("4 steps", 11, 550) + 8, y + 4, "1 folded", 11, 420, T["ink4"])
    svg.end()
    y += 22
    for ic, text, tool, tt in rows:
        cl = svg.show(tt, end, rise=4)
        svg.g(cl)
        svg.rect(24, y - 11, 1, 22, fill=T["rule2"])
        svg.icon(40, y, ic, 12, T["ink2"])
        svg.text(54, y + 4.2, text, 12, 420, T["ink2"])
        svg.end()
        y += 24
    y += 14
    say = ("All %d checks pass on %s. The slice is %s and %s of filament, %s layers. Your phone's thickness is assumed "
           "at %s: measure it with calipers before you print." % (len(ok), F["rev"], F["time"], F["grams"], F["layers"],
                                                                 F["params"]["device_thickness"].split(" (")[0]))
    reply = svg.show(t0 + 6.1, end, rise=6)
    svg.g(reply)
    for i, ln in enumerate(wrap(say, 300, 13)):
        svg.text(16, y + i * 20, ln, 13, 420, T["ink"])
    svg.end()
    # composer at the bottom of the column
    svg.rect(13, 806, 315, 93, 14, fill=T["plate2"], stroke=T["rule2"])
    svg.text(29, 828, "Ask about %s, or describe a" % F["name"], 13, 420, T["ink3"])
    svg.text(29, 846, "change…", 13, 420, T["ink3"])
    svg.icon(29, 879, "paperclip", 13, T["ink3"])
    w = svg.text(48, 883.5, "Claude Code · Default", 13, 420, T["ink"])
    svg.icon(48 + w + 10, 879, "chevron_down", 11, T["ink3"])
    svg.circle(305, 880, 13, T["plate3"])
    svg.icon(305, 880, "arrow_up", 12, T["ink3"])
    svg.text(16, 917, "Enter sends · Shift+Enter for a new line · drop files to attach", 11, 420, T["ink3"])

    # ── the inspector: stages, then Prove ──
    px = 1040
    svg.rect(px, 44, 400, H - 44, fill=T["plate1"])
    svg.rect(px, 44, 1, H - 44, fill=T["rule"])
    tabs = [("01", "Brief", "0/6 measured"), ("02", "Shape", "%d features" % 3), ("03", "Fit", "100% modelled"),
            ("04", "Prove", "All pass"), ("05", "Release", "Ready")]
    tabs[1] = ("02", "Shape", "4 features")
    cxs = [1087, 1162, 1241, 1318, 1392]
    svg.rect(1287, 52, 64, 47, 8, fill=T["washOn"])
    for (n, t, s), cx_ in zip(tabs, cxs):
        on = t == "Prove"
        wn = text_w(n, 9, 420, "mono")
        wt = text_w(t, 13, 620)
        x0 = cx_ - (wn + 4 + wt) / 2
        svg.text(x0, 70, n, 9, 420, T["ink4"], family="mono")
        svg.text(x0 + wn + 4, 70, t, 13, 620, T["ink"] if on else T["ink2"])
        col = T["pass"] if t in ("Fit", "Prove") else T["ink3"]
        svg.text(cx_, 88, s, 10, 420, col, anchor="middle")
    svg.rect(px, 108, 400, 1, fill=T["rule"])
    head = svg.show(t0 + 3.2 + 0.16 * len(ok), end)
    svg.circle(1063, 126, 3, T["pass"], cls=head)
    svg.text(1076, 130.5, "All %d checks pass for %s." % (len(ok), F["rev"]), 13, 420, T["ink2"], cls=head)
    run = svg.anim([(0, {"opacity": "0"}), (t0 + 0.4, {"opacity": "0"}), (t0 + 0.6, {"opacity": "1"}),
                    (t0 + 3.2 + 0.16 * len(ok), {"opacity": "1"}), (t0 + 3.4 + 0.16 * len(ok), {"opacity": "0"})])
    svg.circle(1063, 126, 3, T["datum"], cls=run)
    svg.text(1076, 130.5, "Building %s, checking it, slicing it…" % F["rev"], 13, 420, T["ink3"], cls=run)
    svg.rect(px, 147, 400, 1, fill=T["rule"])
    # the score
    ck0 = t0 + 3.0
    for j, (lab, colr, n) in enumerate((("pass", T["pass"], len(ok)), ("to review", T["amber"], 0), ("failed", T["signal"], 0))):
        x = 1060 + j * 120
        if j == 0:
            for k in range(n + 1):
                a = ck0 + 0.16 * k
                b = ck0 + 0.16 * (k + 1) if k < n else end - 0.2
                cls = svg.anim([(0, {"opacity": "1" if k == 0 else "0"}), (a - 0.001, {"opacity": "1" if k == 0 else "0"}), (a, {"opacity": "1"}),
                                (b, {"opacity": "1"}), (b + 0.001, {"opacity": "1" if (k == 0 and b >= end - 0.2) else "0"})], ease="steps(1)")
                svg.text(x, 198, str(k), 30, 600, colr if k else T["ink4"], family="mono", ls=-0.6, cls=cls)
        else:
            svg.text(x, 198, "0", 30, 600, T["ink4"], family="mono", ls=-0.6)
        svg.text(x, 222, lab, 10, 620, T["ink2"] if (j == 0) else T["ink4"], ls=0.9, upper=True)
    svg.rect(1060, 241, 356, 4, 2, fill=T["rule"])
    bar = svg.anim([(0, {"transform": "scaleX(0)"}), (ck0, {"transform": "scaleX(0)"}), (ck0 + 0.16 * len(ok), {"transform": "scaleX(1)"}),
                    (end - 0.2, {"transform": "scaleX(1)"}), (end, {"transform": "scaleX(0)"})], ease="linear", origin="left")
    svg.rect(1060, 241, 356, 4, 2, fill=T["pass"], cls=bar)
    for i, ln in enumerate(wrap("Checks for %s · %s. Each says how it is known." % (F["rev"], F["mix"]), 356, 11)):
        svg.text(1060, 268 + i * 17, ln, 11, 420, T["ink3"])
    svg.rect(1060, 300, 360, 1, fill=T["rule"])
    # passed, one line each with its evidence class
    svg.icon(1066, 318, "chevron_down", 11, T["ink3"])
    svg.text(1080, 321.6, "PASSED", 10, 620, T["ink3"], ls=0.9)
    svg.text(1420, 321.6, "%d · %s" % (len(ok), F["mix"]), 11, 420, T["ink3"], anchor="end")
    y = 334
    for i, c in enumerate(ok):
        cl = svg.show(ck0 + 0.16 * (i + 1) - 0.1, end - 0.2, 0.16, rise=4)
        svg.g(cl)
        tag(svg, 1060, y + 7, c["evidence"], c["evidence"])
        lab = c["label"]
        val = c["value"]
        val = elide(val, 128, 12, 420, "mono")
        vw = text_w(val, 12, 420, "mono")
        lab = elide(lab, 268 - vw, 13, 420)
        svg.text(1144, y + 20, lab, 13, 420, T["ink"])
        svg.text(1420, y + 19.5, val, 12, 420, T["ink2"], family="mono", anchor="end")
        svg.end()
        y += 30
    y += 8
    svg.rect(1060, y, 360, 1, fill=T["rule"])
    # the slice
    sl = svg.show(t0 + 5.5, end - 0.2, rise=6)
    svg.g(sl)
    y += 30
    svg.text(1060, y, "SLICE OF %s" % F["rev"].upper(), 10, 620, T["ink3"], ls=0.9)
    tag(svg, 1420 - text_w("SIMULATED", 10, 620, ls=0.6) - 12, y - 12, "simulated", "simulated")
    y += 34
    for j, (big, small) in enumerate(((F["time"], "estimated print time"), (F["grams"], "of filament"), (F["layers"], "layers to %s mm" % F["zmax"]))):
        x = 1060 + j * 120
        svg.text(x, y, big, 18, 600, T["ink"], family="mono", ls=-0.3)
        svg.text(x, y + 22, small, 11, 420, T["ink3"])
    y += 46
    w = btn(svg, 1060, y, "Watch it print", "play", h=28, quiet=False)
    btn(svg, 1060 + w + 8, y, "Inspect layers", "layers", h=28, quiet=False)
    y += 52
    for i, ln in enumerate(wrap("A slice shows the toolpaths %s would send with these presets. It is not a print: adhesion, "
                                "warping and fit are only known after printing." % "Bambu Studio", 356, 11)):
        svg.text(1060, y + i * 17, ln, 11, 420, T["ink3"])
    svg.end()


def hero(data, light: bool):
    W, H, M = 1440, 928, 28
    loop = 17.0
    svg = Svg(W + 2 * M, H + 2 * M + 8, loop, "Form Studio")
    cid = window(svg, M, M, W, H, light)
    svg.add('<g clip-path="url(#%s)"><g transform="translate(%d %d)">' % (cid, M, M))
    t_type0, t_type1, t_send = 0.9, 4.6, 5.2
    home_g = svg.anim([(0, {"opacity": "1"}), (t_send + 0.25, {"opacity": "1"}), (t_send + 0.5, {"opacity": "0"}),
                       (loop - 0.55, {"opacity": "0"}), (loop - 0.05, {"opacity": "1"})], ease="cubic-bezier(.23,1,.32,1)")
    work_g = svg.anim([(0, {"opacity": "0"}), (t_send + 0.2, {"opacity": "0"}), (t_send + 0.5, {"opacity": "1"}),
                       (loop - 0.55, {"opacity": "1"}), (loop - 0.05, {"opacity": "0"})])
    svg.add('<g class="%s">' % work_g)
    workspace_scene(svg, W, H, data["desk-phone-stand"], t_send + 0.3, loop - 0.4)
    svg.add('</g><g class="%s">' % home_g)
    home_scene(svg, W, H, data, (t_type0, t_type1, t_send))
    svg.add("</g></g></g>")
    window_edge(svg, M, M, W, H, light)
    F = stand_facts(data["desk-phone-stand"])
    desc = ("Form Studio, drawn from the app: on Home a request is typed into the composer and sent; the workspace opens, "
            "the %s is built by the CAD kernel (%s mm), %d checks pass, and the slicer estimates %s and %s."
            % (F["name"].lower(), F["size"], len(F["checks"]), F["time"], F["grams"]))
    return svg.render(desc), desc


# ═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# Cards: one piece of the app each, at its real size
# ═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
CW, CH, CM = 680, 420, 20          # card content, margin around the window


def card(loop: float, title: str, light: bool):
    svg = Svg(CW + 2 * CM, CH + 2 * CM + 6, loop, title)
    cid = window(svg, CM, CM, CW, CH, light, r=12)
    svg.add('<g clip-path="url(#%s)"><g transform="translate(%d %d)">' % (cid, CM, CM))
    return svg


def card_end(svg: Svg, light: bool):
    svg.add("</g></g>")
    window_edge(svg, CM, CM, CW, CH, light, r=12)


def viewport_bg(svg: Svg, x, y, w, h):
    bg = svg.id("vpg")
    svg.defs.append('<radialGradient id="%s" cx=".5" cy=".3" r=".85"><stop offset="0" stop-color="#23282b"/><stop offset="1" stop-color="#131618"/></radialGradient>' % bg)
    svg.rect(x, y, w, h, fill="url(#%s)" % bg)


def plate_mask(svg: Svg, x, y, w, h, cx=".5", cy=".6") -> str:
    pf = svg.id("pf")
    svg.defs.append('<radialGradient id="%sg" cx="%s" cy="%s" r=".62"><stop offset="0" stop-color="#fff"/>'
                    '<stop offset=".72" stop-color="#fff" stop-opacity=".55"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></radialGradient>'
                    '<mask id="%s"><rect x="%s" y="%s" width="%s" height="%s" fill="url(#%sg)"/></mask>' % (pf, cx, cy, pf, x, y, w, h, pf))
    return pf


def rot(axis, ang):
    a = np.asarray(axis, float)
    a /= np.linalg.norm(a)
    c, s = math.cos(ang), math.sin(ang)
    x, y, z = a
    return np.array([[c + x * x * (1 - c), x * y * (1 - c) - z * s, x * z * (1 - c) + y * s],
                     [y * x * (1 - c) + z * s, c + y * y * (1 - c), y * z * (1 - c) - x * s],
                     [z * x * (1 - c) - y * s, z * y * (1 - c) + x * s, c + z * z * (1 - c)]])


def hinge_card(data, light: bool):
    """The hinged box assembled, its lid swept through the joint's range, with the joint slider and the sweep's check."""
    d = data["hinged-box"]
    asm = d["asm"]
    joint = asm["joints"][0]
    lid = next(p for p in asm["parts"] if p["id"] == joint["part"])
    M = np.array(lid["placement"]["m"])
    lo_deg, hi_deg = joint["range"]
    check = next(parse_check(c) for c in d["state"]["checks"] if joint["label"] in c and "moves" in c)
    body_t = np.concatenate([m["tris"] for m in d["meshes"] if m["part"] != lid["id"]])
    lid_t = np.concatenate([m["tris"] for m in d["meshes"] if m["part"] == lid["id"]])
    lid_a = lid_t @ M[:, :3].T + M[:, 3]
    be = d["part_edges"].get("body")
    le = d["part_edges"].get(lid["id"])
    le_a = le @ M[:, :3].T + M[:, 3] if le is not None else None
    o = np.array(joint["origin"])
    N = 14
    angles = [lo_deg + (hi_deg - lo_deg) * (1 - math.cos(math.pi * i / (N - 1))) / 2 for i in range(N)]
    loop = 7.6
    svg = card(loop, "Lid hinge", light)
    viewport_bg(svg, 0, 0, CW, CH)
    # frame the open and closed box together, the way the viewport frames an assembly
    allp = [body_t.reshape(-1, 3)]
    for a in (angles[0], angles[-1]):
        R = rot(joint["axis"], math.radians(a))
        allp.append((lid_a.reshape(-1, 3) - o) @ R.T + o)
    allp = np.concatenate(allp)
    lo, hi = allp.min(0), allp.max(0)
    cam = Camera(az=-34, el=24, target=(lo + hi) / 2, dist=420)
    cam.fit(allp, (170, 70, 360, 300))
    c = (lo + hi) / 2
    draw_plate(svg, cam, (180, 180), center=(0, 0), fade_id=plate_mask(svg, 0, 0, CW, CH), plate_fill="#2a3034", grid_ink="#1b2023")
    # frames: closed, opening, open, closing, closed
    hold0, move, hold1 = 0.7, 2.4, 0.9
    step = move / (N - 1)
    seq = [(0, 0.0, hold0)]
    t = hold0
    for i in range(1, N):
        seq.append((i, t, t + step))
        t += step
    seq[-1] = (N - 1, seq[-1][1], t + hold1)
    t += hold1
    for i in range(N - 2, -1, -1):
        seq.append((i, t, t + step))
        t += step
    seq[-1] = (0, seq[-1][1], loop)
    classes = []
    for i in range(N):
        iv = [(s, e) for j, s, e in seq if j == i]
        fr = [(0, {"opacity": "1" if iv[0][0] == 0 else "0"})]
        for s, e in iv:
            if s > 0:
                fr += [(s - 1e-3, {"opacity": "0"}), (s, {"opacity": "1"})]
            if e < loop:
                fr += [(e, {"opacity": "1"}), (e + 1e-3, {"opacity": "0"})]
            else:
                fr += [(loop, {"opacity": "1"})]
        classes.append(svg.anim(fr, ease="steps(1)"))
    for i, a in enumerate(angles):
        R = rot(joint["axis"], math.radians(a))
        lt = (lid_a - o) @ R.T + o
        tris = np.concatenate([body_t, lt])
        ed = None
        if be is not None and le_a is not None:
            ed = np.concatenate([be, (le_a - o) @ R.T + o])
        fills, edges = draw_solid(cam, tris, svg.w, svg.h, ed)
        svg.add('<g class="%s">%s%s</g>' % (classes[i], fills, edges))
    # the HUD: arrangement and the joint's slider (HudSlider.qml)
    seg(svg, 14, 14, ["Assembled", "Exploded", "Print layout"], on=0, h=26, size=12)
    sx = 14 + sum(text_w(t, 12, 520) + 20 for t in ["Assembled", "Exploded", "Print layout"]) + 6 + 8
    lw = text_w(joint["label"], 12)
    sw = lw + 118 + 30 + 30
    svg.rect(sx, 14, sw, 26, 6, fill=alpha(T["plate1"], 0.9), stroke=T["rule"])
    svg.text(sx + 10, 31.3, joint["label"], 12, 420, T["ink2"])
    tx0 = sx + 10 + lw + 10
    svg.rect(tx0, 26, 110, 2, 1, fill=T["rule2"])
    for i, a in enumerate(angles):
        f = (a - lo_deg) / (hi_deg - lo_deg)
        g = svg.id("hs")
        svg.add('<g class="%s">' % classes[i])
        svg.rect(tx0, 26, 110 * f, 2, 1, fill=T["datum"])
        svg.circle(tx0 + 110 * f, 27, 6, T["ink"])
        svg.text(sx + sw - 10, 31, "%d°" % round(a), 11, 420, T["ink"], family="mono", anchor="end")
        svg.add("</g>")
    # views
    vs = ["Iso", "Front", "Side", "Top"]
    ws_ = [text_w(v, 12, 520) + 16 for v in vs]
    x = CW - 14 - sum(ws_) - 4
    svg.rect(x, 14, sum(ws_) + 4, 26, 6, fill=alpha(T["plate1"], 0.92), stroke=T["rule"])
    x += 2
    for k, (v, w) in enumerate(zip(vs, ws_)):
        if k == 0:
            svg.rect(x, 16, w, 22, 5, fill=T["plate3"])
        svg.text(x + w / 2, 31.2, v, 12, 520, T["ink"] if k == 0 else T["ink2"], anchor="middle")
        x += w
    # the check the sweep produced
    y = CH - 48
    lab = check["label"]
    val = check["value"]
    w = text_w(lab, 13) + text_w(val, 12, 420, "mono") + 92 + 40
    svg.rect(14, y, w, 34, 9, fill=alpha(T["plate1"], 0.92), stroke=T["rule"])
    tag(svg, 24, y + 8.5, check["evidence"], check["evidence"])
    svg.text(108, y + 21.5, lab, 13, 420, T["ink"])
    svg.text(14 + w - 12, y + 21.3, val, 12, 420, T["ink2"], family="mono", anchor="end")
    svg.circle(CW - 30, y + 17, 3, T["pass"])
    svg.text(CW - 40, y + 21.3, "%s · %s" % (d["state"]["name"], "r%02d" % d["state"]["head"]), 12, 420, T["ink3"], anchor="end")
    card_end(svg, light)
    desc = ("The %s's lid swung through its %s range, %d to %d degrees, drawn from the CAD kernel's meshes; the sweep check: %s, %s."
            % (d["state"]["name"].lower(), joint["label"].lower(), lo_deg, hi_deg, lab.lower(), val))
    return svg.render(desc), desc


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


def fmt_clock(s: float) -> str:
    s = int(round(s))
    return "%d:%02d:%02d" % (s // 3600, s % 3600 // 60, s % 60)


def print_card(data, light: bool):
    """The print played back from the slicer's G-code: layers stack up, the current one in its line types."""
    d = data["desk-phone-stand"]
    tp = d["toolpath"]
    F = stand_facts(d)
    loop = 9.0
    svg = card(loop, "Print playback", light)
    viewport_bg(svg, 0, 0, CW, CH)
    L = tp.layers
    (bx0, by0, _), (bx1, by1, zt) = tp.bbox
    cx, cy = (bx0 + bx1) / 2, (by0 + by1) / 2
    # plate frame: the G-code's coordinates are the bed's; centre the part like the viewport does
    pts = np.array([[bx0, by0, 0], [bx1, by1, zt], [bx0, by1, zt], [bx1, by0, 0], [bx0, by0, zt], [bx1, by1, 0]], float)
    pts[:, 0] -= cx
    pts[:, 1] -= cy
    cam = Camera(az=-34, el=28.4, target=(0, 0, zt / 2), dist=420)
    cam.fit(pts, (200, 62, 280, 238))
    draw_plate(svg, cam, (180, 180), fade_id=plate_mask(svg, 0, 0, CW, CH, cy=".5"), plate_fill="#2a3034", grid_ink="#1b2023")
    K = 36
    t_build0, t_build1 = 0.4, 6.8
    groups = np.array_split(np.arange(0, L, 2), K)
    ow = tp.types.index("Outer wall")
    px_per_mm = cam.s * cam.k / 420
    sw = max(0.6, tp.width * px_per_mm * 1.6)
    shade_side = mix(T["clay"], "#000000", 0.18)
    for gi, ls in enumerate(groups):
        t_in = t_build0 + (t_build1 - t_build0) * gi / K
        cls = svg.anim([(0, {"opacity": "0"}), (t_in, {"opacity": "0"}), (t_in + 0.001, {"opacity": "1"}),
                        (loop - 0.6, {"opacity": "1"}), (loop - 0.2, {"opacity": "0"})], ease="steps(1)")
        parts = []
        for l in ls:
            s0, s1 = tp.start[l], tp.start[l + 1]
            sg = tp.seg[s0:s1][tp.seg_type[s0:s1] == ow]
            if not len(sg):
                continue
            z = float(tp.z[l])
            dd = []
            for pl in chain(sg):
                P = np.array([[x - cx, y - cy, z] for x, y in pl])
                xy, _ = cam.project(P)
                xy = rdp(xy, 0.25)
                if len(xy) < 2:
                    continue
                dd.append("M" + "L".join("%s %s" % (f1(a), f1(b)) for a, b in xy) + ("Z" if np.allclose(pl[0], pl[-1], atol=1e-2) else ""))
            if dd:
                parts.append('<path d="%s" fill="#3b4246" fill-rule="evenodd" stroke="%s" stroke-width="%s" stroke-linejoin="round"/>'
                             % ("".join(dd), shade_side, f1(sw) if sw >= 1 else "%.2f" % sw))
        svg.add('<g class="%s">%s</g>' % (cls, "".join(parts)))
        # the layer being printed, in its line types, while it is the newest
        l = int(ls[-1])
        s0, s1 = tp.start[l], tp.start[l + 1]
        by_type = {}
        for (x0, y0, x1, y1), ty in zip(tp.seg[s0:s1], tp.seg_type[s0:s1]):
            by_type.setdefault(int(ty), []).append((x0, y0, x1, y1))
        z = float(tp.z[l])
        cur = []
        for ty, sgs in by_type.items():
            dd = []
            for pl in chain(np.array(sgs)):
                P = np.array([[x - cx, y - cy, z] for x, y in pl])
                xy, _ = cam.project(P)
                xy = rdp(xy, 0.2)
                dd.append("M" + "L".join("%s %s" % (f1(a), f1(b)) for a, b in xy))
            cur.append('<path d="%s" stroke="%s" stroke-width="1" stroke-linecap="round" stroke-linejoin="round"/>'
                       % ("".join(dd), TYPE_INK.get(tp.types[ty], T["ink2"])))
        t_out = t_build0 + (t_build1 - t_build0) * (gi + 1) / K if gi < K - 1 else loop - 0.6
        ccls = svg.anim([(0, {"opacity": "0"}), (t_in, {"opacity": "0"}), (t_in + 0.001, {"opacity": "1"}),
                         (t_out, {"opacity": "1"}), (t_out + 0.001, {"opacity": "0"})], ease="steps(1)")
        svg.add('<g class="%s">%s</g>' % (ccls, "".join(cur)))
    # header: back to the design and the SIMULATED tag, the sentence the app shows
    btn(svg, 14, 14, "Back to the design", "arrow_left", h=28, quiet=False)
    tag(svg, 14 + text_w("Back to the design", 13, 520) + 22 + 14 + 22 + 8, 19.5, "simulated", "simulated")
    svg.text(16, 58, "Simulated from the slicer's G-code. Not a print.", 11, 420, T["ink3"])
    # line types, as the legend lists them
    lx, ly = CW - 196, 14
    shown = [t for t in tp.types if t in TYPE_INK]
    lengths = tp.type_lengths() if hasattr(tp, "type_lengths") else {}
    svg.rect(lx, ly, 182, 30 + 17 * len(shown), 9, fill=alpha(T["plate1"], 0.92), stroke=T["rule"])
    svg.text(lx + 12, ly + 19, "LINE TYPES", 10, 620, T["ink3"], ls=0.9)
    svg.text(lx + 170, ly + 19, "m of path", 10, 420, T["ink4"], anchor="end")
    for k, t in enumerate(shown):
        yy = ly + 36 + k * 17
        svg.rect(lx + 12, yy - 8, 8, 8, 2, fill=TYPE_INK[t])
        svg.text(lx + 26, yy, t, 11, 420, T["ink2"])
        ln = lengths.get(t)
        if isinstance(ln, (int, float)):
            svg.text(lx + 170, yy, "%.1f" % (ln / 1000), 10, 420, T["ink3"], family="mono", anchor="end")
    # the transport bar: layer, height and the slicer's clock, then the time of every layer
    bx, byy, bw, bh = 14, CH - 104, CW - 28, 90
    svg.rect(bx, byy, bw, bh, 12, fill=alpha(T["plate1"], 0.94), stroke=T["rule"])
    svg.rect(bx + 10, byy + 10, 64, 26, 6, fill=T["datum"])
    svg.icon(bx + 24, byy + 23, "pause", 12, T["datumInk"])
    svg.text(bx + 34, byy + 27.3, "Pause", 12, 620, T["datumInk"])
    for gi, ls in enumerate(groups):
        l = int(ls[-1])
        t_in = t_build0 + (t_build1 - t_build0) * gi / K
        t_out = t_build0 + (t_build1 - t_build0) * (gi + 1) / K if gi < K - 1 else loop - 0.2
        c_ = svg.anim([(0, {"opacity": "1" if gi == 0 else "0"}), (t_in, {"opacity": "1" if gi == 0 else "0"}), (t_in + 0.001, {"opacity": "1"}),
                       (t_out, {"opacity": "1"}), (t_out + 0.001, {"opacity": "0"})], ease="steps(1)")
        svg.g(c_)
        svg.text(bx + 88, byy + 27.3, "Layer %d / %d  ·  z %.2f mm" % (l + 1, L, tp.z[l]), 12, 420, T["ink"], family="mono")
        el = float(tp.t0[l + 1])
        svg.text(bx + bw - 120, byy + 27.3, "%s elapsed  ·  %s left" % (fmt_clock(el), fmt_clock(tp.total_time_s - el)), 11, 420, T["ink3"], family="mono", anchor="end")
        svg.end()
    tag(svg, bx + bw - 110, byy + 14.5, "slicer estimate", "simulated")
    # time per layer, as the app charts it (real per-layer seconds from the slicer's markers)
    cx0, cy0, cw_, ch_ = bx + 12, byy + 46, bw - 24, 34
    tmax = float(np.percentile(tp.time, 98))
    bars = []
    step = cw_ / L
    for l in range(L):
        h = min(1.0, tp.time[l] / tmax) * ch_
        bars.append("M%s %sV%s" % (f1(cx0 + l * step + step / 2), f1(cy0 + ch_), f1(cy0 + ch_ - max(1, h))))
    svg.add('<path d="%s" stroke="%s" stroke-width="%s"/>' % ("".join(bars), T["ink4"], "%.2f" % max(0.6, step * 0.7)))
    clip = svg.id("tc")
    svg.defs.append('<clipPath id="%s"><rect x="%s" y="%s" width="%s" height="%s">'
                    '<animate attributeName="width" dur="%gs" repeatCount="indefinite" keyTimes="0;%.4f;%.4f;%.4f;1" values="0;0;%s;%s;%s"/></rect></clipPath>'
                    % (clip, f1(cx0), f1(cy0), f1(cw_), ch_, loop, t_build0 / loop, t_build1 / loop, (loop - 0.2) / loop, f1(cw_), f1(cw_), f1(cw_)))
    svg.add('<path d="%s" stroke="%s" stroke-width="%s" clip-path="url(#%s)"/>' % ("".join(bars), T["ink2"], "%.2f" % max(0.6, step * 0.7), clip))
    head = svg.anim([(0, {"transform": "translateX(0px)"}), (t_build0, {"transform": "translateX(0px)"}),
                     (t_build1, {"transform": "translateX(%spx)" % f1(cw_)}), (loop - 0.2, {"transform": "translateX(%spx)" % f1(cw_)}),
                     (loop, {"transform": "translateX(0px)"})], ease="linear")
    svg.rect(cx0 - 0.5, cy0 - 3, 1.5, ch_ + 4, fill=T["datum"], cls=head)
    card_end(svg, light)
    desc = ("The %s's print played back from %s's G-code: %d layers, %s, built up layer by layer with the line types of the "
            "current layer; a simulation, not a print." % (F["name"].lower(), "Bambu Studio", L, F["time"]))
    return svg.render(desc), desc


def prove_card(data, light: bool):
    """Prove: the score and every passed check with how it is known, ticking in as the checks finish."""
    d = data["desk-phone-stand"]
    F = stand_facts(d)
    ok = [c for c in F["checks"] if c["status"] == "PASS"]
    loop = 8.0
    svg = card(loop, "Prove", light)
    # the part, left
    viewport_bg(svg, 0, 0, 280, CH)
    tris = np.concatenate([m["tris"] for m in d["meshes"]])
    lo, hi = tris.reshape(-1, 3).min(0), tris.reshape(-1, 3).max(0)
    cam = Camera(az=-34, el=28.4, target=(lo + hi) / 2, dist=420)
    cam.fit(tris.reshape(-1, 3), (40, 92, 200, 220))
    clip = svg.id("pc")
    svg.defs.append('<clipPath id="%s"><rect width="280" height="%s"/></clipPath>' % (clip, CH))
    svg.add('<g clip-path="url(#%s)">' % clip)
    draw_plate(svg, cam, (180, 180), fade_id=plate_mask(svg, 0, 0, 280, CH), plate_fill="#2a3034", grid_ink="#1b2023")
    fills, edges = draw_solid(cam, tris, svg.w, svg.h, d["edges"])
    svg.add(fills + edges + "</g>")
    svg.text(16, CH - 18, "%s mm" % F["size"], 11, 420, T["ink2"], family="mono")
    svg.text(16, 30, F["name"], 13, 620, T["ink"])
    svg.text(16 + text_w(F["name"], 13, 620) + 8, 30, F["rev"], 12, 420, T["ink2"], family="mono")
    # the panel
    px = 280
    svg.rect(px, 0, CW - px, CH, fill=T["plate1"])
    svg.rect(px, 0, 1, CH, fill=T["rule"])
    x0 = px + 20
    right = CW - 20
    ck0, dt = 0.5, 0.22
    done = ck0 + dt * len(ok)
    for j, (lab, colr, n) in enumerate((("pass", T["pass"], len(ok)), ("to review", T["amber"], 0), ("failed", T["signal"], 0))):
        x = x0 + j * 110
        if j == 0:
            for k in range(n + 1):
                a = ck0 + dt * k if k else 0.0
                b = ck0 + dt * (k + 1) if k < n else loop - 0.3
                fr = [(0, {"opacity": "1" if k == 0 else "0"})]
                if k:
                    fr += [(a - 1e-3, {"opacity": "0"}), (a, {"opacity": "1"})]
                fr += [(b, {"opacity": "1"}), (b + 1e-3, {"opacity": "0"})]
                if k == 0:
                    fr += [(loop - 0.3, {"opacity": "0"}), (loop - 0.3 + 1e-3, {"opacity": "1"})]
                cls = svg.anim(fr, ease="steps(1)")
                svg.text(x, 50, str(k), 30, 600, colr if k else T["ink4"], family="mono", ls=-0.6, cls=cls)
        else:
            svg.text(x, 50, "0", 30, 600, T["ink4"], family="mono", ls=-0.6)
        svg.text(x, 72, lab, 10, 620, T["ink2"] if j == 0 else T["ink4"], ls=0.9, upper=True)
    svg.rect(x0, 86, right - x0, 4, 2, fill=T["rule"])
    bar = svg.anim([(0, {"transform": "scaleX(0)"}), (ck0, {"transform": "scaleX(0)"}), (done, {"transform": "scaleX(1)"}),
                    (loop - 0.3, {"transform": "scaleX(1)"}), (loop, {"transform": "scaleX(0)"})], ease="linear", origin="left")
    svg.rect(x0, 86, right - x0, 4, 2, fill=T["pass"], cls=bar)
    svg.text(x0, 111, "Checks for %s · %s." % (F["rev"], F["mix"]), 11, 420, T["ink3"])
    y = 124
    for i, c in enumerate(ok):
        cl = svg.show(ck0 + dt * (i + 1) - 0.12, loop - 0.3, 0.14, rise=4)
        svg.g(cl)
        tag(svg, x0, y + 7, c["evidence"], c["evidence"])
        val = elide(c["value"], 128, 12, 420, "mono")
        vw = text_w(val, 12, 420, "mono")
        svg.text(x0 + 84, y + 20, elide(c["label"], right - x0 - 84 - vw - 12, 13), 13, 420, T["ink"])
        svg.text(right, y + 19.5, val, 12, 420, T["ink2"], family="mono", anchor="end")
        svg.end()
        y += 26
    card_end(svg, light)
    desc = "Prove for the %s %s: %s; %s." % (F["name"].lower(), F["rev"], ", ".join("%s %s" % (c["label"].lower(), c["value"]) for c in ok), F["mix"])
    return svg.render(desc), desc


def header(data, light: bool):
    """The wordmark on the bench: the mark, the name, and a datum line crossing a build-plate grid."""
    W, H = 1200, 300
    svg = Svg(W, H, 9.0, "Form Studio")
    ink = "#0e1113" if light else T["ink"]
    ink2 = "#5b6562" if light else T["ink2"]
    part = "#0e1113" if light else T["clay"]
    datum = "#2f8a6c" if light else T["datum"]
    # the bench grid in perspective, fading out
    cam = Camera(az=0, el=24, target=(0, 0, 0), dist=300)
    pts = np.array([[-200, -60, 0], [200, -60, 0], [200, 200, 0], [-200, 200, 0]], float)
    cam.fit(pts, (-200, 120, W + 400, 360))
    m = svg.id("hm")
    svg.defs.append('<radialGradient id="%sg" cx=".5" cy=".55" r=".55"><stop offset="0" stop-color="#fff" stop-opacity=".9"/>'
                    '<stop offset="1" stop-color="#fff" stop-opacity="0"/></radialGradient><mask id="%s"><rect width="%d" height="%d" fill="url(#%sg)"/></mask>'
                    % (m, m, W, H, m))
    lines = []
    for gx in np.arange(-200, 201, 20):
        a, _ = cam.project(np.array([[gx, -60, 0], [gx, 200, 0]]))
        lines.append("M%s %sL%s %s" % (f1(a[0][0]), f1(a[0][1]), f1(a[1][0]), f1(a[1][1])))
    for gy in np.arange(-60, 201, 20):
        a, _ = cam.project(np.array([[-200, gy, 0], [200, gy, 0]]))
        lines.append("M%s %sL%s %s" % (f1(a[0][0]), f1(a[0][1]), f1(a[1][0]), f1(a[1][1])))
    gink = "rgba(14,17,19,.10)" if light else "rgba(232,237,235,.07)"
    svg.add('<path d="%s" stroke="%s" stroke-width="1" mask="url(#%s)"/>' % ("".join(lines), gink, m))
    # the scan line
    sg = svg.id("scan")
    svg.defs.append('<linearGradient id="%s" x1="0" x2="1"><stop offset="0" stop-color="%s" stop-opacity="0"/><stop offset=".5" stop-color="%s" stop-opacity=".9"/>'
                    '<stop offset="1" stop-color="%s" stop-opacity="0"/></linearGradient>' % (sg, datum, datum, datum))
    sc = svg.anim([(0, {"transform": "translateY(0px)", "opacity": "0"}), (0.6, {"transform": "translateY(0px)", "opacity": "0"}),
                   (1.2, {"opacity": ".9"}), (3.4, {"opacity": ".9"}), (4.2, {"transform": "translateY(170px)", "opacity": "0"})], ease="ease-in-out")
    svg.rect(150, 120, W - 300, 1.2, fill="url(#%s)" % sg, cls=sc)
    # the mark: the origin first, then the arms, as the app's first start draws it
    size = 96
    u = size / 48
    total = 40 * u + 0.42 * size + LOGO_W * (size / 1.5 / LOGO_CAP)
    x = (W - total) / 2
    y = 110 - size / 2
    o = svg.show(0.2, None, 0.5, scale=0.6)
    svg.rect(x, y, 12 * u, 12 * u, fill=datum, cls=o)
    cut = 2 * u
    for k, (rx, ry, rw, rh) in enumerate(((12 * u + cut, 0, 28 * u - cut, 12 * u), (0, 12 * u + cut, 12 * u, 36 * u - cut), (12 * u, 20 * u, 20 * u, 12 * u))):
        cls = svg.anim([(0, {"opacity": "0", "transform": "translate(%spx,%spx)" % ("-10" if k != 1 else "0", "0" if k != 1 else "-10")}),
                        (0.45 + 0.12 * k, {"opacity": "0", "transform": "translate(%spx,%spx)" % ("-10" if k != 1 else "0", "0" if k != 1 else "-10")}),
                        (0.95 + 0.12 * k, {"opacity": "1", "transform": "translate(0px,0px)"})])
        svg.rect(x + rx, y + ry, rw, rh, fill=part, cls=cls)
    cap = size / 1.5
    k_ = cap / LOGO_CAP
    wx, wy = x + 40 * u + 0.42 * size, y + (size - cap) / 2
    wc = svg.show(0.9, None, 0.6, rise=6)
    svg.add('<g class="%s"><g transform="translate(%.2f %.2f) scale(%.5f)"><path d="%s" fill="%s"/><path d="%s" fill="%s"/></g></g>'
            % (wc, wx, wy, k_, LOGO_FORM, ink, LOGO_STUDIO, ink2))
    t1 = svg.show(1.5, None, 0.6, rise=6)
    svg.text(W / 2, 222, "What are we making?", 30, 620, ink, anchor="middle", ls=-0.8, cls=t1)
    t2 = svg.show(1.8, None, 0.6, rise=6)
    svg.text(W / 2, 256, "Describe it. An agent designs it in a real CAD kernel. Form Studio proves it and slices it.", 16, 420,
             "#5b6562" if light else T["ink3"], anchor="middle", cls=t2)
    # header runs once (it does not loop forever: everything holds after the entrance)
    svg.css = [c.replace(" infinite;", " 1 forwards;") for c in svg.css]
    desc = "Form Studio. What are we making?"
    return svg.render(desc), desc


SCENES = {"header": header, "hero": hero, "prove": prove_card, "hinge": hinge_card, "print": print_card}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--keep", type=Path, help="projects folder to build into and reuse")
    ap.add_argument("--only", help="comma-separated drawings to write")
    ap.add_argument("--fresh", action="store_true", help="read the engine again even when --keep has a cache")
    a = ap.parse_args()
    data_dir = a.keep or Path(tempfile.mkdtemp(prefix="form-readme-"))
    cache = data_dir / ".readme-art.pkl"
    if a.keep and cache.exists() and not a.fresh:
        import pickle
        data = pickle.loads(cache.read_bytes())
    else:
        data = engine(data_dir)
        if a.keep:
            import pickle
            cache.write_bytes(pickle.dumps(data))
    OUT.mkdir(parents=True, exist_ok=True)
    for name, fn in SCENES.items():
        if a.only and name not in a.only.split(","):
            continue
        for light in (False, True):
            svg_text, desc = fn(data, light)
            p = OUT / ("%s-%s.svg" % (name, "light" if light else "dark"))
            p.write_text(svg_text, encoding="utf-8")
            print("%-28s %7.1f kB" % (p.relative_to(ROOT), p.stat().st_size / 1024))


if __name__ == "__main__":
    main()
