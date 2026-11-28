"""Print orientation as a search over several objectives, with the Pareto front returned and the pick written to the
design's print setup.

    r = run(st, p, cosmetic=[[x, y, z]], study="s1a2b3c", verify=3)     # the front, ranked by stated weights
    pick(st, p, r["front"][0]["id"])                                     # the person's choice -> the print setup

**Objectives** (form/printphys/geom.py and timemodel.py; each row says how it is known):

    support_mm3              support volume: columns under the overhang facets, down to the part or the plate (computed)
    support_contact_mm2      where support touches the part: what it holds up plus where it stands (computed)
    time_s                   print time by the layer-time model (modelled; calibrated on a real slice when one is there)
    strength_use             1 / safety factor of a layered material under the load of a strength study: tension
                             across the layers against the Z strength, von Mises against the in-plane strength
                             (modelled from the isotropic study's stress field); or, with only a load direction, the
                             share of in-plane strength left along it
    cosmetic_cusp_um         mean stair height on the faces marked cosmetic (computed, Dolenc and Makela 1994)
    cosmetic_supported_mm2   area of those faces that needs support, so carries its marks (computed)
    tip_over_deg             the tilt at which the part tips off its plate contact (computed; more is better)

**Search.** Candidates are the six axis orientations, every flat face of the part's convex hull (the ways it can lie
on the plate), and a geodesic grid over the sphere of directions (162 at level 2, about 16 degrees apart). From the
non-dominated candidates a local refinement walks to neighbours that dominate, at half the grid spacing and halving,
down to 1 degree. The front is recomputed over everything evaluated, and its rows are integrated again with finer
pieces and a second quadrature rule, whose difference is the stated spread of the support volume.

**The pick is the person's.** The front is ranked by weights that are shown and can be changed; that ranking is a
convention, not a result. Nothing is written to the print setup until an orientation is picked.

**Verification.** verify=N slices the N best-ranked candidates with the real slicer, supports on (normal supports at
the same critical angle), and compares the slicer's time and support filament with the prediction. The errors are
reported per candidate. The slice the model is calibrated on is marked: its error is zero by construction and is not
counted.
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import numpy as np

from . import CRITICAL_DEG, VERSION, geom, timemodel

OBJECTIVES = {
    "support_mm3": {"label": "Support volume", "unit": "mm3", "better": "less", "how_known": "computed (tessellation)"},
    "support_contact_mm2": {"label": "Support contact on the part", "unit": "mm2", "better": "less",
                            "how_known": "computed (tessellation)"},
    "time_s": {"label": "Print time", "unit": "s", "better": "less", "how_known": "modelled (layer-time model)"},
    "strength_use": {"label": "Strength used by the load", "unit": "1 / safety factor", "better": "less",
                     "how_known": "modelled (isotropic stress field, max-stress criterion, datasheet Z and X-Y strengths)"},
    "cosmetic_cusp_um": {"label": "Stair height on cosmetic faces", "unit": "um", "better": "less",
                         "how_known": "computed (cusp height, Dolenc and Makela 1994)"},
    "cosmetic_supported_mm2": {"label": "Cosmetic area under support", "unit": "mm2", "better": "less",
                               "how_known": "computed (tessellation)"},
    "tip_over_deg": {"label": "Tilt before it tips", "unit": "deg", "better": "more", "how_known": "computed (centre of "
                     "mass over the plate contact)"},
}
WEIGHTS = {"support_mm3": 0.25, "support_contact_mm2": 0.10, "time_s": 0.20, "strength_use": 0.25,
           "cosmetic_cusp_um": 0.05, "cosmetic_supported_mm2": 0.05, "tip_over_deg": 0.10}
SCORE_NOTE = ("score = sum of weight x the objective scaled 0 to 1 across the front (0 = the best on the front); lower "
              "is better. The weights are a convention you can change; the front itself does not depend on them.")
NOT = ("A ranking from geometry and stated models. It does not know cooling, bridging, adhesion, the slicer's support "
       "style or seam, and the strength term is first order. Slice the pick to confirm (verify=N does it).")
REFINE_EVALS = 260
FRONT_REFINE = 40


def _analysis():
    from .. import analysis
    return analysis


def canonical(down) -> tuple:
    """(orientation id, the direction that id stands for): a named orientation where the direction is one."""
    a = _analysis()
    d = geom.unit(down)
    for name in a.NAMED:
        if float(a.orientation_down(name) @ d) > 0.99995:
            return name, a.orientation_down(name)
    oid = a.down_id(d)
    return oid, a.parse_down(oid)


def _quantum(m: geom.Mesh, t_ref: float) -> dict:
    """The step below which two values of an objective count as the same (so noise does not make a front)."""
    return {"support_mm3": max(1.0, 0.002 * abs(m.volume)), "support_contact_mm2": max(1.0, 0.002 * m.surface),
            "time_s": max(5.0, 0.01 * t_ref), "strength_use": 1e-3, "cosmetic_cusp_um": 0.5,
            "cosmetic_supported_mm2": max(0.5, 0.001 * m.surface), "tip_over_deg": 0.5}


class Search:
    """The candidates of one design and their objectives. Pure numpy: used by the kernel op and by the tests."""

    def __init__(self, m: geom.Mesh, settings: dict, envelope=(180, 180, 180), margin: float = 2.0,
                 cosmetic: np.ndarray | None = None, stress: dict | None = None, load: dict | None = None,
                 critical_deg: float | None = None, evaluate=None, free: bool = False):
        self.m, self.s = m, settings
        self.v = settings["values"] if "values" in settings else settings
        self.env, self.margin = list(envelope), float(margin)
        self.cos = cosmetic if cosmetic is not None and np.any(cosmetic) else None
        self.stress, self.load = stress, load
        self.crit = float(critical_deg if critical_deg is not None else self.v.get("critical_deg", CRITICAL_DEG))
        self.rows: dict[str, dict] = {}
        self.free, self.no_stable = bool(free), False
        self._evaluate = evaluate                              # tests give synthetic objectives: f(down) -> {name: value}
        self.names = None

    # -- one candidate --
    def row(self, down, fine: bool = False) -> dict:
        oid, d = canonical(down)
        if oid in self.rows and not fine:
            return self.rows[oid]
        if self._evaluate is not None:
            obj = dict(self._evaluate(d))
            r = {"id": oid, "down": [float(x) for x in d], "fits": True, "objectives": obj}
            self.rows[oid] = r
            return r
        m = self.m
        g = geom.evaluate(m, d, self.crit, res=(m.diag / 120.0 if fine else None), samples_max=(250000 if fine else 40000),
                          layer=self.v["layer_height"], cosmetic=self.cos, three_point=fine)
        t = timemodel.estimate(g, abs(m.volume), self.s)
        fx, fy = g["footprint_mm"]
        ex, ey, ez = self.env[0] - 2 * self.margin, self.env[1] - 2 * self.margin, self.env[2]
        fits = bool(g["height_mm"] <= ez and ((fx <= ex and fy <= ey) or (fy <= ex and fx <= ey)))
        r = {"id": oid, "down": [float(x) for x in d], "fits": fits, **g, "time_s": t["time_s"], "filament_g": t["filament_g"],
             "support_g": t["support_g"], "layers": t["layers"], "time_parts": t["parts"], "uncalibrated": t["uncalibrated"],
             "integrated": "fine" if fine else "search"}
        obj = {"support_mm3": g["support_mm3"], "support_contact_mm2": g["support_contact_mm2"], "time_s": t["time_s"],
               "tip_over_deg": g["tip_over_deg"]}
        if self.stress is not None:
            al = geom.across_layers(self.stress["stress"], d, self.stress.get("ok"))
            sz, sxy, vm = self.stress.get("S_z"), self.stress.get("S_xy"), self.stress.get("vm_peak") or 0.0
            use = [x for x in ((al["tension_MPa"] / sz) if sz else None, (vm / sxy) if sxy else None) if x is not None]
            st = {"tension_across_MPa": al["tension_MPa"], "interlayer_shear_MPa": al["shear_MPa"],
                  "sf_across_layers": (sz / al["tension_MPa"]) if sz and al["tension_MPa"] > 0 else None,
                  "sf_in_plane": (sxy / vm) if sxy and vm > 0 else None}
            if use:
                st["safety_factor"] = 1.0 / max(max(use), 1e-300)
                st["governing"] = "across_layers" if sz and al["tension_MPa"] / sz >= max(use) - 1e-12 else "in_plane"
                obj["strength_use"] = max(use)
            else:                                          # no strength sourced: the tension across the layers itself
                obj["strength_use"] = al["tension_MPa"]
                st["note"] = "No strength is sourced: ranked by the tension across the layers (MPa), not by a factor."
            r["strength"] = st
        elif self.load is not None:
            b = -geom.unit(d)
            c2 = float((b @ geom.unit(self.load["direction"])) ** 2)
            kd = self.load.get("knockdown")
            st = {"share_across_layers": c2}
            if kd:
                st["strength_along_load"] = float(min(1.0, kd / max(c2, 1e-12)))
                obj["strength_use"] = 1.0 / st["strength_along_load"]
            else:
                obj["strength_use"] = c2
            r["strength"] = st
        if self.cos is not None:
            obj["cosmetic_cusp_um"] = g["cosmetic_cusp_um"]
            obj["cosmetic_supported_mm2"] = g["cosmetic_supported_mm2"]
        r["objectives"] = obj
        self.rows[oid] = r
        return r

    # -- dominance --
    def table(self, rows: list) -> np.ndarray:
        names = self.names = self.names or list(rows[0]["objectives"])
        F = np.array([[r["objectives"][n] for n in names] for r in rows], dtype=np.float64)
        q = _quantum(self.m, float(np.min(F[:, names.index("time_s")])) if "time_s" in names else 1.0) \
            if self._evaluate is None else {}
        for j, n in enumerate(names):
            if OBJECTIVES.get(n, {}).get("better") == "more":
                F[:, j] = -F[:, j]
            if q.get(n):
                F[:, j] = np.round(F[:, j] / q[n])
        return F

    def feasible(self, rows: list | None = None) -> list:
        """The candidates the front is taken over: they fit the bed and, unless free, stand on the plate on their
        own (a flat face on it, the centre of mass over it). A part with no such orientation keeps every one that
        fits, and the result says so."""
        every = rows is None
        rows = [r for r in (rows if rows is not None else self.rows.values()) if r["fits"]]
        if self.free or self._evaluate is not None:
            return rows
        stable = [r for r in rows if r.get("tip_over_deg", 0.0) > 0.0]
        if every:
            self.no_stable = not stable and bool(rows)
            return stable or rows
        return rows if self.no_stable else stable            # a few candidates: by the rule the whole set settled

    def front(self) -> list:
        rows = self.feasible()
        if not rows:
            return []
        keep = geom.pareto(self.table(rows))
        return [r for r, k in zip(rows, keep) if k]

    # -- the search --
    def run(self, level: int = 2, rest=(), extra=(), refine: bool = True, progress=None) -> dict:
        a = _analysis()
        progress = progress or (lambda *_: None)
        t0 = time.perf_counter()
        seeds = [a.orientation_down(n) for n in a.NAMED] + list(rest) + [a.orientation_down(x) for x in extra]
        grid = geom.icosphere(level)
        for d in seeds + list(grid):
            self.row(d)
        self.feasible()                                           # settles whether the part stands in any of them
        n_grid = len(self.rows)
        steps = 0
        if refine:
            step0 = geom.spacing_deg(level) / 2.0
            for seed in list(self.front())[:24]:
                cur, step = seed, step0
                while step >= 1.0 and len(self.rows) - n_grid < REFINE_EVALS:
                    nb = self.feasible([self.row(d) for d in geom.ring(cur["down"], step)])
                    best = None
                    if nb:
                        F = self.table([cur] + nb)
                        dom = [i for i in range(1, len(F)) if np.all(F[i] <= F[0]) and np.any(F[i] < F[0])]
                        if dom:
                            best = nb[min(dom, key=lambda i: float(F[i].sum())) - 1]
                    if best is not None:
                        cur = best
                        steps += 1
                    else:
                        step /= 2.0
        if self._evaluate is None:
            for r in self.front()[:FRONT_REFINE]:                 # the front again, integrated finer, with the spread
                self.row(r["down"], fine=True)
            for x in extra:                                       # and the orientation in the print setup
                self.row(a.orientation_down(x), fine=True)
        front = {r["id"] for r in self.front()}
        rows = list(self.rows.values())
        for r in rows:
            r["on_front"] = r["id"] in front
        return {"rows": rows, "search": {"grid_level": level, "grid_directions": int(len(grid)), "grid_spacing_deg": round(geom.spacing_deg(level), 1),
                                         "flat_faces": len(rest), "evaluated": len(rows), "refinement_moves": steps,
                                         "refined_to_deg": 1.0 if refine else None, "front": len(front),
                                         "stand_on_the_plate": sum(1 for r in rows if r.get("tip_over_deg", 0.0) > 0.0),
                                         "free": self.free, "none_stands": self.no_stable,
                                         "seconds": round(time.perf_counter() - t0, 2)},
                "objectives": self.names}


def rank(rows: list, weights: dict | None = None) -> list:
    """The rows of the front ordered by the weighted sum of their objectives, each scaled 0 to 1 across the front."""
    if not rows:
        return []
    w = {**WEIGHTS, **{k: float(v) for k, v in (weights or {}).items() if k in OBJECTIVES}}
    names = list(rows[0]["objectives"])
    F = np.array([[r["objectives"][n] for n in names] for r in rows], dtype=np.float64)
    out = np.zeros(len(rows))
    terms = np.zeros_like(F)
    for j, n in enumerate(names):
        col = -F[:, j] if OBJECTIVES.get(n, {}).get("better") == "more" else F[:, j]
        lo, hi = col.min(), col.max()
        terms[:, j] = w.get(n, 0.0) * (np.zeros(len(col)) if hi - lo < 1e-12 else (col - lo) / (hi - lo))
        out += terms[:, j]
    order = np.argsort(out, kind="stable")
    ranked = []
    for k, i in enumerate(order):
        ranked.append({**rows[i], "rank": k + 1, "score": round(float(out[i]), 4),
                       "score_terms": {n: round(float(terms[i, j]), 4) for j, n in enumerate(names)}})
    return ranked


# ---- kernel side ---------------------------------------------------------------------------------------------------

def _decode_field(path: str) -> dict | None:
    import base64
    try:
        f = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    fl = f.get("fields") or {}
    if "stress" not in fl:
        return None

    def arr(x, cols):
        return np.frombuffer(base64.b64decode(x["data"]), dtype="<f4" if x["type"] == "f4" else "u1").reshape(-1, cols) \
            if cols > 1 else np.frombuffer(base64.b64decode(x["data"]), dtype="<f4" if x["type"] == "f4" else "u1")
    out = {"stress": arr(fl["stress"], 6).astype(np.float64)}
    if "singular" in fl:
        out["ok"] = arr(fl["singular"], 1) == 0
    return out


def op_print_orient(key, recipe_id, values, envelope=(180, 180, 180), margin=2.0, settings=None, level=2, cosmetic=(),
                    stress=None, load=None, current="as_modelled", critical_deg=None, free=False, tol=0.1):
    """The search on the head's tessellation (worker). stress: {"field": path, "S_z", "S_xy", "vm_peak"}."""
    from .. import analysis, kernel, selection
    model = kernel._get(key, recipe_id, values, tol)
    P, T = kernel._mesh_arrays(model)
    m = geom.Mesh(P, T)
    face_of_tri = np.concatenate([np.full(len(f["T"]), i) for i, f in enumerate(model["faces"])])
    cos_mask, cos_info = None, []
    if cosmetic:
        ctx = selection._Ctx(model, "as_modelled")
        cos_mask = np.zeros(len(T), dtype=bool)
        feats = {f.id: f.label for f in model["recipe"].features}
        for at in cosmetic:
            pt = np.asarray(at, dtype=np.float64)
            dist, fi, _on, _tk = ctx.nearest(pt)
            if dist > 1.0:
                return {"error": f"The point {np.round(pt, 3).tolist()} is {dist:.2f} mm off the part's surface: a "
                                 "cosmetic face is picked by a point on it."}
            sel = face_of_tri == fi
            cos_mask |= sel
            fid = model["faces"][fi].get("feature")
            cos_info.append({"at": [float(x) for x in pt], "face_index": int(fi), "feature": fid,
                             "feature_label": feats.get(fid, str(fid)), "area_mm2": float(m.area[sel].sum())})
    st_in = None
    if stress:
        f = _decode_field(stress["field"])
        if f is None:
            return {"error": "The strength study's stored field has no stress tensor; run the study again."}
        st_in = {**f, "S_z": stress.get("S_z"), "S_xy": stress.get("S_xy"), "vm_peak": stress.get("vm_peak")}
    s = Search(m, settings or timemodel.settings(), envelope, margin, cos_mask, st_in, load, critical_deg, free=free)
    out = s.run(level=level, rest=analysis.rest_directions(P, T), extra=(current,) if analysis.valid_orientation(current) else ())
    cur_down = analysis.orientation_down(current) if analysis.valid_orientation(current) else None
    feats = {f.id: f.label for f in model["recipe"].features}
    tri_feature = np.concatenate([np.full(len(f["T"]), str(f.get("feature")), dtype=object) for f in model["faces"]])
    for r in out["rows"]:
        d = np.asarray(r["down"])
        r["label"] = analysis.orientation_label(r["id"])
        r["current"] = bool(cur_down is not None and float(d @ cur_down) > 0.9995)
        if r["id"] not in analysis.NAMED and r["contact_mm2"] >= 1.0:          # name the face it rests on
            R = geom.rotation(d)
            zc = (m.a + m.b + m.c) @ R[2] / 3.0
            on = (-(m.n @ R[2]) > geom.FLAT) & (zc - (P @ R[2]).min() < geom.CONTACT_EPS)
            if on.any():
                ids = np.unique(tri_feature[on])
                best = max(ids, key=lambda fid: float(m.area[on & (tri_feature == fid)].sum()))
                r["label"] = f"On a face of {feats.get(best, best)}"
        elif r["rests_on_supports"]:
            r["label"] += " (on supports: no flat face on the plate)"
    out.update({"mesh": {"triangles": int(len(T)), "tessellation_mm": tol, "volume_mm3": abs(m.volume),
                         "surface_mm2": m.surface, "centre_of_mass": [float(x) for x in m.com]},
                "cosmetic": cos_info, "critical_deg": s.crit, "current": current})
    return out


