"""Surrogate-assisted multi-objective search: few real evaluations, each one chosen by a model of the others.

    out = run(evaluate, dim=3, n_obj=2, n_con=1, evals=40)

`evaluate(X)` takes (k, dim) points in the unit box and returns one row per point it really evaluated:
{"x": the point as evaluated (it may have been snapped to a step), "f": [objectives, all minimised] or None when the
evaluation failed, "g": [constraint values, feasible where <= 0], "info": anything}. It may return fewer rows than
it was given (a budget ran out), and the search stops there.

The loop (NumPy only):

1. A Latin hypercube of real evaluations, with any start points.
2. A Gaussian process per objective and per constraint, fitted to every real evaluation (form/inverse/surrogate.py);
   one more on "did the evaluation fail" when some did.
3. NSGA-II (form/inverse/nsga2.py) on the surrogates, read optimistically: mean minus KAPPA standard deviations, so
   a region that is unknown is worth a look.
4. From that predicted front, the points whose optimistic prediction adds the most hypervolume to the front of real
   evaluations are evaluated for real, a few per round; after each pick the front is extended by the pick's mean
   prediction, so a round's picks spread out. When no prediction improves the front, the most uncertain is taken.
5. Repeat from 2 until the evaluations are used up or `stop()` says so.

What comes back is only what was really evaluated: every point with its objectives and constraints, which of them
are feasible, and which feasible ones no other dominates (the front). The front is approximate: a better point may
exist between the ones that were evaluated, and nothing here bounds how much better.
"""
from __future__ import annotations

import numpy as np

from . import nsga2
from .surrogate import GP, latin_hypercube

KAPPA = 1.0                 # optimism on the objectives, in standard deviations
KAPPA_G = 0.5               # and on the constraints
REF = 1.1                   # hypervolume reference, in objective ranges past the worst real point
SURROGATE_POP = 60
SURROGATE_GENERATIONS = 50


def _norm(F, lo, hi):
    return (np.asarray(F, float) - lo) / np.where(hi > lo, hi - lo, 1.0)


def _state(rows: list, n_obj: int, n_con: int) -> dict:
    X = np.array([r["x"] for r in rows], float).reshape(len(rows), -1)
    ok = np.array([r.get("f") is not None for r in rows], bool)
    F = np.array([r["f"] if r.get("f") is not None else [np.nan] * n_obj for r in rows], float).reshape(len(rows), n_obj)
    G = np.array([(r.get("g") if r.get("g") is not None else [np.nan] * n_con) if ok[i] else [np.nan] * n_con
                  for i, r in enumerate(rows)], float).reshape(len(rows), n_con)
    G = np.where(np.isnan(G), np.inf, G)                 # a constraint that could not be read is not met
    feas = ok & (G <= 0).all(axis=1)
    front = np.zeros(len(rows), bool)
    if feas.any():
        idx = np.where(feas)[0]
        front[idx[nsga2.pareto_mask(F[idx])]] = True
    return {"X": X, "F": F, "G": G, "ok": ok, "feasible": feas, "front": front}


def _hv(s: dict) -> tuple:
    """Hypervolume of the real front in normalised objectives, with the bounds used."""
    ok = s["ok"]
    if not ok.any():
        return 0.0, None, None
    lo, hi = s["F"][ok].min(axis=0), s["F"][ok].max(axis=0)
    P = _norm(s["F"][s["front"]], lo, hi)
    return (nsga2.hypervolume(P, np.full(P.shape[1], REF)) if len(P) else 0.0), lo, hi


