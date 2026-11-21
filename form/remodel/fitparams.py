"""fit_params: tune a design's DECLARED Params so it lies closer to the reference mesh, and keep the result only if it
is closer.

Only the Params the design declares are varied, each inside its own min and max and at most `max_change` mm from its
current value; the design's code is never changed and nothing is fitted that the design does not name. The method is
generic bounded nonlinear least squares (scipy.optimize.least_squares, trust-region reflective, forward differences
with an absolute step per Param) on a fixed-length residual vector:

    the distance from fixed points sampled on the mesh to the design's surface, and the distance from a fixed number
    of points sampled on the design's surface (one seeded draw per build) to the mesh, each side weighted equally.

Every evaluation is a real build of the design by the kernel (a candidate, never a revision). At the end the best
values found, and the same values rounded to each Param's step, are compared with the starting values on the same
measure; the change is kept only if the mean distance drops and the largest distance does not grow. Otherwise the
design is left exactly as it was ("kept": false). It can therefore never make the deviation worse.

Evidence: computed (the design's tessellation against the mesh as given). Fitted values are recorded with provenance
"mesh": computed from an imported mesh, not measured.
"""
from __future__ import annotations

import math
import time

import numpy as np

SIDE_SAMPLES = 4000          # points drawn on the design's surface per build (fixed, so the vector has one length)
MAX_PARAMS = 8
NOISE_MM = 0.002          # mean distances closer than this are the same (tessellation chords), not a gain


def fit(evaluate, x0, lo, hi, step, max_evals: int = 60) -> dict:
    """Bounded least squares of evaluate(x) -> residual vector (or None when x does not build). Generic: it knows
    nothing about CAD. Returns {"x", "evals", "history"} with the best point evaluated (never worse than x0)."""
    from scipy.optimize import least_squares
    x0 = np.asarray(x0, dtype=np.float64)
    lo, hi, step = (np.asarray(a, dtype=np.float64) for a in (lo, hi, step))
    cache: dict = {}
    hist = []
    first = evaluate(x0)
    if first is None:
        raise ValueError("The design does not build at its current values.")
    first = np.asarray(first, dtype=np.float64)
    m = len(first)
    big = 10.0 * max(float(np.abs(first).max()), 1.0)
    cache[tuple(np.round(x0, 9))] = first
    hist.append((x0.copy(), float(np.sqrt(np.mean(first ** 2)))))

    class Stop(Exception):
        pass

    def f(x):
        key = tuple(np.round(x, 9))
        if key in cache:
            return cache[key]
        if len(cache) >= max_evals:
            raise Stop()
        r = evaluate(np.asarray(x, dtype=np.float64))
        r = np.full(m, big) if r is None or len(r) != m else np.asarray(r, dtype=np.float64)
        cache[key] = r
        hist.append((np.asarray(x, dtype=np.float64).copy(), float(np.sqrt(np.mean(r ** 2)))))
        return r

    def jac(x):
        r0 = f(x)
        J = np.empty((m, len(x)))
        for i in range(len(x)):
            h = step[i] if x[i] + step[i] <= hi[i] else -step[i]
            xi = x.copy()
            xi[i] += h
            J[:, i] = (f(xi) - r0) / h
        return J

    try:
        least_squares(f, x0, jac=jac, bounds=(lo, hi), method="trf", x_scale=np.maximum(step * 10, 1e-6),
                      xtol=1e-4, ftol=1e-6, max_nfev=max_evals)
    except Stop:
        pass
    best = min(hist, key=lambda t: t[1])
    return {"x": best[0], "evals": len(cache), "history": [(list(map(float, x)), s) for x, s in hist]}


