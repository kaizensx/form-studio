"""Effective stiffness of one periodic unit cell by finite elements, to check the scaling-law estimate.

Two models, both with periodic boundary conditions and a unit macroscopic strain (first-order computational
homogenisation: the cell's displacement is the strain's affine field plus a periodic fluctuation that minimises the
strain energy):

  struts   a space frame: each strut a Timoshenko beam of circular section (axial, bending, shear, torsion), rigidly
           joined at the nodes. numpy only. The six unit strains give the full 6 x 6 stiffness; E along the cell's
           axis is 1 / S11. The beam model leaves out the material at the nodes, so it reads low for stubby struts
           (it is the model the scaling laws themselves come from).
  TPMS     voxels: n³ trilinear hexahedra, each with the solid's volume fraction in it as a linear scale on E
           (Andreassen and Andreasen 2014, "How to determine composite material properties using numerical
           homogenization", Comput. Mater. Sci. 83). Needs SciPy (sparse conjugate gradients). The cell has cubic
           symmetry, so one solve (strain along x) gives C11 and C12 and E = (C11 - C12)(C11 + 2 C12) / (C11 + C12).
           A thin wall is only a voxel or two thick at the default n, so the result carries its resolution and the
           change from a coarser grid as its stated error.

Both return E relative to the solid's E (and need only Poisson's ratio of the solid).
"""
from __future__ import annotations

import math

import numpy as np

from . import cells as C

EVIDENCE_FRAME = "computed (periodic frame FE, Timoshenko beams; node volume not modelled)"
EVIDENCE_VOXEL = "computed (periodic voxel FE homogenisation)"


def _periodic_struts(kind: str):
    """The struts of an endless lattice once each, with their periodic node ids: (P (m, 2, 3) in units of a,
    node id per end (m, 2), node count)."""
    S = C.struts(kind, (2, 2, 2))
    mid = S.mean(axis=1) % 1.0
    mid = np.where(np.abs(mid - 1.0) < 1e-9, 0.0, mid)
    d = S[:, 1] - S[:, 0]
    d = np.where((C._lex_less(np.zeros_like(d), d))[:, None], d, -d)
    _, first = np.unique(np.round(np.hstack([mid, d]), 6), axis=0, return_index=True)
    S = S[np.sort(first)]
    pts = np.round(S.reshape(-1, 3) % 1.0, 6)
    pts = np.where(np.abs(pts - 1.0) < 1e-6, 0.0, pts)
    uniq, inv = np.unique(pts, axis=0, return_inverse=True)
    return S, inv.reshape(-1, 2), len(uniq)


def _beam(L: float, r: float, E: float, nu: float) -> np.ndarray:
    """12 x 12 stiffness of a Timoshenko beam along local x (u, v, w, rx, ry, rz at each end)."""
    A = math.pi * r * r
    I = math.pi * r ** 4 / 4.0                              # noqa: E741
    J = 2.0 * I
    G = E / (2.0 * (1.0 + nu))
    kap = 6.0 * (1.0 + nu) / (7.0 + 6.0 * nu)               # shear coefficient of a solid circle (Cowper 1966)
    phi = 12.0 * E * I / (kap * G * A * L * L)
    K = np.zeros((12, 12))
    ea, gj = E * A / L, G * J / L
    for i, j, v in ((0, 0, ea), (0, 6, -ea), (6, 6, ea), (3, 3, gj), (3, 9, -gj), (9, 9, gj)):
        K[i, j] = K[j, i] = v
    a = 12.0 * E * I / (L ** 3 * (1 + phi))
    b = 6.0 * E * I / (L ** 2 * (1 + phi))
    c = (4.0 + phi) * E * I / (L * (1 + phi))
    d = (2.0 - phi) * E * I / (L * (1 + phi))
    # bending in the x-y plane: v (1, 7) with rz (5, 11)
    for i, j, v in ((1, 1, a), (1, 5, b), (1, 7, -a), (1, 11, b), (5, 5, c), (5, 7, -b), (5, 11, d), (7, 7, a),
                    (7, 11, -b), (11, 11, c)):
        K[i, j] = K[j, i] = v
    # bending in the x-z plane: w (2, 8) with ry (4, 10)
    for i, j, v in ((2, 2, a), (2, 4, -b), (2, 8, -a), (2, 10, -b), (4, 4, c), (4, 8, b), (4, 10, d), (8, 8, a),
                    (8, 10, b), (10, 10, c)):
        K[i, j] = K[j, i] = v
    return K