def run(evaluate, dim: int, n_obj: int, n_con: int = 0, evals: int = 40, batch: int = 4, seed: int = 1,
        start=None, stop=None, on_step=None, init: int | None = None) -> dict:
    if not 1 <= n_obj <= 3:
        raise ValueError("one to three objectives")
    rng = np.random.default_rng(seed)
    stop = stop or (lambda: False)
    rows: list = []
    history: list = []
    seen: set = set()

    def real(Z, why: str) -> int:
        Z = np.atleast_2d(np.asarray(Z, float))[: max(0, evals - len(rows))]
        if len(Z) == 0:
            return 0
        got = evaluate(Z) or []
        n = 0
        for r in got:
            key = tuple(np.round(np.asarray(r["x"], float), 9))
            if key in seen:
                continue
            seen.add(key)
            r["why"] = why
            rows.append(r)
            n += 1
        s = _state(rows, n_obj, n_con) if rows else None
        hv = _hv(s)[0] if s is not None else 0.0
        history.append({"evaluations": len(rows), "step": why, "feasible": int(s["feasible"].sum()) if s else 0,
                        "front": int(s["front"].sum()) if s else 0, "hypervolume": round(float(hv), 6)})
        if on_step is not None:
            on_step(history[-1], rows)
        return n

    n0 = init if init is not None else max(2 * dim + 2, min(evals // 3, 5 * dim))
    n0 = max(2, min(n0, evals))
    first = latin_hypercube(n0, dim, rng)
    if start is not None and len(start):
        first = np.concatenate([np.clip(np.atleast_2d(np.asarray(start, float)), 0, 1), first])[: max(n0, len(start))]
    real(first, "start (Latin hypercube)")
    stalled = 0
    while len(rows) < evals and not stop():
        s = _state(rows, n_obj, n_con)
        ok = s["ok"]
        if ok.sum() < 3:
            if real(rng.random((batch, dim)), "random (too few evaluations succeeded to fit a model)") == 0:
                break
            continue
        lo, hi = s["F"][ok].min(axis=0), s["F"][ok].max(axis=0)
        Xo = s["X"][ok]
        gp_f = [GP().fit(Xo, _norm(s["F"][ok], lo, hi)[:, j]) for j in range(n_obj)]
        Gok = np.where(np.isfinite(s["G"][ok]), s["G"][ok], np.nan)
        gp_g = []
        for j in range(n_con):
            col = Gok[:, j]
            m = np.isfinite(col)
            gp_g.append(GP().fit(Xo[m], col[m]) if m.sum() >= 3 else None)
        gp_fail = GP(noise=1e-3).fit(s["X"], (~ok).astype(float)) if (~ok).any() else None

        def model(Z, kf=KAPPA, kg=KAPPA_G):
            mf, sf = zip(*(g.predict(Z) for g in gp_f))
            mf, sf = np.column_stack(mf), np.column_stack(sf)
            cols = []
            for g in gp_g:
                if g is not None:
                    mg, sg = g.predict(Z)
                    cols.append(mg - kg * sg)
            if gp_fail is not None:
                cols.append(gp_fail.predict(Z)[0] - 0.5)
            return mf, sf, (np.column_stack(cols) if cols else np.zeros((len(Z), 0)))

        def surrogate(Z):
            mf, sf, g = model(Z)
            return mf - KAPPA * sf, g
        seeds = s["X"][s["front"]] if s["front"].any() else Xo
        Zc, _, _ = nsga2.minimise(surrogate, dim, pop=SURROGATE_POP, generations=SURROGATE_GENERATIONS,
                                  seed=int(rng.integers(1 << 30)), start=seeds, stop=stop)
        if len(Zc) == 0:
            break
        mf, sf, g = model(Zc)
        opt = mf - KAPPA * sf
        okc = (g <= 0).all(axis=1) if g.shape[1] else np.ones(len(Zc), bool)
        P = _norm(s["F"][s["front"]], lo, hi) if s["front"].any() else np.zeros((0, n_obj))
        ref = np.full(n_obj, REF)
        dmin = 0.02 * np.sqrt(dim)
        taken = list(s["X"])
        picks, why = [], []
        for _ in range(min(batch, evals - len(rows))):
            far = np.array([min(np.linalg.norm(z - t) for t in taken) > dmin for z in Zc])
            cand = np.where(far & okc)[0] if (far & okc).any() else np.where(far)[0]
            if len(cand) == 0:
                break
            base = nsga2.hypervolume(P, ref) if len(P) else 0.0
            gain = np.array([nsga2.hypervolume(np.vstack([P, opt[i]]), ref) - base for i in cand])
            if gain.max() > 1e-9:
                i = cand[int(np.argmax(gain))]
                why.append("predicted to extend the front")
            else:
                i = cand[int(np.argmax(sf[cand].sum(axis=1)))]
                why.append("most uncertain (no predicted improvement)")
            picks.append(Zc[i])
            taken.append(Zc[i])
            P = np.vstack([P, mf[i]])
        if not picks:
            picks, why = [rng.random(dim)], ["random (the model proposed nothing new)"]
        added = real(np.array(picks), "; ".join(sorted(set(why))))
        stalled = stalled + 1 if added == 0 else 0
        if stalled >= 3:
            break
    s = _state(rows, n_obj, n_con) if rows else {"X": np.zeros((0, dim)), "F": np.zeros((0, n_obj)), "G": np.zeros((0, n_con)),
                                                 "ok": np.zeros(0, bool), "feasible": np.zeros(0, bool), "front": np.zeros(0, bool)}
    return {**s, "rows": rows, "history": history, "evaluations": len(rows),
            "method": "surrogate-assisted NSGA-II: Gaussian processes (Matérn 5/2) on the real evaluations, NSGA-II on "
                      "their optimistic predictions, infill by predicted hypervolume improvement"}
