"""Share card and revision history, rendered headless from the kernel's own tessellation.

    share.card(st, p)                    -> {"file": ".../share/<id>_r04_card.png", ...}   1600 x 900 PNG
    share.history(st, p, "out.gif")      -> every revision in turn, cross-faded, as GIF or animated WebP
    share.revisions(st, p)               -> who made each revision, when, its note and its stamp text

The card says only what is known, each number with how it is known: size and volume are computed from the solid;
print time and grams are the slicer's simulation and appear only when the slice is current; checks appear only
when they are current; the fit yield is modelled. Nothing is claimed about a physical print unless a result was
recorded for the revision.

No GPU, no browser, no OCCT in this process (same as form/render.py): a small z-buffer rasteriser with smooth
shading, the kernel's edges, a ground shadow and drawing-style dimension lines.
"""
from __future__ import annotations

import math
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import __version__, render
from .studio import H, StudioError
from . import fsutil

VERSION = 3                      # part of every cached card's name: change the drawing, change this
SIZE = (1600, 900)
PLATE, PLATE1, PLATE2 = (14, 17, 19), (19, 23, 26), (25, 30, 34)
INK, INK2, INK3, INK4 = (232, 237, 235), (168, 178, 175), (113, 123, 120), (73, 82, 79)
DATUM, AMBER, PASS, SIGNAL, CLAY = (185, 232, 215), (233, 184, 96), (134, 217, 173), (255, 111, 81), (216, 211, 200)
EVIDENCE = {"computed": DATUM, "specified": DATUM, "simulated": AMBER, "modelled": AMBER, "assumed": AMBER,
            "physical": PASS, "measured": PASS}
FONTS = Path(__file__).resolve().parent
CAMERA = (-58.0, 24.0)           # azimuth, elevation (degrees): from the front left, slightly above


def _font(kind: str, size: int):
    f = {"bold": FONTS / "fonts" / "FormMark-Bold.ttf", "sans": FONTS / "app" / "assets" / "fonts" / "InstrumentSans.ttf",
         "mono": FONTS / "app" / "assets" / "fonts" / "GeistMono.ttf"}[kind]
    try:
        return ImageFont.truetype(str(f), size)
    except OSError:
        return render._font(size)


# ---- rasteriser ------------------------------------------------------------------------------------------------

def _mesh(view: dict):
    """All triangles with smooth per-vertex normals (the kernel splits vertices at sharp edges, so creases stay crisp)."""
    Ps, Ns, Ts, off = [], [], [], 0
    for m in view["mesh"]:
        P = render._arr(m["positions"], np.float32, 3).astype(np.float64)
        T = render._arr(m["indices"], np.uint32, 3).astype(np.int64)
        n = np.zeros_like(P)
        a, b, c = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
        fn = np.cross(b - a, c - a)
        for k in range(3):
            np.add.at(n, T[:, k], fn)
        ln = np.linalg.norm(n, axis=1, keepdims=True)
        ln[ln == 0] = 1
        Ps.append(P)
        Ns.append(n / ln)
        Ts.append(T + off)
        off += len(P)
    return np.concatenate(Ps), np.concatenate(Ns), np.concatenate(Ts)