def op_print_stl(key, recipe_id, values, orientation, out, tol=0.05):
    """The head's tessellation as a binary STL in a print orientation, standing on z = 0 (worker)."""
    from .. import analysis, kernel
    model = kernel._get_near(key, recipe_id, values, tol)
    P, T = kernel._mesh_arrays(model)
    Q = P @ analysis.orientation_matrix(orientation).T
    Q = Q - np.array([(Q[:, 0].min() + Q[:, 0].max()) / 2, (Q[:, 1].min() + Q[:, 1].max()) / 2, Q[:, 2].min()])
    a, b, c = Q[T[:, 0]], Q[T[:, 1]], Q[T[:, 2]]
    n = np.cross(b - a, c - a)
    n /= np.maximum(np.linalg.norm(n, axis=1), 1e-300)[:, None]
    rec = np.zeros(len(T), dtype=[("n", "<f4", 3), ("a", "<f4", 3), ("b", "<f4", 3), ("c", "<f4", 3), ("attr", "<u2")])
    rec["n"], rec["a"], rec["b"], rec["c"] = n, a, b, c
    with open(out, "wb") as f:
        f.write(b"Form Studio print orientation".ljust(80, b" "))
        f.write(np.uint32(len(T)).tobytes())
        f.write(rec.tobytes())
    return {"stl": str(out), "triangles": int(len(T)), "size_mm": [float(x) for x in (Q.max(axis=0) - Q.min(axis=0))]}


