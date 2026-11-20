"""Product classes: what a full-face helmet, a mouse, a bottle ... look like, so critique can say whether a design
reads as one. numpy and Pillow only (no OCCT): the kernel worker computes the views, the rest runs anywhere.

A class has
  aliases     words in a brief that name it ("motorcycle helmet", "computer mouse")
  ratios      bounding-box proportions with the range real products fall in and where the range comes from
  outlines    reference silhouettes in three views, hand-drawn from typical products and normalised to the bounding
              box (u across, v up, both 0..1). They are class norms, not any one product.
  signature   what must be there for it to read as the class, checked on depth maps (an eye port you can see into,
              a neck opening, a hump behind centre, a split between the buttons ...)

Frame: the product faces +X (its front), Z is up, Y is its width. side = seen from -Y (u = x), front = seen from +X
(u = y), top = seen from +Z (u = x, v = y), bottom = seen from -Z.

Everything here is evidence class "heuristic": a silhouette that matches a class norm is a prompt that the form is in
the right family, never proof that it is good, and the reference outlines are drawings. The agent still has to look
at the views and answer the "reads as" question.
"""
from __future__ import annotations

import math

import numpy as np

EVIDENCE = "heuristic"
RES = 160                                     # pixels across the larger side of a view

# Each outline is a closed polygon in normalised (u, v). Sources are the products these proportions are typical of.
CLASSES = {
    "helmet_fullface": {
        "label": "full-face motorcycle helmet",
        "aliases": ["full-face helmet", "full face helmet", "fullface helmet", "motorcycle helmet", "motorbike helmet",
                    "racing helmet", "moto helmet", "crash helmet"],
        "ratios": {"W/L": (0.74, 0.86), "H/L": (0.84, 0.99)},
        "ratios_source": "typical size M full-face shells: about 310-330 long (chin bar to spoiler) x 245-260 wide x "
                         "280-300 mm high (manufacturer specification sheets); EN 960 headform J inside",
        "outlines": {
            "side": [(0.45, 1.0), (0.66, 0.97), (0.82, 0.89), (0.92, 0.77), (0.97, 0.63), (0.985, 0.50), (0.975, 0.40),
                     (0.995, 0.30), (0.995, 0.17), (0.95, 0.05), (0.88, 0.0), (0.74, 0.03), (0.60, 0.10), (0.46, 0.14),
                     (0.30, 0.15), (0.14, 0.16), (0.04, 0.17), (0.01, 0.24), (0.0, 0.40), (0.01, 0.53), (0.04, 0.66),
                     (0.10, 0.80), (0.20, 0.91), (0.32, 0.98)],
            "front": [(0.5, 1.0), (0.70, 0.975), (0.86, 0.89), (0.955, 0.76), (0.995, 0.62), (1.0, 0.50), (0.985, 0.36),
                      (0.95, 0.22), (0.91, 0.13), (0.82, 0.07), (0.66, 0.02), (0.5, 0.0), (0.34, 0.02), (0.18, 0.07),
                      (0.09, 0.13), (0.05, 0.22), (0.015, 0.36), (0.0, 0.50), (0.005, 0.62), (0.045, 0.76),
                      (0.14, 0.89), (0.30, 0.975)],
            "top": [(1.0, 0.5), (0.97, 0.68), (0.88, 0.84), (0.72, 0.95), (0.50, 1.0), (0.28, 0.97), (0.11, 0.87),
                    (0.02, 0.70), (0.0, 0.5), (0.02, 0.30), (0.11, 0.13), (0.28, 0.03), (0.50, 0.0), (0.72, 0.05),
                    (0.88, 0.16), (0.97, 0.32)],
        },
        "signature": ["eye_port", "visor", "chin_bar", "chin_projects", "neck_opening", "edge_rises_back"],
        "transparent": ["visor", "lens", "glass", "shield"],
    },
    "helmet_open": {
        "label": "cycling / half-shell helmet",
        "aliases": ["bicycle helmet", "cycling helmet", "bike helmet", "half-shell helmet", "half shell helmet",
                    "skate helmet", "climbing helmet"],
        "ratios": {"W/L": (0.68, 0.84), "H/L": (0.50, 0.70)},
        "ratios_source": "typical size M road and urban helmets: about 270-290 x 200-220 x 150-180 mm (manufacturer "
                         "specification sheets)",
        "outlines": {
            "side": [(0.55, 1.0), (0.75, 0.95), (0.90, 0.80), (0.99, 0.58), (1.0, 0.42), (0.86, 0.36), (0.6, 0.22),
                     (0.3, 0.08), (0.08, 0.0), (0.0, 0.10), (0.04, 0.45), (0.15, 0.75), (0.32, 0.93)],
            "front": [(0.5, 1.0), (0.75, 0.95), (0.92, 0.78), (1.0, 0.50), (0.985, 0.15), (0.92, 0.0), (0.5, 0.25),
                      (0.08, 0.0), (0.015, 0.15), (0.0, 0.50), (0.08, 0.78), (0.25, 0.95)],
            "top": [(1.0, 0.5), (0.96, 0.75), (0.80, 0.94), (0.55, 1.0), (0.25, 0.95), (0.06, 0.78), (0.0, 0.5),
                    (0.06, 0.22), (0.25, 0.05), (0.55, 0.0), (0.80, 0.06), (0.96, 0.25)],
        },
        "signature": ["vents_open"],
        "transparent": ["visor", "lens"],
    },
    "mouse": {
        "label": "computer mouse",
        "aliases": ["computer mouse", "mouse shell", "gaming mouse", "ergonomic mouse", "mouse"],
        "ratios": {"W/L": (0.45, 0.70), "H/L": (0.27, 0.42)},
        "ratios_source": "palm-grip mice: Logitech G Pro 125 x 64 x 40, Razer DeathAdder 127 x 62 x 43, Logitech G502 "
                         "132 x 75 x 40, MX Master 3 125 x 84 x 51 mm (manufacturer specification sheets)",
        "outlines": {
            "side": [(0.0, 0.10), (0.0, 0.35), (0.04, 0.60), (0.13, 0.83), (0.26, 0.96), (0.40, 1.0), (0.55, 0.97),
                     (0.70, 0.87), (0.84, 0.72), (0.94, 0.56), (0.99, 0.40), (1.0, 0.22), (0.99, 0.06), (0.96, 0.0),
                     (0.04, 0.0)],
            "front": [(0.0, 0.0), (0.0, 0.30), (0.06, 0.62), (0.20, 0.87), (0.38, 0.99), (0.52, 1.0), (0.70, 0.93),
                      (0.86, 0.75), (0.96, 0.48), (1.0, 0.20), (1.0, 0.0)],
            "top": [(1.0, 0.5), (0.98, 0.78), (0.90, 0.93), (0.70, 0.98), (0.42, 1.0), (0.18, 0.96), (0.04, 0.82),
                    (0.0, 0.5), (0.04, 0.18), (0.18, 0.04), (0.42, 0.0), (0.70, 0.03), (0.90, 0.08), (0.98, 0.22)],
        },
        "signature": ["hump_behind_centre", "flat_base", "button_split", "wheel"],
        "transparent": [],
    },
    "bottle": {
        "label": "bottle",
        "aliases": ["bottle", "water bottle", "drinks bottle", "flask"],
        "ratios": {"W/L": (0.85, 1.18), "H/L": (2.2, 4.2)},
        "ratios_source": "PET drinks bottles 330 ml-1.5 l: diameter 58-90 mm, height 170-320 mm; PCO 1881 neck",
        "outlines": {
            "side": [(0.08, 0.0), (0.92, 0.0), (1.0, 0.04), (1.0, 0.68), (0.88, 0.80), (0.66, 0.89), (0.68, 0.90),
                     (0.66, 0.91), (0.66, 1.0), (0.34, 1.0), (0.34, 0.91), (0.32, 0.90), (0.34, 0.89), (0.12, 0.80),
                     (0.0, 0.68), (0.0, 0.04)],
        },
        "signature": ["neck"],
        "transparent": [],
    },
}


