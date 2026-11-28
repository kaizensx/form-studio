"""Modelling by hand, with the agent in the loop: the feature tree and picked features, written as the design's source.

One source for the person and the agent. Every action here is an edit of the design's code through the edit
protocol (form/edits.py), so it is reviewable, diffable (geometry_diff), revertible and optimisable, and the agent
reads it like its own work.

The tree (B1), edit ops on a FeatureDesign:

    {"op": "suppress", "feature": "holes"}                 @feature(..., suppressed=True): in the source, not built
    {"op": "restore",  "feature": "holes"}                 built again
    {"op": "move",     "feature": "holes", "after": "rib"} | "before": ...   the build order; refused when a feature
                                                           would come before one it reads (static), or when the
                                                           build then leaves one out or makes it do nothing (built)
    {"op": "rename",   "feature": "holes", "label": "Mount holes", "id": "mount_holes"}   the label, the id or both;
                                                           a new id is carried to every place the source names it

    tree_of(source)          per feature: label, role, suppressed, and what it depends on: the parameters it reads,
                             the features it names (picked edges and faces, a pattern's feature), helpers and members
    view_upto(st, p, fid)    the solid as it stood after one feature: the rollback bar. The features up to it load from
                             their checkpoints (form/featureprog.py), so it costs a tessellation, not a rebuild

Picked features (B2): plan(st, p, kind, picks, ...) reads the picks on the head in the kernel (form/handfeat.py,
op model_pick) and returns the edit ops that add one feature method and its parameters:

    fillet    picks near edges, radius                      chamfer   picks near edges, length
    hole      a pick on a flat face; standard clearance (ISO 273: close | normal | loose), tapped (tap drill),
              iso286 (nominal Ø and a hole tolerance such as H7, modelled at mid-tolerance) or plain (d);
              style plain | counterbore | countersink (ISO 4762 / ISO 10642 heads + clearance); depth 0 = through
    pattern   of=<feature>, linear (axis, count, pitch mm) or polar (axis, origin, count, angle step degrees)
    shell     an optional pick on the face to leave open, thickness

preview(st, p, ops) builds the result without saving it (a draft with computed impact: volume, box, faces, the build
log of every feature, form.craft's notes) and says when it must be refused. commit(...) previews, then saves one
revision through edits.edit; the caller runs the pipeline, so every check is computed again on the new solid.
Nothing here imports the kernel: the builds run in the worker.
"""
from __future__ import annotations

import ast
import re

from . import edits, featureprog

TREE_OPS = ("suppress", "restore", "move", "rename")
SKETCH_KINDS = ("extrude", "cut", "revolve")
from .modelling_more import KINDS as MORE_KINDS  # noqa: E402

KINDS = ("fillet", "chamfer", "hole", "pattern", "shell") + SKETCH_KINDS + MORE_KINDS
ROLES = {"fillet": "finish", "chamfer": "finish", "hole": "interface", "pattern": "structure", "shell": "structure",
         "extrude": "structure", "cut": "structure", "revolve": "structure"}
EVIDENCE = "computed (B-rep)"
RB_START = "# ---- Form Studio: rollback view (built up to one feature; never saved) ----"
RB_END = "# ---- end of rollback view ----"


def _bad(msg: str, hint: str = ""):
    return edits._Bad(msg, hint)


def _err(msg: str, hint: str = "", **extra):
    from .studio import StudioError
    return StudioError(msg, hint, **extra)


# ---- reading the feature class -------------------------------------------------------------------------------------

def _methods(source: str) -> tuple[ast.Module, object, dict]:
    tree = ast.parse(featureprog.strip_partial(source))
    c = featureprog._feature_class(tree)
    if c is None:
        raise _bad("this design has no feature methods", "The tree works on a FeatureDesign; get_design_source "
                   "shows the canonical form an edit is applied to.")
    nodes = {n.name: n for n in c.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
             and featureprog._is_feature(n)}
    return tree, c, nodes


def _deco(fn):
    for d in fn.decorator_list:
        t = d.func if isinstance(d, ast.Call) else d
        if featureprog._base_name(t) == "feature":
            return d
    return None


def _deco_kw(fn) -> dict:
    d = _deco(fn)
    out = {}
    if isinstance(d, ast.Call):
        if d.args and isinstance(d.args[0], ast.Constant):
            out["label"] = d.args[0].value
        for k in d.keywords:
            if k.arg:
                try:
                    out[k.arg] = ast.literal_eval(k.value)
                except ValueError:
                    out[k.arg] = ast.unparse(k.value)
    return out


def _q(s: str) -> str:
    """A string literal as designs write them (double quotes)."""
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def _pos(source: str, line: int, col: int) -> int:
    return edits._offsets(source)[line - 1] + col


def _splice(source: str, a: int, b: int, new: str) -> str:
    raw = source.encode("utf-8")
    return (raw[:a] + new.encode("utf-8") + raw[b:]).decode("utf-8")


def _set_deco(source: str, fn, changes: dict) -> str:
    """The source with the @feature(...) of fn changed in place, the rest of its text kept as written: label (the
    first argument) and one keyword at a time (a value sets it, None takes it out)."""
    for k, v in changes.items():
        tree = ast.parse(source)
        c = featureprog._feature_class(tree)
        fn = next(n for n in c.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == fn.name)
        d = _deco(fn)
        if not isinstance(d, ast.Call):                    # a bare @feature: give it its call
            a, b = _pos(source, d.lineno, d.col_offset), _pos(source, d.end_lineno, d.end_col_offset)
            source = _splice(source, a, b, source.encode("utf-8")[a:b].decode("utf-8") + "()")
            tree = ast.parse(source)
            c = featureprog._feature_class(tree)
            fn = next(n for n in c.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == fn.name)
            d = _deco(fn)
        end = _pos(source, d.end_lineno, d.end_col_offset) - 1          # the closing parenthesis
        if k == "label":
            if d.args and isinstance(d.args[0], ast.Constant):
                source = edits._cut(source, d.args[0], _q(v))
            elif any(x.arg == "label" for x in d.keywords):
                source = edits._cut(source, next(x for x in d.keywords if x.arg == "label").value, _q(v))
            else:
                at = _pos(source, d.func.end_lineno, d.func.end_col_offset) + 1
                source = _splice(source, at, at, _q(v) + (", " if d.args or d.keywords else ""))
            continue
        kw = next((x for x in d.keywords if x.arg == k), None)
        lit = repr(v) if not isinstance(v, str) else _q(v)
        if kw is not None and v is not None:
            source = edits._cut(source, kw.value, lit)
        elif kw is None and v is not None:
            source = _splice(source, end, end, (", " if d.args or d.keywords else "") + f"{k}={lit}")
        elif kw is not None:
            items = list(d.args) + list(d.keywords)
            i = items.index(kw)
            b = _pos(source, kw.end_lineno, kw.end_col_offset)
            if i:                                          # from the end of the item before it
                prev = items[i - 1]
                a = _pos(source, prev.end_lineno, prev.end_col_offset)
            else:                                          # the first item: up to the next one
                a = _pos(source, kw.lineno, kw.col_offset)
                if len(items) > 1:
                    b = _pos(source, items[1].lineno, items[1].col_offset)
            source = _splice(source, a, b, "")
    return source


