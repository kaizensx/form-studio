"""The verification of the topology optimiser: the published benchmarks, with their published numbers (runs in the
FEA engine's Python).

    <engine python> -m form.topo.verify [--json] [--quick]

The MBB beam, half of it by symmetry, 50 % volume, penalty 3, on a grid of unit squares: the problem of Sigmund's
"A 99 line topology optimization code written in Matlab" (2001) and of Andreassen, Clausen, Schevenels, Lazarov and
Sigmund, "Efficient topology optimization in MATLAB using 88 lines of code" (2011). The second paper prints the
final compliance under its optimised designs (its figures 2 and 3) for three meshes and two filters: 216.81, 219.52
and 222.29 with the sensitivity filter, 233.71, 235.73 and 238.31 with the density filter. The first two meshes of
each are reproduced here to the digits printed there, through the same loop (form/topo/simp.py optimise) that optimises a design's own mesh.

    mesh      rmin   filter        published compliance
    60 x 20   2.4    sensitivity   216.81
    60 x 20   2.4    density       233.71
    150 x 50  6.0    sensitivity   219.52
    150 x 50  6.0    density       235.73

Accepted: compliance within 0.05 % of the published value, the volume fraction within 0.001 of 0.5. The topology
is checked by what defines it: material along the top and bottom chords and the diagonal web, void in the
triangles between them (the densities at stated places of the 60 x 20 result).

Then the same loop on a tetrahedral mesh (form/topo/mesh3d.py), which has no published number: a cantilever plate,
checked for what must hold in any correct implementation: the compliance of the full solid equals the work of the
loads (u.f) to solver precision, the volume constraint is met, the compliance falls monotonically after the first
iterations, and the optimised layout is stiffer than the same amount of material spread evenly.
"""
from __future__ import annotations

import json
import sys
import time

import numpy as np

from . import simp

PUBLISHED = (
    # nelx, nely, rmin, filter, published compliance, published iterations (None: not compared)
    (60, 20, 2.4, "sensitivity", 216.81, None),
    (60, 20, 2.4, "density", 233.71, None),
    (150, 50, 6.0, "sensitivity", 219.52, None),
    (150, 50, 6.0, "density", 235.73, None),
)
TOL = 5e-4


def mbb(quick: bool = False) -> list:
    rows = []
    for nx, ny, rmin, ft, c_ref, it_ref in PUBLISHED:
        if quick and nx > 60:
            continue
        t0 = time.perf_counter()
        g = simp.Grid2D(nx, ny, "mbb")
        o = simp.optimise(g, 0.5, rmin, ft=ft, max_iter=2000)
        err = abs(o["compliance"] - c_ref) / c_ref
        row = {"case": f"MBB {nx}x{ny}, rmin {rmin:g}, {ft} filter", "compliance": round(o["compliance"], 4),
               "published": c_ref, "error": round(err, 6), "tolerance": TOL, "iterations": o["iterations"],
               "volume": round(o["volume"], 5), "seconds": round(time.perf_counter() - t0, 1),
               "ok": bool(err <= TOL and abs(o["volume"] - 0.5) <= 1e-3 and o["converged"])}
        if it_ref is not None:
            row["published_iterations"] = it_ref
            row["ok"] = bool(row["ok"] and o["iterations"] == it_ref)
        if (nx, ny, ft) == (60, 20, "sensitivity"):
            img = g.image(o["density"])                  # (20, 60), row 0 at the top
            probes = {"top chord (row 0, column 20)": (img[0, 20], 1), "bottom chord (row 19, column 30)": (img[19, 30], 1),
                      "support corner (row 19, column 59)": (img[19, 59], 1), "under the load (row 0, column 0)": (img[0, 0], 1),
                      "void at the top right (row 2, column 55)": (img[2, 55], 0),
                      "void triangle (row 10, column 22)": (img[10, 22], 0)}
            row["topology"] = {k: {"density": round(float(v), 3), "expected": "solid" if want else "void",
                                   "ok": bool((v > 0.8) if want else (v < 0.2))} for k, (v, want) in probes.items()}
            row["ok"] = bool(row["ok"] and all(x["ok"] for x in row["topology"].values()))
        rows.append(row)
    return rows


def tet() -> dict:
    """The loop on a tetrahedral mesh: a cantilever plate 60 x 20 x 4 mm, 2.5D along z."""
    from netgen.occ import Box, Pnt

    from ..fea import mesh as mesh_mod
    from . import mesh3d
    t0 = time.perf_counter()
    geo = mesh_mod.from_shape(Box(Pnt(0, 0, 0), Pnt(60, 20, 4)))
    spec = {"kind": "static", "materials": [{"name": "test", "E": 2000.0, "nu": 0.35, "yield": 50.0}],
            "fixtures": [{"type": "fixed", "faces": [{"samples": [[0, 10, 2]]}]}],
            "loads": [{"type": "force", "faces": [{"samples": [[60, 10, 2]]}], "vector": [0, -100, 0]}]}
    prob = mesh3d.TetProblem(geo, spec, 2.0, pull=[0, 0, 1])
    c1, ce = prob.solve(np.ones(prob.n))
    work = float(prob.u @ prob.f)
    vf = 0.5
    c_even, _ = prob.solve(np.full(prob.n, mesh3d.EMIN_3D + vf ** 3 * (1 - mesh3d.EMIN_3D)))
    solid = prob.keep(2.0)
    o = simp.optimise(prob, vf, rmin=2.5, solid=solid, max_iter=40, emin=mesh3d.EMIN_3D)
    cs = [h["compliance"] for h in o["history"]]
    rises = sum(1 for a, b in zip(cs[5:], cs[6:]) if b > a * 1.002)
    return {"case": "cantilever plate on tetrahedra, 2.5D", "elements": int(prob.n), "unknowns": int(prob.model.sp.ndof),
            "compliance_solid": round(c1, 6), "work_of_loads": round(work, 6),
            "energy_balance_error": float(abs(c1 - work) / work),
            "compliance_even_material": round(c_even, 4), "compliance_optimised": round(o["compliance"], 4),
            "stiffer_than_even_by": round(c_even / o["compliance"], 3), "volume": round(o["volume"], 5),
            "rises_after_iteration_5": rises, "iterations": o["iterations"], "seconds": round(time.perf_counter() - t0, 1),
            "ok": bool(abs(c1 - work) / work < 1e-6 and abs(o["volume"] - vf) < 2e-3 and rises == 0
                       and o["compliance"] < c_even / 1.5)}


def run(quick: bool = False) -> dict:
    rows = mbb(quick)
    rows.append(tet())
    return {"passed": all(r["ok"] for r in rows), "cases": rows,
            "reference": "Sigmund (2001), A 99 line topology optimization code written in Matlab, Struct Multidisc Optim "
                         "21; Andreassen et al. (2011), Efficient topology optimization in MATLAB using 88 lines of "
                         "code, Struct Multidisc Optim 43, figures 2 and 3"}


if __name__ == "__main__":
    r = run("--quick" in sys.argv)
    print(json.dumps(r, indent=1))
    sys.exit(0 if r["passed"] else 1)
