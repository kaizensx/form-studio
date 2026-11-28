"""One strength study from geometry to a result with its stated error (runs in the FEA engine's Python).

    result, field = run(geometry, spec, progress=None, cancelled=None)

`spec` (millimetres, newtons, MPa; every face is {"samples": [[x, y, z], ...], "area": mm2}, points on the face):

    {"kind": "static" | "modal" | "buckling" | "thermal",
     "materials": [{"name", "E": MPa, "nu", "density": kg/m3, "yield": MPa | None, "k": W/(m K), "cte": 1/K,
                    "centre": [x, y, z]}],   # one per solid
     "thermal": {"reference": C, "conditions": [...]},   # form/fea/thermal.py; with kind "static": thermal stress
     "fixtures": [{"type": "fixed" | "roller" | "pin", "faces": [...], "axis": [x, y, z] (pin)},
                  {"type": "hold", "faces": [...], "directions": [[x, y, z], ...]}],   # no movement along these;
                                                # with "faces_b": only on the edge the two face sets share
     "loads": [{"type": "force", "faces": [...], "vector": [Fx, Fy, Fz]},          # N, spread evenly over the faces
               {"type": "pressure", "faces": [...], "value": MPa},                 # pushes on the face
               {"type": "preload", "faces": [...], "faces_b": [...], "force": N},  # a clamping pair, see below
               {"type": "gravity", "vector": [gx, gy, gz]}],                       # mm/s2 (9806.65 for 1 g)
     "modes": 6, "mesh": {"h0", "levels_max", "dof_max", "budget_s", "tol_disp", "tol_stress", "tol_freq",
                          "singular_radius"}}

What makes the result honest:

* **Refinement until it stops changing.** The solid is meshed again, finer, at least three times. For a static study
  the next mesh is finer where the error indicator of the last one is large (Zienkiewicz-Zhu stress recovery), so
  fillets, holes and load paths get the elements. Every level is kept: unknowns, strain energy, largest displacement,
  peak von Mises stress and the indicator. The stated error of a quantity is twice its last change (or the
  remaining change by Aitken's extrapolation, when larger) where the levels shrink steadily, and twice the larger
  of the last two changes where they go up and down (twice their sum where they move one way without shrinking).
  It is an estimate with a margin, not a bound. A study that does not reach its tolerance says so (`converged: false`) and gives no safety factor.
* **Singularities are named.** At a sharp inside corner the elastic stress is unbounded: the number there grows with
  every refinement and means nothing. Such edges are found on the mesh (two faces meeting at more than 180 degrees
  inside the solid), refinement is held back there, and stress within `singular_radius` of them is left out of the
  peak and the safety factor, and reported as left out. The edge of a fixed face and the edge of a loaded face are
  treated the same way when the peak is there and the stress there rises at each of the last two refinements, by
  more than 8 % in all. A zone that is left out stays out.
* **Equilibrium is checked.** The reactions at the supports balance the applied loads to a stated residual; a study
  that fails the balance fails.
* **A hand estimate beside it.** Where the part reads as a prismatic bar fixed at one end, the beam-theory stress
  and deflection are given next to the simulated ones (form/fea/hand.py; evidence: computed, closed form).
* **Supports must hold the part.** A static or buckling study whose supports leave a rigid motion free is refused,
  with the number of free motions.

Bolt preload is a modelled connector: two equal and opposite forces pressing the two face sets towards each other
along the line between their centres. The bolt itself (its stiffness, the loss of preload when the joint opens) is not
in the model. Several solids are bonded where their faces touch (a shared mesh); sliding or opening contact is not
modelled.
"""
from __future__ import annotations

import base64
import time

import numpy as np

from . import mesh as mesh_mod
from . import solve as S

ENGINE_VERSION = 1
G0 = 9806.65                                   # standard gravity, mm/s2
DEFAULTS = {"levels_min": 3, "levels_max": 7, "dof_max": 600_000, "budget_s": 90.0, "tol_disp": 0.01,
            "tol_stress": 0.05, "tol_freq": 0.01, "tol_buckling": 0.02, "tol_temp": 0.01, "growth": 2.4, "balance": 1e-6}
EIG_DOF_MAX = 160_000                          # modal and buckling: many solves with one matrix, factored once
GLOBAL_SHRINK = 0.85                           # the largest element allowed shrinks by this at every refinement
MIN_GROWTH = 1.5                               # a refinement has at least this many times the elements of the last
GROWTH = 0.08                                  # stress at a fixture or load edge that rises this much over two
                                               # refinements, and at each, is growing without bound, not converging
MARGIN = 2.0                                   # the stated error is this times the change the refinements show
REENTRANT_DEG = 15.0                           # faces meeting at an inside corner sharper than this are singular
ASSUMPTIONS = ["linear elastic material (stress proportional to strain; no yielding, creep or fatigue)",
               "small strain and small displacement (the load does not change the shape it acts on)",
               "isotropic, homogeneous material in each solid (a printed part: solid, no layers or infill)",
               "curved faces are followed by quadratic element sides, not exactly",
               "supports are rigid and loads are spread evenly over the picked faces",
               "several solids are bonded where they touch; sliding or opening contact is not modelled"]


THERMAL_ASSUMPTIONS = ["steady state: temperatures no longer change with time",
                       "conductivity and expansion do not change with temperature and are the same in every direction",
                       "no radiation; a face with no thermal condition is insulated"]


class StudyError(RuntimeError):
    def __init__(self, message: str, hint: str = "", kind: str = "study"):
        super().__init__(message)
        self.hint, self.kind = hint, kind


def _b64(a: np.ndarray) -> str:
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode("ascii")


# ---- the model on one mesh ---------------------------------------------------------------------------------------

