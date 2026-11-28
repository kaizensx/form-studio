"""A first-order warp-risk indicator for a printed part. An indicator: it ranks orientations and materials. It is not
a prediction of how many millimetres a corner lifts.

**The model.** Wang, Xi and Jin (2007), "A model research for prototype warp deformation in the FDM process",
International Journal of Advanced Manufacturing Technology 33:1087-1096 (doi:10.1007/s00170-006-0556-9), as
reproduced by Armillotta, Bellotti and Cavallaro (2018), "Warpage of FDM parts: Experimental tests and analytic
model", Robotics and Computer-Integrated Manufacturing (doi:10.1016/j.rcim.2017.09.007), eq. 2: each
layer shrinks by alpha (Tg - Te) as it cools from the glass transition to the chamber temperature while the stack
under it does not, which bends a stack of n layers of thickness dh to the curvature

    1 / R = 6 alpha (Tg - Te) (n - 1) / (n^3 dh)        and lifts its ends by        delta = R (1 - cos(L / 2R))

over a section of length L. Its assumptions: nothing is stressed above Tg; a finished layer is at the chamber
temperature; layers are flat, solid, elastic and perfectly bonded; the part is free of the plate. Real parts are
held by the plate, are not solid, and yield, so the model's delta is far from a lift you would measure, and
Armillotta's tests found the largest warpage at intermediate heights where this model falls steadily with height.
What the tests do confirm is the ranking the model gives over length (it "accounts for about 90% of the total
variation", growing faster than linearly) and that width does not matter.

**The indicator.** index = the model's delta over one layer height, for L = the longest span of the part's footprint
on the plate and n = the part's mean height over that footprint, in layers. The model has one height, and a part is
rarely a block: a thin plate with one tall boss warps like the plate, so the height used is the volume over the
footprint's area (never more than the real height; the index at the full height is given beside it). It is
dimensionless and reported with every input and how each is known:

    alpha    the material's linear thermal expansion (sourced: form/printphys/sources.py, or given)
    Tg       its glass transition (sourced or given; the Vicat softening temperature of the filament's datasheet
             stands in where no Tg is sourced, and is then labelled assumed)
    Te       the chamber temperature: given, else assumed 25 C (an open printer in a room)
    L, n     computed on the tessellation in the print orientation; dh from the slicer preset or assumed

The band (low, moderate, high) is Form Studio's convention on that index (below 0.25, below 1, 1 and above: a model
lift of a quarter of a layer, and of a whole layer), raised one step by each of two stated geometric conditions that
manufacturers' guides name and the model does not contain: sharp corners at the ends of the footprint (Bambu Lab
Wiki, "Brim": brim ears "only at sharp corners of the model"; "Model Warping, Falling Off, or Collapsing": "sharp
corners popping up"), and a footprint the part touches on less than half of its extent (less first-layer area to hold
it down). The aspect ratio says along which axis it will lift. Nothing here knows the plate, its temperature, the
adhesive, drafts, infill or a brim.
"""
from __future__ import annotations

import math

import numpy as np

from . import geom

MODEL = {"name": "Wang, Xi and Jin (2007) layer-shrinkage warp model",
         "source": "Wang, Xi, Jin: A model research for prototype warp deformation in the FDM process, Int J Adv Manuf "
                   "Technol 33:1087-1096 (2007), doi:10.1007/s00170-006-0556-9; equation as reproduced in Armillotta, "
                   "Bellotti, Cavallaro: Warpage of FDM parts: Experimental tests and analytic model, Robot Comput "
                   "Integr Manuf (2018), doi:10.1016/j.rcim.2017.09.007, eq. 2",
         "equation": "1/R = 6 alpha (Tg - Te)(n - 1)/(n^3 dh); delta = R (1 - cos(L/(2R)))",
         "limits": "The part is free of the plate, solid, elastic and perfectly bonded, and cools layer by layer from Tg "
                   "to Te. Tests (Armillotta 2018) confirm the trend over length and that width does not matter; they "
                   "find the largest warpage at intermediate heights, which this model does not show."}
