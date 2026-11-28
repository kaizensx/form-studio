"""Fixes: a concrete edit to the design's source for a failing rule, previewed, applied, then proved.

Each proposal is a list of edit_design ops (form/edits.py), so the change is a reviewable, diffable, revertible
feature or parameter of the design, the same thing a person would write by hand:

    draft           insert parameter dfm_draft_deg and feature dfm_draft (form.dfm.ops.draft): every face along the
                    pull tilted to the angle the source recommends, about the proposed parting plane
    corner_radius   insert parameter dfm_corner_r and feature dfm_corners (form.dfm.ops.round_corners): every sharp
                    internal corner along the tool filleted to at least the tool radius (and a third of the cavity
                    depth when that fits); an existing blend that is a parameter is raised by set_param
    escape_holes    insert parameter dfm_escape_d and feature dfm_escape (form.dfm.ops.escape_holes): the source's
                    hole diameter and count from each enclosed void to the outside
    thicken         set_param on the parameter whose value is the measured wall, to the limit
    hole_to_drill   set_param on the parameter whose value is the hole (diameter or radius), to the nearest drill

apply_fix proves it: the candidate source is built and checked without saving (the preview). Only a candidate that
turns every targeted rule to pass is applied, and only when no other rule got worse (a trade is shown, never applied
unless accepted). It is then saved through edit_design as a new revision and the check is run again on the new head,
from a fresh measurement; the answer says fixed only when that run passes the rule. Before and after pictures come
from the two runs.
"""
from __future__ import annotations

import math
import re

from . import rules

RANK = {"pass": 0, "n/a": 0, "info": 0, "warn": 1, "not_checked": 2, "fail": 3}


def _err(msg, hint="", status=400, **kw):
    from ..studio import StudioError
    return StudioError(msg, hint, status=status, **kw)


def _uid(source: str, base: str) -> str:
    name, k = base, 2
    while re.search(rf"\b{re.escape(name)}\b", source or ""):
        name, k = f"{base}_{k}", k + 1
    return name


def _ceil(x: float, step: float) -> float:
    return round(math.ceil(x / step - 1e-9) * step, 6)


def _param_route(st, p, value: float, target: float, words=(), tol: float | None = None, exact: bool = False) -> list:
    """set_param ops for a parameter whose value is the measured one (or its half, for a radius), raised to the
    target: [(ops, why)] best first."""
    rec = st.recipe(p)
    vals = st.rev(p)["values"]
    tol = tol if tol is not None else max(0.02, 0.02 * abs(value))
    out = []
    for q in rec.params:
        v = vals.get(q.key, q.default)
        for scale, what in ((1.0, ""), (0.5, " (a radius)")):
            if abs(v - value * scale) <= tol * max(scale, 0.5):
                new = round(target * scale, 6) if exact else _ceil(target * scale, 0.05)
                ok = q.min - 1e-9 <= new <= q.max + 1e-9
                score = (0 if any(w in (q.key + " " + q.label).lower() for w in words) else 1, abs(v - value * scale))
                out.append((score, ok, [{"op": "set_param", "param": q.key, "value": new}],
                            f"{q.key} {v:g} → {new:g} {q.unit}{what}" + ("" if ok else f" (outside {q.min:g} to {q.max:g})")))
    out.sort(key=lambda x: x[0])
    return [(ops, why) for _s, ok, ops, why in out if ok]


def _rows(res):
    return {r["id"]: r for r in res["rows"]}