class Model:
    """Faces, materials, supports and loads of a spec, resolved on one mesh."""

    def __init__(self, geo, m, spec, faces):
        self.geo, self.m, self.spec, self.faces = geo, m, spec, faces
        self.sp = S.Space(m)
        self.surf = mesh_mod.surface(m)
        mats = spec["materials"]
        dom = self._domains(mats)
        self.dom_mat = dom
        md = dom[m.dom]
        self.E = np.array([mats[k]["E"] for k in range(len(mats))], float)[md]
        self.nu = np.array([mats[k]["nu"] for k in range(len(mats))], float)[md]
        self.rho = np.array([(mats[k].get("density") or 0.0) * 1e-12 for k in range(len(mats))], float)[md]
        ys = [mats[k].get("yield") for k in range(len(mats))]
        self.has_yield = all(y for y in ys)
        self.yld = np.array([float(y) if y else np.nan for y in ys])[md]
        self.lam, self.mu = S.lame(self.E, self.nu)
        self.dom = m.dom if len(np.unique(m.dom)) > 1 else None
        # thermal: conductivity W/(mm K) and expansion 1/K per element (0 where the material has none sourced)
        self.k = np.array([(mats[i].get("k") or 0.0) * 1e-3 for i in range(len(mats))], float)[md]
        self.alpha = np.array([(mats[i].get("cte") or 0.0) for i in range(len(mats))], float)[md]
        self.has_cte = all(mats[i].get("cte") for i in range(len(mats)))

    def _domains(self, mats) -> np.ndarray:
        """Material number of each mesh solid: the material whose solid centre is nearest."""
        cs = mesh_mod.solid_centres(self.geo)
        if len(mats) == 1:
            return np.zeros(len(cs), dtype=int)
        if any(not mt.get("centre") for mt in mats):
            raise StudyError("A study of several solids needs each material's solid (its centre).")
        pts = np.array([mt["centre"] for mt in mats], float)
        return np.array([int(np.argmin(np.linalg.norm(pts - np.array(c["centre"]), axis=1))) for c in cs])

    def tris(self, face_ids) -> np.ndarray:
        return np.where(np.isin(self.m.face, list(face_ids)) & self.surf["outside"])[0]

    def node_normals(self, tris):
        """Nodes of the triangles and the outward normal of the (curved) surface at each."""
        return self.sp.node_normals(tris)

    def constraints(self) -> S.Constraints:
        con = S.Constraints(self.sp)
        for fx, ids in zip(self.spec.get("fixtures") or [], self.faces["fixtures"]):
            ids_b = None
            if isinstance(ids, tuple):
                ids, ids_b = ids
            tr = self.tris(ids)
            if len(tr) == 0:
                raise StudyError("A support's face has no triangles on the outside of the mesh.")
            if fx["type"] == "fixed":
                con.fix(self.sp.tri_nodes(tr).ravel())
            elif fx["type"] == "roller":
                nodes, nrm = self.node_normals(tr)
                con.hold(nodes, nrm)
            elif fx["type"] == "pin":
                ax = np.asarray(fx["axis"], float)
                ax /= np.linalg.norm(ax)
                nodes, nrm = self.node_normals(tr)
                nrm = nrm - (nrm @ ax)[:, None] * ax[None, :]
                nrm /= np.maximum(np.linalg.norm(nrm, axis=1), 1e-300)[:, None]
                con.hold(nodes, nrm)
                con.hold(nodes, ax)
            elif fx["type"] == "hold":
                nodes = np.unique(self.sp.tri_nodes(tr))
                if ids_b is not None:                     # only the edge the two face sets share
                    nodes = np.intersect1d(nodes, np.unique(self.sp.tri_nodes(self.tris(ids_b))))
                    if len(nodes) == 0:
                        raise StudyError("The two face sets of a support share no edge.")
                for d in fx["directions"]:
                    d = np.asarray(d, float)
                    con.hold(nodes, d / np.linalg.norm(d))
            else:
                raise StudyError(f"Unknown support type “{fx['type']}” (fixed, roller, pin, hold).")
        return con

    def face_centre(self, tris):
        a, b, c = (self.m.P[self.m.S[tris][:, i]] for i in range(3))
        w = self.surf["area"][tris]
        return ((a + b + c) / 3 * w[:, None]).sum(axis=0) / w.sum()

    def load_vector(self) -> tuple[np.ndarray, list]:
        f = np.zeros(self.sp.ndof)
        info = []
        for ld, ids in zip(self.spec.get("loads") or [], self.faces["loads"]):
            t = ld["type"]
            if t == "gravity":
                if not np.any(self.rho > 0):
                    raise StudyError("Gravity needs the material's density.")
                fi = self.sp.body(self.rho, ld["vector"])
            elif t == "force":
                tr = self.tris(ids)
                area = self.sp.tri_area(tr).sum()
                fi = self.sp.traction(tr, np.asarray(ld["vector"], float) / area)
            elif t == "pressure":
                tr = self.tris(ids)
                fi = self.sp.traction(tr, pressure=float(ld["value"]))
            elif t == "preload":
                ta, tb = self.tris(ids[0]), self.tris(ids[1])
                d = self.face_centre(tb) - self.face_centre(ta)
                if ld.get("axis"):
                    ax = np.asarray(ld["axis"], float)
                    d = ax * np.sign(ax @ d or 1.0)
                d = d / np.linalg.norm(d)
                N = float(ld["force"])
                fi = self.sp.traction(ta, N * d / self.sp.tri_area(ta).sum()) + \
                    self.sp.traction(tb, -N * d / self.sp.tri_area(tb).sum())
            else:
                raise StudyError(f"Unknown load type “{t}” (force, pressure, preload, gravity).")
            f += fi
            info.append({"type": t, "resultant_N": [float(x) for x in fi.reshape(-1, 3).sum(axis=0)]})
        return f, info

    def zones(self, fixed_ids, load_ids, line_pairs=()) -> dict:
        """Distance of every node to: sharp inside corners, edges of fixed faces, edges of loaded faces."""
        e = mesh_mod.face_edges(self.m, self.surf)
        P, X = self.m.P, self.sp.X
        sharp = e["reentrant"] & (e["angle_deg"] > REENTRANT_DEG)
        in_fix = np.isin(e["f1"], fixed_ids) ^ np.isin(e["f2"], fixed_ids)
        for a, b in line_pairs:                                  # a support along a line
            in_fix |= (np.isin(e["f1"], a) & np.isin(e["f2"], b)) | (np.isin(e["f1"], b) & np.isin(e["f2"], a))
        in_load = np.isin(e["f1"], load_ids) ^ np.isin(e["f2"], load_ids)

        def dist(mask):
            v = e["v"][mask]
            return mesh_mod.distance_to_segments(X, P[v[:, 0]], P[v[:, 1]]).astype(np.float32)
        out = {"corner": dist(sharp), "fixture": dist(in_fix & ~sharp), "load": dist(in_load & ~sharp & ~in_fix)}
        self.sharp_segments = (P[e["v"][sharp][:, 0]], P[e["v"][sharp][:, 1]])
        return out


def _resolve_faces(geo, m, spec) -> dict:
    def many(refs):
        out = []
        for r in refs or []:
            out.extend(mesh_mod.faces_at(m, r, geo.diag))
        return sorted(set(out))
    fx = [(many(f.get("faces")), many(f["faces_b"])) if f.get("faces_b") else many(f.get("faces"))
          for f in spec.get("fixtures") or []]
    ld = []
    for ld_ in spec.get("loads") or []:
        if ld_["type"] == "preload":
            ld.append((many(ld_.get("faces")), many(ld_.get("faces_b"))))
        elif ld_["type"] == "gravity":
            ld.append([])
        else:
            ld.append(many(ld_.get("faces")))
    th = [many(c.get("faces")) for c in (spec.get("thermal") or {}).get("conditions") or []]
    return {"fixtures": fx, "loads": ld, "thermal": th}


def _free_rigid_motions(model: Model, con: S.Constraints) -> int:
    Q, fixed = con.build()
    if len(fixed) == 0:
        return 6
    B = model.sp.rigid_modes()
    B = B / np.linalg.norm(B, axis=0)
    C = (Q.T @ B)[fixed]
    s = np.linalg.svd(C, compute_uv=False)
    return int(6 - (s > 1e-6 * max(s.max(), 1e-300)).sum())