KERNEL_OPS = {"print_orient": op_print_orient, "print_stl": op_print_stl}


# ---- studio side ---------------------------------------------------------------------------------------------------

def _err(msg: str, hint: str = "", status: int = 400):
    from ..studio import StudioError
    return StudioError(msg, hint, status=status)


def _settings(st, p: dict, critical_deg=None) -> tuple:
    """(time-model settings, the slicer info they were read from)."""
    from .. import material_library as ml
    from .. import materials
    s = st.slicer_info(p=p)
    presets = s.get("presets") or {} if s.get("available") else {}
    given = {"critical_deg": critical_deg} if critical_deg is not None else {}
    out = timemodel.settings((presets.get("process") or {}).get("data"), (presets.get("filament") or {}).get("data"), given)
    out["source"] = ({k: (presets.get(k) or {}).get("name") for k in ("machine", "process", "filament")}
                     if presets else "no slicer preset: every value is assumed")
    mat = materials.resolved(p).get("material")
    if out["how_known"]["density_g_cm3"] == timemodel.ASSUMED and mat:
        try:
            d = ml.density(mat)
            out["values"]["density_g_cm3"] = d["value"] / 1000.0
            out["how_known"]["density_g_cm3"] = f"{d['evidence']}: {d['source']}"
        except KeyError:
            pass
    if s.get("nozzle_mm"):
        out["values"]["nozzle"], out["how_known"]["nozzle"] = float(s["nozzle_mm"]), timemodel.PRESET
    return out, s


