"""Layer 2, gears: a spur gear in the mesh becomes a parametric gear (teeth, module, pressure angle). Beta.

The mesh is cut across its axis at mid-width. A spur gear's outline repeats once per tooth: the tooth count is the
strongest repetition of the radius round the axis (FFT), the tip and root radii are the largest and smallest radius.
The flanks are fitted as involutes of one base circle (least squares on every outline point between root and tip:
base radius, tooth thickness at the base circle, angular phase). With the standard tooth thickness (no profile shift)
the base radius and the thickness give the pressure angle and the module.

Two recipes are tried, each built and compared with the mesh:

1. the gear Form Studio makes (form.parts.spur_gear, py_gearworks), with module and pressure angle snapped to standard
   values: when the mesh is such a gear, this is it again, with its own Params;
2. an involute outline drawn from the fitted values (form.recon.ops.spur_gear_profile): tip and root as the mesh has
   them (straight across or on a circle).

The first one within the limit is the result. Values are "computed from mesh"; the module and pressure angle assume
no profile shift, and the report says so.
"""
from __future__ import annotations

import math
import time

import numpy as np

STANDARD_MODULES = [0.3, 0.4, 0.5, 0.6, 0.7, 0.75, 0.8, 0.9, 1.0, 1.125, 1.25, 1.375, 1.5, 1.75, 2.0, 2.25, 2.5, 2.75,
                    3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0, 7.0, 8.0, 9.0, 10.0]
STANDARD_ANGLES = [14.5, 20.0, 25.0]


def inv(a):
    return math.tan(a) - a


def inv_inverse(x):
    a = 0.3
    for _ in range(60):
        a -= (inv(a) - x) / (math.tan(a) ** 2)
        a = min(max(a, 1e-4), 1.4)
    return a


def slice_mesh(V, F, o, d):
    """Closed polylines where the plane (o, d) cuts the mesh."""
    s = (V - o) @ d
    s = np.where(np.abs(s) < 1e-12, 1e-12, s)
    sv = s[F]
    cross = (np.sign(sv).min(axis=1) < 0) & (np.sign(sv).max(axis=1) > 0)
    pts, segs = {}, []
    for t in np.flatnonzero(cross).tolist():
        tri = F[t]
        ends = []
        for i in range(3):
            a, b = int(tri[i]), int(tri[(i + 1) % 3])
            if (s[a] < 0) != (s[b] < 0):
                k = (min(a, b), max(a, b))
                if k not in pts:
                    w = s[a] / (s[a] - s[b])
                    pts[k] = V[a] + w * (V[b] - V[a])
                ends.append(k)
        if len(ends) == 2:
            segs.append(tuple(ends))
    nb = {}
    for a, b in segs:
        nb.setdefault(a, []).append(b)
        nb.setdefault(b, []).append(a)
    loops, used = [], set()
    for start in list(nb):
        if start in used:
            continue
        loop, prev, cur = [start], None, start
        used.add(start)
        while True:
            nxt = [q for q in nb[cur] if q != prev]
            if not nxt or nxt[0] == start or nxt[0] in used:
                break
            prev, cur = cur, nxt[0]
            loop.append(cur)
            used.add(cur)
        if len(loop) >= 3:
            loops.append(np.array([pts[k] for k in loop]))
    return loops


def _frame(d):
    t = np.array([1.0, 0, 0]) if abs(d[0]) < 0.9 else np.array([0, 1.0, 0])
    u = np.cross(t, d)
    u /= np.linalg.norm(u)
    return u, np.cross(d, u)