class Measure:
    """The fixed residual vector between the mesh and one design build, and its summary numbers."""

    def __init__(self, V, F, spacing: float | None = None):
        from ..recon.distance import MeshDistance, sample_surface
        diag = float(np.linalg.norm(np.ptp(V, axis=0)))
        self.spacing = spacing or max(diag / 250, 0.05)
        S, _, _ = sample_surface(V, F, self.spacing)
        if len(S) > 20000:
            S = S[np.random.default_rng(0).choice(len(S), 20000, replace=False)]
        self.SA = S
        self.mesh = MeshDistance(V, F, self.spacing)

    def vector(self, P, T) -> np.ndarray:
        from ..recon.distance import MeshDistance
        md = MeshDistance(P, T, self.spacing)
        dA = md.closest(self.SA)[0]
        a, b, c = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
        area = np.linalg.norm(np.cross(b - a, c - a), axis=1)
        rng = np.random.default_rng(1)
        t = rng.choice(len(T), SIDE_SAMPLES, p=area / area.sum())
        u, v = rng.random(SIDE_SAMPLES), rng.random(SIDE_SAMPLES)
        flip = u + v > 1
        u[flip], v[flip] = 1 - u[flip], 1 - v[flip]
        SB = a[t] + u[:, None] * (b[t] - a[t]) + v[:, None] * (c[t] - a[t])
        dB = self.mesh.closest(SB)[0]
        return np.r_[dA / math.sqrt(len(dA)), dB / math.sqrt(len(dB))], float(max(dA.max(), dB.max())), \
            float(np.r_[dA, dB].mean())