def propose(st, p, res: dict, options: dict) -> list:
    """The fixes this result allows, without building anything: [{"id", "kind", "rules", "summary", "attempts"}],
    attempts being alternative op lists tried in order (a smaller radius when the larger cannot be built)."""
    src = st.source_text(p) or ""
    t = rules.table(res["process"])
    by_id = {r["id"]: r for r in t["rules"]}
    rows = _rows(res)
    bad = {rid: r for rid, r in rows.items() if r["status"] in ("fail", "warn")}
    props = []
    data = res.get("data") or {}
    python = not st.rid(p).startswith("scad:")

    # moulding draft
    drafts = [rid for rid in bad if by_id[rid].get("fix") == "draft"]
    if drafts and python:
        target = max(max(x for x in (rows[r].get("fail"), rows[r].get("warn")) if x is not None) for r in drafts)
        pull = data.get("pull") or [0, 0, 1]
        hr = (data.get("parting_line") or {}).get("height_range_mm")
        neutral = hr[0] if hr else None
        fid, key = _uid(src, "dfm_draft"), _uid(src, "dfm_draft_deg")
        code = (f"def {fid}(self, v, body):\n"
                f"    from form.dfm import ops\n"
                f"    return ops.draft(body, pull=({pull[0]!r}, {pull[1]!r}, {pull[2]!r}), angle=v[{key!r}], "
                f"neutral={neutral!r})\n")
        props.append({"id": "draft", "kind": "draft", "rules": drafts, "summary": f"Draft {target:g}° on every face "
                      f"along the pull {data.get('pull_name', pull)}, about the parting plane"
                      + (f" at {neutral:g} mm" if neutral is not None else ""),
                      "attempts": [[{"op": "insert", "param": {"key": key, "label": "Mould draft", "default": target,
                                                                "min": 0.5, "max": 10.0, "step": 0.5, "unit": "°",
                                                                "group": "process", "feature": fid,
                                                                "doc": "From the manufacturability check: "
                                                                + "; ".join(rows[r].get("evidence", "") for r in drafts)}},
                                    {"op": "insert", "feature": fid, "label": "Draft for moulding", "role": "finish",
                                     "code": code}]]})

    # CNC internal corners
    corner = [rid for rid in bad if by_id[rid].get("fix") == "corner_radius"]
    if corner and python and options.get("tool_d"):
        r_tool = float(options["tool_d"]) / 2
        sharp = [f for f in res["findings"] if f["rule"] in corner and f.get("sharp")]
        blends = [f for f in res["findings"] if f["rule"] in corner and not f.get("sharp") and f.get("r_mm")]
        attempts = []
        if sharp:
            axes = []
            for f in sharp:
                a = tuple(round(abs(x), 6) for x in f.get("axis", (0, 0, 1)))
                if a not in axes:
                    axes.append(a)
            deep = max(f.get("depth_mm", 0) for f in sharp)
            want = [_ceil(max(r_tool * 1.05, deep / 3), 0.25), _ceil(r_tool * 1.05, 0.25)]
            fid, key = _uid(src, "dfm_corners"), _uid(src, "dfm_corner_r")
            code = (f"def {fid}(self, v, body):\n"
                    f"    from form.dfm import ops\n"
                    f"    return ops.round_corners(body, axes={tuple(axes)!r}, radius=v[{key!r}])\n")
            for r in dict.fromkeys(want):
                attempts.append([{"op": "insert", "param": {"key": key, "label": "Internal corner radius", "default": r,
                                                             "min": round(r_tool, 3), "max": max(r * 4, 20.0), "step": 0.25,
                                                             "unit": "mm", "group": "process", "feature": fid,
                                                             "doc": f"At least the Ø{options['tool_d']:g} mm tool's radius "
                                                                    "(computed) and a third of the cavity depth (rule)."}},
                                 {"op": "insert", "feature": fid, "label": "Corners for the cutter", "role": "finish",
                                  "code": code}])
        for f in blends:
            deep = f.get("depth_mm") or 0
            for ops, why in _param_route(st, p, f["r_mm"], max(r_tool * 1.05, deep / 3), ("fillet", "radius", "corner")):
                attempts.append(ops)
                break
        if attempts:
            props.append({"id": "corner_radius", "kind": "corner_radius", "rules": corner,
                          "summary": f"Internal vertical corners raised to the Ø{options['tool_d']:g} mm tool's radius "
                                     f"{r_tool:g} mm or more" + (f" ({len(sharp)} sharp edges filleted)" if sharp else ""),
                          "attempts": attempts})

    # escape holes
    trap = [rid for rid in bad if by_id[rid].get("fix") == "escape_holes"]
    if trap and python:
        r = by_id[trap[0]]
        d, n = float(r["hole_d"]), int(r.get("hole_n", 2))
        fid, key = _uid(src, "dfm_escape"), _uid(src, "dfm_escape_d")
        code = (f"def {fid}(self, v, body):\n"
                f"    from form.dfm import ops\n"
                f"    return ops.escape_holes(body, d=v[{key!r}], count={n})\n")
        src_txt = rules.source_text(t["sources"][r["hole_source"]]) if r.get("hole_source") in t["sources"] else "unsourced"
        props.append({"id": "escape_holes", "kind": "escape_holes", "rules": trap,
                      "summary": f"{n} escape holes Ø{d:g} mm from each enclosed void ({src_txt})",
                      "attempts": [[{"op": "insert", "param": {"key": key, "label": "Escape hole diameter", "default": d,
                                                                "min": d, "max": max(4 * d, 10.0), "step": 0.25, "unit": "mm",
                                                                "group": "process", "feature": fid,
                                                                "doc": r.get("hole_quote", "")}},
                                    {"op": "insert", "feature": fid, "label": "Escape holes", "role": "access",
                                     "code": code}]]})

    # thicker walls, by the parameter that sets them
    thin = [rid for rid in bad if by_id[rid].get("fix") == "thicken" and rows[rid]["op"] == ">="]
    for rid in thin:
        row = rows[rid]
        target = max(x for x in (row.get("fail"), row.get("warn")) if x is not None)
        v = row.get("value")
        if not isinstance(v, (int, float)):
            continue
        routes = _param_route(st, p, v, target, ("wall", "thick", "t", "skin", "rib"))
        if routes:
            props.append({"id": f"thicken:{rid}", "kind": "thicken", "rules": [rid],
                          "summary": f"Wall {v:g} → {target:g} mm by " + routes[0][1],
                          "attempts": [ops for ops, _w in routes[:3]]})
        else:
            props.append({"id": f"thicken:{rid}", "kind": "thicken", "rules": [rid], "attempts": [],
                          "summary": f"No parameter of the design is the {v:g} mm wall: thicken it in the source "
                                     "(edit_design) or say which value sets it."})

    # holes to the drill series
    drill = [rid for rid in bad if by_id[rid].get("fix") == "hole_to_drill"]
    for rid in drill:
        att = []
        for f in res["findings"]:
            if f["rule"] == rid and f.get("d_mm") and f.get("nearest_drill_mm"):
                for ops, _why in _param_route(st, p, f["d_mm"], f["nearest_drill_mm"], ("hole", "bore", "d"),
                                              tol=1e-3 + 0.002 * f["d_mm"], exact=True):
                    att.append(ops)
                    break
        if att:
            props.append({"id": f"drill:{rid}", "kind": "hole_to_drill", "rules": [rid],
                          "summary": "Holes set to the nearest drill size", "attempts": [sum(att, [])]})

    for pr in props:
        pr["proof"] = "Built without saving and checked (preview); applied through edit_design; checked again on " \
                      "the new head. Fixed only when that run passes " + ", ".join(pr["rules"]) + "."
        pr["ops"] = pr["attempts"][0] if pr["attempts"] else []
    return props