def _strength_input(st, p: dict, study: str = "", load_direction=None, strict: bool = True) -> tuple:
    """(what the kernel op needs, what the result says about it). strict: a named study without a current result
    is an error; otherwise (a search repeated from stored options) strength is left out, with the reason."""
    from .. import material_library as ml
    from .. import materials
    from ..fea import material as fmat
    from ..fea import study as fstudy
    if load_direction is not None:
        try:
            d = [float(x) for x in load_direction]
            geom.unit(d)
        except (TypeError, ValueError):
            raise _err("load_direction is three numbers (design frame), not all zero.") from None
        mat = materials.resolved(p).get("material")
        kd = None
        info = {"from": "load direction", "direction": d,
                "note": "Only the direction of the load is known: the term is the share of in-plane strength left "
                        "along it, from the datasheet's Z / X-Y strength ratio. A strength study gives the real stress."}
        if mat:
            k = (ml.knockdown_z(mat) or {}).get("uts")
            if k:
                kd = k["ratio"]
                info["knockdown"] = {**k, "material": mat}
        if kd is None:
            info["note"] += (" No Z / X-Y strength ratio is sourced for the design's material, so the candidates are "
                             "ranked by the share of the load that pulls across the layers.")
        return {"load": {"direction": d, "knockdown": kd}}, info
    statics = [d for d in fstudy.definitions(p) if d["kind"] == "static"]
    if study and not strict and study not in (p.get("strength") or {}):
        return {}, {"from": None, "note": f"Strength study “{study}” no longer exists, so strength is not among the objectives."}
    if study:
        d = fstudy.get(p, study)
        if d["kind"] != "static":
            raise _err(f"Study “{study}” is not a static study; the strength term needs a stress field.")
    else:
        cur = [d for d in statics if fstudy.state(st, p, d["id"])["state"] == "current"]
        if len(cur) != 1:
            why = ("No strength study is defined for this design" if not statics else
                   "No static strength study has a current result" if not cur else
                   "Several static studies have current results: name one with study=")
            return {}, {"from": None, "note": f"{why}, so strength is not among the objectives. strength_study defines "
                                               "the load; load_direction=[x, y, z] gives its direction alone."}
        d = cur[0]
    r = fstudy.result(st, p, d["id"], stale_ok=False)
    res = r.get("result")
    if (r["state"]["state"] != "current" or res is None) and not strict:
        return {}, {"from": None, "study": d["id"],
                    "note": f"Strength study “{d['name']}” has no current result (state: {r['state']['state']}), so strength "
                            "is not among the objectives. Run it, then search again."}
    if r["state"]["state"] != "current" or res is None:
        raise _err(f"Study “{d['id']}” has no current result (state: {r['state']['state']}).", "Run it first: strength_study(project, study=...).", 409)
    path = fstudy.field_path(st, p, d["id"])
    if path is None:
        raise _err("The study's result has no field data.", "Run the study again.", 409)
    try:
        has_stress = "stress" in (json.loads(path.read_text(encoding="utf-8")).get("fields") or {})
    except (OSError, ValueError):
        has_stress = False
    if not has_stress:
        why = (f"The stored result of study “{d['name']}” was made before results kept the stress tensor, so the "
               "tension across the layers cannot be read from it.")
        if strict:
            raise _err(why, f"Solve it again: strength_study(project, study=\"{d['id']}\", force=True).", 409)
        return {}, {"from": None, "study": d["id"], "note": why + " Solve it again, then search again."}
    if not res.get("converged"):
        return {}, {"from": d["id"], "note": "The strength study did not converge, so its stress is not used."}
    mats = fstudy.materials_for(st, p, {k: v for k, v in d.items() if k != "layers"})
    if len(mats) != 1:
        return {}, {"from": d["id"], "note": "The strength term is for a design of one solid."}
    (m,) = mats.values()
    ly = fmat.layered(m, [0, 0, 1], (d.get("layers") or {}).get("assume"))
    info = {"from": "strength study", "study": d["id"], "name": d["name"], "evidence": res.get("evidence"),
            "peak_von_mises_MPa": res.get("peak_von_mises_MPa"), "S_z_MPa": ly["S_z"], "S_xy_MPa": ly["S_xy"],
            "how_known": {k: ly["how_known"].get(k) for k in ("S_z", "S_xy")}, "knockdown": ly.get("knockdown"),
            "note": "The stress is the study's isotropic field on its surface nodes, outside the zones it left out as "
                    "singular. How the layered stiffness moves the stress is not in this term: print_strength solves it."}
    if d.get("layers"):
        info["note"] = ("The stress is the layered study's own field, solved for one build direction; for the other "
                        "candidates it is first order.")
    return {"stress": {"field": str(path), "S_z": ly["S_z"], "S_xy": ly["S_xy"], "vm_peak": res.get("peak_von_mises_MPa")},
            "_key": [d["id"], r.get("result_key")]}, info