GUIDE = {"source": "Bambu Lab Wiki: Brim (wiki.bambulab.com/en/software/bambu-studio/auto-brim); Model Warping, Falling "
                   "Off, or Collapsing (wiki.bambulab.com/en/filament-acc/filament/print-quality/warping-falling-off-collapsing)",
         "says": "sharp corners are where a part lifts first; a brim, or brim ears at the sharp corners, holds them down"}
BANDS = (("low", 0.25), ("moderate", 1.0), ("high", math.inf))
SHARP_TURN_DEG = 45.0           # a footprint corner that turns by more than this in one vertex is sharp
CHAMBER_ASSUMED_C = 25.0


def wang_delta(alpha: float, dT: float, L: float, n: float, dh: float) -> dict:
    """The model's curvature and end lift (mm) for a stack of n layers of thickness dh over a length L."""
    if n <= 1 or alpha * dT <= 0 or L <= 0:
        return {"curvature_per_mm": 0.0, "delta_mm": 0.0}
    k = 6.0 * alpha * dT * (n - 1.0) / (n ** 3 * dh)
    R = 1.0 / k
    ang = L / (2.0 * R)
    delta = R * (1.0 - math.cos(ang)) if ang < math.pi / 2 else R       # past a quarter circle the model has no meaning
    return {"curvature_per_mm": k, "delta_mm": delta}


def footprint(m: geom.Mesh, down) -> dict:
    """The part's first layer in a print orientation: the area on the plate, the hull of that contact, its longest
    span, the sides of its smallest bounding rectangle, and its sharp corners (design-frame points)."""
    d = geom.unit(down)
    R = geom.rotation(d)
    zax = R[2]
    za, zb, zc = m.a @ zax, m.b @ zax, m.c @ zax
    zmin = float(min(za.min(), zb.min(), zc.min()))
    height = float(max(za.max(), zb.max(), zc.max()) - zmin)
    contact = (-(m.n @ zax) > geom.FLAT) & (np.maximum(np.maximum(za, zb), zc) - zmin < geom.CONTACT_EPS)
    out = {"height_mm": height, "contact_mm2": float(m.area[contact].sum())}
    if not contact.any():
        return {**out, "span_mm": 0.0, "hull_mm2": 0.0, "corners": [], "rect_mm": [0.0, 0.0]}
    pts = np.concatenate([m.a[contact], m.b[contact], m.c[contact]]) @ R.T
    hull = geom.hull2d(pts[:, :2])
    if len(hull) < 3:
        return {**out, "span_mm": 0.0, "hull_mm2": 0.0, "corners": [], "rect_mm": [0.0, 0.0]}
    x, y = hull[:, 0], hull[:, 1]
    area = 0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))
    dd = np.linalg.norm(hull[:, None, :] - hull[None, :, :], axis=2)
    i, j = np.unravel_index(int(np.argmax(dd)), dd.shape)
    span = float(dd[i, j])
    # the smallest rectangle around the hull has a side along one of its edges (rotating calipers, by trying each)
    best = None
    e = np.roll(hull, -1, axis=0) - hull
    for v in e:
        ln = np.linalg.norm(v)
        if ln < 1e-9:
            continue
        u = v / ln
        w = np.array([-u[1], u[0]])
        a_, b_ = hull @ u, hull @ w
        sides = (float(np.ptp(a_)), float(np.ptp(b_)))
        if best is None or sides[0] * sides[1] < best[0] * best[1]:
            best = sides
    rect = sorted(best or (0.0, 0.0), reverse=True)
    # corners: turn at each hull vertex
    prev, nxt = hull - np.roll(hull, 1, axis=0), np.roll(hull, -1, axis=0) - hull
    lp, ln_ = np.linalg.norm(prev, axis=1), np.linalg.norm(nxt, axis=1)
    cosang = np.einsum("ij,ij->i", prev, nxt) / np.maximum(lp * ln_, 1e-300)
    turn = np.degrees(np.arccos(np.clip(cosang, -1, 1)))
    cen = hull.mean(axis=0)
    far = np.linalg.norm(hull - cen, axis=1)
    corners = []
    for k in np.argsort(-far):
        if turn[k] > SHARP_TURN_DEG:
            p3 = R.T @ np.array([hull[k, 0], hull[k, 1], zmin])
            corners.append({"at": [round(float(t), 3) for t in p3], "interior_angle_deg": round(180.0 - float(turn[k]), 1),
                            "from_centre_mm": round(float(far[k]), 2)})
    out["mean_height_mm"] = float(min(height, abs(m.volume) / area)) if area > 0 else height
    return {**out, "span_mm": span, "hull_mm2": area, "rect_mm": [round(rect[0], 3), round(rect[1], 3)],
            "span_ends": [[round(float(t), 3) for t in R.T @ np.array([hull[q, 0], hull[q, 1], zmin])] for q in (i, j)],
            "corners": corners[:12], "sharp_corners": len(corners),
            "sharpest_deg": min((c["interior_angle_deg"] for c in corners), default=None)}