# ---- convergence -------------------------------------------------------------------------------------------------

def series(values: list) -> dict:
    """How a quantity converged over the refinements: its last value, the change over the last refinement, and the
    stated error.

    * The last three levels shrink steadily (same direction, ratio r < 0.9): MARGIN x the last change, or the
      remaining change by Aitken's extrapolation (last change x r / (1 - r)) when that is larger. The extrapolated
      value is given.
    * They go up and down (a peak read off a mesh does not converge smoothly): MARGIN x the larger of the last two
      changes, so one small step between two meshes does not read as convergence.
    * They move the same way without shrinking (r >= 0.9): nothing to extrapolate from; MARGIN x the sum of the
      last two changes, marked "not_shrinking". Growth without bound (a singularity) shows as changes far above any
      tolerance, so it reads as not converged."""
    v = [float(x) for x in values]
    out = {"values": v, "value": v[-1], "change": None, "error": None, "extrapolated": None, "ratio": None}
    if len(v) < 2 or v[-1] == 0:
        return out
    d1 = v[-1] - v[-2]
    out["change"] = abs(d1) / abs(v[-1])
    err = MARGIN * out["change"]
    if len(v) >= 3:
        d0 = v[-2] - v[-3]
        r = d1 / d0 if d0 != 0 else 0.0
        out["ratio"] = r
        if 0 < r < 0.9:
            rest = d1 * r / (1 - r)
            out["extrapolated"] = v[-1] + rest
            err = max(err, abs(rest) / abs(v[-1]))
        elif r >= 0.9 and out["change"] > 1e-9:
            err = MARGIN * (abs(d1) + abs(d0)) / abs(v[-1])
            out["not_shrinking"] = True
        else:
            err = MARGIN * max(abs(d1), abs(d0)) / abs(v[-1])
    out["error"] = err
    return out


def _next_field(model: Model, eta: np.ndarray, growth: float, hold: np.ndarray | None, hold_h: float):
    """The size field for the next mesh: smaller where the error indicator is large, about `growth` x the elements."""
    m = model.m
    h = mesh_mod.element_sizes(m)
    cen = m.P[m.T].mean(axis=1)
    tau = np.sqrt((eta ** 2).sum() / len(eta))
    base = (tau / np.maximum(eta, 1e-300)) ** (2.0 / 7.0)           # eta_e ~ h^(p + d/2), p = 2, d = 3
    lo, hi = 0.05, 20.0
    for _ in range(40):                                              # the factor that gives the wanted growth
        c = np.sqrt(lo * hi)
        ratio = np.clip(c * base, 0.4, 1.0)
        if (ratio ** -3).sum() > growth * len(eta):
            lo = c
        else:
            hi = c
    ratio = np.clip(np.sqrt(lo * hi) * base, 0.4, 1.0)
    hn = h * ratio
    if hold is not None:                                             # no chasing of a singular corner
        hn = np.where(hold, np.maximum(hn, np.minimum(h, hold_h)), hn)
    # Netgen restricts the size at points: give it every node of the mesh (the smallest target of the elements
    # that share it) and every centroid, so the field is dense enough to be followed
    d = model.sp.edofs
    node_h = np.full(model.sp.N, np.inf)
    np.minimum.at(node_h, d, hn[None, :])
    sizes = np.concatenate([hn, node_h])
    # three significant figures: the next mesh does not depend on the last digits of an iterative solve
    mag = 10.0 ** (np.floor(np.log10(np.maximum(sizes, 1e-12))) - 2)
    return np.concatenate([cen, model.sp.X]), np.round(sizes / mag) * mag


def _element(model: Model) -> str:
    sp = model.sp
    if sp.curved:
        return "10-node tetrahedron (quadratic displacement; isoparametric, mid-side nodes on the geometry)"
    return "10-node tetrahedron (quadratic displacement, straight sides" + \
        (f": {sp.curved_note}" if sp.curved_note else "") + ")"


def _where(model: Model, node: int) -> dict:
    x = model.sp.X[node]
    return {"at": [round(float(t), 4) for t in x]}


# ---- the static study --------------------------------------------------------------------------------------------

def _static_level(model: Model, cancelled, direct: bool | None = None) -> dict:
    t0 = time.perf_counter()
    sp = model.sp
    K = sp.stiffness(model.lam, model.mu)
    f, loads = model.load_vector()
    thermal_info = T = th_el = None
    if model.spec.get("thermal"):                        # the temperature field first, then its expansion as a load
        from . import thermal as thermal_mod
        if not model.has_cte:
            raise StudyError("Thermal stress needs the thermal expansion coefficient of every solid's material.")
        T, thermal_info = thermal_mod.solve(model, model.faces)
        dT = T - float(model.spec["thermal"].get("reference", 20.0))
        beta = (3 * model.lam + 2 * model.mu) * model.alpha
        f = f + sp.thermal_load(beta, dT)
        th_el = beta[:, None] * dT[sp.edofs.T]
    con = model.constraints()
    free = _free_rigid_motions(model, con)
    if free:
        raise StudyError(f"The supports leave {free} rigid motion{'s' if free > 1 else ''} free: the part can still move "
                         "or turn as a whole, so a static result does not exist.",
                         "Add a fixed face, or rollers and pins that together stop it sliding and turning in every "
                         "direction.", kind="unconstrained")
    if not np.any(f):
        raise StudyError("No load: every load is zero.", "Give a force, a pressure, a preload or gravity." if T is None
                         else "The temperature equals the reference temperature everywhere, so nothing expands.")
    t1 = time.perf_counter()
    system = S.System(sp, K, con, cancelled)
    if direct is not None:
        system.prepare(direct=direct)
    r = S.solve_static(system, f)
    t2 = time.perf_counter()
    st = sp.stress(r["u"], model.lam, model.mu, model.dom, thermal=th_el)
    vm = S.von_mises(st["nodal"])
    unorm = np.linalg.norm(r["u"].reshape(-1, 3), axis=1)
    eta_rel = float(np.sqrt((st["eta"] ** 2).sum() / max(2 * r["energy"] + (st["eta"] ** 2).sum(), 1e-300)))
    return {"system": system, "K": K, "f": f, "loads": loads, "sol": r, "stress": st, "vm": vm, "unorm": unorm,
            "eta_rel": eta_rel, "T": T, "thermal": thermal_info, "seconds": {"assemble": t1 - t0, "solve": t2 - t1, "stress": time.perf_counter() - t2}}