def detect(text: str) -> str | None:
    """The class a brief names (longest alias wins), or None."""
    low = " " + " ".join((text or "").lower().replace("-", " ").split()) + " "
    best, blen = None, 0
    for cid, c in CLASSES.items():
        for a in c["aliases"]:
            a2 = " " + a.replace("-", " ") + " "
            if a2 in low and len(a2) > blen:
                best, blen = cid, len(a2)
    return best


# ---- views ---------------------------------------------------------------------------------------------------------

_AXES = {"side": (0, 2, 1, -1), "front": (1, 2, 0, +1), "top": (0, 1, 2, +1), "bottom": (0, 1, 2, -1)}
# view: (u axis, v axis, depth axis, which side the eye is on: +1 looks from +depth toward -depth)


def _raster(tris2d, box, shape):
    from PIL import Image, ImageDraw
    (u0, v0), (u1, v1) = box
    h, w = shape
    img = Image.new("1", (w, h), 0)
    d = ImageDraw.Draw(img)
    su, sv = (w - 1) / max(u1 - u0, 1e-9), (h - 1) / max(v1 - v0, 1e-9)
    for t in tris2d:
        d.polygon([((x - u0) * su, (h - 1) - (y - v0) * sv) for x, y in t], fill=1)
    return np.array(img, dtype=bool)