def analyse(V, F, d, tol):
    """Is the mesh a spur gear about direction d? Returns its fitted dimensions or None (with the reason)."""
    from scipy.optimize import least_squares
    d = d / np.linalg.norm(d)
    # the axis exactly: the faces across it (a gear's two flat sides), averaged over their facets
    from .mesh import tri_normals
    N, A = tri_normals(V, F)
    c = N @ d
    flat = np.abs(c) > math.cos(math.radians(3))
    if flat.any():
        m = (N[flat] * (np.sign(c[flat]) * A[flat])[:, None]).sum(axis=0)
        d = m / np.linalg.norm(m)
    s = V @ d
    s0, s1 = float(s.min()), float(s.max())
    width = s1 - s0
    if width <= 0:
        return None, "no width"
    # the outline at mid-width; its centre is the axis
    loops = slice_mesh(V, F, (0.5 * (s0 + s1)) * d, d)
    if not loops:
        return None, "the cut across the axis is empty"
    u, w = _frame(d)
    q2 = [np.c_[L @ u, L @ w] for L in loops]
    outer = max(q2, key=lambda Q: np.ptp(Q, axis=0).prod())
    c = outer.mean(axis=0)
    for _ in range(3):                                      # centre: the middle of the tip circle, refined
        r = np.linalg.norm(outer - c, axis=1)
        top = outer[r > np.percentile(r, 90)]
        A = np.c_[2 * top, np.ones(len(top))]
        sol, *_ = np.linalg.lstsq(A, (top ** 2).sum(1), rcond=None)
        c = sol[:2]
    rel = outer - c
    r = np.linalg.norm(rel, axis=1)
    th = np.arctan2(rel[:, 1], rel[:, 0])
    ra, rf = float(r.max()), float(r.min())
    if ra - rf < 0.05 * ra:
        return None, "the outline is round, not toothed"
    # tooth count: strongest repetition of r(theta)
    order = np.argsort(th)
    grid = np.linspace(-math.pi, math.pi, 4096, endpoint=False)
    rg = np.interp(grid, th[order], r[order], period=2 * math.pi)
    spec = np.abs(np.fft.rfft(rg - rg.mean()))
    z = int(np.argmax(spec[6:400]) + 6)
    if spec[z] < 0.2 * spec[1:].max() * 0.99 and spec[z] != spec[1:].max():
        return None, "no repeating teeth"
    # phase: the tooth centres are where r(theta) peaks, smoothed over a tooth
    ph = -math.atan2(np.sum(rg * np.sin(z * grid)), np.sum(rg * np.cos(z * grid))) / z
    pitch = 2 * math.pi / z
    m0 = 2 * ra / (z + 2)
    # the flanks: well above the root (fillets, undercut) and below the tip (rounding); refitted once the base
    # circle is known, since an involute starts there
    lo, hi = rf + 0.35 * (ra - rf), ra - 0.12 * (ra - rf)
    rb0 = 0.5 * m0 * z * math.cos(math.radians(20))
    x0 = [rb0, math.pi / (2 * z) + inv(math.radians(20)), 0.0]
    fit = None
    for _ in range(2):
        band = (r > lo) & (r < hi)
        if band.sum() < 4 * z:
            return None, "too few points on the flanks"
        R, T = r[band], th[band]
        rel_t = (T - ph + pitch / 2) % pitch - pitch / 2          # angle from the nearest tooth centre
        side = np.sign(rel_t)

        def resid(x):
            rb, half, dph = x
            a = np.arccos(np.clip(rb / R, -1, 1))
            model = side * (half - (np.tan(a) - a)) + dph
            return (rel_t - model) * R                            # tangential distance, mm
        x0[0] = min(x0[0], 0.995 * R.min())
        fit = least_squares(resid, x0, bounds=([0.3 * ra, 0.0, -pitch / 4], [0.999 * R.min(), pitch / 2, pitch / 4]))
        x0 = list(fit.x)
        lo = max(lo, 1.02 * fit.x[0])
    rb, half, dph = fit.x
    err = float(np.abs(fit.fun).max())
    phase = ph + dph
    alpha = inv_inverse(max(half - math.pi / (2 * z), 1e-6))
    module = 2 * rb / (z * math.cos(alpha))
    # tip and root shape
    gap = (th - phase) % pitch
    near_gap = np.abs(gap - pitch / 2) < 0.15 * pitch
    r_gap_mid = float(r[near_gap].min()) if near_gap.any() else rf
    r_start = max(rb, rf)
    a_s = math.acos(min(1.0, rb / r_start))
    flank_gap = pitch - 2 * (half - inv(a_s))                     # angle between neighbouring flank starts
    chord_mid = r_start * math.cos(flank_gap / 2)
    root = "chord" if abs(r_gap_mid - chord_mid) <= max(2 * tol, 0.02 * module) else "arc"
    near_tip = np.abs(((th - phase + pitch / 2) % pitch) - pitch / 2) < 0.05 * pitch
    r_tip_mid = float(r[near_tip].max()) if near_tip.any() else ra
    a_t = math.acos(min(1.0, rb / ra))
    tip_half = half - inv(a_t)
    tip = "arc" if abs(r_tip_mid - ra) < abs(r_tip_mid - ra * math.cos(tip_half)) else "chord"
    inner = [Q for Q in q2 if Q is not outer]
    bore = None
    if inner:
        Qb = min(inner, key=lambda Q: np.linalg.norm(Q.mean(axis=0) - c))
        rb_ = np.linalg.norm(Qb - c, axis=1)
        if np.ptp(rb_) < max(2 * tol, 0.01 * rb_.mean()):
            bore = 2 * float(rb_.mean())
    centre = c[0] * u + c[1] * w + s0 * d
    return {"teeth": z, "module": module, "pressure_angle": math.degrees(alpha), "base_r": rb, "half": half, "phase": phase,
            "tip_d": 2 * ra, "root_d": 2 * rf, "width": width, "tip": tip, "root": root, "bore": bore, "centre": centre,
            "d": d, "u": u, "w": w, "flank_fit_mm": err, "other_loops": len(inner) - (1 if bore else 0)}, ""