def _utilisation(model: Model, st: dict) -> np.ndarray | None:
    """Von Mises stress over yield at every node (the largest over the solids that share it)."""
    if not model.has_yield:
        return None
    sp = model.sp
    vme = S.von_mises(st["element"]) / model.yld[:, None]            # per element at its own nodes
    util = np.zeros(sp.N)
    if model.dom is None:
        return S.von_mises(st["nodal"]) / model.yld[0]
    w = np.zeros(sp.N)
    d = sp.edofs.T
    for k in np.unique(model.dom):
        sel = model.dom == k
        acc, w = np.zeros(sp.N), np.zeros(sp.N)
        np.add.at(w, d[sel], sp.vol[sel][:, None])
        np.add.at(acc, d[sel], vme[sel] * sp.vol[sel][:, None])
        has = w > 0
        acc[has] /= w[has]
        util = np.maximum(util, acc)
    return util


def _assess(levels: list, rz: float, tol: dict, already: list | None = None) -> dict:
    """Peak stress outside the singular zones over the levels, adding the fixture and load edges when the stress
    there is what keeps growing. already: zones left out at an earlier refinement. A zone stays out once it is out:
    refinement is held back there afterwards, so its stress no longer grows, and that must not read as converged."""
    excluded = ["corner"] if np.isfinite(levels[-1]["zones"]["corner"]).any() else []
    excluded += [z for z in (already or []) if z not in excluded]
    candidates = [z for z in ("fixture", "load") if z not in excluded]
    while True:
        peaks, nodes = [], []
        for lv in levels:
            ok = np.ones(len(lv["vm"]), bool)
            for z in excluded:
                ok &= lv["zones"][z] > rz
            if not ok.any():
                ok[:] = True
            k = int(np.argmax(np.where(ok, lv["vm"], -1)))
            peaks.append(float(lv["vm"][k]))
            nodes.append(k)
        s = series(peaks)
        done = len(levels) >= 3 and s["error"] is not None and s["error"] <= tol["tol_stress"]
        if done or len(levels) < 3 or not candidates:
            return {"series": s, "excluded": excluded, "node": nodes[-1], "ok": done}
        last = levels[-1]

        def grows(z):                                    # rising at each of the last two refinements, by GROWTH in all
            v = [float(np.where(x["zones"][z] <= rz, x["vm"], 0).max()) for x in levels[-3:]]
            return v[0] < v[1] < v[2] and v[2] - v[0] > GROWTH * v[2]
        near = [z for z in candidates if last["zones"][z][nodes[-1]] <= rz and grows(z)]
        if not near:
            return {"series": s, "excluded": excluded, "node": nodes[-1], "ok": False}
        excluded.append(near[0])
        candidates.remove(near[0])


_ZONE_TEXT = {
    "corner": ("sharp inside corner",
               "Two faces meet at a sharp inside corner. The elastic stress there has no finite value: it grows with "
               "every refinement. Add a fillet to get a real number, or read the stress outside the radius given."),
    "fixture": ("edge of a held face, or a support along a line",
                "The stress at the edge of a rigidly held face (or along a line support) keeps growing with "
                "refinement: a perfectly rigid support is a model, and its edge is a singular line. The real support "
                "gives a little."),
    "load": ("edge of a loaded face",
             "The stress at the edge of a loaded face keeps growing with refinement: the load ends abruptly there, or "
             "the face is so small that it acts as a point load."),
}


def run_static(geo, spec, progress, cancelled) -> tuple[dict, dict]:
    opt = {**DEFAULTS, **(spec.get("mesh") or {})}
    rz = float(opt.get("singular_radius") or max(0.02 * geo.diag, 0.5))
    h0 = float(opt.get("h0") or geo.diag / 12.0)
    t_start = time.perf_counter()
    levels, field, faces, last_dt = [], None, None, 0.0
    stop, left_out = "", []
    while True:
        if cancelled():
            raise StudyError("Cancelled.", kind="cancelled")
        n = len(levels)
        progress(f"Meshing, refinement {n + 1}", min(0.95, n / 6))
        tl = time.perf_counter()
        hn = h0 * GLOBAL_SHRINK ** n
        m = mesh_mod.generate(geo, hn, field=field)
        for _ in range(4):                                       # a refinement that did not refine is not one
            if not levels or len(m.T) >= MIN_GROWTH * levels[-1]["record"]["tets"]:
                break
            field = (field[0], field[1] * 0.8)
            hn *= 0.9
            m = mesh_mod.generate(geo, hn, field=field)
        if levels and len(m.T) < MIN_GROWTH * levels[-1]["record"]["tets"]:
            stop = "Netgen did not make a finer mesh"
            break
        if faces is None:
            faces = _resolve_faces(geo, m, spec)
        model = Model(geo, m, spec, faces)
        progress(f"Solving refinement {n + 1}: {model.sp.ndof:,} unknowns", min(0.95, (n + 0.4) / 6))
        lv = _static_level(model, cancelled)
        fixed_ids, line_pairs = set(), []
        for fx, ids in zip(spec.get("fixtures") or [], faces["fixtures"]):
            if isinstance(ids, tuple):                           # held only on the edge two face sets share: a line
                line_pairs.append(ids)
            elif fx["type"] in ("fixed", "hold"):
                fixed_ids |= set(ids)
        fixed_ids = sorted(fixed_ids)
        load_ids = sorted({i for ld, ids in zip(spec.get("loads") or [], faces["loads"]) if ld["type"] in ("force", "pressure")
                           for i in ids} | {i for ld, ids in zip(spec.get("loads") or [], faces["loads"]) if ld["type"] == "preload"
                                            for i in list(ids[0]) + list(ids[1])})
        lv["zones"] = model.zones(fixed_ids, load_ids, line_pairs)
        lv["model"] = model
        lv["util"] = _utilisation(model, lv["stress"])
        sol = lv["sol"]
        lv["record"] = {"level": n + 1, "h_mean_mm": round(m.info["h_mean"], 4), "h_min_mm": round(m.info["h_min"], 4),
                        "tets": m.info["tets"], "nodes": int(model.sp.N), "unknowns": int(model.sp.ndof),
                        "strain_energy_mJ": float(sol["energy"]), "max_displacement_mm": float(lv["unorm"].max()),
                        "max_von_mises_MPa_anywhere": float(lv["vm"].max()),
                        "error_indicator": lv["eta_rel"], "force_balance": sol["force_residual"],
                        "moment_balance": sol["moment_residual"], "solver": lv["system"].method,
                        "iterations": int(lv["system"].iterations),
                        "seconds": round(time.perf_counter() - tl, 3), "mesh_seconds": round(m.seconds, 3),
                        "mesh_quality_min": round(m.info["quality_min"], 4), "curved_elements": bool(model.sp.curved)}
        if lv.get("T") is not None:
            lv["record"].update({"t_max_C": lv["thermal"]["t_max_C"], "t_min_C": lv["thermal"]["t_min_C"]})
        for old in levels:                                       # only the finest level keeps its matrices
            for k in ("system", "K", "f", "model", "stress", "sol"):
                old.pop(k, None)
        levels.append(lv)
        last_dt = time.perf_counter() - tl
        peak = _assess(levels, rz, opt, left_out)
        left_out = list(peak["excluded"])
        disp = series([x["record"]["max_displacement_mm"] for x in levels])
        lv["record"]["peak_von_mises_MPa"] = peak["series"]["value"]
        if len(levels) >= opt["levels_min"] and peak["ok"] and disp["error"] <= opt["tol_disp"]:
            break
        if len(levels) >= opt["levels_max"]:
            stop = f"the limit of {opt['levels_max']} refinements was reached"
            break
        if model.sp.ndof * opt["growth"] > opt["dof_max"]:
            stop = f"the next mesh would pass the limit of {opt['dof_max']:,} unknowns"
            break
        if time.perf_counter() - t_start + 3.0 * last_dt > opt["budget_s"]:
            stop = f"the time budget of {opt['budget_s']:.0f} s would be passed by the next refinement"
            break
        # no chasing of a singular line: sharp inside corners from the start, a fixture's or a load's edge once the
        # stress there has been seen to grow without settling
        hold = np.zeros(model.sp.nel, bool)
        for z in set(peak["excluded"]) | {"corner"}:
            hold |= lv["zones"][z][model.sp.edofs[:4]].min(axis=0) <= rz
        field = _next_field(model, lv["stress"]["eta"], opt["growth"], hold if hold.any() else None, rz / 4.0)
    return _static_result(geo, spec, opt, rz, levels, stop, time.perf_counter() - t_start, left_out)