def _reads(fn, ids: set) -> dict:
    """What one feature method reads, from its code (static): parameters, other features named, helpers, members."""
    vname = fn.args.args[1].arg if len(fn.args.args) > 1 else "v"
    params, feats, helpers, members = set(), set(), set(), set()
    for x in ast.walk(fn):
        if isinstance(x, ast.Subscript) and isinstance(x.value, ast.Name) and x.value.id == vname \
                and isinstance(x.slice, ast.Constant) and isinstance(x.slice.value, str):
            params.add(x.slice.value)
        elif isinstance(x, ast.Call) and isinstance(x.func, ast.Attribute) and isinstance(x.func.value, ast.Name) \
                and x.func.value.id == vname and x.func.attr == "get" and x.args and isinstance(x.args[0], ast.Constant):
            params.add(x.args[0].value)
        elif isinstance(x, ast.Constant) and isinstance(x.value, str) and x.value in ids and x.value != fn.name:
            feats.add(x.value)
        elif isinstance(x, ast.Call) and isinstance(x.func, ast.Name):
            helpers.add(x.func.id)
        elif isinstance(x, ast.Attribute) and isinstance(x.value, ast.Name) and x.value.id == "self" \
                and not x.attr.startswith("_form_"):
            members.add("setup" if x.attr == "ctx" else x.attr)
    return {"params": sorted(params), "features": sorted(feats), "helpers": sorted(helpers), "members": sorted(members)}


def tree_of(source: str) -> list:
    """The features in build order with what each depends on (read from the source; no build)."""
    try:
        tree, c, nodes = _methods(source)
    except (edits._Bad, SyntaxError):
        return []
    mod_funcs = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    owned: dict = {}                                  # a feature that hands v to a helper reads its own parameters
    for key, call in edits._param_calls(tree)[1].items():
        f = edits._param_fields(call).get("feature")
        if isinstance(f, ast.Constant) and isinstance(f.value, str):
            owned.setdefault(f.value, []).append(key)
    ids = list(nodes)
    out, prev = [], None
    for fid in ids:
        fn = nodes[fid]
        kw = _deco_kw(fn)
        r = _reads(fn, set(ids))
        vname = fn.args.args[1].arg if len(fn.args.args) > 1 else "v"
        if any(isinstance(x, ast.Call) and any(isinstance(a, ast.Name) and a.id == vname for a in x.args)
               for x in ast.walk(fn)):
            r["params"] = sorted(set(r["params"]) | set(owned.get(fid, [])))
        r["helpers"] = [h for h in r["helpers"] if h in mod_funcs]
        row = {"id": fid, "label": kw.get("label") or fid.replace("_", " ").capitalize(), "role": kw.get("role", "structure"),
               "suppressed": bool(kw.get("suppressed")), "after": prev, "reads": r}
        out.append(row)
        if not row["suppressed"]:
            prev = fid
    users: dict = {}
    for row in out:
        for f in row["reads"]["features"]:
            users.setdefault(f, []).append(row["id"])
    for row in out:
        row["used_by"] = users.get(row["id"], [])
    return out


# ---- the tree ops (applied by edits._apply_one) --------------------------------------------------------------------

def suppress(source: str, fid: str, on: bool) -> str:
    _tree, _c, nodes = _methods(source)
    if fid not in nodes:
        raise _bad(f"no feature “{fid}”", "Features: " + ", ".join(nodes) + ".")
    if on and fid == next(iter(nodes)):
        raise _bad(f"{fid} is the first feature: every later feature starts from it, so it cannot be suppressed",
                   "Suppress the features after it instead.")
    now = bool(_deco_kw(nodes[fid]).get("suppressed"))
    if now == on:
        raise _bad(f"{fid} is already {'suppressed' if on else 'built (not suppressed)'}")
    if on:
        users = [r["id"] for r in tree_of(source) if fid in r["reads"]["features"] and not r["suppressed"]]
        if users:
            raise _bad(f"{', '.join(users)} read{'s' if len(users) == 1 else ''} what {fid} makes, so {fid} cannot be "
                       "suppressed alone", "Suppress " + ", ".join(users) + " first (or in the same edit, before it).")
    return _set_deco(source, nodes[fid], {"suppressed": True if on else None})


def rename(source: str, fid: str, label: str | None = None, new_id: str | None = None) -> str:
    _tree, _c, nodes = _methods(source)
    if fid not in nodes:
        raise _bad(f"no feature “{fid}”", "Features: " + ", ".join(nodes) + ".")
    if label is None and not new_id:
        raise _bad("rename needs label, id or both")
    out = source
    if label is not None:
        label = str(label).strip()
        if not label or len(label) > 80:
            raise _bad("a feature's label is 1 to 80 characters")
        out = _set_deco(out, nodes[fid], {"label": label})
    if new_id and new_id != fid:
        if not featureprog._ID.fullmatch(new_id) or new_id in featureprog.RESERVED:
            raise _bad(f"“{new_id}” cannot be a feature id", "Lower-case letters, digits and _, not a Recipe method name.")
        tree = ast.parse(out)
        c = featureprog._feature_class(tree)
        if any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == new_id for n in c.body):
            raise _bad(f"the design already has a method called {new_id}")
        lines = out.splitlines(keepends=True)
        fn = next(n for n in c.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == fid)
        # every place the source names the feature: parameters' feature field, picked edges' owners, patterns
        consts = [x for x in ast.walk(tree) if isinstance(x, ast.Constant) and x.value == fid]
        for x in sorted(consts, key=lambda n: (n.lineno, n.col_offset), reverse=True):
            out = edits._cut(out, x, _q(new_id))
        lines = out.splitlines(keepends=True)
        i = fn.lineno - 1
        lines[i] = re.sub(r"\bdef\s+" + re.escape(fid) + r"\b", "def " + new_id, lines[i], count=1)
        out = "".join(lines)
    return out


