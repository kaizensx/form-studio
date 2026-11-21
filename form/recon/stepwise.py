"""The stepwise loop: add one feature, compare the residual with the mesh, keep it only if the residual drops.

The program route (program.py) reads every sketch it can off the mesh and builds them all at once; a feature the
verification blames is then kept as the mesh's own slices, sometimes together with neighbours that were fine. This
loop goes back over what was kept, one feature at a time:

1. Candidates: runs kept as the mesh that do have a sketch (an extrusion or a ruled loft read off the mesh), largest
   wall area first.
2. Step: the candidate becomes a feature again, the recipe is built, and the result is compared with the mesh
   (form/remodel/compare.py: two-sided distances from samples on both surfaces).
3. Residual: the share of the result's surface that is still the mesh's own slices (not made by a feature), plus the
   share of the samples farther from the mesh than the tolerance. The step is kept only if the result is one valid
   solid within the limit and its residual is lower than before; otherwise the candidate goes back to the mesh.

Every step is reported (candidate, residual before and after, kept or not). Kernel worker only.
"""
from __future__ import annotations

import time

import numpy as np

MIN_DROP = 0.05            # residual points (percent) a step must remove to be kept
MAX_STEPS = 12


def residual(edit_pct: float, cmp: dict) -> float:
    """Residual of a result: % of its surface not made by features plus % of samples outside the tolerance."""
    return round((100.0 - float(edit_pct)) + float(cmp.get("over_tolerance_area_pct", 0.0)), 4)


def _wall_area(plan, r) -> float:
    subs = plan["subs"]
    return sum(float(np.linalg.norm(np.diff(np.r_[lp.mid, lp.mid[:1]], axis=0), axis=1).sum()) * (subs[k][1] - subs[k][0])
               for k, lp in r.loops)


def build(V, F, tol, limit, name, out, plan, tag, others=None, measure=True):
    """Build the plan as it stands (its features, the rest kept as the mesh; with `others` carving its blocks) and
    measure it (`measure`: also the residual comparison). Returns {"result", "ok", "edit", "cmp"} or {"error"};
    never raises."""
    from . import program, solid, verify
    from ..remodel import compare as rcompare
    from .pipeline import _step
    try:
        kept = [r for r in plan["runs"] if r.fate == "kept"]
        ra = f"{name}_kept{tag}.step" if any(r.add for r in kept) else None
        rc = f"{name}_kept{tag}_cut.step" if any(not r.add for r in kept) else None
        refs = {}
        used = [plan] + (list(others) if others and any(b["fate"] == "envelope" for b in plan["blocks"]) else [])
        src, pool, progs = program.source(name, used, tol, ra, rc)
        if kept:
            add, cut, err = program.residual(plan, kept, tol, progs[0])
            if err:
                return {"error": err}
            for ref, sh in ((ra, add), (rc, cut)):
                if ref and sh is not None:
                    _step(sh, out / ref)
                    refs[ref] = str(out / ref)
            if (ra and add is None) or (rc and cut is None):
                src, pool, progs = program.source(name, used, tol, ra if add is not None else None,
                                                  rc if cut is not None else None)
        stages, _ = program.build_stages(src, refs)
        shape = stages[-1].shape
        ck = solid.check(shape.wrapped)
        fl = []
        P, T = solid.tessellate(shape, max(tol / 10, 1e-4), faces_out=fl)
        diag = float(np.linalg.norm(np.ptp(V, axis=0)))
        cmp = verify.compare(V, F, P, T, spacing=max(diag / 200, 1e-3), shape=shape.wrapped, check_above=limit, faces=fl)
        ok = bool(ck["valid"] and ck["solids"] == 1 and cmp["hausdorff_mm"] <= limit)
        feats_only = next((s.shape for s in reversed(stages) if s.feature != "kept"), None) if refs else None
        edit = 100.0 if not refs else program.editable_share(shape.wrapped, feats_only.wrapped if feats_only is not None
                                                             else None, tol)
        rc_ = rcompare.compare(V, F, P, T, tol=limit, name=name) if measure else {}
        return {"result": (src, shape, ck, P, T, cmp, refs, pool, progs, feats_only, ok), "ok": ok, "edit": edit,
                "cmp": rc_, "hausdorff": cmp["hausdorff_mm"]}
    except Exception as e:                              # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"[:300]}