def _inputs(st, p: dict, opts: dict, strict: bool = True) -> dict:
    """Everything the search is keyed by and run with."""
    from ..studio import H
    pe = st.printer_env(p)
    settings, slicer = _settings(st, p, opts.get("critical_deg"))
    for k, v in (opts.get("settings") or {}).items():
        if k in settings["values"]:
            settings["values"][k], settings["how_known"][k] = float(v), "given"
    strength, sinfo = _strength_input(st, p, opts.get("study") or "", opts.get("load_direction"), strict)
    cosmetic = []
    for c in opts.get("cosmetic") or []:
        at = c.get("at") if isinstance(c, dict) else c
        try:
            at = [float(x) for x in at]
            assert len(at) == 3
        except (TypeError, ValueError, AssertionError):
            raise _err("A cosmetic face is a point on it: [x, y, z] in design millimetres.") from None
        cosmetic.append(at)
    level = int(opts.get("level") or 2)
    if not 1 <= level <= 3:
        raise _err("level is 1, 2 or 3 (42, 162 or 642 grid directions).")
    r = st.rev(p)
    gk = st.keys(p)["geometry"]
    kw = {"envelope": list(pe["envelope"]), "margin": pe["margin"], "settings": {"values": settings["values"]},
          "level": level, "cosmetic": cosmetic, "current": p["orientation"], "critical_deg": settings["values"]["critical_deg"],
          "free": bool(opts.get("free"))}
    key = H("print-orient", VERSION, gk, kw, strength.get("_key") or strength.get("load"),
            (strength.get("stress") or {}).get("S_z"), (strength.get("stress") or {}).get("S_xy"))
    if strength.get("stress"):
        kw["stress"] = strength["stress"]
    if strength.get("load"):
        kw["load"] = strength["load"]
    return {"key": key, "gk": gk, "rev": r, "kw": kw, "settings": settings, "slicer": slicer, "strength": sinfo, "printer": pe}


def result_key(st, p: dict, opts: dict | None = None) -> str:
    return _inputs(st, p, opts or stored_options(p), strict=False)["key"]


def stored_options(p: dict) -> dict:
    """The options of the design's last orientation search (cosmetic faces, the study, weights), kept in the project."""
    return dict(((p.get("print") or {}).get("orient") or {}).get("options") or {})


def cached(st, p: dict, opts: dict | None = None) -> dict | None:
    try:
        key = result_key(st, p, opts)
    except Exception:                                    # noqa: BLE001 - cannot be keyed: nothing stored under it
        return None
    path = st.dir(p["id"]) / "artifacts" / "analysis" / f"print-orient-{key}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    except (OSError, ValueError):
        return None