def indicator(fp: dict, alpha: dict, tg: dict, chamber: dict, layer: dict) -> dict:
    """The indicator from a footprint and the inputs, each {"value", "how_known", ...}."""
    dh = float(layer["value"])
    n_full = max(1.0, fp["height_mm"] / dh)
    n = max(1.0, fp.get("mean_height_mm", fp["height_mm"]) / dh)
    dT = float(tg["value"]) - float(chamber["value"])
    w = wang_delta(float(alpha["value"]), dT, fp["span_mm"], n, dh)
    w_full = wang_delta(float(alpha["value"]), dT, fp["span_mm"], n_full, dh)
    out = {"indicator": "warp risk (first order)", "model": MODEL,
           "inputs": {"alpha_per_K": alpha, "glass_transition_C": tg, "chamber_C": chamber, "layer_height_mm": layer,
                      "span_mm": {"value": round(fp["span_mm"], 3), "how_known": "computed (longest span of the plate contact's hull)"},
                      "layers": {"value": round(n, 1), "how_known": "computed (mean height over the footprint / layer height)"},
                      "mean_height_mm": {"value": round(fp.get("mean_height_mm", fp["height_mm"]), 3),
                                         "how_known": "computed (volume / area of the footprint's hull, at most the height)"},
                      "height_mm": {"value": round(fp["height_mm"], 3), "how_known": "computed"},
                      "first_layer_mm2": {"value": round(fp["contact_mm2"], 2), "how_known": "computed (flat area on the plate)"}},
           "shrinkage_strain": {"value": float(alpha["value"]) * dT, "what": "alpha (Tg - Te): how much each layer wants to "
                                "shorten on cooling", "how_known": "computed from the inputs above"}}
    if fp["contact_mm2"] < 1.0 or fp["span_mm"] <= 0:
        out.update({"index": None, "band": None,
                    "note": "Nothing flat lies on the plate in this orientation: the part stands on supports, and the model "
                            "(a stack of layers on the plate) does not apply."})
        return out
    if dT <= 0:
        out.update({"index": 0.0, "band": "low", "raised_by": [],
                    "note": "The chamber is at or above the glass transition: the model has no shrinkage to act."})
        return out
    index = w["delta_mm"] / dh
    band_i = next(i for i, (_n, hi) in enumerate(BANDS) if index < hi)
    fill = fp["contact_mm2"] / fp["hull_mm2"] if fp["hull_mm2"] > 0 else 1.0
    aspect = fp["rect_mm"][0] / fp["rect_mm"][1] if fp["rect_mm"][1] > 1e-9 else None
    raised = []
    if fp.get("sharp_corners") and index >= 0.05:
        raised.append({"by": "sharp corners at the ends of the footprint",
                       "value": f"{fp['sharp_corners']} corners, the sharpest {fp['sharpest_deg']:g} deg",
                       "basis": "guide: " + GUIDE["source"], "how_known": "computed (corners of the contact's hull)"})
    if fill < 0.5 and index >= 0.05:
        raised.append({"by": "little of the footprint touches the plate", "value": f"{100 * fill:.0f} % of its hull",
                       "basis": "Form Studio's convention: less first-layer area holds the same span down",
                       "how_known": "computed"})
    band = BANDS[min(band_i + len(raised), len(BANDS) - 1)][0]
    out.update({
        "index": round(index, 4), "index_is": "the model's end lift over one layer height (dimensionless)",
        "index_at_full_height": round(w_full["delta_mm"] / dh, 4),
        "band": band, "band_from_model_alone": BANDS[band_i][0], "raised_by": raised,
        "bands": {"low": "index below 0.25", "moderate": "0.25 to 1", "high": "1 and above",
                  "how_known": "Form Studio's convention on the model's index, not a measured threshold"},
        "model_terms": {"curvature_per_mm": w["curvature_per_mm"], "end_lift_mm": round(w["delta_mm"], 4),
                        "note": "The model's own numbers for a free, solid, elastic stack. Not a prediction of the lift of "
                                "this part: the plate holds it, and the model is not calibrated to any print."},
        "geometry": {"first_layer_mm2": round(fp["contact_mm2"], 2), "footprint_hull_mm2": round(fp["hull_mm2"], 2),
                     "contact_share_of_hull": round(fill, 3), "bounding_rectangle_mm": fp["rect_mm"],
                     "aspect_ratio": round(aspect, 2) if aspect else None, "span_ends": fp.get("span_ends"),
                     "sharp_corners": fp.get("sharp_corners", 0), "sharpest_corner_deg": fp.get("sharpest_deg"),
                     "corners": fp["corners"],
                     "lifts_first": "the two ends of the longest span" + (", at its sharp corners" if fp.get("sharp_corners") else "")},
        "evidence": "modelled (Wang, Xi and Jin 2007; uncalibrated) on computed geometry",
        "not": "An indicator, not a predicted lift in millimetres. It does not know the plate and its temperature, the "
               "adhesive, an enclosure's draft, infill, cooling or a brim.",
    })
    if aspect and aspect >= 3:
        out["geometry"]["note"] = "A long, narrow footprint: it lifts at the two ends of its long axis."
    return out


