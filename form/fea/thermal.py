"""Steady heat conduction on the same quadratic tetrahedra, and the temperature field as a load (FEA engine's Python).

    T, info = solve(model, faces)          # temperature at every node (deg C), heat flows, the balance

Conditions (spec["thermal"]["conditions"], each on picked faces):

    {"type": "temperature", "faces": [...], "value": C}                  the face is held at this temperature
    {"type": "heat_flux",   "faces": [...], "value": W/m2}              heat entering through the face, per area
    {"type": "heat",        "faces": [...], "value": W}                 heat entering, spread evenly over the faces
    {"type": "convection",  "faces": [...], "h": W/(m2 K), "ambient": C}   exchange with a fluid: q = h (ambient - T)

A face with no condition is insulated (no heat crosses it): that is also what a symmetry plane is. Without a
temperature or a convection somewhere the temperature has no level and the study is refused.

Units inside: mm, W, K; conductivity k is W/(mm K) (W/(m K) x 1e-3), flux and h per mm2 (x 1e-6).

The model: steady state, conductivity constant with temperature and the same in every direction, no radiation,
perfect thermal contact between bonded solids. Thermal stress (core.run_static with spec["thermal"]) adds the strain
alpha (T - reference) to the linear static study: expansion that the supports or the part itself hold back becomes
stress; expansion that is free does not.
"""
from __future__ import annotations

import numpy as np
import scipy.sparse as sp_
import scipy.sparse.linalg as spla

TYPES = ("temperature", "heat_flux", "heat", "convection")


def _err(msg, hint=""):
    from .core import StudyError
    return StudyError(msg, hint)


def solve(model, faces: dict) -> tuple[np.ndarray, dict]:
    """The steady temperature field of spec["thermal"] on this model's mesh."""
    sp = model.sp
    th = model.spec["thermal"]
    conds = th.get("conditions") or []
    if not np.all(model.k > 0):
        raise _err("A thermal study needs the thermal conductivity of every solid's material.")
    K = sp.conduction(model.k)
    f = np.zeros(sp.N)
    fixed, tfix = [], []
    rows = []
    for c, ids in zip(conds, faces["thermal"]):
        tr = model.tris(ids)
        if len(tr) == 0:
            raise _err("A thermal condition's face has no triangles on the outside of the mesh.")
        area = float(sp.tri_area(tr).sum())
        t = c["type"]
        row = {"type": t, "area_mm2": area}
        if t == "temperature":
            nodes = np.unique(sp.tri_nodes(tr))
            fixed.append(nodes)
            tfix.append(np.full(len(nodes), float(c["value"])))
        elif t == "heat_flux":
            fi = sp.surface_load(tr, float(c["value"]) * 1e-6)
            f += fi
            row["heat_W"] = float(fi.sum())
        elif t == "heat":
            fi = sp.surface_load(tr, float(c["value"]) / area)
            f += fi
            row["heat_W"] = float(fi.sum())
        elif t == "convection":
            h = float(c["h"]) * 1e-6
            K = K + sp.surface_mass(tr, h)
            f += sp.surface_load(tr, h * float(c["ambient"]))
        else:
            raise _err(f"Unknown thermal condition “{t}” ({', '.join(TYPES)}).")
        rows.append(row)
    if not any(c["type"] in ("temperature", "convection") for c in conds):
        raise _err("Nothing sets the temperature level: with only heat going in, a steady state does not exist.",
                   "Hold a face at a temperature, or give a face convection to the surroundings.")
    T = np.zeros(sp.N)
    free = np.ones(sp.N, bool)
    if fixed:
        nodes = np.concatenate(fixed)
        vals = np.concatenate(tfix)
        T[nodes] = vals                                    # a node on two held faces takes the later one
        free[nodes] = False
    K = K.tocsr()
    fr = np.where(free)[0]
    if len(fr):
        A = K[fr][:, fr].tocsc()
        b = f[fr] - K[fr][:, ~free] @ T[~free]
        if len(fr) <= 250000:
            T[fr] = spla.splu(A, permc_spec="MMD_AT_PLUS_A", diag_pivot_thresh=0.0, options={"SymmetricMode": True}).solve(b)
        else:
            import pyamg
            np.random.seed(0)
            ml = pyamg.smoothed_aggregation_solver(A.tocsr())
            T[fr], info = spla.cg(A, b, rtol=1e-10, atol=0.0, maxiter=2000, M=ml.aspreconditioner())
            if info != 0:
                raise _err("The temperature solve did not converge.")
    # heat entering through each condition: the reaction at held nodes, the convective exchange elsewhere
    react = K @ T - f
    total_in = 0.0
    for c, ids, row in zip(conds, faces["thermal"], rows):
        tr = model.tris(ids)
        if c["type"] == "temperature":
            nodes = np.unique(sp.tri_nodes(tr))
            # the reaction of a held node includes its convection terms only if it is also on a convective face
            row["heat_W"] = float(react[nodes].sum())
            row["temperature_C"] = float(c["value"])
        elif c["type"] == "convection":
            h = float(c["h"]) * 1e-6
            row["heat_W"] = float(sp.surface_load(tr, h * float(c["ambient"])).sum() - (sp.surface_mass(tr, h) @ T).sum())
            nodes = np.unique(sp.tri_nodes(tr))
            row["surface_mean_C"] = float(T[nodes].mean())
        total_in += row["heat_W"]
    through = sum(abs(r["heat_W"]) for r in rows) / 2.0
    info = {"conditions": rows, "heat_through_W": float(through),
            "balance_residual": float(abs(total_in) / max(through, 1e-300)) if through > 0 else 0.0,
            "t_min_C": float(T.min()), "t_max_C": float(T.max())}
    return T, info


def flux(model, T: np.ndarray) -> np.ndarray:
    """Heat flux magnitude at every node (W/mm2): -k grad T, the volume-weighted mean over the elements at a node."""
    sp = model.sp
    Te = T[sp.edofs.T]                                       # (nel, 10)
    g = np.einsum("ajen,ea->enj", sp.dNn, Te, optimize=True)  # (nel, 10 nodes, 3)
    q = -model.k[:, None, None] * g
    acc = np.zeros((sp.N, 3))
    w = np.zeros(sp.N)
    np.add.at(acc, sp.edofs.T, q * sp.vol[:, None, None])
    np.add.at(w, sp.edofs.T, sp.vol[:, None])
    acc /= np.maximum(w, 1e-300)[:, None]
    return np.linalg.norm(acc, axis=1)


def conduction_matrix(space, k: np.ndarray) -> sp_.csr_matrix:
    return space.conduction(k)