def run(st, p: dict, cosmetic=None, study: str = "", load_direction=None, level: int = 2, weights: dict | None = None,
        calibrate="auto", verify: int = 0, critical_deg: float | None = None, settings: dict | None = None,
        top: int = 8, remember: bool = True, free: bool = False, strict: bool = True) -> dict:
    """The Pareto front of print orientations of the head revision, ranked, with what is known about each number."""
    from .. import analysis
    opts = {"cosmetic": cosmetic or [], "study": study, "load_direction": load_direction, "level": level,
            "critical_deg": critical_deg, "settings": settings or {}, "free": bool(free)}
    if weights:
        bad = [k for k in weights if k not in OBJECTIVES]
        if bad:
            raise _err(f"Unknown objective “{bad[0]}” in weights.", "Objectives: " + ", ".join(OBJECTIVES) + ".")
    inp = _inputs(st, p, opts, strict)
    raw = analysis._cached(st, p, "print-orient", inp["key"],
                           lambda: st._k("print_orient", timeout=900, key=inp["gk"], recipe_id=st.rid(p),
                                         values=inp["rev"]["values"], p=p, **inp["kw"]))
    if raw.get("error"):
        path = st.dir(p["id"]) / "artifacts" / "analysis" / f"print-orient-{inp['key']}.json"
        path.unlink(missing_ok=True)
        raise _err(raw["error"])
    if remember:
        with st.lock(p["id"]):
            cur = st.load(p["id"])
            cur.setdefault("print", {}).setdefault("orient", {})["options"] = {k: v for k, v in opts.items() if v not in (None, "", [], {})}
            if weights:
                cur["print"]["orient"]["weights"] = weights
            st.save(cur)
        p["print"] = cur["print"]
    weights = weights or ((p.get("print") or {}).get("orient") or {}).get("weights")
    rows = raw["rows"]
    vol = raw["mesh"]["volume_mm3"]
    # calibration: one real slice of one orientation scales the model's time and grams
    cal = _calibration(st, p, inp, rows, calibrate)
    if cal.get("factors"):
        for r in rows:
            t = timemodel.estimate(r, vol, inp["settings"], cal["factors"])
            r.update({"time_s": t["time_s"], "filament_g": t["filament_g"], "support_g": t["support_g"], "time_parts": t["parts"]})
            r["objectives"]["time_s"] = t["time_s"]
    front = rank([r for r in rows if r.get("on_front")], weights)
    names = list(front[0]["objectives"]) if front else []
    cur_row = next((r for r in rows if r.get("current")), None)
    out = {"project": p["id"], "rev": inp["rev"]["n"], "key": inp["key"],
           "evidence": "computed (geometry on the tessellation) and modelled (time; strength); see each objective",
           "objectives": {n: OBJECTIVES[n] for n in names},
           "front": [_public(r) for r in front[:max(1, int(top))]], "front_size": len(front),
           "candidates_evaluated": len(rows), "recommended": front[0]["id"] if front else None,
           "weights": {n: {**WEIGHTS, **(weights or {})}.get(n, 0.0) for n in names}, "score_note": SCORE_NOTE,
           "current": _public(cur_row) if cur_row else None, "current_orientation": p["orientation"],
           "current_on_front": bool(cur_row and cur_row.get("on_front")),
           "settings": {"values": inp["settings"]["values"], "how_known": inp["settings"]["how_known"],
                        "units": timemodel.UNITS, "source": inp["settings"].get("source")},
           "critical_deg": {"value": raw["critical_deg"], "from": "vertical",
                            "how_known": inp["settings"]["how_known"]["critical_deg"]},
           "calibration": {k: v for k, v in cal.items() if k != "slice"}, "strength_input": inp["strength"],
           "cosmetic": raw["cosmetic"] or {"note": "No face is marked cosmetic, so surface quality is not among the "
                                                   "objectives. cosmetic=[[x, y, z], ...] marks faces by a point on each."},
           "search": raw["search"], "mesh": raw["mesh"], "printer": inp["printer"]["name"],
           "envelope_mm": inp["printer"]["envelope"], "not": NOT,
           "next": "Pick one: print_orient(project, pick=\"<id>\") writes it to the print setup. Nothing is set until then."}
    unfit = [r for r in rows if not r["fits"]]
    if unfit:
        out["do_not_fit"] = len(unfit)
    if not front:
        out["note"] = "No orientation fits the printer's bed."
    elif raw["search"].get("none_stands"):
        out["note"] = ("In no orientation does the part stand on the plate on its own (a flat face on it, the centre of "
                       "mass over it), so every orientation that fits was kept: each rests on supports.")
    elif not free:
        out["stability_rule"] = ("The front is taken over the orientations in which the part stands on the plate on its "
                                 "own: a flat face on it and the centre of mass over that face. free=True also admits "
                                 "orientations that rest on supports.")
    if verify and front:
        chosen = front[:max(1, min(int(verify), 6))]
        if cur_row is not None and all(r["id"] != cur_row["id"] for r in chosen):
            chosen = chosen + [{**cur_row, "rank": None}]          # the orientation in the print setup, for comparison
        out["verification"] = verification(st, p, inp, chosen, cal)
    else:
        out["verification"] = {"ran": False, "note": "verify=N slices the N best-ranked candidates with the real slicer and "
                                                     "reports the model's error in time and support filament."}
    return out


PUBLIC = ("rank", "id", "label", "down", "score", "score_terms", "objectives", "current", "fits", "rests_on_supports",
          "support_mm3", "support_mm3_spread", "support_contact_mm2", "support_on_part_mm2", "support_g", "time_s",
          "time_parts", "filament_g", "layers", "contact_mm2", "tip_over_deg", "com_height_mm", "height_mm",
          "footprint_mm", "overhang_mm2", "strength", "cosmetic_cusp_um", "cosmetic_cusp_max_um",
          "cosmetic_supported_mm2", "cosmetic_on_plate_mm2", "integrated")


def _public(r: dict) -> dict:
    def rnd(v):
        if isinstance(v, float):
            return round(v, 4 if abs(v) < 10 else 2)
        if isinstance(v, dict):
            return {k: rnd(x) for k, x in v.items()}
        if isinstance(v, list):
            return [rnd(x) for x in v]
        return v
    return {k: rnd(r[k]) for k in PUBLIC if k in r}


# ---- the real slicer: calibration and verification ---------------------------------------------------------------

def gcode_features(path) -> dict:
    """Net filament length (mm of filament) per slicer feature of a G-code file: {"feature": mm, ...}."""
    out: dict[str, float] = {}
    feat, rel, last = "", True, 0.0
    with open(path, errors="ignore", encoding="utf-8") as f:
        for line in f:
            c = line[:1]
            if c == ";":
                if line.startswith("; FEATURE:"):
                    feat = line[10:].strip()
                elif line.startswith(";TYPE:"):
                    feat = line[6:].strip()
                continue
            if c == "M":
                if line.startswith("M83"):
                    rel = True
                elif line.startswith("M82"):
                    rel = False
                continue
            if c != "G":
                continue
            i = line.find(" E")
            if i < 0:
                continue
            head = line[:3]
            if head.startswith("G92"):
                try:
                    last = float(line[i + 2:].split()[0].split(";")[0])
                except (ValueError, IndexError):
                    pass
                continue
            if head not in ("G1 ", "G0 ", "G2 ", "G3 "):
                continue
            try:
                e = float(line[i + 2:].split()[0].split(";")[0])
            except (ValueError, IndexError):
                continue
            de = e if rel else e - last
            if not rel:
                last = e
            out[feat] = out.get(feat, 0.0) + de
    return out