def move(source: str, fid: str, before: str | None = None, after: str | None = None) -> str:
    _tree, _c, nodes = _methods(source)
    ids = list(nodes)
    if fid not in nodes:
        raise _bad(f"no feature “{fid}”", "Features: " + ", ".join(ids) + ".")
    if bool(before) == bool(after):
        raise _bad("move needs exactly one of before or after (a feature id)")
    ref = before or after
    if ref not in nodes or ref == fid:
        raise _bad(f"no other feature “{ref}” to move {fid} {'before' if before else 'after'}")
    if fid == ids[0]:
        raise _bad(f"{fid} is the first feature (the skeleton every other one starts from); it stays first")
    if before == ids[0]:
        raise _bad(f"nothing goes before {ids[0]}: it is the skeleton every other feature starts from")
    order = [x for x in ids if x != fid]
    order.insert(order.index(ref) + (0 if before else 1), fid)
    if order == ids:
        raise _bad(f"{fid} is already there")
    rows = {r["id"]: r for r in tree_of(source)}
    for k, x in enumerate(order):
        later = [f for f in rows[x]["reads"]["features"] if f in order[k + 1:]]
        if later:
            raise _bad(f"{x} reads what {later[0]} makes (its picked edges or faces, or the feature it repeats), so it "
                       f"cannot come before {later[0]}", f"Keep {x} after {later[0]}.")
    spans = featureprog.method_spans(source)
    lines = source.splitlines()
    a, b = spans[fid]
    while a > 1 and not lines[a - 2].strip():
        a -= 1
    block = lines[a - 1:b]
    rest = lines[:a - 1] + lines[b:]
    s2 = "\n".join(rest) + "\n"
    sp2 = featureprog.method_spans(s2)
    ra, rb = sp2[ref]
    rl = s2.splitlines()
    block = [ln for ln in block]
    while block and not block[0].strip():
        block = block[1:]
    if before:
        at = ra - 1
        new = rl[:at] + block + [""] + rl[at:]
    else:
        new = rl[:rb] + [""] + block + rl[rb:]
    return "\n".join(new) + "\n"


def apply_tree_op(source: str, op: dict) -> str:
    kind = op.get("op")
    fid = op.get("feature")
    if not isinstance(fid, str) or not fid:
        raise _bad(f"{kind} needs feature: the feature's id")
    if kind in ("suppress", "restore"):
        return suppress(source, fid, kind == "suppress")
    if kind == "rename":
        return rename(source, fid, op.get("label"), op.get("id"))
    return move(source, fid, op.get("before"), op.get("after"))


# ---- the rollback view ---------------------------------------------------------------------------------------------

def upto_source(source: str, fid: str) -> str:
    base = featureprog.strip_partial(strip_rollback(source))
    ids = featureprog.feature_ids(base)
    if fid not in ids:
        raise _err(f"No feature “{fid}” in this design.", "Features: " + ", ".join(ids) + ".")
    cls = featureprog._class_name(base)
    return (base.rstrip() + f"\n\n{RB_START}\nfrom form import featureprog as _form_fp\n"
            f"{cls} = _form_fp.rollback({cls}, upto={_q(fid)})\n{RB_END}\n")


def strip_rollback(source: str) -> str:
    i = source.find(RB_START)
    if i < 0:
        return source
    j = source.find(RB_END, i)
    return (source[:i].rstrip() + "\n" + (source[j + len(RB_END):].lstrip("\n") if j >= 0 else "")).rstrip() + "\n"


def _canonical(st, p) -> dict:
    c = edits.canonical(st, p)
    if c["mode"] == "none" or not featureprog.is_feature_design(c["source"]):
        raise _err("This design is not written as features, so the tree and picked features do not apply to it.",
                   c.get("why") or "Write it as a FeatureDesign (design_guide) and every feature becomes a line here.",
                   status=409)
    return c


def view_upto(st, p: dict, fid: str, tol: float = 0.03) -> dict:
    """The head's solid as it stood after feature fid (the features after it are not built). From checkpoints."""
    import time
    c = _canonical(st, p)
    ids = featureprog.feature_ids(c["source"])
    if fid not in ids:
        raise _err(f"No feature “{fid}” in this design.", "Features: " + ", ".join(ids) + ".")
    k = ids.index(fid)
    t0 = time.perf_counter()
    vals = st.rev(p)["values"]
    rid = st._load_design(upto_source(c["source"], fid), "python")
    v = st._k("view", key=st.geometry_key(p, rid, vals), recipe_id=rid, values=vals, tol=tol, p=p, rev=p["head"])
    v["upto"] = {"feature": fid, "built": ids[:k + 1], "after": ids[k + 1:], "rev": p["head"],
                 "ms": round(1000 * (time.perf_counter() - t0), 1),
                 "note": "Built up to this feature from its checkpoints; nothing is saved."}
    return v


def _spans(source: str) -> dict:
    """Each method of the source's classes: the lines it takes there, decorators included (1-based, inclusive)."""
    out: dict = {}
    try:
        mod = ast.parse(source)
    except SyntaxError:
        return out
    for cls in mod.body:
        if isinstance(cls, ast.ClassDef):
            for fn in cls.body:
                if isinstance(fn, ast.FunctionDef):
                    out[fn.name] = [min([fn.lineno] + [d.lineno for d in fn.decorator_list]), fn.end_lineno or fn.lineno]
    return out


