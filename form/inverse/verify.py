"""The verification of the search: analytic problems whose Pareto front is known (NumPy only).

    python -m form.inverse.verify        prints the table as JSON; exit 0 when every case passes

ZDT1 (a convex front, f2 = 1 - sqrt(f1)) and ZDT2 (a concave one, f2 = 1 - f1^2), Zitzler, Deb and Thiele 2000.
The measure is the inverted generational distance (IGD) to 500 points of the known front: the mean distance from
each of them to the nearest found point, so it is small only when the found front is both on the true one and
covers it. Cases:

    nsga2      NSGA-II alone, 30 variables, population 100, 600 generations         IGD <= 0.02
    surrogate  the surrogate-assisted search, 6 variables, 80 real evaluations       IGD <= 0.08, and at least ten
               times nearer than NSGA-II alone given the same 80 evaluations
    constraint ZDT1 with x1 >= 0.3: no reported point violates it, and the front is found on the allowed part
"""
from __future__ import annotations

import json
import sys

from . import nsga2, search


def run(seed: int = 2) -> dict:
    rows = []
    for name in ("zdt1", "zdt2"):
        fn, front = nsga2.zdt(name)
        ref = front(500)
        _X, F, _G = nsga2.minimise(fn, 30, pop=100, generations=600, seed=seed)
        d = nsga2.igd(F, ref)
        rows.append({"case": f"{name} nsga2", "igd": round(d, 5), "limit": 0.02, "points": int(len(F)),
                     "evaluations": 100 * 601, "ok": bool(d <= 0.02)})

        def ev(X, fn=fn):
            Fx, _ = fn(X)
            return [{"x": x, "f": f.tolist(), "g": []} for x, f in zip(X, Fx)]
        out = search.run(ev, 6, 2, evals=80, batch=4, seed=seed)
        Fs = out["F"][out["front"]]
        ds = nsga2.igd(Fs, ref)
        _X, Fa, _G = nsga2.minimise(fn, 6, pop=20, generations=3, seed=seed)       # the same 80 evaluations, no model
        da = nsga2.igd(Fa, ref)
        rows.append({"case": f"{name} surrogate", "igd": round(ds, 5), "limit": 0.08, "points": int(len(Fs)),
                     "evaluations": int(out["evaluations"]), "nsga2_alone_same_evaluations_igd": round(da, 5),
                     "ok": bool(ds <= 0.08 and ds * 10 <= da)})
    fn, front = nsga2.zdt("zdt1")

    def evc(X):
        Fx, _ = fn(X)
        return [{"x": x, "f": f.tolist(), "g": [0.3 - x[0]]} for x, f in zip(X, Fx)]
    out = search.run(evc, 4, 2, n_con=1, evals=50, seed=1)
    Fc = out["F"][out["front"]]
    ref = front(500)
    ref = ref[ref[:, 0] >= 0.3]
    dc = nsga2.igd(Fc, ref)
    clean = bool((out["X"][out["front"]][:, 0] >= 0.3 - 1e-9).all())
    rows.append({"case": "zdt1 constraint x1 >= 0.3", "igd": round(dc, 5), "limit": 0.08, "points": int(len(Fc)),
                 "evaluations": int(out["evaluations"]), "front_violates_constraint": not clean,
                 "ok": bool(clean and dc <= 0.08)})
    return {"passed": all(r["ok"] for r in rows), "cases": rows,
            "reference": "Zitzler, Deb and Thiele (2000), Comparison of multiobjective evolutionary algorithms; "
                         "Deb et al. (2002), NSGA-II",
            "measure": "inverted generational distance to 500 points of the known front"}


if __name__ == "__main__":
    r = run()
    print(json.dumps(r, indent=1))
    sys.exit(0 if r["passed"] else 1)