def _static_result(geo, spec, opt, rz, levels, stop, seconds, left_out) -> tuple[dict, dict]:
    lv = levels[-1]
    model: Model = lv["model"]
    sol = lv["sol"]
    if _KEEP is not None:
        _KEEP.update(model=model, u=sol["u"].reshape(-1, 3), stress=lv["stress"]["nodal"], vm=lv["vm"])
    peak = _assess(levels, rz, opt, left_out)
    for x, v in zip(levels, peak["series"]["values"]):           # with the zones that were left out in the end
        x["record"]["peak_von_mises_MPa"] = v
    disp = series([x["record"]["max_displacement_mm"] for x in levels])
    energy = series([x["record"]["strain_energy_mJ"] for x in levels])
    balanced = max(sol["force_residual"], sol["moment_residual"]) <= opt["balance"] * 1e3
    conv_disp = disp["error"] is not None and disp["error"] <= opt["tol_disp"] and len(levels) >= 3
    converged = bool(peak["ok"] and conv_disp and balanced)
    ok_nodes = np.ones(model.sp.N, bool)
    singular = []
    for z in peak["excluded"]:
        inside = lv["zones"][z] <= rz
        if not inside.any():
            continue
        ok_nodes &= ~inside
        k = int(np.argmax(np.where(inside, lv["vm"], -1)))
        grow = [float(np.where(x["zones"][z] <= rz, x["vm"], 0).max()) for x in levels]
        singular.append({"kind": z, "label": _ZONE_TEXT[z][0], "why": _ZONE_TEXT[z][1], **_where(model, k),
                         "stress_there_MPa_by_refinement": [round(g, 3) for g in grow],
                         "left_out_within_mm": round(rz, 3),
                         "nodes_left_out": int(inside.sum())})
    node = peak["node"]
    out = {
        "kind": "static", "engine_version": ENGINE_VERSION, "converged": converged, "seconds": round(seconds, 2),
        "stopped_because": stop or "every tolerance was met",
        "convergence": {"levels": [x["record"] for x in levels],
                        "max_displacement": disp, "peak_von_mises": peak["series"], "strain_energy": energy,
                        "tolerance": {"displacement": opt["tol_disp"], "stress": opt["tol_stress"]},
                        "error_indicator_last": lv["eta_rel"],
                        "method": "h-refinement: the solid is meshed again, finer where the Zienkiewicz-Zhu stress-"
                                  "recovery indicator is large; the stated error is twice the last change (or "
                                  "Aitken's remaining change, when larger) where the levels shrink steadily, and "
                                  "twice the larger of the last two changes where they go up and down. An estimate "
                                  "with a margin, not a bound."},
        "max_displacement_mm": disp["value"], "max_displacement_at": _where(model, int(np.argmax(lv["unorm"])))["at"],
        "peak_von_mises_MPa": peak["series"]["value"], "peak_at": _where(model, node)["at"],
        "discretisation_error": {"stress": peak["series"]["error"], "displacement": disp["error"],
                                 "energy_norm_indicator": lv["eta_rel"]},
        "singularities": singular,
        "equilibrium": {"force_residual": sol["force_residual"], "moment_residual": sol["moment_residual"],
                        "balanced": bool(balanced), "applied_N": [float(x) for x in sol["applied"]],
                        "reaction_N": [float(x) for x in sol["reaction"]], "tolerance": opt["balance"] * 1e3},
        "loads": lv["loads"],
        "mesh": {"element": _element(model), "mesher": "Netgen",
                 "tets": lv["record"]["tets"], "nodes": lv["record"]["nodes"], "unknowns": lv["record"]["unknowns"],
                 "h_mean_mm": lv["record"]["h_mean_mm"], "h_min_mm": lv["record"]["h_min_mm"],
                 "solids": geo.solids, "bonded": bool(geo.glued)},
        "model": "linear static", "assumptions": ASSUMPTIONS,
    }
    sf_field = None
    if lv["util"] is not None:
        util = lv["util"]
        with np.errstate(divide="ignore"):
            sf_field = np.where(util > 0, 1.0 / np.maximum(util, 1e-300), np.inf)
        umax = float(np.where(ok_nodes, util, 0).max())
        if converged and umax > 0:
            err = peak["series"]["error"] or 0.0
            out["safety_factor"] = {"value": 1.0 / umax, "low": 1.0 / (umax * (1 + err)), "against": "yield",
                                    "at": _where(model, int(np.argmax(np.where(ok_nodes, util, 0))))["at"],
                                    "note": "yield strength over the peak von Mises stress outside the singular zones; "
                                            "`low` applies the stated discretisation error"}
        else:
            out["safety_factor"] = None
            out["safety_factor_withheld"] = "The study did not converge, so no safety factor is given."
    else:
        out["safety_factor"] = None
        out["safety_factor_withheld"] = "No yield strength is sourced for the material, so no safety factor is given."
    if not converged:
        why = []
        if not peak["ok"]:
            e = peak["series"]["error"]
            why.append("the peak stress still changes by " + (f"{100 * e:.1f} %" if e is not None else "an unknown amount")
                       + f" per refinement at {out['peak_at']} (tolerance {100 * opt['tol_stress']:.0f} %)")
        if not conv_disp:
            why.append("the displacement has not settled" if len(levels) >= 3 else "fewer than three refinements were solved")
        if not balanced:
            why.append("the reactions do not balance the loads")
        out["not_converged_because"] = "; ".join(why) + (f". Stopped because {stop}." if stop else ".")
    out["evidence"] = evidence(out)
    try:                                                 # a second opinion that does not share the solver
        from . import hand
        out["hand_estimate"] = hand.estimate(model, spec, model.faces, sol["u"].reshape(-1, 3), out["peak_von_mises_MPa"])
    except Exception as e:                               # noqa: BLE001 - the estimate is an extra, never a failure
        out["hand_estimate"] = {"applies": False, "why": f"the estimate could not be made ({type(e).__name__}: {e})"}
    data = {"displacement": sol["u"].reshape(-1, 3), "von_mises": lv["vm"], "safety_factor": sf_field, "singular": ~ok_nodes}
    if lv.get("T") is not None:
        out["thermal"] = {**lv["thermal"], "reference_C": float(spec["thermal"].get("reference", 20.0)),
                          "temperature_by_refinement": [x["record"].get("t_max_C") for x in levels]}
        out["model"] = "linear static with thermal strain from a steady temperature field"
        out["assumptions"] = out["assumptions"] + THERMAL_ASSUMPTIONS
        out["equilibrium"]["note"] = ("Thermal expansion is a self-balanced load: the applied resultant counts the "
                                      "mechanical loads only.")
        data["temperature"] = lv["T"]
        out["evidence"] = evidence(out)
    fld = _surface_field(model, data)
    return out, fld


