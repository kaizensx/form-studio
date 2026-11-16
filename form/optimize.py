"""Goal seek over a recipe's parameters, with every candidate built by the real kernel.

Search: a space-filling start (Latin hypercube) followed by a shrinking pattern
search around the best feasible point. It finds good designs inside the given
ranges; it does not prove a global optimum, and it says so.
"""
from __future__ import annotations

import math
import operator
import random
import re

OPS = {">=": operator.ge, "<=": operator.le, ">": operator.gt, "<": operator.lt, "==": lambda a, b: abs(a - b) < 1e-9}
_CON = re.compile(r"^\s*([\w.]+)\s*(>=|<=|==|>|<)\s*(-?[\d.]+)\s*$")


class OptimizeError(ValueError):
    pass


def parse_constraints(items: list) -> list[tuple]:
    out = []
    for c in items or []:
        if isinstance(c, dict):
            out.append((c["metric"], c.get("op", ">="), float(c["value"])))
            continue
        m = _CON.match(str(c))
        if not m:
            raise OptimizeError(f"Cannot read constraint “{c}”. Write it like “statics.safety_factor >= 3”.")
        out.append((m.group(1), m.group(2), float(m.group(3))))
    for _, op, _ in out:
        if op not in OPS:
            raise OptimizeError(f"Unknown operator {op}.")
    return out


def run(studio, p: dict, vary: list, objective: dict, constraints: list, budget: int = 40, seed: int = 7) -> dict:
    recipe = studio.recipe(p)
    base = studio.rev(p)["values"]
    if not 1 <= len(vary) <= 4:
        raise OptimizeError("Vary one to four parameters.")
    if len(objective) != 1 or next(iter(objective)) not in ("minimize", "maximize"):
        raise OptimizeError('Objective must be {"minimize": metric} or {"maximize": metric}.')
    sense, target = next(iter(objective.items()))
    cons = parse_constraints(constraints)
    axes = []
    for ax in vary:
        sp = recipe.spec(ax["key"])
        lo = max(sp.min, float(ax.get("min", sp.min)))
        hi = min(sp.max, float(ax.get("max", sp.max)))
        if hi < lo:
            raise OptimizeError(f"{ax['key']}: min is above max.")
        axes.append({"key": sp.key, "lo": lo, "hi": hi, "step": sp.step or 0.1, "integer": sp.step >= 1 and sp.unit in ("", "u")})
    need_wall = target == "min_wall_mm" or any(m == "min_wall_mm" for m, _, _ in cons)
    budget = max(8, min(int(budget), 120))
    rng = random.Random(seed)

    def snap(ax, x):
        x = min(ax["hi"], max(ax["lo"], x))
        st = ax["step"]
        x = ax["lo"] + round((x - ax["lo"]) / st) * st
        return float(round(x)) if ax["integer"] else round(min(ax["hi"], x), 6)

    seen, evaluated = {}, []

    def evaluate(points):
        fresh = []
        for pt in points:
            k = tuple(pt[a["key"]] for a in axes)
            if k not in seen:
                seen[k] = None
                fresh.append(pt)
        if not fresh:
            return
        rows = studio._k("evaluate", timeout=240, recipe_id=studio.rid(p), base=base, candidates=fresh, need_wall=need_wall, p=p)
        for r in rows:
            k = tuple(r["changes"][a["key"]] for a in axes)
            if r["ok"]:
                met = r["metrics"]
                if any(m.startswith("fit") for m, _, _ in cons) or target.startswith("fit"):
                    f = studio.fit(p, {**base, **r["changes"]})
                    met["fit_yield"] = f["yield"] if f else None
                missing = [m for m, _, _ in cons if met.get(m) is None] + ([target] if met.get(target) is None else [])
                if missing:
                    raise OptimizeError(f"Unknown metric(s) {', '.join(sorted(set(missing)))}. Available: {', '.join(sorted(met))}.")
                viol = [f"{m} {op} {v:g} (is {met[m]:.3g})" for m, op, v in cons if not OPS[op](met[m], v)]
                r.update(feasible=not viol, violations=viol, score=met[target])
            else:
                r.update(feasible=False, violations=[r["error"]["message"]], score=None)
            seen[k] = r
            evaluated.append(r)

    def better(a, b):
        if b is None:
            return True
        return a["score"] < b["score"] if sense == "minimize" else a["score"] > b["score"]

    def best():
        out = None
        for r in evaluated:
            if r["feasible"] and better(r, out):
                out = r
        return out

    # 1. space-filling start: Latin hypercube, plus the current design
    n0 = max(6, min(budget // 2, 6 * len(axes)))
    cols = []
    for ax in axes:
        cells = list(range(n0))
        rng.shuffle(cells)
        cols.append([snap(ax, ax["lo"] + (c + rng.random()) / n0 * (ax["hi"] - ax["lo"])) for c in cells])
    start = [{ax["key"]: snap(ax, base[ax["key"]]) for ax in axes}]
    start += [{ax["key"]: cols[j][i] for j, ax in enumerate(axes)} for i in range(n0)]
    evaluate(start)

    # 2. pattern search around the incumbent, halving the step when nothing improves
    steps = {ax["key"]: (ax["hi"] - ax["lo"]) / 4 for ax in axes}
    while len(evaluated) < budget:
        inc = best()
        if inc is None:
            evaluate([{ax["key"]: snap(ax, rng.uniform(ax["lo"], ax["hi"])) for ax in axes} for _ in range(4)])
            if len(evaluated) >= budget:
                break
            continue
        moves = []
        for ax in axes:
            for sgn in (1, -1):
                pt = dict(inc["changes"])
                pt[ax["key"]] = snap(ax, pt[ax["key"]] + sgn * steps[ax["key"]])
                moves.append(pt)
        before = inc
        evaluate(moves[: budget - len(evaluated)])
        if best() is before:
            shrunk = False
            for ax in axes:
                if steps[ax["key"]] > ax["step"]:
                    steps[ax["key"]] /= 2
                    shrunk = True
            if not shrunk:
                break

    win = best()
    feasible = sorted([r for r in evaluated if r["feasible"]], key=lambda r: r["score"], reverse=sense == "maximize")
    cur = seen.get(tuple(snap(ax, base[ax["key"]]) for ax in axes))
    fmt = lambda r: {"values": r["changes"], target: round(r["score"], 4),
                     **{m: round(r["metrics"][m], 4) for m, _, _ in cons if r["metrics"].get(m) is not None}}
    return {
        "objective": f"{sense} {target}", "constraints": [f"{m} {op} {v:g}" for m, op, v in cons],
        "evaluated": len(evaluated), "feasible": len(feasible),
        "infeasible_reasons": sorted({v for r in evaluated if not r["feasible"] for v in r["violations"]})[:6],
        "best": fmt(win) if win else None,
        "current": (fmt(cur) | {"feasible": cur["feasible"]}) if cur and cur.get("ok") else None,
        "runners_up": [fmt(r) for r in feasible[1:5]],
        "note": "Every candidate was built by the kernel. Search is local (Latin hypercube, then pattern search): "
                "good inside these ranges, not a proof of the global optimum. Nothing was saved; preview and commit the one you choose.",
    }