# ---- kernel side -------------------------------------------------------------------------------------------------

def op_print_footprint(key, recipe_id, values, orientations, tol=0.05):
    """The first-layer geometry of the head revision in each orientation (worker)."""
    from .. import analysis, kernel
    model = kernel._get_near(key, recipe_id, values, tol)
    P, T = kernel._mesh_arrays(model)
    m = geom.Mesh(P, T)
    return {"footprints": {o: footprint(m, analysis.orientation_down(o)) for o in orientations},
            "volume_mm3": abs(m.volume), "tessellation_mm": tol}


KERNEL_OPS = {"print_footprint": op_print_footprint}


# ---- studio side -------------------------------------------------------------------------------------------------

def _err(msg: str, hint: str = "", status: int = 400):
    from ..studio import StudioError
    return StudioError(msg, hint, status=status)


def material_inputs(material, alpha_per_K=None, tg_C=None, source: str = "") -> tuple:
    """(alpha, Tg, material key) for a stored material key, each {"value", "how_known", "source", ...}; a value
    given by the caller wins. Raises StudioError naming what no source gives."""
    from .. import material_library as ml
    from .. import materials
    from . import sources
    key = materials._key(material) if material else None
    if material and key is None:
        raise _err(f"Unknown material “{material}”.", materials.known())

    def given(v, unit):
        return {"value": float(v), "unit": unit, "source": source or None,
                "how_known": "specified (given, source named)" if source else "assumed (given, no source named)"}

    def sourced(name):
        if not key:
            return None
        p = ml.prop(key, name) if name in ("cte",) else None
        if p and p.get("status") != "unsourced" and p.get("value") is not None:
            return {**{k: p.get(k) for k in ("value", "unit", "source", "url", "quote", "condition", "retrieved")},
                    "how_known": p.get("evidence")}
        s = sources.get(key, name)
        if s:
            return {**{k: s.get(k) for k in ("value", "unit", "spread", "min", "max", "source", "url", "quote", "condition",
                                             "retrieved", "basis", "note") if s.get(k) is not None}, "how_known": s["evidence"]}
        return None
    alpha = given(alpha_per_K, "1/K") if alpha_per_K is not None else sourced("cte")
    tg = given(tg_C, "°C") if tg_C is not None else sourced("tg")
    if tg is None and key:
        v = ml.prop(key, "vicat")
        if v.get("status") != "unsourced" and v.get("value") is not None:
            tg = {**{k: v.get(k) for k in ("value", "unit", "source", "url", "quote", "condition", "retrieved")},
                  "how_known": "assumed (no glass transition is sourced: the datasheet's Vicat softening temperature stands in)"}
    missing = [w for w, x in (("the thermal expansion coefficient (alpha_per_K, 1/K)", alpha),
                              ("the glass transition temperature (tg_C)", tg)) if x is None]
    if missing:
        who = (ml.record(key)["label"] if key else "this design (no material is set)")
        raise _err(f"No source gives {' or '.join(missing)} for {who}, and the indicator cannot be made without it. "
                   "Nothing is assumed.", "Give it with where it is from: alpha_per_K=..., tg_C=..., source=\"...\".")
    if not alpha["value"] > 0:
        raise _err("The thermal expansion coefficient must be positive (1/K, e.g. 9e-5).")
    return alpha, tg, key