def _f(x):
    return f"{float(x):.6f}".rstrip("0").rstrip(".") if abs(float(x)) >= 5e-7 else "0"


def _v(p):
    return "(" + ", ".join(_f(x) for x in p) + ")"


def _src_parts(g, name, m, alpha, phase_deg):
    """The gear made the way Form Studio makes gears (form.parts.spur_gear, py_gearworks)."""
    bore = g["bore"] or 0.0
    return f'''"""{name}: reconstructed from a mesh by Form Studio (Layer 2, parametric spur gear, beta).

A spur gear made with form.parts.spur_gear (py_gearworks). Teeth, module and pressure angle are computed from the
mesh (module and pressure angle snapped to standard values; no profile shift assumed); width and bore too.
"""
from build123d import Axis, Location, Plane

from form.parts import spur_gear
from form.recipes.base import Feature, Param, Recipe, Stage


class Design(Recipe):
    title = {(name + ' (reconstructed)')!r}
    summary = "Rebuilt from a mesh as a parametric spur gear."
    params = [
        Param("teeth", "Teeth", {g['teeth']}, 6, 300, 1, "", "form", "gear", "computed from mesh: repetitions of the outline round the axis", provenance="mesh"),
        Param("module", "Module", {_f(m)}, 0.3, 20, 0.05, "mm", "form", "gear", "computed from mesh: base circle and tooth thickness, snapped to a standard module", provenance="mesh"),
        Param("pressure_angle", "Pressure angle", {_f(alpha)}, 10, 35, 0.5, "°", "form", "gear", "computed from mesh: involute flanks, snapped to a standard angle", provenance="mesh"),
        Param("width", "Face width", {_f(round(g['width'], 4))}, 0.5, {_f(round(g['width'] * 4 + 1, 2))}, 0.01, "mm", "form", "gear", "computed from mesh: distance between the faces", provenance="mesh"),
        Param("bore_d", "Bore diameter", {_f(round(bore, 4))}, 0, {_f(round(g['root_d'], 2))}, 0.01, "mm", "form", "bore", "computed from mesh: diameter of the round hole on the axis (0 = none)", provenance="mesh"),
    ]
    features = [Feature("gear", "Gear", "interface", "Involute spur gear teeth."), Feature("bore", "Bore", "interface", "The hole on the axis.")]

    def build(self, v):
        g = spur_gear(module=v["module"], teeth=int(round(v["teeth"])), thickness=v["width"], bore=0, backlash=0,
                      pressure_angle=v["pressure_angle"])
        place = Location(Plane(origin={_v(g['centre'])}, x_dir={_v(g['u'])}, z_dir={_v(g['d'])}))
        gear = place * g.shape.rotate(Axis.Z, {_f(phase_deg)})
        stages = [Stage("gear", gear)]
        if v["bore_d"] > 0:
            from build123d import Align, Cylinder
            cut = place * Cylinder(v["bore_d"] / 2, v["width"] + 2, align=(Align.CENTER, Align.CENTER, Align.MIN)).moved(Location((0, 0, -1)))
            stages.append(Stage("bore", gear - cut))
        return stages
'''