def _candidate(st, p, ops):
    """The head's canonical source with the ops applied, stored as a source (not a revision), and its values."""
    from .. import edits
    c = edits.canonical(st, p, verify=True)
    new, info = edits.apply(c["source"], ops)
    rid = st._load_design(new, "python")
    rec = st.recipes[rid]
    head = st.rev(p)["values"]
    keys = {q.key for q in rec.params}
    vals = {**rec.defaults(), **{k: v for k, v in head.items() if k in keys}, **{k: float(v) for k, v in info["values"].items()}}
    return rid, st._validate(rid, vals), c.get("mode")


def _worse(before: dict, after: dict, targets) -> list:
    out = []
    for rid, b in before.items():
        a = after.get(rid)
        if a is None or rid in targets:
            continue
        if RANK.get(a["status"], 0) > RANK.get(b["status"], 0):
            out.append({"rule": rid, "before": b["status"], "after": a["status"], "value_before": b.get("value"),
                        "value_after": a.get("value")})
    return out


def _row_diff(before: dict, after: dict, ids) -> list:
    return [{"rule": i, "title": before[i]["title"], "before": before[i]["status"], "after": after.get(i, {}).get("status"),
             "value_before": before[i].get("value"), "value_after": after.get(i, {}).get("value"),
             "unit": before[i].get("unit")} for i in ids if i in before]