def tree(st, p: dict) -> dict:
    c = _canonical(st, p)
    head = st.rev(p)
    log = {e["feature"]: e for e in head.get("build_log") or []}
    rows = tree_of(c["source"])
    vals = head["values"]
    for r in rows:
        e = log.get(r["id"])
        if e:
            r["last_build"] = {k: e[k] for k in ("status", "s", "dvol", "solids") if k in e}
        r["reads"]["values"] = {k: vals[k] for k in r["reads"]["params"] if k in vals}
    # who made each feature: the first revision whose build log names it, and that revision's origin. A feature no
    # build log names (a design older than build logs) carries no mark: nothing is guessed.
    made: dict = {}
    for rv in p.get("revisions") or []:
        for e in rv.get("build_log") or []:
            made.setdefault(e.get("feature"), {"rev": rv.get("n"), "origin": rv.get("origin") or "user"})
    spans = _spans(c["source"])
    for r in rows:
        if r["id"] in made:
            r["made"] = made[r["id"]]
        if r["id"] in spans:
            r["lines"] = spans[r["id"]]                  # its method in the source returned here, first and last line
    return {"project": p["id"], "head": p["head"], "form": c["mode"], "features": rows, "source": c["source"],
            "evidence": "read from the source (static); last_build is the head's build log; made is the first revision "
                        "whose build log names the feature"}


# ---- picked features: the ops that add one ---------------------------------------------------------------------------

def _free(ids, kind) -> tuple[str, int]:
    n = 1
    while f"{kind}_{n}" in ids:
        n += 1
    return f"{kind}_{n}", n


def _num(o, k, lo, hi, what, default=None):
    x = o.get(k, default)
    if x is None:
        raise _err(f"{what} is needed.", f"Give {k}.")
    try:
        x = float(x)
    except (TypeError, ValueError):
        raise _err(f"{what} must be a number.")
    if not (lo <= x <= hi):
        raise _err(f"{what} must be between {lo:g} and {hi:g}.")
    return x


def _r(x, d=3):
    return round(float(x), d)


def _lit(x) -> str:
    return repr(x).replace("'", '"')


def _axis(a) -> list:
    if isinstance(a, str) and a.lower().lstrip("-+") in ("x", "y", "z"):
        s = -1.0 if a.startswith("-") else 1.0
        return [s if a.lower().lstrip("-+") == k else 0.0 for k in "xyz"]
    try:
        v = [float(x) for x in a]
    except (TypeError, ValueError):
        raise _err("The axis is x, y, z or three numbers.")
    if len(v) != 3 or sum(x * x for x in v) < 1e-12:
        raise _err("The axis is x, y, z or three numbers that are not all 0.")
    return v


def _param(key, label, default, lo, hi, fid, doc, step=0.1, unit="mm", prov="assumed") -> dict:
    return {"key": key, "label": label, "default": _r(default, 4), "min": _r(lo, 4), "max": _r(hi, 4),
            "step": step, "unit": unit, "group": "form", "feature": fid, "doc": doc, "provenance": prov}