def _with_supports(s: dict, critical_deg: float) -> tuple:
    """The slicer info with supports switched on in the process preset: normal supports from the plate and the part,
    at the same critical angle. Returns (info, what was set) or (None, why not)."""
    proc = ((s.get("presets") or {}).get("process") or {})
    data = proc.get("data")
    if not s.get("available") or not isinstance(data, dict):
        return None, "The slicer cannot run here: " + str(s.get("reason") or "none is set up.")
    thr = str(int(round(90.0 - critical_deg)))
    if "enable_support" in data or "support_threshold_angle" in data or "wall_loops" in data:       # Bambu Studio, OrcaSlicer and forks
        setv = {"enable_support": "1", "support_type": "normal(auto)", "support_threshold_angle": thr,
                "support_on_build_plate_only": "0", "support_style": "default"}
    elif "support_material" in data or "perimeters" in data:                                         # PrusaSlicer family
        setv = {"support_material": "1", "support_material_auto": "1", "support_material_threshold": thr,
                "support_material_buildplate_only": "0"}
    else:
        return None, "This slicer's process preset has no support settings Form Studio knows."
    new = dict(data)
    new.update(setv)
    out = dict(s)
    out["presets"] = {**s["presets"], "process": {**proc, "data": new}}
    return out, setv


def _slice(st, p: dict, inp: dict, oid: str) -> dict:
    """One orientation sliced by the real slicer with supports on. Cached under a key of the geometry, the
    orientation, the presets and the critical angle. Returns the slice's numbers, or {"error": why}."""
    from .. import slicer as slicer_mod
    from ..adapters.common import SlicerBlocked, SlicerFailed, dur, gcode_stats
    from ..studio import H
    crit = inp["settings"]["values"]["critical_deg"]
    res, setv = _with_supports(inp["slicer"], crit)
    if res is None:
        return {"error": setv}
    tag = [res.get("kind"), {k: [v.get("name"), v.get("sha")] for k, v in res["presets"].items()}, setv, res.get("version")]
    key = H("print-slice", VERSION, inp["gk"], oid, tag)
    base = st.dir(p["id"]) / "artifacts" / "print" / "slices"
    meta = base / f"{key}.json"
    if meta.is_file():
        try:
            return json.loads(meta.read_text(encoding="utf-8"))
        except ValueError:
            pass
    work = base / f"{key}.work"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    try:
        stl = work / "model.stl"
        st._k("print_stl", timeout=300, key=inp["gk"], recipe_id=st.rid(p), values=inp["rev"]["values"], orientation=oid,
              out=str(stl), p=p)
        try:
            info = slicer_mod.slice_stl(res, stl, work / "sliced", timeout=float(st.cfg["slicer"].get("timeout_s", 600)))
        except (SlicerBlocked, SlicerFailed) as e:
            return {"error": f"{type(e).__name__}: {e}", "orientation": oid}
        g = work / "sliced" / (info.get("gcode") or "plate_1.gcode")
        feats = gcode_features(g)
        stats = gcode_stats(g)
        total = sum(feats.values())
        sup = sum(v for k, v in feats.items() if "support" in k.lower())
        model_t = dur(stats["model_time"]) if stats.get("model_time") else None
        out = {"orientation": oid, "time_s": info.get("time_s"), "model_time_s": model_t, "filament_g": info.get("filament_g"),
               "support_g": (info["filament_g"] * sup / total) if info.get("filament_g") and total > 0 else None,
               "support_share": (sup / total) if total > 0 else None, "support_used": info.get("support_used"),
               "layers": info.get("layers"), "slicer": info.get("slicer_name"), "slicer_version": info.get("slicer_version"),
               "presets": info.get("presets"), "set_for_this_slice": setv, "seconds": info.get("seconds"),
               "features_mm": {k: round(v, 1) for k, v in sorted(feats.items()) if abs(v) > 0.05},
               "evidence": "simulated (the slicer's own slice)", "ts": time.time()}
        tmp = meta.with_name(meta.name + ".tmp")
        tmp.write_text(json.dumps(out), encoding="utf-8")
        tmp.replace(meta)
        return out
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _slicer_time(sl: dict):
    """The time a slice is compared by: the model's own printing time when the slicer states it apart from the
    printer's start-up routine, else its total."""
    return (sl.get("model_time_s"), "model printing time") if sl.get("model_time_s") else (sl.get("time_s"), "total time")


def _calibration(st, p: dict, inp: dict, rows: list, calibrate) -> dict:
    """{"factors": {"time", "mass"} | None, "how": ..., "on": orientation}."""
    none = {"factors": None, "how_known": "uncalibrated", "note": "No real slice was used: the times are the model's "
            "own, from the speeds listed in settings. They rank orientations; the absolute time is not to be trusted."}
    if calibrate in (False, "off", "none", 0):
        return none
    row = next((r for r in rows if r.get("current")), None)
    if row is None:
        return none
    if calibrate == "auto" and not _slice_cached(st, p, inp, row["id"]):
        return {**none, "note": none["note"] + " calibrate=True slices the current orientation once and scales the model by it."}
    sl = _slice(st, p, inp, row["id"])
    if sl.get("error"):
        return {**none, "note": f"Calibration slice failed ({sl['error']}); the model is uncalibrated."}
    t_sl, t_what = _slicer_time(sl)
    un = row["uncalibrated"]
    if not t_sl or not sl.get("filament_g") or un["time_s"] <= 0 or un["filament_g"] <= 0:
        return {**none, "note": "The calibration slice reported no time or filament; the model is uncalibrated."}
    f = {"time": t_sl / un["time_s"], "mass": sl["filament_g"] / un["filament_g"]}
    return {"factors": {k: round(v, 4) for k, v in f.items()}, "how_known": "calibrated on one real slice",
            "on": row["id"], "on_label": row.get("label"), "slicer": sl.get("slicer"), "slicer_version": sl.get("slicer_version"),
            "slicer_time_s": t_sl, "slicer_time_is": t_what, "slicer_filament_g": sl["filament_g"],
            "model_time_s": round(un["time_s"], 1), "model_filament_g": round(un["filament_g"], 3), "slice": sl,
            "note": f"Time x {f['time']:.3f} and filament x {f['mass']:.3f}: the slicer's {t_what} and grams over the model's, "
                    f"for the current orientation ({row.get('label')}), supports on. One slice, one factor each; the error "
                    "on other orientations is what verify measures."}