def _src_involute(g, name):
    bore = g["bore"] or 0.0
    alpha = g["pressure_angle"]
    return f'''"""{name}: reconstructed from a mesh by Form Studio (Layer 2, parametric spur gear, beta).

Involute teeth drawn from values computed from the mesh: teeth, module and pressure angle (no profile shift assumed),
tip and root diameters, tooth thickness at the base circle; tip {g['tip']}, root {g['root']} as in the mesh.
"""
import math

from build123d import Align, Cylinder, Location, Plane, extrude, make_face

from form.recipes.base import Feature, Param, Recipe, Stage
from form.recon.ops import spur_gear_profile


class Design(Recipe):
    title = {(name + ' (reconstructed)')!r}
    summary = "Rebuilt from a mesh as a parametric spur gear."
    params = [
        Param("teeth", "Teeth", {g['teeth']}, 6, 300, 1, "", "form", "gear", "computed from mesh: repetitions of the outline round the axis", provenance="mesh"),
        Param("module", "Module", {_f(round(g['module'], 5))}, 0.1, 20, 0.01, "mm", "form", "gear", "computed from mesh: base circle and tooth thickness (no profile shift assumed)", provenance="mesh"),
        Param("pressure_angle", "Pressure angle", {_f(round(alpha, 4))}, 10, 35, 0.1, "°", "form", "gear", "computed from mesh: involute flanks fitted to the outline", provenance="mesh"),
        Param("tip_d", "Tip diameter", {_f(round(g['tip_d'], 4))}, 1, 1000, 0.01, "mm", "form", "gear", "computed from mesh: largest diameter", provenance="mesh"),
        Param("root_d", "Root diameter", {_f(round(g['root_d'], 4))}, 1, 1000, 0.01, "mm", "form", "gear", "computed from mesh: smallest diameter of the outline", provenance="mesh"),
        Param("width", "Face width", {_f(round(g['width'], 4))}, 0.5, {_f(round(g['width'] * 4 + 1, 2))}, 0.01, "mm", "form", "gear", "computed from mesh: distance between the faces", provenance="mesh"),
        Param("bore_d", "Bore diameter", {_f(round(bore, 4))}, 0, {_f(round(g['root_d'], 2))}, 0.01, "mm", "form", "bore", "computed from mesh: diameter of the round hole on the axis (0 = none)", provenance="mesh"),
    ]
    features = [Feature("gear", "Gear", "interface", "Involute spur gear teeth."), Feature("bore", "Bore", "interface", "The hole on the axis.")]

    def build(self, v):
        z, m, a = int(round(v["teeth"])), v["module"], math.radians(v["pressure_angle"])
        half = math.pi / (2 * z) + math.tan(a) - a          # standard tooth thickness at the base circle
        wire = spur_gear_profile(z, m, v["pressure_angle"], v["tip_d"], v["root_d"], half, tip={g['tip']!r}, root={g['root']!r},
                                 phase={_f(g['phase'])})
        place = Location(Plane(origin={_v(g['centre'])}, x_dir={_v(g['u'])}, z_dir={_v(g['d'])}))
        gear = place * extrude(make_face(wire), v["width"])
        stages = [Stage("gear", gear)]
        if v["bore_d"] > 0:
            cut = place * Cylinder(v["bore_d"] / 2, v["width"] + 2, align=(Align.CENTER, Align.CENTER, Align.MIN)).moved(Location((0, 0, -1)))
            stages.append(Stage("bore", gear - cut))
        return stages
'''


def _phase_of(P, T, g):
    """Angular phase of a built gear's teeth, measured the same way as on the mesh."""
    from .mesh import weld
    V, F, _ = weld(P[T])
    h, _ = analyse(V, F, g["d"], 0.01)
    return h["phase"] if h else None