def _rot(dv: np.ndarray) -> np.ndarray:
    x = dv / np.linalg.norm(dv)
    ref = np.array([0.0, 0.0, 1.0]) if abs(x[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
    y = np.cross(ref, x)
    y /= np.linalg.norm(y)
    z = np.cross(x, y)
    R = np.stack([x, y, z])
    T = np.zeros((12, 12))
    for k in range(4):
        T[3 * k:3 * k + 3, 3 * k:3 * k + 3] = R
    return T


_VOIGT = ((0, 0), (1, 1), (2, 2), (1, 2), (0, 2), (0, 1))


def frame(kind: str, radius_over_cell: float, nu: float = 0.3) -> dict:
    """The effective stiffness of a strut lattice, relative to the solid's E: the 6 x 6 matrix (Voigt, engineering
    shear), E along a cell axis, and the Zener anisotropy ratio."""
    S, ids, n = _periodic_struts(kind)
    r = float(radius_over_cell)
    ndof = 6 * n
    K = np.zeros((ndof, ndof))
    F = np.zeros((ndof, 6))
    els = []
    for (p, q), (i, j) in zip(S, ids):
        dv = q - p
        T = _rot(dv)
        ke = T.T @ _beam(float(np.linalg.norm(dv)), r, 1.0, nu) @ T
        dof = np.r_[6 * i:6 * i + 6, 6 * j:6 * j + 6]
        K[np.ix_(dof, dof)] += ke
        u0 = np.zeros((12, 6))
        for a, (m, k) in enumerate(_VOIGT):
            eps = np.zeros((3, 3))
            eps[m, k] = eps[k, m] = 1.0 if m == k else 0.5
            u0[0:3, a], u0[6:9, a] = eps @ p, eps @ q
        F[dof] -= ke @ u0
        els.append((dof, ke, u0))
    free = np.arange(3, ndof)                                # one node's translations held: no rigid translation
    U = np.zeros((ndof, 6))
    U[free] = np.linalg.lstsq(K[np.ix_(free, free)], F[free], rcond=None)[0]
    Cm = np.zeros((6, 6))
    for dof, ke, u0 in els:
        d = U[dof] + u0
        Cm += d.T @ ke @ d
    Sm = np.linalg.inv(Cm)
    c11, c12, c44 = Cm[0, 0], Cm[0, 1], Cm[3, 3]
    return {"E_rel": float(1.0 / Sm[0, 0]), "C": Cm.tolist(), "zener": float(2.0 * c44 / (c11 - c12)) if abs(c11 - c12) > 1e-15 else None,
            "struts": int(len(S)), "nodes": int(n), "evidence": EVIDENCE_FRAME}


def frame_exponent(kind: str, nu: float = 0.3, radii=(0.01, 0.02)) -> float:
    """d ln E / d ln rho of the frame model between two slender radii: 1 for a stretch-dominated lattice, 2 for a
    bending-dominated one."""
    e = [frame(kind, r, nu)["E_rel"] for r in radii]
    rho = [C.strut_density_first_order(kind, r, 1.0) for r in radii]
    return float(math.log(e[1] / e[0]) / math.log(rho[1] / rho[0]))


# ── voxels ───────────────────────────────────────────────────────────────────────────────────────────────────────

def _hex_ke(nu: float):
    """24 x 24 stiffness of a unit cube trilinear element with E = 1, and the nodal forces of the six unit strains
    (24 x 6), by 2 x 2 x 2 Gauss quadrature. Node order: (0,0,0) (1,0,0) (1,1,0) (0,1,0) then the same at z = 1."""
    lam, mu = nu / ((1 + nu) * (1 - 2 * nu)), 1.0 / (2 * (1 + nu))
    D = np.zeros((6, 6))
    D[:3, :3] = lam
    D[np.arange(3), np.arange(3)] += 2 * mu
    D[np.arange(3, 6), np.arange(3, 6)] = mu
    nodes = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]], float)
    g = 0.5 + np.array([-1, 1]) / (2 * math.sqrt(3))
    KE, FE = np.zeros((24, 24)), np.zeros((24, 6))
    for x in g:
        for y in g:
            for z in g:
                dN = np.zeros((8, 3))
                for a, (X, Y, Z) in enumerate(nodes):
                    fx, fy, fz = (x if X else 1 - x), (y if Y else 1 - y), (z if Z else 1 - z)
                    dN[a] = ((1 if X else -1) * fy * fz, (1 if Y else -1) * fx * fz, (1 if Z else -1) * fx * fy)
                B = np.zeros((6, 24))
                for a in range(8):
                    dx, dy, dz = dN[a]
                    B[0, 3 * a], B[1, 3 * a + 1], B[2, 3 * a + 2] = dx, dy, dz
                    B[3, 3 * a + 1], B[3, 3 * a + 2] = dz, dy
                    B[4, 3 * a], B[4, 3 * a + 2] = dz, dx
                    B[5, 3 * a], B[5, 3 * a + 1] = dy, dx
                KE += B.T @ D @ B / 8.0
                FE += B.T @ D / 8.0
    return KE, FE, nodes