def views(P: np.ndarray, T: np.ndarray, keep: np.ndarray | None = None, res: int = RES, density: float = 10.0,
          max_samples: int = 3_000_000, seed: int = 3) -> dict:
    """Silhouette masks and depth maps of a triangle mesh in the side, front, top and bottom views.
    keep: a boolean per triangle (False for transparent parts such as a visor: they are left out of the depth maps
    but kept in the silhouettes). Depth is a z-buffer of points sampled on every kept triangle in proportion to its
    projected area (density samples per pixel), so every pixel a surface covers gets a depth. Returns {view: {"mask",
    "depth" (nan where empty), "box": ((u0, v0), (u1, v1)), "mm_per_px"}, "bbox": (lo, hi)} with row 0 at the top."""
    P = np.asarray(P, float)
    T = np.asarray(T, int)
    lo, hi = P.min(0), P.max(0)
    k = np.ones(len(T), bool) if keep is None else np.asarray(keep, bool)
    rng = np.random.default_rng(seed)
    tri = P[T]                                                # (m, 3, 3)
    out = {}
    for name, (ui, vi, di, eye) in _AXES.items():
        du, dv = hi[ui] - lo[ui], hi[vi] - lo[vi]
        mm = max(du, dv) / (res - 1)
        w_, h_ = int(round(du / mm)) + 1, int(round(dv / mm)) + 1
        box = ((lo[ui], lo[vi]), (lo[ui] + (w_ - 1) * mm, lo[vi] + (h_ - 1) * mm))
        mask = _raster(np.stack([tri[:, :, ui], tri[:, :, vi]], -1), box, (h_, w_))
        depth = np.full((h_, w_), np.nan)
        kt = tri[k]
        if len(kt):
            e1, e2 = kt[:, 1] - kt[:, 0], kt[:, 2] - kt[:, 0]
            apx = np.abs(e1[:, ui] * e2[:, vi] - e1[:, vi] * e2[:, ui]) / 2 / (mm * mm)
            n = np.ceil(apx * density).astype(int) + 1
            if n.sum() > max_samples:
                n = np.maximum(1, (n * max_samples / n.sum()).astype(int))
            idx = np.repeat(np.arange(len(kt)), n)
            r1, r2 = rng.random(len(idx)), rng.random(len(idx))
            sq = np.sqrt(r1)
            S = ((1 - sq)[:, None] * kt[idx, 0] + (sq * (1 - r2))[:, None] * kt[idx, 1] + (sq * r2)[:, None] * kt[idx, 2])
            S = np.concatenate([S, kt.reshape(-1, 3)])
            cu = np.clip(np.round((S[:, ui] - lo[ui]) / mm).astype(int), 0, w_ - 1)
            cv = np.clip((h_ - 1) - np.round((S[:, vi] - lo[vi]) / mm).astype(int), 0, h_ - 1)
            best = np.full(h_ * w_, -np.inf)
            np.maximum.at(best, cv * w_ + cu, S[:, di] * eye)    # larger = nearer the eye
            best = best.reshape(h_, w_)
            depth = np.where(np.isinf(best), np.nan, best * eye)
        out[name] = {"mask": mask, "depth": depth, "box": box, "mm_per_px": mm, "eye": eye, "depth_axis": di}
    out["bbox"] = (lo.tolist(), hi.tolist())
    return out


# ---- profiles and comparison ----------------------------------------------------------------------------------------

def _poly_mask(poly, shape):
    from PIL import Image, ImageDraw
    h, w = shape
    img = Image.new("1", (w, h), 0)
    ImageDraw.Draw(img).polygon([(u * (w - 1), (h - 1) - v * (h - 1)) for u, v in poly], fill=1)
    return np.array(img, dtype=bool)