def evidence(r: dict) -> str:
    kind = {"static": "thermal stress" if r.get("thermal") else "linear static", "modal": "modal",
            "buckling": "linear buckling", "thermal": "steady heat"}[r["kind"]]
    if not r.get("converged"):
        return f"simulated (FEA, {kind}, not converged)"
    e = {"static": (r.get("discretisation_error") or {}).get("stress"),
         "modal": (r.get("discretisation_error") or {}).get("frequency"),
         "buckling": (r.get("discretisation_error") or {}).get("load_factor"),
         "thermal": (r.get("discretisation_error") or {}).get("temperature")}[r["kind"]]
    return f"simulated (FEA, {kind}, converged to {max(100 * (e or 0), 0.1):.1f} %)"


# ---- what the viewport colours -----------------------------------------------------------------------------------

def _surface_field(model: Model, data: dict) -> dict:
    """The outside surface of the finest mesh with per-vertex results (see FIELD_FORMAT)."""
    m = model.m
    tr = np.where(model.surf["outside"])[0]
    S3 = m.S[tr].copy()
    n = model.surf["normal"][tr]
    a, b, c = m.P[S3[:, 0]], m.P[S3[:, 1]], m.P[S3[:, 2]]
    flip = np.einsum("ij,ij->i", np.cross(b - a, c - a), n) < 0      # outward winding
    S3[flip] = S3[flip][:, [0, 2, 1]]
    used, inv = np.unique(S3.ravel(), return_inverse=True)
    nodes = model.sp._vdof[used]
    out = {"format": FIELD_FORMAT, "version": 1, "units": {"length": "mm", "stress": "MPa", "frequency": "Hz"},
           "vertices": int(len(used)), "triangles": int(len(S3)),
           "positions": _b64(m.P[used].astype("<f4")), "indices": _b64(inv.reshape(-1, 3).astype("<u4")),
           "face": _b64(m.face[tr].astype("<u4")), "fields": {}, "ranges": {}}
    for name, arr in data.items():
        if arr is None:
            continue
        a_ = np.asarray(arr)[nodes] if np.asarray(arr).shape[0] == model.sp.N else np.asarray(arr)[:, nodes]
        if a_.dtype == bool:
            out["fields"][name] = {"type": "u1", "components": 1, "data": _b64(a_.astype("u1"))}
            continue
        comps = 1 if a_.ndim == 1 else a_.shape[-1]
        finite = a_[np.isfinite(a_)]
        out["fields"][name] = {"type": "f4", "components": comps, "data": _b64(a_.astype("<f4"))}
        if a_.ndim > 1 and a_.shape[0] != len(used):
            out["fields"][name]["count"] = int(a_.shape[0])
        if len(finite):
            out["ranges"][name] = [float(finite.min()), float(finite.max())]
    return out


FIELD_FORMAT = "form.fea.field/1"
_KEEP: dict | None = None


# ---- modal and buckling ------------------------------------------------------------------------------------------

def _uniform_levels(geo, spec, opt, progress, cancelled, solve_level, tol, label):
    """Refinement by a smaller size everywhere (x 0.72 per level), for studies driven by a global quantity."""
    h0 = float(opt.get("h0") or geo.diag / 10.0)
    t_start = time.perf_counter()
    levels, faces, stop = [], None, ""
    while True:
        if cancelled():
            raise StudyError("Cancelled.", kind="cancelled")
        n = len(levels)
        h = h0 * 0.72 ** n if not levels else levels[-1]["h"] * 0.72
        progress(f"Meshing, refinement {n + 1}", min(0.95, n / 5))
        tl = time.perf_counter()
        m = mesh_mod.generate(geo, h)
        for _ in range(8):                                       # a refinement that did not refine is not one
            if not levels or len(m.T) >= 1.8 * levels[-1]["record"]["tets"]:
                break
            h *= 0.8
            m = mesh_mod.generate(geo, h)
        if faces is None:
            faces = _resolve_faces(geo, m, spec)
        model = Model(geo, m, spec, faces)
        if levels and model.sp.ndof > opt["dof_max"]:
            stop = f"the next mesh would pass the limit of {opt['dof_max']:,} unknowns"
            break
        progress(f"Solving refinement {n + 1}: {model.sp.ndof:,} unknowns", min(0.95, (n + 0.4) / 5))
        lv = solve_level(model)
        lv["model"], lv["h"] = model, h
        lv["record"].update({"level": n + 1, "h_mean_mm": round(m.info["h_mean"], 4), "tets": m.info["tets"],
                             "curved_elements": bool(model.sp.curved),
                             "nodes": int(model.sp.N), "unknowns": int(model.sp.ndof),
                             "seconds": round(time.perf_counter() - tl, 3), "mesh_seconds": round(m.seconds, 3)})
        for old in levels:
            old.pop("model", None)
            old.pop("modes", None)
        levels.append(lv)
        dt = time.perf_counter() - tl
        vals = np.array([x["values"] for x in levels], float)        # (levels, k)
        ss = [series(vals[:, i]) for i in range(vals.shape[1])]
        if len(levels) >= opt["levels_min"] and all(s["error"] is not None and s["error"] <= tol for s in ss[:label]):
            break
        if len(levels) >= opt["levels_max"]:
            stop = f"the limit of {opt['levels_max']} refinements was reached"
            break
        if model.sp.ndof * 2.0 > opt["dof_max"]:
            stop = f"the next mesh would pass the limit of {opt['dof_max']:,} unknowns"
            break
        if time.perf_counter() - t_start + 4.0 * dt > opt["budget_s"]:
            stop = f"the time budget of {opt['budget_s']:.0f} s would be passed by the next refinement"
            break
    return levels, stop, time.perf_counter() - t_start