def voxel_fraction(spec: dict, n: int) -> np.ndarray:
    """The solid's volume fraction in each of n³ voxels of one cell (smoothed count, 2³ points per voxel)."""
    m = 2 * n
    t = (np.arange(m) + 0.5) / m
    if C.is_tpms(spec["kind"]):
        X, Y, Z = np.meshgrid(*(t * 2 * math.pi,) * 3, indexing="ij")
        g = np.maximum(C.tpms_grad(spec["kind"], X, Y, Z), 1e-9)
        d = C.tpms_solid(spec["kind"], spec.get("form", "sheet"), X, Y, Z, float(spec["level"])) / g
        v = np.clip(0.5 - d / (2 * math.pi / m), 0.0, 1.0)
    else:
        from .geom import _with_nodes
        S, R = _with_nodes(C.struts(spec["kind"], (3, 3, 3)) - 1.0, float(spec["strut_d"]) / 2 / float(spec["cell"]),
                           float(spec.get("node", 1.25)))
        P = np.stack(np.meshgrid(t, t, t, indexing="ij"), axis=-1).reshape(-1, 3)
        v = np.clip(0.5 - C.capsule_distance(P, S, R) * m, 0.0, 1.0).reshape(m, m, m)
    return v.reshape(n, 2, n, 2, n, 2).mean(axis=(1, 3, 5))