def plan(st, p: dict, kind: str, picks: list | None = None, **o) -> dict:
    """The edit ops that add one picked feature to the head, with what was picked (computed in the kernel)."""
    if kind not in KINDS:
        raise _err(f"Unknown feature kind “{kind}”.", "Kinds: " + ", ".join(KINDS) + ".")
    c = _canonical(st, p)
    ids = featureprog.feature_ids(c["source"])
    fid, n = _free(ids, kind)
    if o.get("feature_id"):
        fid = str(o["feature_id"])
    vals = st.rev(p)["values"]
    picked = None
    if kind in SKETCH_KINDS:
        return _plan_sketch(st, p, c, kind, fid, n, picks, o)
    if kind in MORE_KINDS:
        from . import modelling_more
        return modelling_more.plan(st, p, c, kind, fid, n, picks, o)
    if kind == "pattern" and isinstance(o.get("axis"), str) and o["axis"] in ids:   # a datum axis
        from . import modelling_more
        ax = modelling_more.axis_from_datum(c["source"], o["axis"])
        if ax is None:
            raise _err(f"{o['axis']} is an axis on an edge or where planes meet; a pattern reads an axis written by "
                       "points or a base axis.", "Give the axis as x, y, z or three numbers.")
        o = {**o, "axis": ax[1], **({"origin": ax[0]} if (o.get("mode") or "linear") == "polar" else {})}
    if kind == "pattern" and picks:                    # the direction (and a polar axis) from a picked edge
        at = picks[0].get("at") if isinstance(picks[0], dict) else picks[0]
        d = st._k("model_pick", key=st.geometry_key(p, c["rid"], vals), recipe_id=c["rid"], values=vals,
                  kind="direction", picks=[{"at": [float(x) for x in at]}], opts={}, p=p)
        o = {**o, "axis": d["axis"], **({"origin": d["origin"]} if d.get("origin") else {})}
        o.setdefault("mode", "polar" if d.get("edge") == "circle" else "linear")
        picked = d
    if kind != "pattern":
        clean = []
        for i, pk in enumerate(picks or [], 1):
            at = pk.get("at") if isinstance(pk, dict) else pk
            try:
                at = [float(x) for x in at]
                assert len(at) == 3
            except (TypeError, ValueError, AssertionError):
                raise _err(f"Pick {i} is not a point.", "Each pick is {\"at\": [x, y, z]} in design millimetres.")
            clean.append({"at": at})
        opts = {k: o[k] for k in ("standard", "size", "fit", "nominal", "d", "style", "head_d", "head_depth",
                                  "head_clearance") if o.get(k) is not None}
        picked = st._k("model_pick", key=st.geometry_key(p, c["rid"], vals), recipe_id=c["rid"], values=vals,
                       kind=kind, picks=clean, opts=opts, p=p)
    label_n = f"{kind.capitalize()} {n}"
    params, body, summary = [], "", ""
    if kind in ("fillet", "chamfer"):
        size = _num(o, "radius" if kind == "fillet" else "length", 0.05, 200,
                    "The fillet radius" if kind == "fillet" else "The chamfer length",
                    o.get("size_mm"))
        e = picked["edges"]
        key = f"{fid}_{'r' if kind == 'fillet' else 'd'}"
        hi = max(size * 4, min(size * 10, picked["shortest_mm"]))
        params.append(_param(key, f"{label_n} {'radius' if kind == 'fillet' else 'length'}", size, min(0.1, size), hi, fid,
                             f"{len(e)} picked edge(s); made at this size or left out, never smaller in silence"))
        q = ",\n            ".join(_lit(x["query"]) for x in e)
        body = (f"return handfeat.{kind}(body, self._form_trail, v[{_q(key)}], [\n            {q}], {_q(fid)})")
        summary = f"{label_n}: {len(e)} edge{'s' if len(e) != 1 else ''}, {'r' if kind == 'fillet' else ''}{size:g} mm"
    elif kind == "hole":
        f = picked["face"]
        sz = picked["size"]
        style = o.get("style") or "plain"
        if style not in ("plain", "counterbore", "countersink"):
            raise _err(f"Unknown hole style “{style}”.", "plain, counterbore or countersink.")
        depth = _num(o, "depth", 0, 1000, "The hole depth", 0.0)
        thru = picked.get("through_mm")
        prov = "specified" if sz["standard"] != "plain" else "assumed"
        params.append(_param(f"{fid}_d", f"{label_n} Ø", sz["d"], max(0.3, sz["d"] * 0.5), sz["d"] * 2, fid, sz["source"],
                             step=0.01, prov=prov))
        params.append(_param(f"{fid}_depth", f"{label_n} depth (0 = through)", depth, 0, max(depth, (thru or 50) * 2),
                             fid, "0 cuts through the whole part", step=0.1))
        extra = ""
        if style != "plain":
            params.append(_param(f"{fid}_head_d", f"{label_n} {style} Ø", sz["head_d"], sz["d"], sz["head_d"] * 2, fid,
                                 sz.get("head_source", ""), step=0.01, prov=prov))
            if style == "counterbore":
                params.append(_param(f"{fid}_head_depth", f"{label_n} counterbore depth", sz["head_depth"], 0.1,
                                     max(1.0, sz["head_depth"] * 3), fid, sz.get("head_source", ""), prov=prov))
                extra = f", style=\"counterbore\", head_d=v[{_q(fid + '_head_d')}], head_depth=v[{_q(fid + '_head_depth')}]"
            else:
                extra = f", style=\"countersink\", head_d=v[{_q(fid + '_head_d')}]"
        name = {"clearance": f"{sz.get('size', '')} clearance hole", "tapped": f"{sz.get('size', '')} tap-drill hole",
                "iso286": f"Ø{sz.get('nominal', 0):g} {sz.get('fit', '')} hole", "plain": f"Ø{sz['d']:g} hole"}[sz["standard"]]
        label_n = name[0].upper() + name[1:] + ("" if style == "plain" else f", {style}")
        at = [_r(x, 4) for x in f["at"]]
        body = (f"return handfeat.hole(body, self._form_trail, {_lit(f['query'])},\n            {_lit(at)}, "
                f"v[{_q(fid + '_d')}], v[{_q(fid + '_depth')}]{extra}, what={_q(fid)})")
        summary = f"{label_n}: Ø{sz['d']:g} mm" + (" through" if not depth else f", {depth:g} mm deep")
        if sz["standard"] == "tapped":
            summary += " (the thread is not modelled: tap it, or use a heat-set insert in a printed part)"
    elif kind == "pattern":
        of = o.get("of") or ""
        if of not in ids:
            raise _err(f"No feature “{of}” to repeat.", "of= names a feature: " + ", ".join(ids[1:]) + ".")
        if of == ids[0]:
            raise _err("The first feature is the whole body; a pattern repeats a feature that adds or cuts something.")
        mode = o.get("mode") or "linear"
        if mode not in ("linear", "polar"):
            raise _err(f"Unknown pattern “{mode}”.", "linear or polar.")
        count = int(_num(o, "count", 2, 200, "The count", 3))
        ax = _axis(o.get("axis") or ("x" if mode == "linear" else "z"))
        if mode == "linear":
            step = _num(o, "pitch", 0.01, 5000, "The pitch", None)
            params.append(_param(f"{fid}_n", f"{label_n} count", count, 2, max(count * 3, 10), fid, "copies, the original included", step=1, unit=""))
            params.append(_param(f"{fid}_pitch", f"{label_n} pitch", step, step * 0.1, step * 5, fid, "between copies"))
            body = (f"return handfeat.pattern(body, self._form_trail, {_q(of)}, \"linear\", v[{_q(fid + '_n')}], "
                    f"v[{_q(fid + '_pitch')}], {_lit([_r(x, 6) for x in ax])}, what={_q(fid)})")
            summary = f"{label_n}: {count} × {of}, {step:g} mm apart"
        else:
            step = _num(o, "angle", 0.1, 360, "The angle step", 360.0 / count)
            origin = [float(x) for x in (o.get("origin") or [0, 0, 0])]
            params.append(_param(f"{fid}_n", f"{label_n} count", count, 2, max(count * 3, 12), fid, "copies, the original included", step=1, unit=""))
            params.append(_param(f"{fid}_angle", f"{label_n} angle step", step, 0.1, 360, fid, "degrees between copies", unit="°"))
            body = (f"return handfeat.pattern(body, self._form_trail, {_q(of)}, \"polar\", v[{_q(fid + '_n')}], "
                    f"v[{_q(fid + '_angle')}], {_lit([_r(x, 6) for x in ax])}, {_lit([_r(x, 4) for x in origin])}, what={_q(fid)})")
            summary = f"{label_n}: {count} × {of}, every {step:g}°"
    else:  # shell
        t = _num(o, "thickness", 0.1, 100, "The wall thickness", None)
        f = picked.get("face")
        params.append(_param(f"{fid}_t", f"{label_n} wall", t, max(0.1, t * 0.25), t * 4, fid, "wall thickness, inward"))
        body = (f"return handfeat.shell(body, self._form_trail, v[{_q(fid + '_t')}], "
                f"{_lit(f['query']) if f else 'None'}, {_q(fid)})")
        summary = f"{label_n}: {t:g} mm walls" + (", one face open" if f else ", closed")
    code = (f"@feature({_q(label_n)}, role={_q(ROLES[kind])})\ndef {fid}(self, v, body):\n"
            f"    from form import handfeat\n    {body}\n")
    ops = [{"op": "insert", "param": prm} for prm in params]
    ops.append({"op": "insert", "feature": fid, "code": code, "label": label_n, "role": ROLES[kind],
                **({"after": o["after"]} if o.get("after") else {})})
    return {"feature": fid, "label": label_n, "kind": kind, "summary": summary, "ops": ops, "picked": picked,
            "params": params, "evidence": EVIDENCE}