def run(st, p: dict, orientation: str | None = None, material: str | None = None, chamber_C: float | None = None,
        alpha_per_K: float | None = None, tg_C: float | None = None, layer_height: float | None = None,
        source: str = "", compare: bool = True) -> dict:
    """The warp-risk indicator of the head revision in an orientation (default: the print setup), and the same for
    the six axis orientations so the ranking is seen."""
    from .. import analysis, materials
    from . import orient as orient_mod
    o = orientation or p["orientation"]
    if not analysis.valid_orientation(o):
        raise _err("Unknown orientation.", "Use one of: " + ", ".join(analysis.NAMED) + ", or a “down:x,y,z” id.")
    mat = material or materials.resolved(p).get("material")
    alpha, tg, key = material_inputs(mat, alpha_per_K, tg_C, source)
    settings, _ = orient_mod._settings(st, p)
    if layer_height is not None:
        layer = {"value": float(layer_height), "how_known": "given"}
    else:
        layer = {"value": settings["values"]["layer_height"], "how_known": settings["how_known"]["layer_height"]}
    if not 0.02 <= layer["value"] <= 2.0:
        raise _err("The layer height is in millimetres (0.02 to 2).")
    chamber = ({"value": float(chamber_C), "how_known": "given"} if chamber_C is not None else
               {"value": CHAMBER_ASSUMED_C, "how_known": "assumed (an open printer in a room at 25 C; give chamber_C for an enclosure)"})
    ids = [o] + ([n for n in analysis.NAMED if n != o] if compare else [])
    r = st.rev(p)
    fps = st._k("print_footprint", timeout=300, key=st.keys(p)["geometry"], recipe_id=st.rid(p), values=r["values"],
                orientations=ids, p=p)["footprints"]
    out = indicator(fps[o], alpha, tg, chamber, layer)
    out.update({"project": p["id"], "rev": r["n"], "orientation": o, "orientation_label": analysis.orientation_label(o),
                "material": key, "guide": GUIDE})
    if compare:
        rows = []
        for i in ids:
            x = indicator(fps[i], alpha, tg, chamber, layer)
            rows.append({"id": i, "label": analysis.orientation_label(i), "index": x.get("index"), "band": x.get("band"),
                         "span_mm": round(fps[i]["span_mm"], 2), "height_mm": round(fps[i]["height_mm"], 2),
                         "first_layer_mm2": round(fps[i]["contact_mm2"], 1), "sharp_corners": fps[i].get("sharp_corners", 0),
                         "chosen": i == o})
        rows.sort(key=lambda x: (x["index"] is None, x["index"] if x["index"] is not None else 0.0))
        out["by_orientation"] = rows
    return out


def headline(r: dict) -> str:
    if r.get("index") is None:
        return "stands on supports: the model does not apply"
    return f"{r['band']} (index {r['index']:.2g}, indicator; span {r['inputs']['span_mm']['value']:.0f} mm, {r['material'] or 'material given'})"
