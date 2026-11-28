"""Redefine a feature made by hand: its options read back from its code, and the edit ops that write new ones.

The property card (form/app/qml/Form/FeatureCard.qml) shows what a hand feature was made with and changes it. Its
numbers are parameters and change as values; its choices are written in the feature's call (an extrude's end
condition, a revolve's mid-plane, a boolean's operation, a split's kept side), so changing one rewrites that call.
options() reads them from the source (no kernel); ops() turns a change into edit ops: the feature's method replaced,
the parameters a new choice reads added, the ones it no longer reads removed, and changed numbers as set_param. The
ops go through modelling.preview / modelling.commit like any other hand edit: built in the kernel before anything is
saved, refused with the reason.

    extrude, cut   end, to (a face query, kept unless to_at picks another face), to_at, offset, reverse, draft,
                   end2, depth2, to2, to2_at, offset2, draft2, thin, thin_mode, thin2
    revolve        end (angle | face), to, to_at, angle2, mid, reverse
    boolean        op;  split  keep, plane;  mirror  plane;  rib  direction, flip;  loft  ruled;  thicken  both;
    draft          flip;  sweep  frenet

Nothing here imports the kernel (a face picked with to_at is found by the worker, op model_pick).
"""
from __future__ import annotations

import ast
import textwrap

from . import featureprog

SKETCH_KINDS = ("extrude", "cut", "revolve")
# the parameters an end condition reads, by suffix (form/modelling_more.end_args writes them)
END_SUFFIXES = ("offset", "offset2", "draft", "draft2", "depth2", "thin", "thin2", "angle2")
# the choices of the further kinds written in their call: (option, positional index or None for a keyword, allowed)
LITERALS = {
    "boolean": [("op", 2, ("combine", "subtract", "intersect"))],
    "split": [("keep", 4, ("both", "above", "below")), ("plane", 2, ("XY", "XZ", "YZ"))],
    "mirror": [("plane", 2, ("XY", "XZ", "YZ"))],
    "rib": [("direction", 6, ("parallel", "normal")), ("flip", None, (True, False))],
    "loft": [("ruled", None, (True, False))],
    "thicken": [("both", None, (True, False))],
    "draft": [("flip", None, (True, False))],
    "sweep": [("frenet", None, (True, False))],
}
HANDMORE = ("sweep", "loft", "rib", "mirror", "draft", "move_face", "thicken", "boolean", "split", "variable_fillet",
            "datum_plane", "datum_axis")


def _err(msg, hint="", **kw):
    from . import modelling
    return modelling._err(msg, hint, **kw)


def _fn(source: str, fid: str):
    tree = ast.parse(featureprog.strip_partial(source))
    c = featureprog._feature_class(tree)
    fn = next((n for n in (c.body if c else []) if isinstance(n, ast.FunctionDef) and n.name == fid), None)
    if fn is None:
        raise _err(f"No feature “{fid}” in this design.")
    return fn


def call_of(source: str, fid: str):
    """(the feature's kind, its handsketch / handmore call node) or (None, None) for a feature written as code."""
    fn = _fn(source, fid)
    ret = [n for n in ast.walk(fn) if isinstance(n, ast.Return) and isinstance(n.value, ast.Call)]
    for r in ret:
        f = r.value.func
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
            if f.value.id == "handsketch" and f.attr in ("extrude", "revolve"):
                mode = _lit(r.value.args[6 if f.attr == "extrude" else 7]) if len(r.value.args) > (6 if f.attr == "extrude" else 7) else "add"
                return ("cut" if f.attr == "extrude" and mode == "cut" else f.attr), r.value
            if f.value.id == "handmore" and f.attr in HANDMORE:
                return f.attr, r.value
    return None, None


def _lit(node):
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError, TypeError):
        return None


def _key(node) -> str | None:
    """The parameter key of v["key"]."""
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
        k = node.slice
        if isinstance(k, ast.Constant) and isinstance(k.value, str):
            return k.value
    return None