def run_modal(geo, spec, progress, cancelled) -> tuple[dict, dict]:
    opt = {**DEFAULTS, "dof_max": EIG_DOF_MAX, **(spec.get("mesh") or {})}
    k = int(spec.get("modes") or 6)

    def level(model: Model):
        if not np.all(model.rho > 0):
            raise StudyError("A modal study needs the density of every solid's material.")
        sp = model.sp
        K = sp.stiffness(model.lam, model.mu)
        M = sp.mass(model.rho)
        con = model.constraints()
        free = _free_rigid_motions(model, con)
        if free not in (0, 6):
            raise StudyError(f"The supports leave {free} rigid motion{'s' if free > 1 else ''} free. A modal study is "
                             "either of a held part (no rigid motion) or of a free one (no supports at all).",
                             "Remove every support for free-free modes, or hold the part fully.", kind="unconstrained")
        system = S.System(sp, K, con, cancelled)
        mats = spec["materials"]
        c = min(np.sqrt(mt["E"] / (mt["density"] * 1e-12)) for mt in mats)      # slowest bar wave speed, mm/s
        r = S.solve_modal(system, M, k, free_body=(free == 6), w_ref=0.1 * c / geo.diag)
        return {"values": [float(x) for x in r["hz"]], "modes": r["modes"], "free_body": free == 6,
                "record": {"frequencies_Hz": [float(x) for x in r["hz"]], "solver": r["method"],
                           "mass_g": float(M.sum() / 3 * 1e6)}}
    levels, stop, seconds = _uniform_levels(geo, spec, opt, progress, cancelled, level, opt["tol_freq"], k)
    lv = levels[-1]
    model = lv["model"]
    vals = np.array([x["values"] for x in levels], float)
    ss = [series(vals[:, i]) for i in range(vals.shape[1])]
    worst = max((s["error"] if s["error"] is not None else np.inf) for s in ss)
    converged = len(levels) >= 3 and worst <= opt["tol_freq"]
    out = {"kind": "modal", "engine_version": ENGINE_VERSION, "converged": bool(converged), "seconds": round(seconds, 2),
           "stopped_because": stop or "every tolerance was met", "free_body": lv["free_body"],
           "frequencies_Hz": [s["value"] for s in ss],
           "modes": [{"mode": i + 1, "frequency_Hz": s["value"], "extrapolated_Hz": s["extrapolated"], "error": s["error"]}
                     for i, s in enumerate(ss)],
           "mass_g": lv["record"]["mass_g"],
           "convergence": {"levels": [x["record"] for x in levels], "frequencies": ss, "tolerance": {"frequency": opt["tol_freq"]},
                           "method": "h-refinement: the solid is meshed again at 0.72 x the size, everywhere; the stated "
                                     "error is twice the last change (or Aitken's remaining change, when larger) "
                                     "where the levels shrink steadily, and twice the larger of the last two changes "
                                     "where they go up and down. An estimate with a margin, not a bound."},
           "discretisation_error": {"frequency": None if not np.isfinite(worst) else worst},
           "mesh": {"element": _element(model), "mesher": "Netgen",
                    "tets": lv["record"]["tets"], "nodes": lv["record"]["nodes"], "unknowns": lv["record"]["unknowns"],
                    "h_mean_mm": lv["record"]["h_mean_mm"], "solids": geo.solids, "bonded": bool(geo.glued)},
           "model": "modal (undamped natural frequencies, consistent mass)",
           "assumptions": ASSUMPTIONS + ["no damping; no prestress from loads (loads are ignored in a modal study)"]}
    if not converged:
        out["not_converged_because"] = (f"a frequency still changes by {100 * worst:.2f} % per refinement" if np.isfinite(worst)
                                        else "fewer than three refinements were solved") + \
            (f". Stopped because {stop}." if stop else ".")
    out["evidence"] = evidence(out)
    modes = lv["modes"].reshape(lv["modes"].shape[0], -1, 3)
    modes = modes / np.maximum(np.abs(modes).max(axis=(1, 2), keepdims=True), 1e-300)       # shapes, largest = 1
    fld = _surface_field(model, {"modes": modes})
    fld["mode_frequencies_Hz"] = out["frequencies_Hz"]
    return out, fld


def run_buckling(geo, spec, progress, cancelled) -> tuple[dict, dict]:
    opt = {**DEFAULTS, "dof_max": EIG_DOF_MAX, **(spec.get("mesh") or {})}
    k = int(spec.get("modes") or 3)

    def level(model: Model):
        lv = _static_level(model, cancelled, direct=model.sp.ndof <= S.DIRECT_EIG_BELOW)   # factored once, used twice
        sp = model.sp
        sq = sp.element_stress_q(lv["sol"]["u"], model.lam, model.mu)
        r = S.solve_buckling(lv["system"], sp.geometric(sq), k)
        if len(r["factors"]) == 0:
            raise StudyError("Nothing in the part is in compression under these loads, so it does not buckle.",
                             "Buckling needs a compressive load path (a column pushed along its length, a thin wall "
                             "in compression).", kind="no_buckling")
        vals = [float(x) for x in r["factors"]] + [float("nan")] * (k - len(r["factors"]))
        return {"values": vals, "modes": r["modes"],
                "record": {"load_factors": [float(x) for x in r["factors"]], "solver": lv["system"].method,
                           "force_balance": lv["sol"]["force_residual"], "moment_balance": lv["sol"]["moment_residual"]}}
    levels, stop, seconds = _uniform_levels(geo, spec, opt, progress, cancelled, level, opt["tol_buckling"], 1)
    lv = levels[-1]
    vals = np.array([x["values"] for x in levels], float)
    ss = [series(vals[:, i]) for i in range(vals.shape[1]) if np.all(np.isfinite(vals[:, i]))]
    first = ss[0]
    converged = len(levels) >= 3 and first["error"] is not None and first["error"] <= opt["tol_buckling"]
    out = {"kind": "buckling", "engine_version": ENGINE_VERSION, "converged": bool(converged), "seconds": round(seconds, 2),
           "stopped_because": stop or "every tolerance was met",
           "load_factor": first["value"], "load_factor_extrapolated": first["extrapolated"],
           "load_factors": [s["value"] for s in ss],
           "meaning": "The loads as given, multiplied by the load factor, are the lowest at which the perfect elastic "
                      "part buckles. A real part buckles earlier: it is never perfectly straight, and its material "
                      "may yield first. A factor below 1 means it buckles under the loads as given.",
           "convergence": {"levels": [x["record"] for x in levels], "load_factors": ss,
                           "tolerance": {"load_factor": opt["tol_buckling"]},
                           "method": "h-refinement: the solid is meshed again at 0.72 x the size, everywhere; the stated "
                                     "error is twice the last change (or Aitken's remaining change, when larger) "
                                     "where the levels shrink steadily, and twice the larger of the last two changes "
                                     "where they go up and down. An estimate with a margin, not a bound."},
           "discretisation_error": {"load_factor": first["error"]},
           "mesh": {"element": _element(lv["model"]), "mesher": "Netgen",
                    "tets": lv["record"]["tets"], "nodes": lv["record"]["nodes"], "unknowns": lv["record"]["unknowns"],
                    "h_mean_mm": lv["record"]["h_mean_mm"], "solids": geo.solids, "bonded": bool(geo.glued)},
           "model": "linear (eigenvalue) buckling on the stress of the linear static solution",
           "assumptions": ASSUMPTIONS + ["a perfect shape with no imperfection; the load keeps its direction"]}
    if not converged:
        e = first["error"]
        out["not_converged_because"] = (f"the load factor still changes by {100 * e:.2f} % per refinement" if e is not None
                                        else "fewer than three refinements were solved") + \
            (f". Stopped because {stop}." if stop else ".")
    out["evidence"] = evidence(out)
    modes = lv["modes"].reshape(lv["modes"].shape[0], -1, 3)
    modes = modes / np.maximum(np.abs(modes).max(axis=(1, 2), keepdims=True), 1e-300)
    fld = _surface_field(lv["model"], {"modes": modes})
    fld["mode_load_factors"] = out["load_factors"]
    return out, fld