def refine(V, F, tol, limit, name, out, plan, best: dict, say=None, deadline=None) -> dict:
    """The stepwise loop over a verified program result `best` (an _attempts result). Returns a result of the same
    shape (with "steps"), better than `best` or `best` itself."""
    say = say or (lambda d: None)
    if not best.get("ok") or best.get("edit", 0.0) >= 100.0:
        return best
    fates0 = [(r.fate, r.why) for r in plan["runs"]]
    cands = [r for r in plan["runs"] if r.fate == "kept" and r.kind in ("prism", "ruled") and r.bot is not None]
    cands.sort(key=lambda r: -_wall_area(plan, r))
    if not cands:
        return best
    from ..remodel import compare as rcompare
    src, shape, ck, P, T, cmp, refs, pool, progs, feats_only, ok = best["result"]
    cur = {**best, "cmp": rcompare.compare(V, F, P, T, tol=limit, name=name)}
    res0 = residual(cur["edit"], cur["cmp"])
    steps, n = [], 0
    for r in cands[:MAX_STEPS]:
        if deadline is not None and time.perf_counter() > deadline:
            steps.append({"stopped": "the time budget ran out"})
            break
        n += 1
        say({"stage": "layer2", "text": f"Stepwise: trying {r.label or 'a kept piece'} as a feature again",
             "fraction": 0.85})
        keep = (r.fate, r.why)
        r.fate, r.why = "feature", ""
        got = build(V, F, tol, limit, name, out, plan, f"_s{n}")
        if got.get("error") or not got["ok"]:
            r.fate, r.why = keep
            steps.append({"candidate": r.label or r.id, "kept": False,
                          "why": got.get("error") or f"not within the limit ({got.get('hausdorff', 0):.4f} mm)"})
            continue
        res1 = residual(got["edit"], got["cmp"])
        if res1 < res0 - MIN_DROP:
            steps.append({"candidate": r.label or r.id, "kept": True, "residual_before": res0, "residual_after": res1})
            cur, res0 = got, res1
        else:
            r.fate, r.why = keep
            steps.append({"candidate": r.label or r.id, "kept": False, "residual_before": res0, "residual_after": res1})
    if cur is best or not any(s.get("kept") for s in steps):
        for r, (f, w) in zip(plan["runs"], fates0):
            r.fate, r.why = f, w
        return {**best, "steps": steps}
    if not cur.get("ok"):                                # cannot happen: only verified steps are kept
        return {**best, "steps": steps}
    # the kept builds wrote their residual under their own tag; the last one kept is the result
    return {"result": cur["result"], "ok": True, "edit": cur["edit"], "hausdorff": cur["hausdorff"],
            "attempts": best.get("attempts", []) + [{"stepwise": steps}], "error": None, "steps": steps,
            "fates": [(r.fate, r.why) for r in plan["runs"]]}


MAX_PRUNE = 40


def prune(V, F, tol, limit, name, out, plan, best: dict, say=None, deadline=None) -> dict:
    """The reverse step, for a result that other directions carve (`best["others_list"]`): each of their features is
    tried as part of its direction's envelope instead (program.envelopes), smallest first; the change is kept when the
    result still verifies, as much of its surface comes from features, and it has fewer Params. Returns a result of
    the same shape (with "pruned"), or `best` itself."""
    from . import program
    say = say or (lambda d: None)
    others = list(best.get("others_list") or [])
    if not others or not best.get("ok"):
        return best
    cur = best
    n_cur = len(best["result"][7].params)
    cands = [(p, r) for p in others for r in p["runs"] if r.fate == "feature"]
    cands.sort(key=lambda t: _wall_area(t[0], t[1]))
    pruned, n = [], 0
    for p, r in cands[:MAX_PRUNE]:
        if deadline is not None and time.perf_counter() > deadline:
            pruned.append({"stopped": "the time budget ran out"})
            break
        keep = (r.fate, r.why, r.block)
        r.fate, r.why, r.block = "envelope", "not needed: the result verifies without it", -1
        program.envelopes(p, tol, superset=True)
        if any(b["fate"] != "envelope" for b in p["blocks"]):
            r.fate, r.why, r.block = keep
            program.envelopes(p, tol, superset=True)
            continue
        n += 1
        say({"stage": "layer2", "text": f"Stepwise: does the result need {r.label or 'this feature'}?", "fraction": 0.88})
        got = build(V, F, tol, limit, name, out, plan, f"_p{n}", others=others, measure=False)
        if not got.get("error") and got["ok"] and got["edit"] >= cur["edit"] - 1e-6 and \
                len(got["result"][7].params) < n_cur:
            pruned.append({"feature": r.label or r.id, "direction": p["frame"].names[2],
                           "params_before": n_cur, "params_after": len(got["result"][7].params)})
            cur, n_cur = got, len(got["result"][7].params)
        else:
            r.fate, r.why, r.block = keep
            program.envelopes(p, tol, superset=True)
    for p in others:                                     # the blocks were made again: name them as the build did
        program._name(p, f"{p['frame'].names[2].lower()}_")
    if cur is best:
        return {**best, "pruned": pruned}
    return {"result": cur["result"], "ok": True, "edit": cur["edit"], "hausdorff": cur["hausdorff"],
            "attempts": best.get("attempts", []) + [{"pruned": pruned}], "error": None, "pruned": pruned,
            "others": True, "others_list": others, "fates": [(r.fate, r.why) for r in plan["runs"]]}