def options(source: str, fid: str, values: dict | None = None) -> dict | None:
    """What the feature was made with, read from its call: {kind, mode, ...options}. A number an option reads from a
    parameter is that parameter's key under "<option>_key" and its value (from values) under the option. None for a
    feature written as code."""
    kind, call = call_of(source, fid)
    if not kind:
        return None
    values = values or {}
    out: dict = {"kind": kind}
    if kind in SKETCH_KINDS:
        i = 6 if kind != "revolve" else 7
        out["mode"] = _lit(call.args[i]) if len(call.args) > i else "add"
        for k in call.keywords:
            if not k.arg:
                continue
            pk = _key(k.value)
            if pk:
                out[k.arg + "_key"] = pk
                out[k.arg] = values.get(pk)
            else:
                out[k.arg] = _lit(k.value)
        if kind != "revolve":
            out.setdefault("end", "")
            out.setdefault("end2", "")
            if not out["end"]:                     # the classic behaviour: blind, or a cut of depth 0 through all
                d = values.get(f"{fid}_depth")
                out["end_shown"] = "through" if kind == "cut" and not d else "blind"
            else:
                out["end_shown"] = out["end"]
            out["has_to"] = isinstance(out.get("to"), (dict, list))
            out["has_to2"] = isinstance(out.get("to2"), (dict, list))
        else:
            out.setdefault("end", "angle")
            out["has_to"] = isinstance(out.get("to"), dict)
        out.pop("to", None)
        out.pop("to2", None)
        return out
    for name, pos, _allowed in LITERALS.get(kind, []):
        if pos is not None:
            v = _lit(call.args[pos]) if len(call.args) > pos else None
            if name == "plane" and isinstance(v, dict):
                v = v.get("datum") or ("face" if "face" in v else "datum plane" if "ref" in v else None)
            out[name] = v
        else:
            kw = next((k for k in call.keywords if k.arg == name), None)
            out[name] = bool(_lit(kw.value)) if kw is not None else False
    if kind == "mirror" and len(call.args) > 3:
        out["of"] = _lit(call.args[3])
    return out


def _seg(source: str, node) -> str:
    return ast.get_source_segment(source, node)


def _method_ops(source: str, call, fid: str, new_call: str) -> dict:
    from . import edits
    new_src = edits._cut(source, call, new_call)
    x, y = featureprog.method_spans(new_src)[fid]
    return {"op": "replace", "feature": fid, "code": textwrap.dedent("\n".join(new_src.splitlines()[x - 1:y]))}