def run_thermal(geo, spec, progress, cancelled) -> tuple[dict, dict]:
    """Steady heat conduction: the temperature field, the heat through each condition and the heat balance."""
    from . import thermal as thermal_mod
    opt = {**DEFAULTS, "dof_max": 900_000, **(spec.get("mesh") or {})}

    def level(model: Model):
        T, info = thermal_mod.solve(model, model.faces)
        span = info["t_max_C"] - info["t_min_C"]
        return {"values": [span, info["heat_through_W"]], "T": T, "info": info,
                "record": {"t_max_C": info["t_max_C"], "t_min_C": info["t_min_C"], "heat_through_W": info["heat_through_W"],
                           "balance_residual": info["balance_residual"], "unknowns_scalar": int(model.sp.N)}}
    levels, stop, seconds = _uniform_levels(geo, spec, opt, progress, cancelled, level, opt["tol_temp"], 2)
    lv = levels[-1]
    model = lv["model"]
    vals = np.array([x["values"] for x in levels], float)
    ss = [series(vals[:, i]) for i in range(2)]
    errs = [s["error"] for s, v in zip(ss, vals[-1]) if abs(v) > 1e-12]
    worst = max(errs) if errs and all(e is not None for e in errs) else (0.0 if not errs else np.inf)
    balanced = lv["info"]["balance_residual"] <= 1e-6
    converged = len(levels) >= 3 and worst <= opt["tol_temp"] and balanced
    info = lv["info"]
    out = {"kind": "thermal", "engine_version": ENGINE_VERSION, "converged": bool(converged), "seconds": round(seconds, 2),
           "stopped_because": stop or "every tolerance was met",
           "t_max_C": info["t_max_C"], "t_min_C": info["t_min_C"],
           "t_max_at": _where(model, int(np.argmax(lv["T"])))["at"], "t_min_at": _where(model, int(np.argmin(lv["T"])))["at"],
           "heat_through_W": info["heat_through_W"], "conditions": info["conditions"],
           "heat_balance": {"residual": info["balance_residual"], "balanced": bool(balanced),
                            "note": "heat in through the conditions against heat out, as a share of the heat through"},
           "convergence": {"levels": [x["record"] for x in levels], "temperature_span": ss[0], "heat_through": ss[1],
                           "tolerance": {"temperature": opt["tol_temp"]},
                           "method": "h-refinement: the solid is meshed again at 0.72 x the size, everywhere; the stated "
                                     "error is twice the last change (or Aitken's remaining change, when larger) "
                                     "where the levels shrink steadily, and twice the larger of the last two changes "
                                     "where they go up and down. An estimate with a margin, not a bound."},
           "discretisation_error": {"temperature": None if not np.isfinite(worst) else float(worst)},
           "mesh": {"element": _element(model), "mesher": "Netgen", "tets": lv["record"]["tets"], "nodes": lv["record"]["nodes"],
                    "unknowns": int(model.sp.N), "h_mean_mm": lv["record"]["h_mean_mm"], "solids": geo.solids,
                    "bonded": bool(geo.glued)},
           "model": "steady heat conduction", "assumptions": THERMAL_ASSUMPTIONS +
           ["several solids are in perfect thermal contact where they touch"]}
    if not converged:
        out["not_converged_because"] = (("the heat balance does not close" if not balanced else
                                         f"the temperature span or the heat flow still changes by {100 * worst:.2f} % per refinement"
                                         if np.isfinite(worst) else "fewer than three refinements were solved")
                                        + (f". Stopped because {stop}." if stop else "."))
    out["evidence"] = evidence(out)
    if _KEEP is not None:
        _KEEP.update(model=model, T=lv["T"])
    fld = _surface_field(model, {"temperature": lv["T"], "heat_flux": thermal_mod.flux(model, lv["T"]) * 1e6})
    fld["units"]["temperature"], fld["units"]["heat_flux"] = "degC", "W/m2"
    return out, fld


def run(geo, spec: dict, progress=None, cancelled=None, keep: dict | None = None) -> tuple[dict, dict]:
    """Solve a study on a mesh_mod.Geometry. Returns (result, field). Raises StudyError when the study cannot be set
    up (no such face, a part that is not held) and mesh_mod.MeshError when the solid cannot be meshed.
    keep: a dict that receives the finest level's model, displacement and stress (for probes in the verification)."""
    global _KEEP
    _KEEP = keep
    progress = progress or (lambda text, fraction=None: None)
    cancelled = cancelled or (lambda: False)
    kind = spec.get("kind", "static")
    if not spec.get("materials"):
        raise StudyError("A study needs a material (E and Poisson's ratio at least).")
    for mt in spec["materials"]:
        if kind == "thermal":
            if not (mt.get("k") and mt["k"] > 0):
                raise StudyError(f"Material “{mt.get('name', '?')}” needs a thermal conductivity k > 0.")
            mt.setdefault("E", 1.0)                      # not used by a heat study; the model carries the fields
            mt.setdefault("nu", 0.0)
        elif not (mt.get("E") and mt["E"] > 0) or mt.get("nu") is None or not (-1 < mt["nu"] < 0.5):
            raise StudyError(f"Material “{mt.get('name', '?')}” needs Young's modulus E > 0 and Poisson's ratio below 0.5.")
    try:
        fn = {"static": run_static, "modal": run_modal, "buckling": run_buckling, "thermal": run_thermal}[kind]
    except KeyError:
        raise StudyError(f"Unknown study kind “{kind}” (static, modal, buckling, thermal).") from None
    try:
        return fn(geo, spec, progress, cancelled)
    except S.SolveError as e:
        if str(e) == "cancelled":
            raise StudyError("Cancelled.", kind="cancelled") from None
        raise StudyError(str(e), kind="solver") from None