class Scene:
    """Orthographic camera fitted to a box, plus the rendered image of one view."""

    def __init__(self, lo, hi, size, camera=CAMERA, pad=0.14, ss=2, extra=None):
        self.w, self.h, self.ss = size[0] * ss, size[1] * ss, ss
        self.right, self.up, self.fwd = render._camera_ae(*camera)
        self.lo, self.hi = np.asarray(lo, float), np.asarray(hi, float)
        self.centre = (self.lo + self.hi) / 2
        corners = np.array([[x, y, z] for x in (self.lo[0], self.hi[0]) for y in (self.lo[1], self.hi[1]) for z in (self.lo[2], self.hi[2])])
        if extra is not None and len(extra):
            corners = np.vstack([corners, extra])
        sx, sy = (corners - self.centre) @ self.right, (corners - self.centre) @ self.up
        self.cx, self.cy = (sx.max() + sx.min()) / 2, (sy.max() + sy.min()) / 2
        self.scale = min(self.w * (1 - 2 * pad) / max(sx.max() - sx.min(), 1e-6), self.h * (1 - 2 * pad) / max(sy.max() - sy.min(), 1e-6))

    def project(self, P):
        P = np.asarray(P, float) - self.centre
        x = (P @ self.right - self.cx) * self.scale + self.w / 2
        y = self.h / 2 - (P @ self.up - self.cy) * self.scale
        return x, y, P @ self.fwd

    def px(self, p):
        """One world point -> output pixels (not supersampled)."""
        x, y, _ = self.project(np.asarray([p], float))
        return float(x[0]) / self.ss, float(y[0]) / self.ss

    def render(self, view: dict, bg=PLATE, clay=CLAY, shadow=True) -> Image.Image:
        P, N, T = _mesh(view)
        X, Y, Z = self.project(P)
        w, h = self.w, self.h
        n_cam = np.stack([N @ self.right, N @ self.up, -(N @ self.fwd)], axis=1)       # normals in camera space, +z toward the eye
        key = np.array([-0.45, 0.62, 0.64]); key /= np.linalg.norm(key)
        fill = np.array([0.7, 0.1, 0.55]); fill /= np.linalg.norm(fill)
        zbuf = np.full((h, w), np.inf)
        shade = np.zeros((h, w))
        for t in T:
            x, y, z = X[t], Y[t], Z[t]
            x0, x1 = max(int(math.floor(x.min())), 0), min(int(math.ceil(x.max())), w - 1)
            y0, y1 = max(int(math.floor(y.min())), 0), min(int(math.ceil(y.max())), h - 1)
            if x1 < x0 or y1 < y0:
                continue
            area = (x[1] - x[0]) * (y[2] - y[0]) - (x[2] - x[0]) * (y[1] - y[0])
            if abs(area) < 1e-9:
                continue
            px, py = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
            w0 = ((x[1] - px) * (y[2] - py) - (x[2] - px) * (y[1] - py)) / area
            w1 = ((x[2] - px) * (y[0] - py) - (x[0] - px) * (y[2] - py)) / area
            w2 = 1 - w0 - w1
            inside = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
            if not inside.any():
                continue
            zz = w0 * z[0] + w1 * z[1] + w2 * z[2]
            zs = zbuf[y0:y1 + 1, x0:x1 + 1]
            m = inside & (zz < zs)
            if not m.any():
                continue
            zs[m] = zz[m]
            nn = (w0[..., None] * n_cam[t[0]] + w1[..., None] * n_cam[t[1]] + w2[..., None] * n_cam[t[2]])[m]
            nn /= np.linalg.norm(nn, axis=1, keepdims=True) + 1e-12
            nn[nn[:, 2] < 0] *= -1                                                    # two-sided
            s = 0.30 + 0.62 * np.clip(nn @ key, 0, 1) + 0.16 * np.clip(nn @ fill, 0, 1) + 0.06 * nn[:, 2]
            shade[y0:y1 + 1, x0:x1 + 1][m] = s
        hit = np.isfinite(zbuf)
        img = np.empty((h, w, 3))
        img[:] = bg
        if shadow:                                   # the part's footprint on the plate, blurred: it sits on something
            zmin = float(P[:, 2].min())
            G = P.copy(); G[:, 2] = zmin
            gx, gy, _ = self.project(G + np.array([1.0, -0.6, 0]) * (self.hi[2] - self.lo[2]) * 0.10)
            mask = Image.new("L", (w // 4, h // 4), 0)
            d = ImageDraw.Draw(mask)
            for t in T[:: max(1, len(T) // 6000)]:
                d.polygon([(gx[i] / 4, gy[i] / 4) for i in t], fill=255)
            mask = mask.filter(ImageFilter.GaussianBlur(max(2, w // 260))).resize((w, h), Image.BILINEAR)
            a = (np.asarray(mask, float) / 255)[..., None] * 0.55
            img = img * (1 - a) + np.array([4, 5, 6]) * a
        col = np.asarray(clay, float)
        img[hit] = np.clip(shade[hit], 0, 1.15)[:, None] * col
        if view.get("edges"):                        # the kernel's edges, where they are in front
            E = render._arr(view["edges"], np.float32, 6).astype(np.float64)
            if len(E):
                ax, ay, az = self.project(E[:, :3])
                bx, by, bz = self.project(E[:, 3:])
                eps = float(np.linalg.norm(self.hi - self.lo)) * 0.004
                steps = np.maximum(np.ceil(np.hypot(bx - ax, by - ay)), 1).astype(int)
                ink = col * 0.34
                for k in range(len(E)):
                    t = np.linspace(0, 1, steps[k] + 1)
                    xs = (ax[k] + (bx[k] - ax[k]) * t).astype(int)
                    ys = (ay[k] + (by[k] - ay[k]) * t).astype(int)
                    zs = az[k] + (bz[k] - az[k]) * t
                    ok = (xs >= 0) & (xs < w - 1) & (ys >= 0) & (ys < h - 1)
                    xs, ys, zs = xs[ok], ys[ok], zs[ok]
                    vis = zs <= zbuf[ys, xs] + eps
                    img[ys[vis], xs[vis]] = ink
                    img[ys[vis], xs[vis] + 1] = ink
        return Image.fromarray(img.clip(0, 255).astype(np.uint8)).resize((w // self.ss, h // self.ss), Image.LANCZOS)


def _bbox(view: dict):
    P = np.concatenate([render._arr(m["positions"], np.float32, 3) for m in view["mesh"]]).astype(np.float64)
    return P.min(0), P.max(0)


def _dim_points(lo, hi, o):
    """Dimension lines like a drawing: width along the front, depth along the right, height at the back right."""
    x0, y0, z0 = lo
    x1, y1, z1 = hi
    t = o * 0.32
    return [
        {"mm": x1 - x0, "a": (x0, y0 - o, z0), "b": (x1, y0 - o, z0),
         "ext": [((x0, y0 - o - t, z0), (x0, y0 - o * 0.15, z0)), ((x1, y0 - o - t, z0), (x1, y0 - o * 0.15, z0))]},
        {"mm": y1 - y0, "a": (x1 + o, y0, z0), "b": (x1 + o, y1, z0),
         "ext": [((x1 + o * 0.15, y0, z0), (x1 + o + t, y0, z0)), ((x1 + o * 0.15, y1, z0), (x1 + o + t, y1, z0))]},
        {"mm": z1 - z0, "a": (x1 + o, y1, z0), "b": (x1 + o, y1, z1),
         "ext": [((x1 + o * 0.15, y1, z1), (x1 + o + t, y1, z1))]},
    ]


def _draw_dims(img: Image.Image, sc: Scene, lo, hi, o, origin=(0, 0), font=None):
    d = ImageDraw.Draw(img)
    font = font or _font("mono", 19)
    ox, oy = origin
    for dim in _dim_points(lo, hi, o):
        a, b = sc.px(dim["a"]), sc.px(dim["b"])
        for p, q in [(dim["a"], dim["b"])] + dim["ext"]:
            (x0, y0), (x1, y1) = sc.px(p), sc.px(q)
            d.line([x0 + ox, y0 + oy, x1 + ox, y1 + oy], fill=tuple(int(c * 0.72) for c in DATUM), width=2)
        text = f"{dim['mm']:.1f}"
        tw = d.textlength(text, font=font)
        mx, my = (a[0] + b[0]) / 2 + ox, (a[1] + b[1]) / 2 + oy
        box = [mx - tw / 2 - 9, my - 15, mx + tw / 2 + 9, my + 15]
        d.rounded_rectangle(box, 5, fill=PLATE, outline=tuple(int(c * 0.45) for c in DATUM))
        d.text((mx - tw / 2, my - 12), text, fill=DATUM, font=font)


# ---- revisions -------------------------------------------------------------------------------------------------

def who(origin: str | None) -> str:
    o = origin or "user"
    if o.startswith("agent:"):
        return o[6:] or "agent"
    if o.startswith("proposal:"):
        return f"you ({o[9:]} proposal)"
    return {"user": "you", "recipe": "you", "variant": "you", "cli": "you (CLI)", "agent": "agent"}.get(o, o)


def revisions(st, p: dict) -> list:
    """Every revision: number, when, who made it, its note, whether it is the head, and its stamp text."""
    from . import marks
    out = []
    for r in sorted(p["revisions"], key=lambda r: r["n"]):
        rid = r.get("recipe") or p["recipe"]
        out.append({"n": r["n"], "ts": r["ts"], "by": who(r.get("origin")), "origin": r.get("origin") or "user",
                    "note": r.get("note", ""), "summary": r.get("summary", ""), "parent": r.get("parent"),
                    "head": r["n"] == p["head"], "stamp": marks.stamp_text(r["n"], marks.short_hash(rid, r["values"])),
                    "changed": list(r.get("touched") or [])})
    return out


def _dur(s: float) -> str:
    m = int(round(s / 60))
    return f"{m // 60} h {m % 60:02d} min" if m >= 60 else f"{m} min"


# ---- the card --------------------------------------------------------------------------------------------------

def facts(st, p: dict) -> dict:
    """What the card states, each with its evidence class. Only current outputs are used."""
    from . import marks
    s = st.state(p["id"])
    head = st.rev(p)
    summ = st.head_summary(p)
    lo, hi = summ["bbox"]
    rows = [{"k": "Size", "v": " × ".join(f"{b - a:.1f}" for a, b in zip(lo, hi)) + " mm", "tag": "computed"},
            {"k": "Material volume", "v": f"{summ['volume_mm3'] / 1000:.1f} cm³", "tag": "computed"}]
    sl = s.get("slice")
    if sl and sl.get("time_s"):
        rows.append({"k": "Print time", "v": _dur(sl["time_s"]), "tag": "simulated"})
        rows.append({"k": "Filament", "v": f"{sl['filament_g']:.1f} g", "tag": "simulated"})
    else:
        rows.append({"k": "Print time", "v": "not sliced", "tag": ""})
    ch = s.get("checks")
    if ch:
        r = ch["rollup"]
        rows.append({"k": "Checks", "v": f"{r.get('PASS', 0)} pass · {r.get('WARN', 0)} review" + (f" · {r['FAIL']} fail" if r.get("FAIL") else ""), "tag": "computed"})
    if s.get("fit"):
        rows.append({"k": "Fit yield", "v": f"{s['fit']['yield'] * 100:.0f} %", "tag": "modelled"})
    recipe = st.recipe(p)
    slicer = ""
    if sl and sl.get("time_s"):
        presets = sl.get("presets") or {}
        slicer = (sl.get("slicer_name") or "Bambu Studio") + (f" {sl['slicer_version']}" if sl.get("slicer_version") else "")
        names = [v.get("name", "") for k, v in presets.items() if k in ("machine", "filament")]
        if any(names):
            slicer += " · " + " · ".join(n for n in names if n)
    return {"name": p["name"], "kind": recipe.title or "Design", "rev": head["n"],
            "stamp": marks.stamp_text(head["n"], marks.short_hash(st.rid(p), head["values"])),
            "date": time.strftime("%Y-%m-%d", time.localtime(head["ts"])), "rows": rows, "slicer": slicer,
            "evidence_level": s["gate"]["evidence_level"], "approved": s["approval"]["state"] == "approved",
            "bbox": [list(lo), list(hi)]}


def _wrap(d, text, font, width, max_lines=2):
    words, lines, cur = text.split(), [], ""
    for wd in words:
        t = (cur + " " + wd).strip()
        if d.textlength(t, font=font) <= width or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = wd
    lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        while lines[-1] and d.textlength(lines[-1] + "…", font=font) > width:
            lines[-1] = lines[-1][:-1]
        lines[-1] += "…"
    return lines


def _tag(d, x, y, text, font):
    col = EVIDENCE.get(text, INK3)
    tw = d.textlength(text, font=font)
    d.rounded_rectangle([x, y, x + tw + 18, y + 26], 6, fill=tuple(int(c * 0.16 + p * 0.84) for c, p in zip(col, PLATE1)),
                        outline=tuple(int(c * 0.42) for c in col))
    d.text((x + 9, y + 3), text, fill=col, font=font)
    return tw + 18


def card(st, p: dict, out: str | Path | None = None, picture: str = "model", force: bool = False) -> dict:
    """Render the share card for the head revision. picture: "model" (kernel geometry with dimension lines) or
    "photo" (the newest current Blender render, when one exists; an illustration, said so on the card).
    Cached in <project>/share/ by geometry, outputs and wording; `out` also copies it there."""
    f = facts(st, p)
    photo_file = None
    if picture == "photo":
        from . import photo
        m = photo.latest(st, p)
        if not m:
            raise StudioError("There is no current Blender render of this revision.", "Render one first (Photo, or render_photo), "
                              "or use picture=\"model\".", status=409)
        photo_file = photo.file(st, p, m["key"])
    elif picture != "model":
        raise StudioError("picture is model or photo.")
    d = st.dir(p["id"]) / "share"
    d.mkdir(parents=True, exist_ok=True)
    key = H("card", VERSION, __version__, st.keys(p)["geometry"], f, picture, str(photo_file))
    target = d / f"{p['id']}_r{f['rev']:02d}_card_{key[:8]}.png"
    cached = target.exists() and not force
    if not cached:
        img = _compose(st, p, f, photo_file)
        tmp = target.with_suffix(".tmp.png")
        img.save(tmp, "PNG", optimize=True)
        fsutil.replace(tmp, target)
        for old in d.glob(f"{p['id']}_r*_card_*.png"):          # keep the folder small: one card per picture kind
            if old != target and old.stat().st_mtime < target.stat().st_mtime - 3600:
                old.unlink(missing_ok=True)
    result = {"file": str(target), "name": target.name, "size": list(SIZE), "bytes": target.stat().st_size, "rev": f["rev"],
              "picture": picture, "cached": cached, "facts": f}
    if out:
        o = Path(out).expanduser()
        o.parent.mkdir(parents=True, exist_ok=True)
        o.write_bytes(target.read_bytes())
        result["out"] = str(o)
    return result


def _compose(st, p: dict, f: dict, photo_file: Path | None) -> Image.Image:
    W, Hh = SIZE
    img = Image.new("RGB", SIZE, PLATE)
    d = ImageDraw.Draw(img)
    split = 1010                                         # picture on the left, facts on the right
    pic = (split, Hh)
    if photo_file is not None:
        ph = Image.open(photo_file).convert("RGB")
        k = max(pic[0] / ph.width, pic[1] / ph.height)
        ph = ph.resize((int(ph.width * k + 0.5), int(ph.height * k + 0.5)), Image.LANCZOS)
        x0, y0 = (ph.width - pic[0]) // 2, (ph.height - pic[1]) // 2
        img.paste(ph.crop((x0, y0, x0 + pic[0], y0 + pic[1])), (0, 0))
        d.text((40, Hh - 54), "Blender render: an illustration with invented light and material, not a photo of a print.",
               fill=INK2, font=_font("sans", 19))
    else:
        v = st.view(p, tol=0.03)
        lo, hi = _bbox(v)
        o = max(6.0, float(np.linalg.norm(hi - lo)) * 0.07)
        pts = []
        for dim in _dim_points(lo, hi, o):
            pts += [dim["a"], dim["b"]] + [q for e in dim["ext"] for q in e]
        sc = Scene(lo, hi, pic, pad=0.13, extra=np.array(pts))
        img.paste(sc.render(v), (0, 0))
        _draw_dims(img, sc, lo, hi, o)
        d = ImageDraw.Draw(img)
        d.text((40, Hh - 54), "Kernel geometry (build123d / OpenCascade). Dimensions in mm, computed from the solid.",
               fill=INK3, font=_font("sans", 19))
    # wordmark
    d.text((40, 36), "Form Studio", fill=INK, font=_font("bold", 24))
    # right column
    d.rectangle([split, 0, W, Hh], fill=PLATE1)
    d.line([split, 0, split, Hh], fill=PLATE2, width=2)
    x, right = split + 54, W - 54
    y = 64
    d.text((x, y), f["kind"].upper(), fill=INK3, font=_font("mono", 17))
    y += 40
    title_font = _font("bold", 54)
    lines = _wrap(d, f["name"], title_font, right - x, 2)
    if len(lines) > 1 or d.textlength(lines[0], font=title_font) > right - x:
        title_font = _font("bold", 44)
        lines = _wrap(d, f["name"], title_font, right - x, 2)
    for ln in lines:
        d.text((x, y), ln, fill=INK, font=title_font)
        y += title_font.size + 8
    y += 10
    mono, sans, tagf = _font("mono", 21), _font("sans", 22), _font("mono", 15)
    d.text((x, y), f"r{f['rev']:02d}", fill=DATUM, font=_font("mono", 24))
    d.text((x + 62, y + 3), f"{f['stamp'].split()[1]} · {f['date']}" + (" · released" if f["approved"] else ""), fill=INK2, font=mono)
    y += 58
    for row in f["rows"]:
        d.line([x, y, right, y], fill=PLATE2, width=2)
        y += 17
        d.text((x, y), row["k"], fill=INK2, font=sans)
        tw = 0
        if row["tag"]:
            tw = d.textlength(row["tag"], font=tagf) + 18
            _tag(d, right - tw, y + 1, row["tag"], tagf)
            tw += 14
        vf = mono
        if right - tw - d.textlength(row["v"], font=vf) < x + d.textlength(row["k"], font=sans) + 24:      # a long value: smaller, never over the label
            vf = _font("mono", 17)
        vw = d.textlength(row["v"], font=vf)
        d.text((right - tw - vw, y + 1 + (mono.size - vf.size) // 2), row["v"], fill=INK if row["tag"] else INK3, font=vf)
        y += 45
    d.line([x, y, right, y], fill=PLATE2, width=2)
    y += 20
    small = _font("sans", 18)
    if f["slicer"]:
        for ln in _wrap(d, "Sliced with " + f["slicer"] + ". A slice is a simulation, not a print.", small, right - x, 3):
            d.text((x, y), ln, fill=INK3, font=small)
            y += 25
        y += 6
    for ln in _wrap(d, f["evidence_level"] + ".", small, right - x, 3):
        d.text((x, y), ln, fill=INK2, font=small)
        y += 25
    # footer
    d.text((x, Hh - 86), "Designed with Form Studio", fill=INK, font=_font("bold", 26))
    d.text((x, Hh - 50), f"open-source CAD with an AI agent · v{__version__}", fill=INK3, font=_font("sans", 18))
    return img


# ---- history: every revision in turn ------------------------------------------------------------------------

def frame(st, p: dict, n: int, size=(720, 540), box=None, caption=True) -> Image.Image:
    """One revision drawn the way the card draws the part."""
    v = st.view(p, n, tol=0.06)
    lo, hi = box if box is not None else _bbox(v)
    sc = Scene(lo, hi, size, pad=0.16)
    im = sc.render(v)
    if caption:
        r = st.rev(p, n)
        d = ImageDraw.Draw(im)
        d.text((22, 18), p["name"], fill=INK, font=_font("bold", 22))
        d.text((22, size[1] - 62), f"r{n:02d}", fill=DATUM, font=_font("mono", 20))
        d.text((74, size[1] - 61), f"by {who(r.get('origin'))}", fill=INK2, font=_font("sans", 18))
        note = (r.get("summary") or r.get("note") or "").strip()
        f = _font("sans", 17)
        while note and d.textlength(note, font=f) > size[0] - 44:
            note = note[:-2].rstrip() + "…" if not note.endswith("…") else note[:-2].rstrip() + "…"
            if len(note) < 4:
                break
        d.text((22, size[1] - 34), note, fill=INK3, font=f)
    return im


def history(st, p: dict, out: str | Path, size=(720, 540), hold_ms: int = 900, fade: int = 4, revs: list | None = None) -> dict:
    """Step through the revisions (all of them, or revs) with a cross-fade between each, as .gif or .webp.
    Each frame is that revision's real geometry at one fixed framing, so sizes compare honestly. Revisions that
    no longer build are skipped and reported."""
    ns = revs or [r["n"] for r in sorted(p["revisions"], key=lambda r: r["n"])]
    views, skipped = [], []
    for n in ns:
        try:
            views.append((n, st.view(p, n, tol=0.06)))
        except StudioError as e:
            skipped.append({"rev": n, "reason": str(e)[:160]})
    if not views:
        raise StudioError("No revision could be built, so there is nothing to animate.", skipped[0]["reason"] if skipped else "")
    boxes = [_bbox(v) for _, v in views]
    box = (np.min([b[0] for b in boxes], axis=0), np.max([b[1] for b in boxes], axis=0))
    stills = [frame(st, p, n, size, box) for n, _ in views]
    frames, durations = [], []
    step = 60
    for i, im in enumerate(stills):
        frames.append(im)
        durations.append(hold_ms)
        nxt = stills[(i + 1) % len(stills)]
        if len(stills) > 1:
            for k in range(1, fade + 1):
                frames.append(Image.blend(im, nxt, k / (fade + 1)))
                durations.append(step)
    out = Path(out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.suffix.lower() == ".webp":
        frames[0].save(out, save_all=True, append_images=frames[1:], duration=durations, loop=0, quality=84, method=4)
    elif out.suffix.lower() == ".gif":
        pal = Image.blend(stills[0], stills[-1], 0.5).convert("P", palette=Image.ADAPTIVE, colors=160)
        q = [fr.quantize(palette=pal, dither=Image.Dither.NONE) for fr in frames]
        q[0].save(out, save_all=True, append_images=q[1:], duration=durations, loop=0, optimize=False, disposal=1)
    else:
        raise StudioError("The history animation is written as .gif or .webp.", "Give a file name ending in .gif or .webp.")
    return {"file": str(out), "kind": "history", "revisions": [n for n, _ in views], "frames": len(frames), "bytes": out.stat().st_size,
            "skipped": skipped, "size": list(size)}