def voxel(spec: dict, nu: float = 0.3, n: int = 24, e_min: float = 1e-5, tol: float = 1e-7) -> dict:
    """E along a cell axis of the cell (relative to the solid's E), C11, C12 and the relative density of the voxel
    model. Raises ImportError without SciPy."""
    import scipy.sparse as sp
    from scipy.sparse.linalg import LinearOperator, cg
    rho = voxel_fraction(spec, n)
    KE, FE, nodes = _hex_ke(nu)
    idx = np.arange(n ** 3).reshape(n, n, n)
    i, j, k = np.meshgrid(np.arange(n), np.arange(n), np.arange(n), indexing="ij")
    en = np.stack([idx[(i + int(a)) % n, (j + int(b)) % n, (k + int(c)) % n].ravel() for a, b, c in nodes], axis=1)
    edof = (3 * en[:, :, None] + np.arange(3)[None, None, :]).reshape(-1, 24)
    w = e_min + (1.0 - e_min) * rho.ravel()
    rows = np.repeat(edof, 24, axis=1).ravel()
    cols = np.tile(edof, (1, 24)).ravel()
    K = sp.csr_matrix(((w[:, None] * KE.ravel()[None, :]).ravel(), (rows, cols)), shape=(3 * n ** 3,) * 2)
    f = np.zeros(3 * n ** 3)
    np.add.at(f, edof.ravel(), (w[:, None] * FE[:, 0][None, :]).ravel())
    diag = K.diagonal()
    M = LinearOperator(K.shape, matvec=lambda x: x / diag)
    f -= f.reshape(-1, 3).mean(axis=0).repeat(n ** 3).reshape(3, -1).T.ravel() * 0     # forces of a periodic cell sum to 0
    chi, info = cg(K, f, M=M, rtol=tol, maxiter=20000)
    # chi0: the nodal displacements of the unit strains on one element
    chi0 = np.zeros((24, 6))
    for a, p in enumerate(nodes):
        chi0[3 * a + 0, 0] = p[0]
        chi0[3 * a + 1, 1] = p[1]
    d1 = chi0[:, 0][None, :] - chi[edof]
    c11 = float((w * np.einsum("ei,ij,ej->e", d1, KE, d1)).sum() / n ** 3)
    c12 = float((w * np.einsum("ei,ij,j->e", d1, KE, chi0[:, 1])).sum() / n ** 3)
    e = (c11 - c12) * (c11 + 2 * c12) / (c11 + c12)
    return {"E_rel": float(e), "C11": c11, "C12": c12, "relative_density": float(rho.mean()), "voxels": n,
            "converged": info == 0, "evidence": EVIDENCE_VOXEL}


def verify(spec: dict, estimate_rel: float, nu: float = 0.3, n: int = 24) -> dict:
    """The FE value of E / Es for the spec's cell beside the scaling-law estimate, with the difference."""
    if not C.is_tpms(spec["kind"]):
        r = frame(spec["kind"], float(spec["strut_d"]) / 2.0 / float(spec["cell"]), nu)
        out = {"method": "periodic frame FE (Timoshenko beams)", "E_rel_fe": r["E_rel"], "evidence": r["evidence"],
               "zener": r["zener"], "exponent": frame_exponent(spec["kind"], nu),
               "limits": "beams joined rigidly at points: the node spheres' material is not in the model, so it "
                         "reads low for stubby struts"}
    else:
        try:
            fine = voxel(spec, nu, n)
            coarse = voxel(spec, nu, max(8, (2 * n) // 3))
        except ImportError:
            return {"available": False, "why": "the voxel model needs SciPy (pip install scipy)"}
        out = {"method": f"periodic voxel FE, {n}³ trilinear elements", "E_rel_fe": fine["E_rel"],
               "evidence": fine["evidence"], "voxel_density": fine["relative_density"], "converged": fine["converged"],
               "resolution_change": abs(fine["E_rel"] - coarse["E_rel"]) / max(fine["E_rel"], 1e-12),
               "limits": f"the change from {coarse['voxels']}³ to {n}³ voxels is the stated discretisation error; a "
                         "thin wall is one or two voxels thick"}
    out["available"] = True
    out["E_rel_estimate"] = float(estimate_rel)
    out["estimate_over_fe"] = float(estimate_rel / out["E_rel_fe"]) if out["E_rel_fe"] > 0 else None
    out["difference"] = float((estimate_rel - out["E_rel_fe"]) / out["E_rel_fe"]) if out["E_rel_fe"] > 0 else None
    return out