def fit_design(st, p: dict, reference: str, params: list | None = None, part: str | None = None,
               max_change: float = 2.0, commit: bool = True, expect_head: int | None = None,
               max_evals: int = 60) -> dict:
    """Fit the design's declared Params to an imported mesh; commit the result as a revision only when it is closer."""
    from ..studio import H, StudioError
    from . import analyze as an
    from . import compare as cmp
    from .project import _ref
    rec, path = _ref(st, p, reference)
    recipe = st.recipe(p)
    head = st.rev(p)
    if expect_head is not None and p["head"] != expect_head:
        raise StudioError(f"The design moved on: head is r{p['head']}, not r{expect_head}.",
                          "Read the project again, then fit again.", status=409, head=p["head"])
    specs = {s.key: s for s in recipe.params}
    if params:
        bad = [k for k in params if k not in specs]
        if bad:
            raise StudioError("Not a declared Param of this design: " + ", ".join(bad) + ".",
                              "fit_params varies only the Params the design declares (get_project lists them).")
        keys = list(dict.fromkeys(params))
    else:
        keys = [k for k, s in specs.items() if s.unit == "mm"]
    keys = [k for k in keys if k in head["values"]]
    if not keys:
        raise StudioError("This design declares no Param in mm to fit.", "Declare the dimensions that matter as Params.")
    if len(keys) > MAX_PARAMS:
        raise StudioError(f"{len(keys)} Params to fit; at most {MAX_PARAMS} at once.",
                          "Name the ones the residual points at: params=[...].")
    if not (0 < float(max_change) <= 50):
        raise StudioError("max_change: between 0 and 50 mm.")
    base = dict(head["values"])
    x0 = np.array([float(base[k]) for k in keys])
    lo = np.array([max(float(specs[k].min), x0[i] - max_change) for i, k in enumerate(keys)])
    hi = np.array([min(float(specs[k].max), x0[i] + max_change) for i, k in enumerate(keys)])
    lo, hi = np.minimum(lo, x0), np.maximum(hi, x0)
    stp = np.array([max(min(float(specs[k].step or 0.05), 0.05), 0.01) for k in keys])
    V, F, _ = an.load(path)
    meas = Measure(V, F)
    tess = max(min(0.01, meas.spacing / 4), 0.003)
    rid = st.rid(p)
    stats: dict = {}
    t0 = time.time()

    def build(x):
        vals = {**base, **{k: float(v) for k, v in zip(keys, x)}}
        try:
            view = st._k("view", key="fit-" + H(rid, vals, tess), recipe_id=rid, values=vals, tol=tess, p=p, timeout=300)
            P, T = cmp.design_mesh(view, part)
        except (StudioError, ValueError):
            return None
        return meas.vector(P, T)

    def evaluate(x):
        out = build(x)
        if out is None:
            return None
        vec, mx, mean = out
        stats[tuple(np.round(x, 9))] = (mx, mean)
        return vec

    try:
        res = fit(evaluate, x0, lo, hi, stp, max_evals=max_evals)
    except ValueError as e:
        raise StudioError(str(e), "Fix the build first (get_project shows why).") from None
    before = stats[tuple(np.round(x0, 9))]
    best = res["x"]
    bst = stats.get(tuple(np.round(best, 9)), before)
    # the designer's grid: the same values rounded to each Param's step, kept when they are as good
    rounded = np.array([min(max(round(v / float(specs[k].step or 0.01)) * float(specs[k].step or 0.01), lo[i]), hi[i])
                        for i, (k, v) in enumerate(zip(keys, res["x"]))])
    if not np.allclose(rounded, res["x"]):
        evaluate(rounded)
        s = stats.get(tuple(np.round(rounded, 9)))
        if s is not None and s[1] <= bst[1] * 1.02 + NOISE_MM and s[0] <= bst[0] + 2 * NOISE_MM:
            best, bst = rounded, s
    gain = bst[1] < before[1] - max(1e-3 * before[1], NOISE_MM) and bst[0] <= before[0]
    fitted = {k: round(float(v), 4) for k, v in zip(keys, best if gain else x0)}
    out = {"evidence": "computed (the design's tessellation against the mesh as given; every evaluation a real build)",
           "reference": rec["file"], "part": part, "params": keys,
           "from": {k: float(base[k]) for k in keys}, "to": fitted,
           "bounds": {k: [round(float(lo[i]), 4), round(float(hi[i]), 4)] for i, k in enumerate(keys)},
           "deviation_before": {"max_mm": round(before[0], 4), "mean_mm": round(before[1], 4)},
           "deviation_after": {"max_mm": round((bst if gain else before)[0], 4),
                               "mean_mm": round((bst if gain else before)[1], 4)},
           "builds": len(stats), "seconds": round(time.time() - t0, 1),
           "kept": bool(gain), "method": "bounded least squares (scipy least_squares, trf) over the declared Params"}
    if not gain:
        out["verdict"] = ("No gain: no values inside the bounds bring the design closer to the mesh, so nothing "
                          "changed. The difference is in the shape, not the sizes: read reference_residual.")
        out["rev"] = p["head"]
        return out
    changed = {k: v for k, v in fitted.items() if abs(v - float(base[k])) > 1e-9}
    if commit and changed:
        prov = {k: {"source": "mesh", "note": f"fitted to {rec['file']} by fit_params"} for k in changed}
        note = "Fitted " + ", ".join(f"{k} {base[k]:g} -> {v:g}" for k, v in changed.items()) + f" to {rec['file']}"
        if all(k in p["revisions"][0]["values"] for k in changed):
            q = st.commit(p, changed, note=note, origin="fit_params", provenance=prov, expect_head=p["head"])
        else:
            # Params added by a later source revision: Studio.commit checks keys against the first revision, so
            # the values go in as a revision of the same source, then their provenance as its own small revision
            q = st.update_design(p, st.source_text(p), note=note, values=changed, origin="fit_params",
                                 expect_head=p["head"])
            q = st.commit(q, {}, note=f"Provenance: fitted to {rec['file']}", origin="fit_params", provenance=prov,
                          expect_head=q["head"])
        out["rev"] = q["head"]
        out["committed"] = True
    else:
        out["rev"] = p["head"]
        out["committed"] = False
    out["verdict"] = (f"Closer: mean distance {before[1]:.4f} -> {bst[1]:.4f} mm, largest {before[0]:.4f} -> "
                      f"{bst[0]:.4f} mm" + (f"; committed as r{out['rev']}." if out["committed"] else
                                             " (not committed: commit=false).")
                      + " Check with compare_to_reference.")
    return out
