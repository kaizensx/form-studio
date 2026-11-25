"""The deficit vector: what a built design lacks, as numbers from 0 (nothing to improve) to 1 (as bad as it gets).

    from form.refine import analyze
    a = analyze.analyze(analyze.Measurement(P, T, tri_feature=..., metrics=..., zones=..., purpose="model"))
    a.deficits      # {"silhouette": 0.62, "edge_hierarchy": 0.4, ...}
    a.total         # weighted mean: the search objective

Pure numpy (scipy for hulls and labels, both build123d dependencies); no OCCT, so it runs in the engine process on
the tessellation and the critique metrics the kernel already returns. Every measure is deterministic: fixed views,
fixed seeds, no clock. Every threshold is a proposal (evidence class "heuristic"); the numbers are computed.

  silhouette         solidity (area over convex hull) of the outline at 64 px in six views; the convexity deficit
                     1 - solidity, averaged. Under 0.06 the outline reads as a blob, over 0.45 as shredded.
  interior_read      a 64 px lit render (three-quarter view, one key light, five value bands): value regions of at
                     least 12 px inside the outline. Six or more read.
  proportion         the two bounding ratios (long:mid, mid:short) against the classic ratios of critique.RATIOS.
  balance            the centre of mass (volume centroid of the closed mesh) over the support polygon (convex hull of
                     the points within 1 % of the height of the lowest), and the best mirror match of the front and
                     side outlines (product_classes.mirror_match).
  detail_scales      feature sizes (each feature's bounding diagonal and twice each blend radius) in three bands of
                     the design's diagonal: primary >= 25 %, secondary 4-25 %, tertiary < 4 %.
  edge_hierarchy     radius tiers (critique.radius_tiers) and the sharp-crease share of edge length; for a game
                     asset the bevel coverage of LOD0 (critique.edge_treatment).
  surface_breaks     the largest patch of triangles whose neighbours turn by under 2 degrees, as a share of the area
                     (or of the bounding box's surface when that is larger, so a fillet does not count against it).
  material_zones     distinct looks (appearance zones, or the game asset's materials).
  material_contrast  luminance spread between the zones' colours (or the baked base colour's value contrast).
  wear               (game) worn share on convex edges, from the baked mask; 2-12 % is the target band.
  touch_points       share of surface samples in the grip zone (the product class's, else the whole part) that lie
                     within reach of a sharp edge; the edges of grip textures and grooves do not count.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from . import DEFICITS, Analysis

PX = 64
VIEWS6 = {"front": (0.0, 0.0), "back": (180.0, 0.0), "left": (-90.0, 0.0), "right": (90.0, 0.0),
          "top": (0.0, 90.0), "three_quarter": (35.0, 25.0)}
SIL_BLOB, SIL_SHRED = 0.06, 0.45
SIL_FLAT_VIEW = 0.02              # a view whose convexity deficit is under this reads as a plain slab or disc
DETAIL_DENSITY = 8.0              # game: feature-edge length (in diagonals of the asset) for a full secondary breakup
READ_REGIONS, READ_MIN_PX, READ_BANDS = 6, 12, 5
FLAT_DEG = 2.0
SHARP_DEG = 25.0
WEAR_BAND = (0.02, 0.12)
WEIGHTS = {"silhouette": 1.5, "interior_read": 1.0, "proportion": 0.6, "balance": 0.6, "detail_scales": 1.0,
           "edge_hierarchy": 1.2, "surface_breaks": 0.8, "material_zones": 0.8, "material_contrast": 0.6,
           "wear": 0.6, "touch_points": 0.8}
# grip zones: where a hand goes on a product class, as bands of the normalised height (0 bottom, 1 top)
GRIP = {"mouse": (0.35, 1.0), "bottle": (0.2, 0.75), "helmet_fullface": None, "helmet_open": None}


@dataclass
class Measurement:
    """What the analysis reads: the tessellation and what the kernel measured."""
    P: np.ndarray
    T: np.ndarray
    tri_feature: list | np.ndarray | None = None      # feature id per triangle
    metrics: dict | None = None                       # critique.op_critique_metrics()
    zones: list | None = None                         # appearance() zones [{"features", "color", "finish"}]
    game: dict | None = None                          # critique.game_evidence() of the built asset
    purpose: str = "model"
    product_class: str | None = None
    extra: dict = field(default_factory=dict)


def _clip(x: float) -> float:
    return float(min(1.0, max(0.0, x)))


def _rot(az: float, el: float) -> np.ndarray:
    a, e = math.radians(az), math.radians(el)
    right = np.array([math.cos(a), math.sin(a), 0.0])
    fwd = np.array([-math.sin(a) * math.cos(e), math.cos(a) * math.cos(e), -math.sin(e)])
    up = np.cross(right, fwd)
    return np.array([right, up, fwd])


def _frame(P):
    c = (P.max(0) + P.min(0)) / 2
    r = float(np.linalg.norm(P - c, axis=1).max()) or 1.0
    return c, r


def masks(P, T, px: int = PX, views=None) -> dict:
    """{view: boolean mask (px, px)} at one scale (form.game.validate.rasterise, vectorised)."""
    from ..game.validate import rasterise
    P, T = np.asarray(P, float), np.asarray(T, np.int64)
    c, r = _frame(P)
    out = {}
    for name, (az, el) in (views or VIEWS6).items():
        q = (P - c) @ _rot(az, el)[:2].T
        Q = (q / (2.1 * r) + 0.5) * px
        out[name] = rasterise(Q, T, px)
    return out


def silhouette(P, T, worst_view: bool = False) -> dict:
    from ..critique import solidity
    M = masks(P, T)
    sol = {k: round(solidity(m), 4) for k, m in M.items()}
    cx = float(np.mean([1 - s for s in sol.values()]))
    d = _clip(1 - cx / SIL_BLOB) if cx < SIL_BLOB else _clip((cx - SIL_SHRED) / 0.3)
    # the worst view counts too: a slab or a disc reads as a plain shape from the side it is seen most, however
    # broken the other views are (half weight: a part may have one plain view by nature)
    worst = float(min(1 - s for s in sol.values()))
    if worst_view and worst < SIL_FLAT_VIEW and cx < SIL_SHRED:
        d = max(d, 0.5 * _clip(1 - worst / SIL_FLAT_VIEW))
    return {"deficit": d, "solidity": sol, "convexity_deficit": round(cx, 4), "worst_view": round(worst, 4),
            "masks": M}


def _tri_normals(P, T):
    n = np.cross(P[T[:, 1]] - P[T[:, 0]], P[T[:, 2]] - P[T[:, 0]])
    ln = np.linalg.norm(n, axis=1)
    return n / np.maximum(ln, 1e-12)[:, None], ln / 2


def interior_read(P, T, px: int = PX, albedo=None) -> dict:
    """Value regions of a small lit render (three-quarter view), by z-buffered surface samples. albedo(k, bary): the
    surface's own value (0..1) at samples on triangles k (a baked base colour); without it the surface is one grey,
    so only the shading reads."""
    from scipy import ndimage
    from ..critique import _area_samples
    P, T = np.asarray(P, float), np.asarray(T, np.int64)
    N, _area = _tri_normals(P, T)
    n = int(min(400_000, max(60_000, 40 * px * px)))
    bary, k = _area_samples(P, T, n, seed=11)
    S = (P[T[k]] * bary[:, :, None]).sum(1)
    R = _rot(*VIEWS6["three_quarter"])
    c, r = _frame(P)
    q = (S - c) @ R.T
    ix = np.clip(((q[:, 0] / (2.1 * r) + 0.5) * px).astype(int), 0, px - 1)
    iy = np.clip(((q[:, 1] / (2.1 * r) + 0.5) * px).astype(int), 0, px - 1)
    pix = iy * px + ix
    order = np.lexsort((q[:, 2], pix))                     # per pixel, nearest to the eye first (fwd points in)
    pix_s = pix[order]
    first = np.r_[True, pix_s[1:] != pix_s[:-1]]
    win = order[first]
    light = np.array([-0.45, -0.55, 0.70])
    light /= np.linalg.norm(light)
    nrm = N[k[win]]
    view = -R[2]
    nrm = np.where((nrm @ view)[:, None] < 0, -nrm, nrm)    # the side that faces the eye
    shade = 0.25 + 0.75 * np.clip(nrm @ light, 0, 1)
    if albedo is not None:                                 # value = albedo x light, stretched back to 0..1
        alb = np.clip(np.asarray(albedo(k[win], bary[win]), float), 0.0, 1.0)
        shade = shade * (0.15 + 0.85 * alb)
        shade = shade / max(float(shade.max()), 1e-6)
    img = np.full(px * px, np.nan)
    img[pix[win]] = shade
    img = img.reshape(px, px)
    mask = masks(P, T, px, {"three_quarter": VIEWS6["three_quarter"]})["three_quarter"]
    have = ~np.isnan(img)
    if have.any():                                         # pixels of the outline no sample landed in: nearest value
        _d, (yy, xx) = ndimage.distance_transform_edt(~have, return_indices=True)
        img = img[yy, xx]
    band = np.minimum((img * READ_BANDS).astype(int), READ_BANDS - 1)
    regions = 0
    for b in range(READ_BANDS):
        lab, m = ndimage.label(mask & (band == b))
        if m:
            sizes = np.bincount(lab.ravel())[1:]
            regions += int((sizes >= READ_MIN_PX).sum())
    return {"deficit": _clip(1 - (regions - 1) / (READ_REGIONS - 1)), "regions": regions}


def proportion(P) -> dict:
    from ..critique import RATIOS
    lo, hi = np.asarray(P).min(0), np.asarray(P).max(0)
    dims = sorted((hi - lo).tolist(), reverse=True)
    rows = []
    for big, small, label in ((dims[0], dims[1], "long:mid"), (dims[1], dims[2], "mid:short")):
        if small > 1e-6:
            r = big / small
            name, val = min(RATIOS.items(), key=lambda kv: abs(math.log(r / kv[1])))
            rows.append({"pair": label, "ratio": round(r, 3), "nearest": name, "off_pct": round(100 * abs(r / val - 1), 1)})
    d = float(np.mean([_clip((x["off_pct"] - 4) / 20) for x in rows])) if rows else 0.0
    return {"deficit": d, "ratios": rows, "bbox_mm": [round(x, 2) for x in (hi - lo).tolist()]}


def _hull2(pts):
    from scipy.spatial import ConvexHull
    pts = np.unique(np.round(pts, 6), axis=0)
    if len(pts) >= 3:
        try:
            h = ConvexHull(pts)
            return pts[h.vertices]
        except Exception:                                  # noqa: BLE001 - collinear support (a knife edge)
            pass
    return None


def _inside_margin(poly, p) -> float:
    """Signed distance of p to the edges of a convex polygon (counter-clockwise): > 0 inside."""
    best = math.inf
    for i in range(len(poly)):
        a, b = poly[i], poly[(i + 1) % len(poly)]
        e = b - a
        ln = float(np.linalg.norm(e)) or 1e-12
        best = min(best, float((e[0] * (p[1] - a[1]) - e[1] * (p[0] - a[0])) / ln))
    return best


def balance(P, T, M: dict | None = None) -> dict:
    from ..product_classes import mirror_match
    P, T = np.asarray(P, float), np.asarray(T, np.int64)
    a, b, c = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
    v6 = np.einsum("ij,ij->i", a, np.cross(b, c))
    vol = float(v6.sum())
    if abs(vol) > 1e-9:
        com = ((a + b + c) * v6[:, None]).sum(0) / (4 * vol)
    else:
        _n, ar = _tri_normals(P, T)
        com = ((a + b + c) / 3 * ar[:, None]).sum(0) / max(ar.sum(), 1e-12)
    zmin, zmax = float(P[:, 2].min()), float(P[:, 2].max())
    foot = P[P[:, 2] <= zmin + 0.01 * max(zmax - zmin, 1e-6)][:, :2]
    poly = _hull2(foot)
    if poly is None:
        support, margin = 1.0, None
    else:
        half = 0.5 * float(min(np.ptp(poly[:, 0]), np.ptp(poly[:, 1])) or 1e-6)
        margin = _inside_margin(poly, com[:2]) / half
        support = 1.0 if margin < 0 else _clip(1 - margin / 0.3)
    M = M or masks(P, T)
    mirror = max(mirror_match(M["front"]), mirror_match(M["left"]))
    return {"deficit": _clip(0.7 * support + 0.3 * (1 - mirror)), "support": round(support, 4),
            "margin": None if margin is None else round(margin, 4), "mirror": round(mirror, 4),
            "com": [round(float(x), 3) for x in com]}


def detail_scales(P, T, tri_feature=None, metrics=None, game=None) -> dict:
    if game and (game.get("scales") or {}).get("count") is not None:
        n = int(game["scales"]["count"])
        d = _clip((3 - n) / 2)
        fed = game["scales"].get("feature_edge_diagonals")
        if fed is not None:          # the secondary breakup's density: a few panel lines on a big shell read as sparse
            d = max(d, 0.6 * _clip(1 - float(fed) / DETAIL_DENSITY))
        return {"deficit": d, "bands": n, "density": fed, "from": "game asset"}
    P = np.asarray(P, float)
    diag = float(np.linalg.norm(P.max(0) - P.min(0))) or 1.0
    sizes = []
    feats = (metrics or {}).get("features") or {}
    if feats:
        sizes += [float(np.linalg.norm(np.asarray(f["hi"]) - np.asarray(f["lo"]))) for f in feats.values()]
    elif tri_feature is not None and len(tri_feature) == len(T):
        tf = np.asarray(tri_feature)
        for name in sorted(set(tf.tolist())):
            Q = P[np.asarray(T)[tf == name].ravel()]
            sizes.append(float(np.linalg.norm(Q.max(0) - Q.min(0))))
    sizes += [2 * float(r) for r in (metrics or {}).get("fillet_radii") or []]
    if not sizes:
        sizes = [diag]
    bands = {"primary": any(s >= 0.25 * diag for s in sizes),
             "secondary": any(0.04 * diag <= s < 0.25 * diag for s in sizes),
             "tertiary": any(0 < s < 0.04 * diag for s in sizes)}
    n = sum(bands.values())
    return {"deficit": _clip((3 - n) / 2), "bands": n, **bands, "sizes": len(sizes)}


def _edge_table(P, T):
    """(length, dihedral degrees) of every interior edge of the welded mesh."""
    from ..critique import _weld
    P, T = np.asarray(P, float), np.asarray(T, np.int64)
    W = _weld(P, T)
    N, _ = _tri_normals(P, T)
    E = np.concatenate([W[:, [0, 1]], W[:, [1, 2]], W[:, [2, 0]]])
    raw = np.concatenate([T[:, [0, 1]], T[:, [1, 2]], T[:, [2, 0]]])
    tri = np.tile(np.arange(len(T)), 3)
    E = np.sort(E, axis=1)
    order = np.lexsort((E[:, 1], E[:, 0]))
    E, tri, raw = E[order], tri[order], raw[order]
    same = np.all(E[1:] == E[:-1], axis=1)
    i = np.nonzero(same)[0]
    i = i[~np.isin(i, i + 1)] if len(i) else i            # exactly the first of each pair (skip triple edges)
    cos = np.clip(np.einsum("ij,ij->i", N[tri[i]], N[tri[i + 1]]), -1, 1)
    L = np.linalg.norm(P[raw[i, 0]] - P[raw[i, 1]], axis=1)
    return L, np.degrees(np.arccos(cos)), tri[i], tri[i + 1]


def edge_hierarchy(P, T, metrics=None, game=None) -> dict:
    from ..critique import radius_tiers
    if game and game.get("edges"):
        cov = float(game["edges"]["coverage"])
        return {"deficit": _clip(1 - cov / 0.75), "coverage": cov, "from": "game asset"}
    m = metrics or {}
    tiers = m.get("radius_tiers")
    if tiers is None:
        tiers = radius_tiers(m.get("fillet_radii") or [])
    sharp = m.get("sharp_edge_fraction")
    if sharp is None:
        L, ang, _a, _b = _edge_table(P, T)
        turn = L[ang > 1.0].sum()
        sharp = float(L[ang > SHARP_DEG].sum() / turn) if turn > 0 else 0.0
    d = 0.6 * (1 - min(int(tiers), 3) / 3) + 0.4 * _clip((float(sharp) - 0.15) / 0.45)
    return {"deficit": _clip(d), "tiers": int(tiers), "sharp_fraction": round(float(sharp), 4)}


def surface_breaks(P, T) -> dict:
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    P, T = np.asarray(P, float), np.asarray(T, np.int64)
    _N, area = _tri_normals(P, T)
    _L, ang, a, b = _edge_table(P, T)
    keep = ang < FLAT_DEG
    g = coo_matrix((np.ones(int(keep.sum())), (a[keep], b[keep])), shape=(len(T), len(T)))
    _n, lab = connected_components(g, directed=False)
    # the share is of the larger of the surface area and the bounding box's surface: a fillet replaces flat area with
    # a blend (a break in its own right), so on the actual area alone the faces left would seem to grow
    ext = P.max(0) - P.min(0)
    box = 2 * float(ext[0] * ext[1] + ext[1] * ext[2] + ext[0] * ext[2])
    share = float(np.bincount(lab, weights=area).max() / max(area.sum(), box, 1e-12))
    return {"deficit": _clip((share - 0.15) / 0.35), "largest_share": round(share, 4)}


def _lum(hexcol) -> float | None:
    s = str(hexcol or "").strip().lstrip("#")
    if len(s) != 6:
        return None
    try:
        rgb = [int(s[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    except ValueError:
        return None
    lin = [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def materials(zones=None, metrics=None, game=None) -> tuple[dict, dict]:
    if game and game.get("materials"):
        n = int(game["materials"]["count"])
        vc = game.get("value_contrast")
    else:
        zs = zones or []
        looks = {(z.get("finish"), str(z.get("color", "")).lower()) for z in zs}
        covered = {f for z in zs for f in z.get("features", [])}
        feats = set(((metrics or {}).get("features") or {}).keys())
        n = len(looks) + (1 if (feats - covered or not zs) else 0)
        lums = [x for x in (_lum(z.get("color")) for z in zs) if x is not None]
        vc = (max(lums) - min(lums)) if len(lums) >= 2 else 0.0
    zd = {1: 1.0, 2: 0.4}.get(n, 0.0 if n >= 3 else 1.0)
    cd = 1.0 if vc is None else _clip(1 - float(vc) / 0.15)
    return ({"deficit": zd, "count": n}, {"deficit": cd, "contrast": None if vc is None else round(float(vc), 4)})


def wear(game=None) -> dict | None:
    if not game or not game.get("wear"):
        return None
    w = game["wear"]
    s = float(w.get("worn_share", w.get("edge_mask_share")) or 0.0)
    lo, hi = WEAR_BAND
    d = _clip((lo - s) / lo) if s < lo else (_clip((s - hi) / hi) if s > hi else 0.0)
    return {"deficit": d, "share": round(s, 4)}


TEXTURE_WORDS = ("knurl", "grip", "textur", "groove", "flute", "parting", "shadow_gap", "shadow gap", "ridge",
                 "emboss", "engrave", "rib")


def texture_features(features: dict) -> set:
    """Feature ids whose id or label names a grip texture or a groove (knurl, grip, texture, groove, flute, parting
    line, shadow gap, ridge, emboss, engrave, rib); features: {id: {"label", ...}}."""
    out = set()
    for k, f in (features or {}).items():
        text = (str(k) + " " + str((f or {}).get("label", ""))).lower()
        if any(w in text for w in TEXTURE_WORDS):
            out.add(k)
    return out


def _texture_tris(tri_feature, T, features) -> np.ndarray | None:
    if tri_feature is None or len(tri_feature) != len(T) or not features:
        return None
    tf = np.asarray(tri_feature)
    hit = [f for f in set(tf.tolist()) if f in features]
    return np.isin(tf, hit) if hit else None


def touch_points(P, T, product_class=None, tri_feature=None, texture=None) -> dict | None:
    """texture: feature ids whose edges are made to be felt (a knurl, a groove): their triangles' edges do not count."""
    from ..critique import _near_sharp_edges, _samples
    if product_class in GRIP and GRIP[product_class] is None:
        return None                                       # worn, not held: no grip zone
    P, T = np.asarray(P, float), np.asarray(T, np.int64)
    ignore = _texture_tris(tri_feature, T, texture)
    S = _samples(P, T, 3000, seed=4)
    z0, z1 = float(P[:, 2].min()), float(P[:, 2].max())
    band = GRIP.get(product_class or "", (0.0, 1.0))
    h = (S[:, 2] - z0) / max(z1 - z0, 1e-9)
    S = S[(h >= band[0]) & (h <= band[1])]
    if not len(S):
        return {"deficit": 0.0, "share": 0.0, "zone": band}
    diag = float(np.linalg.norm(P.max(0) - P.min(0)))
    near = _near_sharp_edges(P, T, S, max(0.6, 0.01 * diag), deg=50.0, ignore=ignore)
    share = float(near.mean())
    return {"deficit": _clip(share / 0.25), "share": round(share, 4), "zone": band}