# ---- sketches (B3): a sketch on a datum or a picked face, extruded, cut or revolved ---------------------------------

def _sketch_code(kind: str, fid: str, label: str, data: dict, axis: int | None = None, extra: str = "",
                 new: bool = False) -> str:
    from . import handsketch
    lit = handsketch.literal(data, "        ")
    mode = "new" if new else "add" if kind in ("extrude", "revolve") else "cut"
    if kind == "revolve":
        call = (f"handsketch.revolve(body, self._form_trail, sketch, v, {_q(fid)}, {int(axis)}, "
                f"v[{_q(fid + '_angle')}], {_q(mode)}{extra})")
    else:
        call = (f"handsketch.extrude(body, self._form_trail, sketch, v, {_q(fid)}, v[{_q(fid + '_depth')}], "
                f"{_q(mode)}{extra})")
    return (f"@feature({_q(label)}, role=\"structure\")\ndef {fid}(self, v, body):\n"
            f"    from form import handsketch\n    sketch = {lit}\n    return {call}\n")


def _sketch_parts(kind, fid, n, data, o, ends=None):
    """(params, code, summary, label) of one sketch feature. ends: (keyword arguments, their parameters, a summary
    suffix) of its end conditions (form/modelling_more.end_args)."""
    from . import handsketch
    sol = handsketch.solve(data)
    if not sol["ok"]:
        raise _err(f"The sketch does not solve: {sol['error']}", sol.get("hint") or "")
    if not sol["closed"]:
        raise _err("The sketch has no closed profile.", "Join the lines end to end into a closed loop (or draw a circle).")
    label = o.get("label") or f"{kind.capitalize()} {n}"
    params = handsketch.params(data, fid)
    axis = None
    if kind == "revolve":
        axis = int(o.get("axis_entity", -1))
        ang = _num(o, "angle", 0.1, 360, "The revolve angle", 360.0)
        params.append(_param(f"{fid}_angle", f"{label} angle", ang, 1, 360, fid, "degrees turned", step=1, unit="°"))
        summary = f"{label}: the sketch turned {ang:g}° about line {axis}"
    else:
        dflt = 10.0 if kind == "extrude" else 0.0
        depth = _num(o, "depth", 0, 5000, "The depth", dflt)
        if kind == "extrude" and depth <= 0 and (o.get("end") or "blind") in ("blind", "mid"):
            raise _err("An extrusion needs a depth above 0.")
        params.append(_param(f"{fid}_depth", f"{label} depth" + (" (0 = through)" if kind == "cut" else ""), depth, 0 if kind == "cut" else 0.1,
                             max(depth * 5, 50), fid, "along the sketch plane's normal" + (", into the part" if kind == "cut" else "")))
        summary = f"{label}: the sketch {'extruded' if kind == 'extrude' else 'cut'} " + \
            (f"{depth:g} mm" if depth else "through everything")
    extra, eparams, said = ends or ("", [], "")
    params += eparams
    if said:
        summary += f", {said}"
    if o.get("new_body"):
        summary += ", as a new body"
    nd = len([x for x in sol["dims"] if x["name"]])
    summary += f" ({nd} dimension{'s' if nd != 1 else ''} as parameters, {'fully constrained' if sol['fully_constrained'] else str(sol['dof']) + ' degrees of freedom left'})"
    return params, _sketch_code(kind, fid, label, data, axis, extra, bool(o.get("new_body"))), summary, label


def sketch_plane(st, p: dict, at) -> dict:
    """The plane and outline of a sketch on the flat face at a picked point (computed in the kernel)."""
    c = _canonical(st, p)
    vals = st.rev(p)["values"]
    return st._k("model_pick", key=st.geometry_key(p, c["rid"], vals), recipe_id=c["rid"], values=vals,
                 kind="sketch", picks=[{"at": [float(x) for x in at]}], opts={}, p=p)


def _plan_sketch(st, p, c, kind, fid, n, picks, o):
    from . import handsketch
    data = o.get("sketch")
    if not isinstance(data, dict):
        raise _err(f"A {kind} needs its sketch.", "Give sketch: {plane, points, entities, constraints} "
                   "(get_sketch shows the form), or draw it in the sketch editor.")
    from . import modelling_more
    data = handsketch.check(modelling_more.expand_sketch_plane(c, data))
    picked = None
    if picks and not o.get("keep_plane"):
        picked = sketch_plane(st, p, (picks[0].get("at") if isinstance(picks[0], dict) else picks[0]))
        data = {**data, "plane": picked["plane"]}
    label = o.get("label") or f"{kind.capitalize()} {n}"
    ends = modelling_more.end_args(st, p, c, kind, fid, label, o)
    params, code, summary, label = _sketch_parts(kind, fid, n, data, o, ends)
    ops = modelling_more._solids_ops(st, p, c, 1) if o.get("new_body") else []
    ops += [{"op": "insert", "param": prm} for prm in params]
    ops.append({"op": "insert", "feature": fid, "code": code, "label": label, "role": "structure",
                **({"after": o["after"]} if o.get("after") else {})})
    return {"feature": fid, "label": label, "kind": kind, "summary": summary, "ops": ops, "picked": picked,
            "params": params, "evidence": EVIDENCE, "sketch": data}


SKETCH_DESIGN = '''"""{title}: modelled by hand in Form Studio, starting from a sketch."""
from form.featureprog import FeatureDesign, feature
from form.recipes.base import Param


class Design(FeatureDesign):
    title = {title_lit}
    params = [{params}]

{feature}'''


def sketch_design_source(name: str, data: dict, kind: str = "extrude", **o) -> tuple[str, str]:
    """(the source of a new design whose first feature is this sketch extruded or revolved, its summary)."""
    if kind not in ("extrude", "revolve"):
        raise _err("A design starts from an extrusion or a revolve of its sketch.")
    if "face" in (data.get("plane") or {}):
        raise _err("The first sketch goes on a datum plane (XY, XZ or YZ): there is no face yet.")
    fid = f"{kind}_1"
    params, code, summary, _label = _sketch_parts(kind, fid, 1, data, o)
    import textwrap
    ptext = (",\n              ").join(edits._param_text(prm) for prm in params)
    src = SKETCH_DESIGN.format(title=name, title_lit=_q(name), params=ptext, feature=textwrap.indent(code, "    "))
    return src, summary


