"""A strength study as a constraint on a search: `fea.safety_factor >= 2` in optimize and make_lighter.

A solve costs seconds, a search builds dozens of candidates, so the strength constraint is not evaluated on every
candidate. The search runs first on what the kernel computes for each candidate (mass, walls, the design's own
statics). Then the study is solved on real candidates, best first, within a stated number of solves and seconds:

* the best candidate by the objective is solved; if it meets the constraint it wins;
* otherwise the candidates are searched by halving between the best that failed and one that passed (strength
  usually falls as the objective improves, which is why a search for the lightest part needs the constraint);
* the winner is the best candidate that was itself solved and met the constraint. A candidate that was not solved is
  never called feasible.

What the result says: which candidates were solved, each one's numbers with the evidence class of its study, how many
solves and seconds were used, and that the search was not steered by the strength constraint.

Metrics (a static study): `fea.safety_factor` is the lower value, the one that applies the stated discretisation
error; `fea.peak_von_mises_MPa`; `fea.max_displacement_mm`. A candidate whose study did not converge, could not be
set up (a picked face that is no longer there) or has no yield strength has no `fea.safety_factor`: it fails the
constraint, with the reason. Each solve runs with the study's own settings and a time budget per candidate.
"""
from __future__ import annotations

import time

PREFIX = "fea."
METRICS = ("fea.safety_factor", "fea.peak_von_mises_MPa", "fea.max_displacement_mm")
RUNS = 8                  # solves per search
SECONDS = 300.0           # and wall time for all of them
PER_SOLVE_S = 45.0        # refinement budget of one candidate's study


def is_fea(metric: str) -> bool:
    return str(metric).startswith(PREFIX)


def check_names(cons: list) -> None:
    from ..studio import StudioError
    bad = [m for m, _, _ in cons if m not in METRICS]
    if bad:
        raise StudioError(f"Unknown strength metric {', '.join(sorted(set(bad)))}.", "Strength metrics: " + ", ".join(METRICS) + ".")


def metrics(res: dict) -> dict:
    sf = res.get("safety_factor") if res.get("converged") else None
    return {"fea.safety_factor": sf["low"] if sf else None,
            "fea.peak_von_mises_MPa": res.get("peak_von_mises_MPa") if res.get("converged") else None,
            "fea.max_displacement_mm": res.get("max_displacement_mm") if res.get("converged") else None}


def solve(st, p: dict, sid: str, values: dict, cons: list, ops: dict) -> dict:
    """One candidate: {"ok", "metrics", "violations", "evidence", "seconds", "why"}."""
    from . import study
    t0 = time.time()
    try:
        res = study.evaluate(st, p, sid, values, budget_s=PER_SOLVE_S)
    except Exception as e:                               # noqa: BLE001 - a candidate that cannot be solved fails, with why
        if getattr(e, "extra", {}).get("kind") in ("unavailable", "cancelled"):
            raise
        return {"ok": False, "metrics": {}, "violations": [f"the strength study could not be solved: {e}"], "evidence": None,
                "seconds": round(time.time() - t0, 1), "why": str(e)}
    met = metrics(res)
    viol = []
    for m, op, v in cons:
        if met.get(m) is None:
            viol.append(f"{m}: " + (("the study did not converge (" + res["not_converged_because"] + ")")
                                    if res.get("not_converged_because") else
                                    res.get("safety_factor_withheld") or "not available"))
        elif not ops[op](met[m], v):
            viol.append(f"{m} {op} {v:g} (is {met[m]:.3g})")
    out = {"ok": not viol, "metrics": {k: (round(x, 4) if x is not None else None) for k, x in met.items()},
           "violations": viol, "evidence": res.get("evidence"), "seconds": round(time.time() - t0, 1),
           "converged": bool(res.get("converged"))}
    if res.get("safety_factor"):
        out["safety_factor"] = {"value": round(res["safety_factor"]["value"], 4), "low": round(res["safety_factor"]["low"], 4),
                                "against": res["safety_factor"].get("against")}
    return out


def verify_ranked(st, p: dict, sid: str, ranked: list, cons: list, ops: dict, runs: int = RUNS, seconds: float = SECONDS) -> dict:
    """ranked: candidates best first, each {"values": {...}} (the whole parameter set). Returns {"winner": index or
    None, "solved": [{"index", "values", ...solve()}], "runs", "seconds", "stopped"}."""
    t0 = time.time()
    solved: dict[int, dict] = {}
    stopped = ""

    def run(i: int):
        nonlocal stopped
        if i in solved:
            return solved[i]
        if len(solved) >= runs:
            stopped = f"the limit of {runs} solves was reached"
            return None
        if time.time() - t0 > seconds:
            stopped = f"the time limit of {seconds:.0f} s was reached"
            return None
        solved[i] = solve(st, p, sid, ranked[i]["values"], cons, ops)
        return solved[i]
    n = len(ranked)
    if n:
        first = run(0)
        if first is not None and not first["ok"] and n > 1:
            last = run(n - 1)
            hi = n - 1
            if last is not None and not last["ok"] and n > 2:      # one more try, in the middle
                hi = (n - 1) // 2
                last = run(hi)
            if last is not None and last["ok"]:
                lo = 0                                    # lo fails, hi passes
                while hi - lo > 1:
                    mid = (lo + hi) // 2
                    r = run(mid)
                    if r is None:
                        break
                    if r["ok"]:
                        hi = mid
                    else:
                        lo = mid
    passing = sorted(i for i, r in solved.items() if r["ok"])
    return {"winner": passing[0] if passing else None,
            "solved": [{"index": i, "values": ranked[i].get("changes", ranked[i]["values"]), **solved[i]} for i in sorted(solved)],
            "runs": len(solved), "seconds": round(time.time() - t0, 1), "stopped": stopped, "candidates": n}
