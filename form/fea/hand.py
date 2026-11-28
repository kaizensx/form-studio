"""A hand estimate beside a static result, where the part reads as something a formula covers (FEA engine's Python).

A second opinion that does not share the solver: closed-form beam theory on section properties measured from the
solid's volume. Evidence class: computed (closed form). It is shown next to the simulated result, never instead of it,
and it says what it leaves out.

What is recognised today: **a prismatic bar fixed at one end** (a cantilever, a tie rod, a strut): one solid, one fixed
support on an end face, loads that are forces on faces, the same cross-section along its length (measured: the area
of four slices agrees within PRISMATIC), and at least SLENDER times longer than it is wide. For it:

    stress at the fixed end    sigma = N / A + bending (unsymmetric bending formula on the section's Iy, Iz, Iyz)
    deflection at the load     delta = F a^3 / (3 E I) per principal direction, + N a / (E A) along the axis

Everything else gets {"applies": False, "why": ...}: no estimate is better than a formula that does not fit.
"""
from __future__ import annotations

import numpy as np

PRISMATIC = 0.08          # the cross-section's area may vary this much along the length
SLENDER = 3.0             # length over the largest width
EVIDENCE = "computed (closed form: Euler-Bernoulli beam, section properties measured on the solid)"


def _no(why: str) -> dict:
    return {"applies": False, "why": why}


def _second_moments(P, T, vol, c):
    """Integral of (x - c)(x - c)^T over the tetrahedra (exact for straight sides)."""
    X = P[T] - c                                           # (n, 4, 3)
    s = X.sum(axis=1)
    return (vol[:, None, None] / 20.0 * (np.einsum("nip,niq->npq", X, X) + np.einsum("np,nq->npq", s, s))).sum(axis=0)