def start_from_sketch(st, name: str, data: dict, kind: str = "extrude", purpose: str = "model", **o) -> dict:
    """A new design from a sketch drawn on a datum plane (Start blank, by hand). Returns the project."""
    from . import handsketch
    name = " ".join(str(name or "").split())[:80] or "Untitled design"
    src, summary = sketch_design_source(name, handsketch.check(data), kind, **o)
    p = st.create_design(name, src, "", purpose=purpose)
    st.activity(p["id"], "commit", f"r01: Created {name} by hand: {summary}", by="you")
    return st.load(p["id"])


def _sketch_node(source: str, fid: str):
    tree = ast.parse(featureprog.strip_partial(source))
    c = featureprog._feature_class(tree)
    fn = next((n for n in (c.body if c else []) if isinstance(n, ast.FunctionDef) and n.name == fid), None)
    if fn is None:
        raise _err(f"No feature “{fid}” in this design.", "Features: " + ", ".join(featureprog.feature_ids(source)) + ".")
    for x in ast.walk(fn):
        if isinstance(x, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "sketch" for t in x.targets) \
                and isinstance(x.value, ast.Dict):
            return fn, x
    raise _err(f"{fid} has no sketch.", "Features made from a sketch (extrude, cut, revolve) hold one: "
               "`sketch = {...}` in their method.")


def get_sketch(st, p: dict, fid: str) -> dict:
    from . import handsketch
    c = _canonical(st, p)
    fn, node = _sketch_node(c["source"], fid)
    data = ast.literal_eval(node.value)
    vals = st.rev(p)["values"]
    solved = handsketch.solve(data, vals, fid + "_")
    kind = "revolve" if "handsketch.revolve" in ast.unparse(fn) else "cut" if "\"cut\"" in ast.unparse(fn) or "'cut'" in ast.unparse(fn) else "extrude"
    return {"project": p["id"], "head": p["head"], "feature": fid, "kind": kind, "sketch": data, "solved": solved,
            "values": {k: vals[k] for k in vals if k.startswith(fid + "_")}, "evidence": "solved by form.sketch2d"}


def sketch_edit_ops(st, p: dict, fid: str, ops: list | None = None, sketch: dict | None = None) -> tuple[list, dict]:
    """(edit ops for the design, the new sketch): sketch ops applied (or a whole new sketch), solved, then written
    back into the feature's method; named dimensions added or removed become parameters, a set dimension a value."""
    from . import handsketch
    c = _canonical(st, p)
    fn, node = _sketch_node(c["source"], fid)
    old = ast.literal_eval(node.value)
    new = handsketch.check(sketch) if sketch is not None else handsketch.apply_ops(old, ops or [])[0]
    vals = st.rev(p)["values"]
    sets = {o["name"]: float(o["value"]) for o in ops or [] if isinstance(o, dict) and o.get("op") == "set"}
    trial = {**vals, **{fid + "_" + k: v for k, v in sets.items()}}
    sol = handsketch.solve(new, trial, fid + "_")
    if not sol["ok"]:
        raise _err(f"Refused: the sketch would not solve: {sol['error']}", sol.get("hint") or "Nothing was changed.",
                   status=422)
    if not sol["closed"]:
        raise _err("Refused: the sketch would have no closed profile.", "Join its lines end to end.", status=422)
    ind = " " * (node.col_offset + 4)
    new_src = edits._cut(c["source"], node.value, handsketch.literal(new, ind))
    spans = featureprog.method_spans(new_src)
    x, y = spans[fid]
    import textwrap
    code = textwrap.dedent("\n".join(new_src.splitlines()[x - 1:y]))
    out = [{"op": "replace", "feature": fid, "code": code}]
    before = {q["key"] for q in handsketch.params(old, fid)}
    after = {q["key"]: q for q in handsketch.params(new, fid)}
    out += [{"op": "insert", "param": q} for k, q in after.items() if k not in before]
    out += [{"op": "delete", "param": k} for k in sorted(before - set(after))]
    out += [{"op": "set_param", "param": fid + "_" + k, "value": v} for k, v in sets.items() if fid + "_" + k in after]
    return out, new


# ---- preview and commit ---------------------------------------------------------------------------------------------

def _is_tree_only(ops) -> bool:
    return all(isinstance(o, dict) and o.get("op") in TREE_OPS for o in ops or [])