def apply_fix(st, p, process, fix=None, options=None, apply=True, accept_trades=False, expect_head=None) -> dict:
    from . import check, evaluate, measured, options_for, process_id, render, default_process
    from .. import edits
    p = st.load(p["id"])
    process = process_id(process or default_process(p) or "")
    if expect_head is not None and p["head"] != expect_head:
        raise _err(f"The design moved on: head is r{p['head']}, not r{expect_head}.",
                   "Read the project again, then ask for the fix again.", status=409, head=p["head"])
    head = p["head"]
    o = options_for(st, p, process, options)
    before = check(st, p, process, options)
    props = before.get("fixes") or []
    if not props:
        failing = [r["id"] for r in before["rows"] if r["status"] in ("fail", "warn")]
        raise _err("No fix can be proposed for this design and process." + (f" Failing: {', '.join(failing)}." if failing else
                   " Nothing fails."), "Fixes exist for draft, internal corners, escape holes, walls set by a "
                   "parameter and holes set by a parameter. Other findings need a change by hand.", status=409)
    if fix:
        pick = [x for x in props if x["id"] == fix or fix in x["rules"] or fix.split("#")[0] in x["rules"]]
        if not pick:
            raise _err(f"No fix “{fix}” for this result.", "Fixes: " + ", ".join(x["id"] for x in props) + ".", status=404)
        prop = pick[0]
    else:
        prop = props[0]
    if not prop["attempts"]:
        return {"fixed": False, "applied": False, "fix": prop, "why": prop["summary"], "before": _short(before)}
    brow = {r["id"]: r for r in before["rows"]}
    tried = []
    chosen = None
    for ops in prop["attempts"]:
        try:
            rid, vals, mode = _candidate(st, p, ops)
            meas, gk = measured(st, p, process, o, rid=rid, values=vals)
            prev = evaluate(st, p, process, o, meas, gk, None)
        except Exception as e:                           # noqa: BLE001 - a candidate that does not build is reported
            tried.append({"ops": ops, "built": False, "error": str(e), "hint": getattr(e, "hint", "")})
            continue
        prow = {r["id"]: r for r in prev["rows"]}
        ok = all(prow.get(r, {}).get("status") in ("pass", "info", "n/a") for r in prop["rules"])
        trades = _worse(brow, prow, prop["rules"])
        tried.append({"ops": ops, "built": True, "targets": _row_diff(brow, prow, prop["rules"]), "trades": trades,
                      "passes": ok})
        if ok:
            chosen = (ops, prev, trades, mode)
            break
    if chosen is None:
        return {"fixed": False, "applied": False, "fix": {k: v for k, v in prop.items() if k != "attempts"},
                "why": "No candidate turned the rule to pass in the preview, so nothing was saved.", "tried": tried,
                "before": _short(before)}
    ops, prev, trades, mode = chosen
    if trades and not accept_trades:
        return {"fixed": False, "applied": False, "fix": {k: v for k, v in prop.items() if k != "attempts"}, "ops": ops,
                "why": "The fix passes its rule but makes another rule worse; nothing was saved.", "trades": trades,
                "preview": _row_diff(brow, {r["id"]: r for r in prev["rows"]}, prop["rules"]), "tried": tried,
                "hint": "Pass accept_trades=true to apply it anyway, or fix by hand."}
    preview = _row_diff(brow, {r["id"]: r for r in prev["rows"]}, prop["rules"])
    if not apply:
        return {"fixed": False, "applied": False, "previewed": True, "fix": {k: v for k, v in prop.items() if k != "attempts"},
                "ops": ops, "preview": preview, "trades": trades, "canonical": mode,
                "note": "Preview only: built and checked, not saved. Apply it to make a revision and prove it."}
    out = edits.edit(st, p, ops, expect_head=head, note=f"Manufacturability fix ({process}): {prop['summary']}",
                     origin="agent")
    p2 = st.load(p["id"])
    after = check(st, p2, process, options, force=True)        # the proof: measured again on the new head
    arow = {r["id"]: r for r in after["rows"]}
    fixed = all(arow.get(r, {}).get("status") in ("pass", "info", "n/a") for r in prop["rules"])
    pics = {}
    for nm, res, pp in (("before", before, p), ("after", after, p2)):
        try:
            pics[nm] = render(st, pp, res)
        except Exception:                                  # noqa: BLE001 - a picture is a convenience
            pics[nm] = None
    return {"fixed": fixed, "applied": True, "head": out["head"], "from_rev": head,
            "fix": {k: v for k, v in prop.items() if k != "attempts"}, "ops": ops,
            "proof": _row_diff(brow, arow, prop["rules"]), "preview": preview,
            "trades": _worse(brow, arow, prop["rules"]), "before": _short(before), "after": _short(after),
            "pictures": pics, "changed": out.get("changed"),
            "note": ("Fixed: the check run again on r%02d passes %s." % (out["head"], ", ".join(prop["rules"]))) if fixed
            else ("Applied as r%02d, but the check run again on it does not pass %s: not fixed." % (out["head"], ", ".join(prop["rules"])))}


def _short(res: dict) -> dict:
    return {"rev": res.get("rev"), "verdict": res.get("verdict"), "headline": res.get("headline"), "key": res.get("key"),
            "rows": [{k: r.get(k) for k in ("id", "status", "value", "unit")} for r in res.get("rows", [])]}
