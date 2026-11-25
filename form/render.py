"""Headless renderer: kernel mesh -> PNG an agent (or a person) can look at.

Orthographic, z-buffered, flat-shaded, colour by feature, visible edges only.
No GPU, no browser, no OCCT in this process: it consumes the tessellation the
kernel worker already produced for the bench.
"""
from __future__ import annotations

import base64
import io
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

VERSION = 4          # part of every cached render's name: change the drawing, change this

VIEWS = {
    #            azimuth (deg, from +X toward +Y), elevation (deg)
    "iso": (-55.0, 28.0),
    "iso_back": (125.0, 28.0),
    "front": (-90.0, 0.0),
    "back": (90.0, 0.0),
    "left": (180.0, 0.0),
    "right": (0.0, 0.0),
    "top": (-90.0, 90.0),
    "bottom": (-90.0, -90.0),
}

PAPER = (244, 241, 234)
INK = (28, 27, 25)
MUTED = (118, 114, 106)
SIGNAL = (226, 77, 38)
PALETTE = [(196, 192, 182), (152, 172, 186), (205, 180, 140), (160, 186, 160), (190, 160, 176),
           (176, 166, 206), (214, 196, 120), (150, 190, 196)]


def _arr(b64: str, dtype, cols: int) -> np.ndarray:
    return np.frombuffer(base64.b64decode(b64), dtype=dtype).reshape(-1, cols)


POSES = ("assembled", "exploded")       # a multi-part design put together (or pulled apart), seen from iso


def posed(view_data: dict, pose: str) -> dict:
    """The view with every part moved from where it prints to where it sits in the assembly (plus its explode
    offset for "exploded"). Raises ValueError when the design has no usable assembly."""
    a = view_data.get("assembly") or {}
    if not a.get("parts"):
        raise ValueError("This design is one part, so it has no assembled view. Use iso, front, top and the others.")
    if a.get("error"):
        raise ValueError(f"The assembly cannot be shown: {a['error']}")
    move = {}
    for part in a["parts"]:
        M = np.array(part["placement"]["m"], dtype=np.float64)
        off = np.array(part["explode_total"] if pose == "exploded" else (0.0, 0.0, 0.0), dtype=np.float64)
        move[part["id"]] = (M[:, :3], M[:, 3] + off)
    mesh = []
    for m in view_data["mesh"]:
        if m.get("part") in move:
            R, tr = move[m["part"]]
            P = _arr(m["positions"], np.float32, 3).astype(np.float64) @ R.T + tr
            m = {**m, "positions": base64.b64encode(np.ascontiguousarray(P.astype(np.float32)).tobytes()).decode()}
        mesh.append(m)
    return {**view_data, "mesh": mesh, "edges": None}     # edges are drawn in the print frame: leave them out


def _camera(view: str):
    if view not in VIEWS:
        raise ValueError(f"Unknown view “{view}”. Choose one of: {', '.join(VIEWS)}.")
    return _camera_ae(*VIEWS[view])


def _camera_ae(az_deg: float, el_deg: float):
    az, el = math.radians(az_deg), math.radians(el_deg)
    fwd = -np.array([math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)])   # camera looks along fwd
    up_hint = np.array([0.0, 1.0, 0.0]) if abs(el) > math.radians(89) else np.array([0.0, 0.0, 1.0])
    right = np.cross(fwd, up_hint)
    right /= np.linalg.norm(right)
    up = np.cross(right, fwd)
    return right, up, fwd