def preview(st, p: dict, ops: list, view: bool = False) -> dict:
    """Build the edited design without saving it: the draft, its computed impact and whether it must be refused."""
    from .studio import BUILD_TIMEOUT, SOLID_TOL, StudioError
    p = st.load(p["id"])
    c = edits.canonical(st, p)
    new, info = edits.apply(c["source"], ops)
    head = st.rev(p)
    if new == c["source"] and not info["values"]:
        raise _err("The ops change nothing.", "Check the op list.")
    from . import preflight as pf
    vals0 = head["values"]
    found = pf.check(new, values={**vals0, **info["values"]}, project=p, strict_values=False)["findings"]
    was = pf.check(st.source_text(p) or "", values=vals0, project=p, strict_values=False)["findings"]
    errs = [f for f in pf.new_findings(found, was) if f["severity"] == "error"]
    if errs:
        return {"ok": False, "refused": "preflight: " + pf.message(errs), "findings": errs,
                "next": "Nothing was built. Fix the source the op writes, or tell your agent what you wanted."}
    rid = st._load_design(new, "python")
    rec = st.recipes[rid]
    keep = {k: v for k, v in vals0.items() if k in {q.key for q in rec.params}}
    vals = st._validate(rid, {**rec.defaults(), **keep, **info["values"]})
    try:
        s = st._k("summary", key=st.geometry_key(p, rid, vals), recipe_id=rid, values=vals, tol=SOLID_TOL, p=p,
                  timeout=BUILD_TIMEOUT)
    except StudioError as e:
        return {"ok": False, "refused": str(e), "hint": e.hint, "feature": e.extra.get("feature"),
                "next": "Nothing changed. Fix with your agent, or undo the change."}
    base = st.head_summary(p)
    old_log = {e["feature"]: e for e in head.get("build_log") or base.get("build_log") or []}
    log = s.get("build_log") or []
    prev_skipped = {x["feature"] for x in (head.get("partial") or {}).get("skipped", [])}
    skipped = [x for x in s.get("skipped") or [] if x["feature"] not in prev_skipped]
    refused = ""
    if skipped:
        x = skipped[0]
        refused = f"{x['feature']} would be left out: {x['message']}"
    moved = any(isinstance(o, dict) and o.get("op") == "move" for o in ops)
    # a feature that changed the solid before and changes nothing now (built or from its checkpoint)
    lost = [e["feature"] for e in log if e.get("status") in ("built", "checkpoint") and abs(e.get("dvol") or 0) <= 1e-6
            and e["feature"] in old_log and abs(old_log[e["feature"]].get("dvol") or 0) > 1e-3
            and e["feature"] != (log[0]["feature"] if log else "")]
    if moved and lost and not refused:
        refused = (f"{lost[0]} would do nothing in the new order (it changed the solid by "
                   f"{old_log[lost[0]]['dvol']:g} mm³ before): it loses what it reads")
    dv = s["volume_mm3"] - base["volume_mm3"]
    out = {"ok": not refused, "refused": refused or None,
           "volume_mm3": {"before": _r(base["volume_mm3"]), "after": _r(s["volume_mm3"]), "change": _r(dv)},
           "bbox_mm": {"before": base["bbox"], "after": s["bbox"]},
           "faces": {"before": base.get("faces"), "after": s.get("faces")},
           "build_log": log, "craft_notes": s.get("craft_notes") or [], "edit": {k: info[k] for k in ("features", "values")},
           "evidence": EVIDENCE, "rid": rid}
    if (s.get("timing") or {}).get("brep") in ("disk", "memory"):
        out["reused_solid"] = "the same solid as an earlier build: loaded whole, nothing was rebuilt"
    if lost and not moved:
        out["warnings"] = [f"{f} no longer changes the solid" for f in lost]
    if refused:
        out["next"] = "Nothing is saved. Change the op, or ask your agent: it reads the same source."
    if view and not refused:
        out["view"] = st._k("view", key=st.geometry_key(p, rid, vals), recipe_id=rid, values=vals, tol=SOLID_TOL, p=p)
    return out


def describe(ops: list, planned: dict | None = None) -> str:
    """One sentence for the revision and the conversation: "You added Fillet 2: 4 edges, r 2 mm"."""
    if planned:
        return "Added " + planned["summary"]
    bits = []
    for o in ops:
        k = o.get("op")
        if k == "suppress":
            bits.append(f"suppressed {o['feature']}")
        elif k == "restore":
            bits.append(f"restored {o['feature']}")
        elif k == "move":
            bits.append(f"moved {o['feature']} {'before ' + o['before'] if o.get('before') else 'after ' + str(o.get('after'))}")
        elif k == "rename":
            bits.append(f"renamed {o['feature']}" + (f" to “{o['label']}”" if o.get("label") else "")
                        + (f" (id {o['id']})" if o.get("id") else ""))
        else:
            bits.append(k or "edit")
    s = "; ".join(bits)
    return s[:1].upper() + s[1:] if s else "Edited"


def commit(st, p: dict, ops: list, expect_head: int | None = None, origin: str = "you", note: str = "",
           planned: dict | None = None) -> dict:
    """Preview (refuse with the reason), then one revision through the edit protocol."""
    pv = preview(st, p, ops)
    if not pv["ok"]:
        raise _err(f"Refused: {pv['refused']}", pv.get("next") or "", status=422, kind="refused",
                   preview={k: pv.get(k) for k in ("build_log", "findings", "feature") if pv.get(k)})
    r = edits.edit(st, st.load(p["id"]), ops, expect_head, note or describe(ops, planned), origin, False, None, "warn")
    r["preview"] = {k: pv[k] for k in ("volume_mm3", "bbox_mm", "faces", "craft_notes", "evidence") if k in pv}
    r["said"] = note or describe(ops, planned)
    return r


# ---- the Bench (form/studies.py PROVIDERS) -------------------------------------------------------------------------

def _head_log(ctx) -> list:
    return list(ctx.rev.get("build_log") or [])


def _features_live(ctx) -> dict:
    """The head's features from its own build log: built, suppressed by hand, and left out (a picked edge or face a
    rebuild could not find, or a feature that failed), each named. Read, never computed: nothing is built here."""
    log = _head_log(ctx)
    by = {k: [e["feature"] for e in log if e.get("status") == k] for k in ("suppressed", "skipped")}
    built = [e["feature"] for e in log if e.get("status") not in ("suppressed", "skipped")]
    bits = [f"{len(built)} built"] + ([f"{len(by['suppressed'])} suppressed"] if by["suppressed"] else []) \
        + ([f"{len(by['skipped'])} left out"] if by["skipped"] else [])
    why = {x.get("feature"): x for x in (ctx.rev.get("partial") or {}).get("skipped") or [] if isinstance(x, dict)}
    detail = " ".join(f"{f}: {(why.get(f) or {}).get('message') or 'left out of the build'}." for f in by["skipped"])
    if by["suppressed"]:
        detail = (detail + " " if detail else "") + "Suppressed by hand: " + ", ".join(by["suppressed"]) + "."
    return {"headline": " · ".join(bits), "evidence": "computed", "detail": detail,
            "data": {"built": built, **by}}


def register_studies(register) -> None:
    """Wave B's entry on the Bench: the feature tree's state, so a hand edit that leaves a feature out shows there."""
    from . import studies
    studies.APPLIES.setdefault("features", (lambda c: bool(_head_log(c)),
                                            "Only for a design written as features (a FeatureDesign)."))
    register(studies.Study("features", "study", "Features", "Every feature of the head as its build log records it: "
                           "built, suppressed by hand, or left out with the reason.", "computed",
                           run=_features_live, live=True, needs=("features",), inputs=("design code", "values"),
                           app="tree", tool="get_design_source", order=5))