def profiles(mask: np.ndarray, n: int = 48) -> dict:
    """The silhouette's four edges as functions on 0..1, normalised to the mask's own extent:
    top(u), bottom(u) (v of the highest and lowest filled pixel in each column) and right(v), left(v) (u of the
    outermost pixels in each row). nan where a column or row is empty."""
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return {}
    m = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    h, w = m.shape
    out = {}
    cols = np.linspace(0, w - 1, n).round().astype(int)
    rows = np.linspace(0, h - 1, n).round().astype(int)
    top, bot, right, left = [], [], [], []
    for c in cols:
        r = np.nonzero(m[:, c])[0]
        top.append(1 - r.min() / max(h - 1, 1) if len(r) else np.nan)
        bot.append(1 - r.max() / max(h - 1, 1) if len(r) else np.nan)
    for rr in rows[::-1]:                                   # v from 0 (bottom) up
        cc = np.nonzero(m[rr, :])[0]
        right.append(cc.max() / max(w - 1, 1) if len(cc) else np.nan)
        left.append(cc.min() / max(w - 1, 1) if len(cc) else np.nan)
    out.update(top=np.array(top), bottom=np.array(bot), right=np.array(right), left=np.array(left))
    return out


def kinks(prof: dict, deg: float = 40.0) -> list:
    """Where a silhouette edge turns sharply (curvature discontinuity): [(edge, position 0..1, turn in degrees)].
    Measured on the normalised profile functions after a light smoothing; the two ends of each edge are skipped
    (corners where edges meet are expected)."""
    out = []
    for name, f in prof.items():
        y = np.asarray(f, float)
        ok = ~np.isnan(y)
        if ok.sum() < 8:
            continue
        x = np.linspace(0, 1, len(y))[ok]
        y = np.convolve(y[ok], np.ones(3) / 3, mode="same")
        ang = np.degrees(np.arctan2(np.diff(y), np.diff(x)))
        turn = np.abs(np.diff(ang))
        for i in np.nonzero(turn[2:-2] > deg)[0] + 2:
            out.append((name, round(float(x[i + 1]), 2), round(float(turn[i]), 1)))
    return out


def compare(mask: np.ndarray, outline) -> dict:
    """A silhouette against a class outline, both normalised to their own bounding boxes: IoU and the mean distance
    between the four edge profiles (in units of the box, 0.03 = 3 % of the size)."""
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return {"iou": 0.0, "profile_dev": 1.0}
    m = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    ref = _poly_mask(outline, m.shape)
    iou = float((m & ref).sum() / max((m | ref).sum(), 1))
    pa, pb = profiles(m), profiles(ref)
    devs = []
    for k in ("top", "bottom", "right", "left"):
        a, b = pa.get(k), pb.get(k)
        if a is None or b is None:
            continue
        ok = ~(np.isnan(a) | np.isnan(b))
        if ok.any():
            devs.append(float(np.abs(a[ok] - b[ok]).mean()))
    return {"iou": round(iou, 3), "profile_dev": round(float(np.mean(devs)) if devs else 1.0, 4)}


def mirror_match(mask: np.ndarray) -> float:
    """IoU of a silhouette with its own mirror image (left-right): 1.0 for a symmetric front view."""
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return 0.0
    m = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    return round(float((m & m[:, ::-1]).sum() / max((m | m[:, ::-1]).sum(), 1)), 3)


# ---- signature checks ------------------------------------------------------------------------------------------------

def _band(img, v0, v1, u0=0.0, u1=1.0):
    h, w = img.shape
    r0, r1 = int((1 - v1) * (h - 1)), int((1 - v0) * (h - 1)) + 1
    c0, c1 = int(u0 * (w - 1)), int(u1 * (w - 1)) + 1
    return img[r0:r1, c0:c1]