def analyze(m: Measurement, weights: dict | None = None) -> Analysis:
    """The deficit vector of one built design. weights: per-key weights over WEIGHTS (a style's emphasis)."""
    P, T = np.asarray(m.P, float), np.asarray(m.T, np.int64)
    if not len(T):
        raise ValueError("analyze: the mesh has no triangles")
    sil = silhouette(P, T, worst_view=m.purpose == "game")
    M = sil.pop("masks")
    lit = ((m.game or {}).get("silhouette") or {}).get("interior_regions_lit")
    if lit is not None:                     # a baked asset: the read of its lit render with the base colour on it
        read = {"deficit": _clip(1 - (int(lit) - 1) / (READ_REGIONS - 1)), "regions": int(lit), "from": "game asset"}
    else:
        read = interior_read(P, T)
    parts = {"silhouette": sil, "interior_read": read, "proportion": proportion(P),
             "balance": balance(P, T, M), "detail_scales": detail_scales(P, T, m.tri_feature, m.metrics, m.game),
             "edge_hierarchy": edge_hierarchy(P, T, m.metrics, m.game), "surface_breaks": surface_breaks(P, T)}
    parts["material_zones"], parts["material_contrast"] = materials(m.zones, m.metrics, m.game)
    if m.purpose == "game":
        w = wear(m.game)
        if w is not None:
            parts["wear"] = w
    tp = touch_points(P, T, m.product_class, m.tri_feature, (m.extra or {}).get("texture_features"))
    if tp is not None:
        parts["touch_points"] = tp
    W = {**WEIGHTS, **(weights or {})}
    deficits = {k: round(float(parts[k]["deficit"]), 4) for k in DEFICITS if k in parts}
    used = {k: float(W.get(k, 1.0)) for k in deficits}
    tot = sum(used.values()) or 1.0
    total = round(sum(deficits[k] * used[k] for k in deficits) / tot, 4)
    measures = {k: {x: y for x, y in v.items() if x != "deficit"} for k, v in parts.items()}
    return Analysis(deficits=deficits, measures=measures, weights=used, total=total)