#: fonts for labels, first found wins: the app's own Instrument Sans (Latin with accents: Capacete de herói, Peça,
#: Lâmpada), then common system fonts. Pillow's built-in font has no accented letters and draws them as boxes.
FONT_FILES = (
    Path(__file__).resolve().parent / "app" / "assets" / "fonts" / "InstrumentSans.ttf",
    Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
    Path("/System/Library/Fonts/Helvetica.ttc"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/usr/share/fonts/TTF/DejaVuSans.ttf"),
    Path("C:/Windows/Fonts/segoeui.ttf"),
    Path("C:/Windows/Fonts/arial.ttf"),
)
_FONTS: dict = {}


def _font(size: int):
    """A Unicode-capable font at size px (cached), so accented names render; Pillow's default only as a last resort."""
    if size in _FONTS:
        return _FONTS[size]
    f = None
    for p in FONT_FILES:
        try:
            if p.is_file():
                f = ImageFont.truetype(str(p), size)
                break
        except OSError:
            continue
    if f is None:
        try:
            f = ImageFont.load_default(size=size)
        except TypeError:          # Pillow < 10.1
            f = ImageFont.load_default()
    _FONTS[size] = f
    return f


RASTER_BATCH = 4_000_000     # candidate pixels per batch of triangles (memory: about 60 bytes each)


def _raster(X, Y, Z, w: int, h: int):
    """Z-buffer of screen-space triangles: (depth, index of the nearest triangle or -1) per pixel. The same pixels
    and the same winner as drawing the triangles one after another with a strict depth test (the nearest wins, the
    first of equal depths), computed for many triangles at once: triangles go in batches of similar box size, each
    batch's pixel candidates are measured together, and the nearest per pixel is kept."""
    zbuf = np.full((h, w), np.inf)
    ibuf = np.full((h, w), -1, dtype=np.int64)
    n = len(X)
    if not n:
        return zbuf, ibuf
    x0 = np.maximum(np.floor(X.min(axis=1)).astype(np.int64), 0)
    x1 = np.minimum(np.ceil(X.max(axis=1)).astype(np.int64), w - 1)
    y0 = np.maximum(np.floor(Y.min(axis=1)).astype(np.int64), 0)
    y1 = np.minimum(np.ceil(Y.max(axis=1)).astype(np.int64), h - 1)
    area = (X[:, 1] - X[:, 0]) * (Y[:, 2] - Y[:, 0]) - (X[:, 2] - X[:, 0]) * (Y[:, 1] - Y[:, 0])
    ok = (x1 >= x0) & (y1 >= y0) & (np.abs(area) >= 1e-9)
    idx = np.flatnonzero(ok)
    if not len(idx):
        return zbuf, ibuf
    gw, gh = x1[idx] - x0[idx] + 1, y1[idx] - y0[idx] + 1
    # triangles in buckets of box size (powers of two), each bucket in batches of RASTER_BATCH candidate pixels
    bx = np.ceil(np.log2(gw)).astype(np.int64)
    by = np.ceil(np.log2(gh)).astype(np.int64)
    order = np.lexsort((idx, bx, by))
    idx, bx, by = idx[order], bx[order], by[order]
    cut = np.flatnonzero((bx[1:] != bx[:-1]) | (by[1:] != by[:-1])) + 1
    batches = []
    for lo_, hi_ in zip(np.r_[0, cut], np.r_[cut, len(idx)]):
        bw, bh = 1 << int(bx[lo_]), 1 << int(by[lo_])
        step = max(1, RASTER_BATCH // (bw * bh))
        batches += [(idx[k:min(k + step, hi_)], bw, bh) for k in range(lo_, hi_, step)]
    pix, dep, tri = [], [], []
    for b, bw, bh in batches:
        ox = np.arange(bw)[None, None, :]
        oy = np.arange(bh)[None, :, None]
        pxi = x0[b][:, None, None] + ox
        pyi = y0[b][:, None, None] + oy
        valid = (pxi <= x1[b][:, None, None]) & (pyi <= y1[b][:, None, None])
        px, py = pxi + 0.5, pyi + 0.5
        x, y, z = X[b], Y[b], Z[b]
        xa, xb, xc = (x[:, k][:, None, None] for k in range(3))
        ya, yb, yc = (y[:, k][:, None, None] for k in range(3))
        ar = area[b][:, None, None]
        w0 = ((xb - px) * (yc - py) - (xc - px) * (yb - py)) / ar
        w1 = ((xc - px) * (ya - py) - (xa - px) * (yc - py)) / ar
        w2 = 1 - w0 - w1
        inside = valid & (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
        zz = w0 * z[:, 0][:, None, None] + w1 * z[:, 1][:, None, None] + w2 * z[:, 2][:, None, None]
        t, r, c = np.nonzero(inside)
        pix.append(pyi[t, r, 0] * w + pxi[t, 0, c])
        dep.append(zz[t, r, c])
        tri.append(b[t])
    pix, dep, tri = np.concatenate(pix), np.concatenate(dep), np.concatenate(tri)
    o = np.lexsort((tri, dep, pix))                      # per pixel: nearest first, then the earlier triangle
    pix, dep, tri = pix[o], dep[o], tri[o]
    first = np.ones(len(pix), dtype=bool)
    first[1:] = pix[1:] != pix[:-1]
    zbuf.reshape(-1)[pix[first]] = dep[first]
    ibuf.reshape(-1)[pix[first]] = tri[first]
    return zbuf, ibuf


def render_png(view_data: dict, features: list, view: str = "iso", highlight: str | None = None,
               size=(960, 680), title: str = "", ss: int = 2, camera: tuple | None = None, frame_box=None,
               overlay: bool = True, caption: str = "", as_image: bool = False, lines: list | None = None):
    """features: [{"id","label"}] in recipe order. Returns PNG bytes (or a PIL image with as_image).

    camera=(azimuth, elevation) in degrees overrides view. frame_box=(lo, hi) fixes the framing so a
    sequence of frames (turntable, morph) does not jump. overlay=False draws only title and caption.
    lines=[(segments (n, 6), rgb)] draws extra visible line sets in a colour (an analysis outline, a measurement).
    """
    W, Hh = size
    w, h = W * ss, Hh * ss
    right, up, fwd = _camera_ae(*camera) if camera else _camera(view)
    order = [f["id"] for f in features]
    tris, tri_feat, tri_rgb = [], [], []
    for m in view_data["mesh"]:
        P = _arr(m["positions"], np.float32, 3).astype(np.float64)
        T = _arr(m["indices"], np.uint32, 3)
        tris.append(P[T])
        tri_feat.append(np.full(len(T), order.index(m["feature"]) if m["feature"] in order else len(order)))
        # an analysis map carries a colour per vertex (form/analysis.py): a triangle takes the mean of its corners
        tri_rgb.append(_arr(m["colors"], np.uint8, 4)[:, :3].astype(np.float64)[T].mean(axis=1) if m.get("colors")
                       else np.full((len(T), 3), np.nan))
    V = np.concatenate(tris)                       # (n, 3, 3) world
    F = np.concatenate(tri_feat)
    lo, hi = V.reshape(-1, 3).min(0), V.reshape(-1, 3).max(0)
    centre = (lo + hi) / 2
    if frame_box is not None:
        flo, fhi = np.asarray(frame_box[0], float), np.asarray(frame_box[1], float)
        centre = (flo + fhi) / 2
    S = np.stack([(V - centre) @ right, (V - centre) @ up, (V - centre) @ fwd], axis=-1)   # screen-space, z = depth
    sx, sy = S[..., 0], S[..., 1]
    span = max(sx.max() - sx.min(), (sy.max() - sy.min()) * w / h, 1e-6)
    _d, _f = ImageDraw.Draw(Image.new("RGB", (1, 1))), _font(13)
    n_rows, x = 1, 18
    for fdef in features:
        wdt = 30 + int(_d.textlength(fdef["label"] + (" (selected)" if fdef["id"] == highlight else ""), font=_f))
        if x > 18 and x + wdt > W - 18:
            n_rows, x = n_rows + 1, 18
        x += wdt
    top_band, bottom_band = 54 * ss, (24 + 20 * n_rows) * ss
    if not overlay:
        top_band, bottom_band = (40 if title else 8) * ss, (28 if caption else 8) * ss
    usable_h = h - top_band - bottom_band
    if frame_box is not None:
        # bound the projection for any azimuth: horizontal radius in XY, vertical from elevation
        ext = fhi - flo
        r_xy = float(np.hypot(ext[0], ext[1])) / 2
        el = math.radians(camera[1]) if camera else math.radians(VIEWS.get(view, (0, 30))[1])
        half_v = r_xy * abs(math.sin(el)) + ext[2] / 2 * abs(math.cos(el))
        scale = min(0.94 * w / (2 * r_xy), 0.94 * usable_h / (2 * max(half_v, 1e-6)))
        cx = cy = 0.0
    else:
        scale = min(0.86 * w / span, 0.92 * usable_h / max(sy.max() - sy.min(), 1e-6))
        cx = (sx.max() + sx.min()) / 2
        cy = (sy.max() + sy.min()) / 2
    X = (sx - cx) * scale + w / 2
    Y = h - ((sy - cy) * scale + bottom_band + usable_h / 2)
    Z = S[..., 2]

    # flat shading: normal facing the camera, light from upper-left-front
    n = np.cross(V[:, 1] - V[:, 0], V[:, 2] - V[:, 0])
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
    n[(n @ fwd) > 0] *= -1
    light = -fwd * 0.75 + up * 0.45 - right * 0.35
    light /= np.linalg.norm(light)
    shade = 0.42 + 0.58 * np.clip(n @ light, 0, 1)

    zbuf, ibuf = _raster(X, Y, Z, w, h)

    hl = order.index(highlight) if highlight in order else None
    base = np.array([PALETTE[k % len(PALETTE)] for k in range(len(order) + 1)], dtype=np.float64)
    if hl is not None:
        base[:] = (200, 197, 190)
        base[hl] = SIGNAL
    col = base[F]
    mapped = np.concatenate(tri_rgb)
    has = ~np.isnan(mapped[:, 0])
    col[has] = mapped[has]
    col = col * shade[:, None]
    img = np.empty((h, w, 3), dtype=np.float64)
    img[:] = PAPER
    hit = ibuf >= 0
    img[hit] = col[ibuf[hit]]

    # visible edges: sample each segment, keep samples not behind the surface
    edge_sets = [(_arr(view_data["edges"], np.float32, 6).astype(np.float64), INK, 1)] if view_data.get("edges") else []
    edge_sets += [(np.asarray(L, dtype=np.float64).reshape(-1, 6), c, 2) for L, c in (lines or []) if len(L)]
    for E, ink, wide in edge_sets:
        diag = float(np.linalg.norm(hi - lo))
        eps = diag * 0.004 * wide
        for a, b in ((E[:, :3], E[:, 3:]),):
            pa, pb = a - centre, b - centre
            ax, ay, az_ = pa @ right, pa @ up, pa @ fwd
            bx, by, bz = pb @ right, pb @ up, pb @ fwd
            Xa, Ya = (ax - cx) * scale + w / 2, h - ((ay - cy) * scale + bottom_band + usable_h / 2)
            Xb, Yb = (bx - cx) * scale + w / 2, h - ((by - cy) * scale + bottom_band + usable_h / 2)
            steps = np.maximum(np.ceil(np.hypot(Xb - Xa, Yb - Ya)), 1).astype(int)
            # every segment's samples at once: segment k has steps[k] + 1 evenly spaced (np.linspace(0, 1, n))
            k = np.repeat(np.arange(len(E)), steps + 1)
            j = np.arange(len(k)) - np.repeat(np.cumsum(steps + 1) - (steps + 1), steps + 1)
            t = j * (1.0 / steps[k])
            t[j == steps[k]] = 1.0
            xs = (Xa[k] + (Xb[k] - Xa[k]) * t).astype(int)
            ys = (Ya[k] + (Yb[k] - Ya[k]) * t).astype(int)
            zs = az_[k] + (bz[k] - az_[k]) * t
            ok = (xs >= 0) & (xs < w) & (ys >= 0) & (ys < h)
            xs, ys, zs = xs[ok], ys[ok], zs[ok]
            vis = zs <= zbuf[ys, xs] + eps
            for dx, dy in (((0, 0), (1, 0), (0, 1)) if wide == 1 else ((0, 0), (1, 0), (0, 1), (1, 1), (2, 0), (0, 2), (2, 1), (1, 2), (2, 2))):
                img[np.clip(ys[vis] + dy, 0, h - 1), np.clip(xs[vis] + dx, 0, w - 1)] = ink

    out = Image.fromarray(img.clip(0, 255).astype(np.uint8)).resize((W, Hh), Image.LANCZOS)
    d = ImageDraw.Draw(out)
    f_title, f_small = _font(17), _font(13)
    if not overlay:
        if title:
            d.text((16, 12), title, fill=INK, font=f_title)
        if caption:
            d.text((16, Hh - 24), caption, fill=MUTED, font=f_small)
        if as_image:
            return out
        buf = io.BytesIO()
        out.save(buf, "PNG", optimize=True)
        return buf.getvalue()
    size_mm = hi - lo
    d.text((18, 14), title or "FORM", fill=INK, font=f_title)
    d.text((18, 36), f"{view} view, orthographic, bounding box {size_mm[0]:.1f} x {size_mm[1]:.1f} x {size_mm[2]:.1f} mm (X x Y x Z)",
           fill=MUTED, font=f_small)
    # legend, wrapped into as many rows as it needs
    items, rows, row, x = [], [], [], 18
    for k, fdef in enumerate(features):
        label = fdef["label"] + (" (selected)" if fdef["id"] == highlight else "")
        wdt = 30 + int(d.textlength(label, font=f_small))
        if row and x + wdt > W - 18:
            rows.append(row)
            row, x = [], 18
        row.append((k, label, x))
        x += wdt
    if row:
        rows.append(row)
    for r_i, row in enumerate(rows):
        y = Hh - 28 - (len(rows) - 1 - r_i) * 20
        for k, label, x in row:
            c = tuple(int(v) for v in (base[k]))
            d.rectangle([x, y, x + 12, y + 12], fill=c, outline=INK)
            d.text((x + 17, y - 1), label, fill=INK if (hl is None or k == hl) else MUTED, font=f_small)
    # scale bar: a round length near 1/5 of the image width
    mm_per_px = 1 / (scale / ss)
    target = mm_per_px * W / 5
    bar = min((v for v in (1, 2, 5, 10, 20, 25, 50, 100, 200) if v >= target * 0.6), default=200)
    px = bar / mm_per_px
    bx, by = W - 24 - px, 112              # top right, under the axis triad, clear of the legend
    d.line([bx, by, bx + px, by], fill=INK, width=2)
    d.line([bx, by - 5, bx, by + 5], fill=INK, width=2)
    d.line([bx + px, by - 5, bx + px, by + 5], fill=INK, width=2)
    d.text((bx, by - 20), f"{bar} mm", fill=INK, font=f_small)
    # axis triad
    ox, oy, L = W - 60, 60, 26
    for vec, name, c in (((1, 0, 0), "X", (190, 60, 50)), ((0, 1, 0), "Y", (60, 140, 70)), ((0, 0, 1), "Z", (50, 90, 190))):
        v = np.array(vec, dtype=float)
        ex, ey = v @ right, v @ up
        if abs(ex) + abs(ey) < 0.05:
            d.ellipse([ox - 3, oy - 3, ox + 3, oy + 3], outline=c, width=2)
            d.text((ox + 5, oy + 3), name, fill=c, font=f_small)
            continue
        d.line([ox, oy, ox + ex * L, oy - ey * L], fill=c, width=2)
        d.text((ox + ex * (L + 7) - 4, oy - ey * (L + 7) - 7), name, fill=c, font=f_small)
    if as_image:
        return out
    buf = io.BytesIO()
    out.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def contact_sheet(pngs: list[bytes], cols: int = 2) -> bytes:
    ims = [Image.open(io.BytesIO(b)) for b in pngs]
    W, H = ims[0].size
    rows = math.ceil(len(ims) / cols)
    sheet = Image.new("RGB", (W * cols, H * rows), PAPER)
    for i, im in enumerate(ims):
        sheet.paste(im, ((i % cols) * W, (i // cols) * H))
    buf = io.BytesIO()
    sheet.save(buf, "PNG", optimize=True)
    return buf.getvalue()