def ops(st, p: dict, fid: str, change: dict, values: dict | None = None) -> tuple[list, str]:
    """(edit ops that give feature fid the changed options, a sentence of what changed). change holds only what
    changes; null removes an option (a draft of 0, no second direction). values: numbers changed with it (param
    key -> value), written as set_param."""
    from . import modelling, modelling_more
    c = modelling._canonical(st, p)
    src = c["source"]
    kind, call = call_of(src, fid)
    if not kind:
        raise _err(f"{fid} is written as code, not made by hand.", "Ask your agent to change it, or edit its code.")
    head = st.rev(p)["values"]
    vals = {**head, **{k: float(v) for k, v in (values or {}).items()}}
    change = dict(change or {})
    declared = {q.key: q for q in st.recipes[c["rid"]].params} if c.get("rid") in st.recipes else {}
    out: list = []
    said: list = []
    if kind in SKETCH_KINDS:
        cur = {}
        for k in call.keywords:
            if not k.arg:
                continue
            pk = _key(k.value)
            cur[k.arg] = vals.get(pk) if pk else _lit(k.value)
        o = {k: v for k, v in cur.items() if v is not None}
        for k in ("to_at", "to2_at"):
            if change.get(k):
                o.pop(k[:-3], None)                  # a newly picked face replaces the one written
        for k, v in change.items():
            if v is None or v == "" or v is False:
                o.pop(k, None)
            else:
                o[k] = v
        for sfx in END_SUFFIXES:                     # a number changed beside the choice: the option takes it
            pk = f"{fid}_{sfx}"
            if pk in (values or {}) and sfx in o and not isinstance(o.get(sfx), str):
                o[sfx] = vals[pk]
        if "depth2" in o and o.get("end2") in (None, ""):
            o.pop("depth2", None)
        if o.get("end2") == "blind" and not o.get("depth2"):    # a blind second direction starts at the first's depth
            o["depth2"] = float(vals.get(f"{fid}_depth") or 0) or 10.0
        if kind != "revolve" and o.get("end") in ("blind", "mid") and not vals.get(f"{fid}_depth"):
            d = float(change.get("depth") or 0) or 10.0
            out.append({"op": "set_param", "param": f"{fid}_depth", "value": d})
            vals[f"{fid}_depth"] = d
        label = fid.replace("_", " ").capitalize()
        kw, eparams, summary = modelling_more.end_args(st, p, c, kind, fid, label, o)
        i = 6 if kind != "revolve" else 7
        pos = [_seg(src, a) for a in call.args]
        while len(pos) <= i:
            pos.append('"add"')
        new_call = _seg(src, call.func) + "(" + ", ".join(pos) + kw + ")"
        want = {q["key"]: q for q in eparams}
        have = {k for k in declared if k.startswith(fid + "_") and k[len(fid) + 1:] in END_SUFFIXES}
        for k, q in want.items():
            if k not in declared:
                out.append({"op": "insert", "param": q})
            elif abs(float(q["default"]) - float(vals.get(k, q["default"]))) > 1e-12 or k in (values or {}):
                out.append({"op": "set_param", "param": k, "value": float(q["default"]),
                            **({"min": min(q["min"], declared[k].min), "max": max(q["max"], declared[k].max)}
                               if not declared[k].min <= float(q["default"]) <= declared[k].max else {})})
        out.append(_method_ops(src, call, fid, new_call))
        out += [{"op": "delete", "param": k} for k in sorted(have - set(want))]
        said.append(summary or "blind")
    else:
        spec = LITERALS.get(kind)
        if not spec:
            raise _err(f"{fid} has no choices to change, only its numbers.", "Change its values in the card.")
        args = [_seg(src, a) for a in call.args]
        kws = {k.arg: _seg(src, k.value) for k in call.keywords if k.arg}
        for name, pos, allowed in spec:
            if name not in change:
                continue
            v = change[name]
            if pos is None:
                v = bool(v)
                if v:
                    kws[name] = "True"
                else:
                    kws.pop(name, None)
                said.append(f"{name} {'on' if v else 'off'}")
                continue
            if v not in allowed:
                raise _err(f"Unknown {name} “{v}”.", ", ".join(str(a) for a in allowed) + ".")
            if name == "plane":
                old = _lit(call.args[pos]) or {}
                if not isinstance(old, dict) or "datum" not in old:
                    raise _err("This plane is a face or a datum plane; only a datum plane XY, XZ or YZ can be "
                               "picked here.", "Ask your agent to move it to another plane.")
                lit = modelling_more._lit({"datum": v, "offset": float(old.get("offset") or 0)})
            else:
                lit = modelling._q(v)
            while len(args) <= pos:
                raise _err(f"{fid}'s call has no {name} to change.", "Ask your agent.")
            if kind == "split" and name == "keep" and v == "both" and _lit(call.args[pos]) != "both":
                out += modelling_more._solids_ops(st, p, c, 1)       # both sides kept: one more body
            args[pos] = lit
            said.append(f"{name} {v}")
        extra = "".join(f", {k}={x}" for k, x in kws.items())
        new_call = _seg(src, call.func) + "(" + ", ".join(args) + extra + ")"
        out.append(_method_ops(src, call, fid, new_call))
    for k, v in (values or {}).items():
        if any(isinstance(x, dict) and x.get("param") == k for x in out) or k not in declared:
            continue
        out.append({"op": "set_param", "param": k, "value": float(v)})
    return out, f"Changed {fid.replace('_', ' ').capitalize()}: " + ", ".join(s for s in said if s)