def recipe(V, F, axis_dirs, tol, name="part", limit=None, progress=None) -> dict:
    """A parametric gear recipe for the mesh, if it is a spur gear about one of axis_dirs. Returns like tree.recipe."""
    from . import solid, verify
    from .tree import _build
    t0 = time.perf_counter()
    limit = tol if limit is None else limit
    rep = {"beta": True, "method": "spur gear"}
    g = why = None
    for d in axis_dirs:
        g, why = analyse(V, F, np.asarray(d, dtype=np.float64), tol)
        if g is not None:
            break
    if g is None:
        rep["error"] = f"Not a spur gear: {why}."
        return {"report": rep}
    if g["other_loops"]:
        rep["error"] = "Not a plain spur gear: the cut across the axis has holes besides the bore."
        return {"report": rep}
    rep["fit"] = {"teeth": g["teeth"], "module_mm": round(g["module"], 5), "pressure_angle_deg": round(g["pressure_angle"], 4),
                  "tip_d_mm": round(g["tip_d"], 4), "root_d_mm": round(g["root_d"], 4), "width_mm": round(g["width"], 4),
                  "bore_mm": round(g["bore"], 4) if g["bore"] else None, "tip": g["tip"], "root": g["root"],
                  "flank_fit_max_mm": round(g["flank_fit_mm"], 5), "provenance": "computed from mesh",
                  "assumes": "standard tooth thickness (no profile shift)"}
    cands = []
    m_std = min(STANDARD_MODULES, key=lambda x: abs(x - g["module"]))
    a_std = min(STANDARD_ANGLES, key=lambda x: abs(x - g["pressure_angle"]))
    if abs(m_std - g["module"]) < 0.02 * m_std and abs(a_std - g["pressure_angle"]) < 1.5:
        try:
            import py_gearworks  # noqa: F401
            cands.append(("form.parts.spur_gear (py_gearworks)", "parts", m_std, a_std))
        except ImportError:
            rep["note"] = "py_gearworks is not installed, so the Form Studio gear was not tried."
    if abs(m_std - g["module"]) < 0.02 * m_std and abs(a_std - g["pressure_angle"]) < 1.5:
        cands.append((f"involute outline, module {m_std:g} and {a_std:g}° (standard values)", "involute", m_std, a_std))
    cands.append(("involute outline fitted to the mesh", "involute", None, None))
    tried = []
    best = None
    for label, kind, m, a in cands:
        try:
            if kind == "parts":
                src0 = _src_parts(g, name, m, a, 0.0)
                sh0 = _build(src0)
                P0, T0 = solid.tessellate(sh0, max(tol / 10, 1e-4))
                ph = _phase_of(P0, T0, g)
                if ph is None:
                    raise ValueError("could not find the teeth of the built gear")
                delta = math.degrees(g["phase"] - ph)
                src = _src_parts(g, name, m, a, delta)
            else:
                src = _src_involute({**g, "module": m, "pressure_angle": a} if m else g, name)
            shape = _build(src)
            ck = solid.check(shape.wrapped)
            P, T = solid.tessellate(shape, max(tol / 10, 1e-4))
            cmp = verify.compare(V, F, P, T)
        except Exception as e:                          # noqa: BLE001
            tried.append({"recipe": label, "error": f"{type(e).__name__}: {e}"[:300]})
            continue
        ok = ck["valid"] and ck["solids"] == 1 and cmp["hausdorff_mm"] <= limit
        tried.append({"recipe": label, "hausdorff_mm": round(cmp["hausdorff_mm"], 6), "valid": ck["valid"], "verified": bool(ok)})
        cur = (src, shape, ck, P, T, cmp, ok, label)
        if ok:
            best = cur
            break
        if best is None or cmp["hausdorff_mm"] < best[5]["hausdorff_mm"]:
            best = cur
    rep["tried"] = tried
    rep["seconds"] = round(time.perf_counter() - t0, 2)
    if best is None:
        rep["error"] = "No gear recipe built."
        return {"report": rep}
    src, shape, ck, P, T, cmp, ok, label = best
    rep.update({"kind": "spur gear", "base": label, "valid": ck["valid"], "solids": ck["solids"], "verified": bool(ok),
                "volume_mm3": round(ck["volume_mm3"], 4),
                **{k: (round(v, 6) if isinstance(v, float) else v) for k, v in cmp.items() if not k.startswith("_")}})
    rep["features"] = [{"kind": "gear", "feature": "gear", "teeth": g["teeth"], "provenance": "computed from mesh"}] + (
        [{"kind": "bore", "feature": "bore", "diameter_mm": round(g["bore"], 4), "provenance": "computed from mesh"}] if g["bore"] else [])
    if not ok:
        rep["error"] = f"The gear builds, but it is {cmp['hausdorff_mm']:.4f} mm from the mesh (limit {limit:.4f} mm)"
    return {"report": rep, "source": src, "verified": ok, "shape": shape.wrapped, "P": P, "T": T, "cmp": cmp, "refs": {}}