def signature(cid: str, V: dict, features: dict | None = None) -> list[dict]:
    """The class's signature checks on the views: [{id, ok, value, want, why}]. features: {feature id: area} of the
    design (some checks look for a part by name, such as a visor)."""
    feats = {k.lower(): v for k, v in (features or {}).items()}
    lo, hi = np.array(V["bbox"][0]), np.array(V["bbox"][1])
    L, W, H = hi - lo
    out = []

    def add(i, ok, value, want, why):
        out.append({"id": i, "ok": bool(ok), "value": value, "want": want, "why": why})

    for sid in CLASSES[cid]["signature"]:
        if sid == "eye_port":
            f = V["front"]
            d = f["depth"]
            deep = (d < hi[0] - 0.35 * L) | (f["mask"] & np.isnan(d))   # you see into the helmet (or through it, past
            # a transparent visor)
            band = _band(deep, 0.30, 0.80)
            cols = band.any(0)
            rows = band.any(1)
            wf = cols.sum() / max(f["mask"].shape[1], 1)
            hf = rows.sum() / max(f["mask"].shape[0], 1)
            add("eye_port", wf >= 0.40 and hf >= 0.10, {"width": round(float(wf), 2), "height": round(float(hf), 2)},
                "an opening you can see into, >= 40 % of the width and >= 10 % of the height, between 30 and 80 % up "
                "(the visor is left out as transparent)", "Seen from the front with the visor clear: is there an eye port?")
        elif sid == "visor":
            names = [k for k in feats if any(w in k for w in CLASSES[cid]["transparent"])]
            add("visor", bool(names), names[:3], "a visor (or shield, lens) feature over the eye port",
                "Real full-face helmets are seen with the visor on; without it the port is a hole.")
        elif sid == "chin_projects":
            p = profiles(V["side"]["mask"])
            r = p.get("right", np.array([np.nan]))
            n = len(r)
            chin = np.nanmax(r[int(0.08 * n):int(0.32 * n)]) if n else np.nan
            face = np.nanmax(r[int(0.40 * n):int(0.65 * n)]) if n else np.nan
            d = float(chin - face) if np.isfinite(chin) and np.isfinite(face) else -1.0
            add("chin_projects", d >= -0.005, round(d, 3), "the chin bar reaches at least as far forward as the face "
                "(side view, normalised)", "The chin bar is the most forward mass of a full-face helmet.")
        elif sid == "wheel":
            t = V["top"]
            d = t["depth"]
            h_, w_ = d.shape
            strip = d[int(0.46 * h_):int(0.54 * h_) + 1, int(0.55 * w_):int(0.95 * w_)]
            if strip.size:
                hole = ((strip < lo[2] + 0.45 * H) | np.isnan(strip)).all(axis=0)   # deep across the whole strip
                run = best = 0
                for x in hole:
                    run = run + 1 if x else 0
                    best = max(best, run)
                gap = best * t["mm_per_px"]
            else:
                gap = L
            add("wheel", gap < 0.06 * L, round(float(gap), 1), "no opening longer than 6 % of the length along the "
                "front centre line seen from above: a scroll wheel fills its slot (mm of the longest empty run)",
                "A mouse has a wheel between the buttons; an empty opening reads as a hole.")
        elif sid == "chin_bar":
            f = V["front"]
            d = f["depth"]
            band = _band(d, 0.06, 0.28, 0.35, 0.65)
            solid = np.nanmean(band >= hi[0] - 0.2 * L) if np.isfinite(band).any() else 0.0
            add("chin_bar", solid >= 0.6, round(float(solid), 2), ">= 60 % of the lower front centre is near the front",
                "A full-face helmet closes in front of the chin.")
        elif sid == "neck_opening":
            b = V["bottom"]
            d = b["depth"]
            inside = (d > lo[2] + 0.35 * H) | (b["mask"] & np.isnan(d))
            frac = inside.sum() / max(b["mask"].sum(), 1)
            add("neck_opening", frac >= 0.20, round(float(frac), 2), ">= 20 % of the footprint opens up into the shell",
                "Seen from below: is there a neck opening?")
        elif sid == "edge_rises_back":
            p = profiles(V["side"]["mask"])
            bot = p.get("bottom", np.array([np.nan]))
            n = len(bot)
            back = np.nanmean(bot[: max(2, n // 6)])
            front = np.nanmin(bot[n // 2:]) if n > 2 else np.nan
            rise = float(back - front) if np.isfinite(back) and np.isfinite(front) else 0.0
            add("edge_rises_back", rise >= 0.07, round(rise, 3), "the lower edge at the back >= 7 % of the height above "
                "the chin's", "A helmet's lower line rises from the chin to the nape.")
        elif sid == "vents_open":
            t = V["top"]
            d = t["depth"]
            holes = (d < hi[2] - 0.5 * H) & t["mask"]
            from scipy import ndimage
            lab, nlab = ndimage.label(holes)
            sizes = ndimage.sum(holes, lab, range(1, nlab + 1)) if nlab else []
            nv = int(sum(1 for s in sizes if s >= 6))
            add("vents_open", nv >= 4, nv, ">= 4 vents you can see through from above", "Cycling helmets breathe.")
        elif sid == "hump_behind_centre":
            p = profiles(V["side"]["mask"])
            top = p.get("top", np.array([np.nan]))
            u = float(np.nanargmax(top) / max(len(top) - 1, 1)) if np.isfinite(top).any() else 0.0
            add("hump_behind_centre", 0.22 <= u <= 0.55, round(u, 2), "the highest point 22-55 % of the length from "
                "the back", "The palm hump sits behind the centre; the buttons slope down to the nose.")
        elif sid == "flat_base":
            p = profiles(V["side"]["mask"])
            bot = p.get("bottom", np.array([np.nan]))
            flat = float(np.nanmean(bot < 0.04)) if np.isfinite(bot).any() else 0.0
            add("flat_base", flat >= 0.75, round(flat, 2), ">= 75 % of the length sits on the base plane",
                "A mouse glides on a flat base.")
        elif sid == "button_split":
            t = V["top"]
            d = t["depth"]
            h_, w_ = d.shape
            rows = slice(int(0.25 * h_), int(0.75 * h_))
            seg = d[rows, int(0.62 * w_):int(0.95 * w_)]
            if seg.size and np.isfinite(seg).any():
                med = np.nanmedian(seg, axis=0)
                groove = (seg < med - max(1.0, 0.03 * H)) | (t["mask"][rows, int(0.62 * w_):int(0.95 * w_)] & np.isnan(seg))
                frac = float(groove.any(0).mean())
            else:
                frac = 0.0
            add("button_split", frac >= 0.5, round(frac, 2), "a split or groove across >= 50 % of the front third, "
                "seen from above", "Two primary buttons are separated by a visible split.")
        elif sid == "neck":
            p = profiles(V["side"]["mask"])
            top = p.get("right", np.array([np.nan])) - p.get("left", np.array([np.nan]))
            n = len(top)
            ratio = float(np.nanmean(top[-max(2, n // 10):]) / max(np.nanmax(top), 1e-9)) if n else 1.0
            add("neck", ratio <= 0.55, round(ratio, 2), "the top 10 % no wider than 55 % of the body",
                "A bottle narrows to a neck.")
    return out


def assess(cid: str, V: dict, features: dict | None = None) -> dict:
    """Everything critique reports for a class: per-view outline comparison, proportions against the class range,
    silhouette symmetry, curvature kinks, signature checks and one score 0..1 (half outline, a quarter proportions,
    a quarter signature). The outline deviation weighs the side view 0.5, the front 0.3, the top 0.2."""
    c = CLASSES[cid]
    lo, hi = np.array(V["bbox"][0]), np.array(V["bbox"][1])
    L, W, H = hi - lo
    vals = {"W/L": W / L, "H/L": H / L}
    ratios = []
    for k, (a, b) in c["ratios"].items():
        x = vals[k]
        off = 0.0 if a <= x <= b else min(abs(x - a), abs(x - b)) / ((a + b) / 2)
        ratios.append({"ratio": k, "value": round(float(x), 3), "range": [a, b], "ok": off == 0.0,
                       "off_pct": round(100 * off, 1)})
    per_view = {}
    for vn, outline in c["outlines"].items():
        cmp_ = compare(V[vn]["mask"], outline)
        cmp_["kinks"] = kinks(profiles(V[vn]["mask"]))[:6]
        per_view[vn] = cmp_
    wts = {"side": 0.5, "front": 0.3, "top": 0.2}               # the side view is the most telling
    tot = sum(wts.get(k, 0.2) for k in per_view) or 1.0
    dev = sum(v["profile_dev"] * wts.get(k, 0.2) for k, v in per_view.items()) / tot if per_view else 1.0
    outline_score = max(0.0, min(1.0, (0.07 - dev) / 0.045))     # 2.5 % or closer = 1, 7 % or further = 0
    sig = signature(cid, V, features)
    ratio_score = sum(1.0 if r["ok"] else max(0.0, 1 - r["off_pct"] / 15) for r in ratios) / max(len(ratios), 1)
    sig_score = sum(s["ok"] for s in sig) / max(len(sig), 1) if sig else 1.0
    score = 0.5 * outline_score + 0.25 * ratio_score + 0.25 * sig_score
    return {"class": cid, "label": c["label"], "views": per_view, "profile_dev": round(dev, 4),
            "ratios": ratios, "ratios_source": c["ratios_source"], "signature": sig,
            "front_mirror": mirror_match(V["front"]["mask"]),
            "score": round(score, 3), "parts": {"outline": round(outline_score, 3), "ratios": round(ratio_score, 3),
                                                "signature": round(sig_score, 3)},
            "evidence": EVIDENCE}