def _slice_cached(st, p, inp, oid) -> bool:
    from ..studio import H
    res, setv = _with_supports(inp["slicer"], inp["settings"]["values"]["critical_deg"])
    if res is None:
        return False
    tag = [res.get("kind"), {k: [v.get("name"), v.get("sha")] for k, v in res["presets"].items()}, setv, res.get("version")]
    return (st.dir(p["id"]) / "artifacts" / "print" / "slices" / f"{H('print-slice', VERSION, inp['gk'], oid, tag)}.json").is_file()


def verification(st, p: dict, inp: dict, top: list, cal: dict) -> dict:
    """Slice the top candidates and compare the slicer's time and support grams with the prediction."""
    rows, t_err, g_err, g_abs = [], [], [], []
    for r in top:
        sl = _slice(st, p, inp, r["id"])
        if sl.get("error"):
            if not rows:
                return {"ran": False, "note": f"The slicer could not verify the candidates: {sl['error']}"}
            rows.append({"id": r["id"], "label": r.get("label"), "error": sl["error"]})
            continue
        t_sl, t_what = _slicer_time(sl)
        is_cal = bool(cal.get("factors") and cal.get("on") == r["id"])
        row = {"rank": r.get("rank"), "id": r["id"], "label": r.get("label"), "calibration_slice": is_cal,
               "on_front": bool(r.get("on_front")), "current": bool(r.get("current")),
               "time_s": {"predicted": round(r["time_s"], 1), "slicer": t_sl, "slicer_time_is": t_what,
                          "error": round((r["time_s"] - t_sl) / t_sl, 4) if t_sl else None},
               "support_g": {"predicted": round(r["support_g"], 3), "slicer": round(sl["support_g"], 3) if sl.get("support_g") is not None else None,
                             "error_g": round(r["support_g"] - sl["support_g"], 3) if sl.get("support_g") is not None else None,
                             "error": (round((r["support_g"] - sl["support_g"]) / sl["support_g"], 4)
                                       if sl.get("support_g") and sl["support_g"] >= 0.1 else None)},
               "filament_g": {"predicted": round(r["filament_g"], 3), "slicer": sl.get("filament_g"),
                              "error": round((r["filament_g"] - sl["filament_g"]) / sl["filament_g"], 4) if sl.get("filament_g") else None},
               "slicer_support_used": sl.get("support_used"), "slicer_seconds": sl.get("seconds")}
        rows.append(row)
        if not is_cal and row["time_s"]["error"] is not None:
            t_err.append(abs(row["time_s"]["error"]))
        if row["support_g"]["error_g"] is not None:
            g_abs.append(abs(row["support_g"]["error_g"]))
        if row["support_g"]["error"] is not None:
            g_err.append(abs(row["support_g"]["error"]))
    ok = [x for x in rows if "error" not in x]
    first = next((x for x in ok), None)
    sl0 = _slice(st, p, inp, first["id"]) if first else {}
    return {"ran": True, "evidence": "simulated (the slicer's own slices) against modelled", "candidates": rows,
            "slicer": sl0.get("slicer"), "slicer_version": sl0.get("slicer_version"), "presets": sl0.get("presets"),
            "set_for_these_slices": sl0.get("set_for_this_slice"),
            "calibrated": bool(cal.get("factors")),
            "time_error": {"mean_abs": round(float(np.mean(t_err)), 4) if t_err else None,
                           "max_abs": round(float(np.max(t_err)), 4) if t_err else None, "over": len(t_err),
                           "note": "relative error of the predicted time, over the verified candidates that are not the "
                                   "calibration slice" + ("" if cal.get("factors") else " (the model is uncalibrated)")},
            "support_error": {"mean_abs_g": round(float(np.mean(g_abs)), 3) if g_abs else None,
                              "max_abs_g": round(float(np.max(g_abs)), 3) if g_abs else None,
                              "mean_abs_relative": round(float(np.mean(g_err)), 4) if g_err else None, "over": len(g_abs),
                              "note": "support filament: the slicer's is its support, support-interface and support-"
                                      "transition extrusion read from the G-code; relative error only where the slicer "
                                      "used 0.1 g or more. The model is the support columns' volume at the preset's "
                                      "pattern spacing plus its interface layers: where the only supports are small "
                                      "(inside holes), the slicer's own minimum structures dominate and the model "
                                      "under-predicts."},
            "note": "A slice is a simulation, not a print."}


def pick(st, p: dict, orientation: str) -> dict:
    """Write the chosen orientation to the design's print setup (the person's pick, or the agent's on their word)."""
    from .. import analysis
    if not analysis.valid_orientation(orientation):
        raise _err("Unknown orientation.", "Use an id from print_orient's front, one of: " + ", ".join(analysis.NAMED)
                   + ", or a “down:x,y,z” id.")
    was = p["orientation"]
    st.settings(p, {"orientation": orientation})
    with st.lock(p["id"]):
        cur = st.load(p["id"])
        cur.setdefault("print", {}).setdefault("orient", {})["picked"] = {"orientation": orientation, "was": was,
                                                                             "rev": cur["head"], "ts": time.time()}
        st.save(cur)
    return {"orientation": orientation, "label": analysis.orientation_label(orientation), "was": was,
            "was_label": analysis.orientation_label(was), "changed": orientation != was,
            "note": "The print setup now uses this orientation. Exports, checks, the slice and layer-aware strength "
                    "studies that follow the setup are stale until they run again."}


def digest(r: dict, top: int = 5) -> dict:
    """A short reading of a result for a listing."""
    f = r.get("front") or []
    return {"recommended": r.get("recommended"), "front_size": r.get("front_size"),
            "candidates_evaluated": r.get("candidates_evaluated"), "front": f[:top], "current": r.get("current"),
            "calibration": r.get("calibration"), "verification": r.get("verification")}


def headline(r: dict) -> str:
    f = (r.get("front") or [None])[0]
    if not f:
        return "no orientation fits the bed"
    cur = r.get("current") or {}
    tail = "" if f.get("current") else (f" · now: {cur.get('label')}" if cur else "")
    return (f"{r.get('front_size')} on the front · first: {f['label']} ({f['support_mm3']:.0f} mm³ support, "
            f"{f['time_s'] / 60:.0f} min{'' if (r.get('calibration') or {}).get('factors') else ' uncalibrated'}){tail}")