def estimate(model, spec: dict, faces: dict, u: np.ndarray, peak_mpa: float) -> dict:
    """The estimate for a solved static level. model: core.Model; u: (N, 3) displacement; peak_mpa: the FEA peak."""
    m, sp = model.m, model.sp
    if model.dom is not None:
        return _no("several solids: no single-section formula applies")
    fixtures, loads = spec.get("fixtures") or [], spec.get("loads") or []
    if len(fixtures) != 1 or fixtures[0]["type"] != "fixed":
        return _no("the formula is for one fixed end; this study is held differently")
    if not loads or any(ld["type"] != "force" for ld in loads):
        return _no("the formula is for forces on faces; this study has other loads")
    lo, hi = m.P.min(axis=0), m.P.max(axis=0)
    ext = hi - lo
    ax = int(np.argmax(ext))
    L = float(ext[ax])
    others = [i for i in range(3) if i != ax]
    if L < SLENDER * float(ext[others].max()):
        return _no(f"not slender: {L:.4g} mm long and {float(ext[others].max()):.4g} mm wide (a beam formula needs "
                   f"at least {SLENDER:g} to 1)")
    a, b, c, d = (m.P[m.T[:, i]] for i in range(4))
    vol = np.abs(np.einsum("ij,ij->i", np.cross(b - a, c - a), d - a)) / 6.0
    cen = m.P[m.T].mean(axis=1)
    V = float(vol.sum())
    # the same cross-section along the length: four slices by where each tetrahedron's centre is
    edges = np.linspace(lo[ax], hi[ax], 5)
    areas = [float(vol[(cen[:, ax] >= e0) & (cen[:, ax] < e1 + 1e-9)].sum() / (e1 - e0)) for e0, e1 in zip(edges, edges[1:])]
    A = V / L
    spread = (max(areas) - min(areas)) / A
    if spread > PRISMATIC:
        return _no(f"the cross-section changes along the length (its area varies by {100 * spread:.0f} %): not a "
                   "prismatic beam")
    # fixed on an end face
    tr = model.tris(faces["fixtures"][0])
    w = model.surf["area"][tr]
    nrm = model.surf["normal"][tr]
    fc = model.face_centre(tr)
    end = 0 if abs(fc[ax] - lo[ax]) < abs(fc[ax] - hi[ax]) else 1
    root = (lo, hi)[end][ax]
    if abs(fc[ax] - root) > 0.02 * L or float((np.abs(nrm[:, ax]) * w).sum() / w.sum()) < 0.97:
        return _no("the fixed face is not an end face of the bar")
    e_ax = np.eye(3)[ax]
    centroid = (vol[:, None] * cen).sum(axis=0) / V
    J = _second_moments(m.P, m.T, vol, centroid) / L        # per unit length: the section's second moments
    e1, e2 = np.eye(3)[others[0]], np.eye(3)[others[1]]
    Iz, Iy, Iyz = float(e1 @ J @ e1), float(e2 @ J @ e2), float(e1 @ J @ e2)     # Iz = int y^2, Iy = int z^2
    det = Iy * Iz - Iyz ** 2
    root_pt = centroid.copy()
    root_pt[ax] = root
    N, M, torsion, defl, arm_max = 0.0, np.zeros(3), 0.0, np.zeros(3), 0.0
    E = float(model.E[0])
    for ld, ids in zip(loads, faces["loads"]):
        F = np.asarray(ld["vector"], float)
        lt = model.tris(ids)
        r = model.face_centre(lt) - root_pt
        arm = abs(float(r[ax]))
        arm_max = max(arm_max, arm)
        N += float(F @ e_ax) * (1 if end == 0 else -1)      # tension positive
        Mi = np.cross(r, F)
        torsion += float(Mi @ e_ax)
        M += Mi - (Mi @ e_ax) * e_ax
        # deflection at this load from this load (cantilever with an end load at distance `arm`)
        defl += e1 * (float(F @ e1) * arm ** 3 / (3 * E * Iz)) + e2 * (float(F @ e2) * arm ** 3 / (3 * E * Iy)) \
            + e_ax * (float(F @ e_ax) * arm / (E * A))
    Fmag = max(float(sum(np.linalg.norm(np.asarray(ld["vector"], float)) for ld in loads)), 1e-300)
    if abs(torsion) > 0.05 * Fmag * max(arm_max, 1e-9):
        return _no("the loads twist the bar about its axis; torsion of a general section has no simple formula here")
    My, Mz = float(M @ e1), float(M @ e2)                   # moments about the e1 and e2 axes
    y = (m.P - centroid) @ e1
    z = (m.P - centroid) @ e2
    # sigma = N/A + My' z - Mz' y with the unsymmetric-bending combination of the moments
    sig = N / A + ((My * Iz + Mz * Iyz) * z - (Mz * Iy + My * Iyz) * y) / det
    k = int(np.argmax(np.abs(sig)))
    hand = float(abs(sig[k]))
    out = {"applies": True, "evidence": EVIDENCE,
           "reads_as": f"a prismatic bar along {'XYZ'[ax]}, {L:.4g} mm long, fixed at one end (section area constant "
                       f"within {100 * spread:.1f} %)",
           "section": {"area_mm2": A, "I_about_" + "XYZ"[others[1]].lower() + "_mm4": Iz,
                       "I_about_" + "XYZ"[others[0]].lower() + "_mm4": Iy},
           "stress_at_fixed_end_MPa": hand, "axial_part_MPa": abs(N) / A, "fea_peak_von_mises_MPa": float(peak_mpa),
           "fea_over_hand": float(peak_mpa) / hand if hand > 0 else None,
           "formula": "sigma = N / A + M c / I at the fixed end; delta = F a^3 / (3 E I) + N a / (E A)",
           "leaves_out": "shear deflection, stress concentrations (fillets, holes, the fixed edge itself) and "
                         "anything that is not beam bending. The simulated peak is read outside the singular zones, "
                         "so it may sit a little away from the fixed end; a simulated peak well above the estimate "
                         "points to a stress concentration the formula does not know."}
    if len(loads) == 1:
        lt = model.tris(faces["loads"][0])
        nodes = np.unique(sp.tri_nodes(lt))
        got = u[nodes].mean(axis=0)
        out.update({"deflection_at_load_mm": float(np.linalg.norm(defl)),
                    "fea_deflection_at_load_mm": float(np.linalg.norm(got)),
                    "fea_over_hand_deflection": float(np.linalg.norm(got) / max(np.linalg.norm(defl), 1e-300))})
    return out
