"""The edit protocol: change a design by naming what changes, not by sending the file again.

    edits.apply(source, ops)                    -> (new source, what changed)       plain text and syntax trees
    edits.canonical(st, p)                      -> the head's source in canonical form (form/canon.py), kernel-checked
    edits.edit(st, p, ops, expect_head=...)     -> one build, one revision

An op is a dict with "op" and one target:

    {"op": "replace", "feature": "holes", "code": "def holes(self, v, body): ..."}     one feature method
    {"op": "replace", "def": "poly", "code": "def poly(pts, L): ..."}                  a helper or another method
    {"op": "replace", "find": "amount=L", "with": "amount=-L"}                        exact text, found once
    {"op": "insert",  "feature": "ribs", "code": "...", "after": "body", "label": "Ribs", "role": "structure"}
    {"op": "insert",  "def": "ring", "code": "def ring(r): ..."}                       a new helper (or method: self)
    {"op": "insert",  "param": {"key": "rib_t", "label": "Rib", "default": 2, "min": 1, "max": 4}}
    {"op": "delete",  "feature": "ribs"} | {"op": "delete", "def": "ring"} | {"op": "delete", "param": "rib_t"}
    {"op": "set_param", "param": "wall", "value": 2.4}                                 this revision's value
    {"op": "set_param", "param": "wall", "default": 2.4, "min": 1.2}                   the declaration (and the value)

Every op is checked before any is applied, and every problem is reported at once. Ops apply in order to the same
text, so a later op sees what an earlier one did.

A plain Recipe is edited in its canonical form: canonical() lifts it, builds the lifted source once and accepts it
only when volume, face count and bounding box equal the head's (computed, 1e-6 relative volume, 1e-4 mm box). That
build leaves a checkpoint per feature, so the edit that follows builds only what it changed. A lift that does not
hold falls back to the skeleton form, then to the source as it is (text, def and param ops still work).
"""
from __future__ import annotations

import ast
import json
import re
import textwrap

from . import canon, featureprog

OPS = ("replace", "insert", "delete", "set_param")
PARAM_FIELDS = ("key", "label", "default", "min", "max", "step", "unit", "group", "feature", "doc", "provenance")
VERIFY_VERSION = 1


def _err(msg: str, hint: str = "", **extra):
    from .studio import StudioError
    return StudioError(msg, hint, **extra)


class _Bad(Exception):
    def __init__(self, msg: str, hint: str = ""):
        super().__init__(msg)
        self.hint = hint


# ---- functions by name ---------------------------------------------------------------------------------------------

def _class(tree):
    c = featureprog._feature_class(tree)
    if c is not None:
        return c
    found = [n for n in tree.body if isinstance(n, ast.ClassDef)]
    recipe = [n for n in found if any(featureprog._base_name(b) in ("Recipe", "FeatureDesign") for b in n.bases)]
    return (recipe or found or [None])[-1]


def _find_def(tree, name: str):
    """(node, in class?) of a function by name: `poly`, `Design.derived` or a bare method name."""
    cls = _class(tree)
    if "." in name:
        cname, name = name.split(".", 1)
        cls = next((n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cname), None)
        if cls is None:
            return None, False
        hit = [n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]
        return (hit[-1], True) if hit else (None, True)
    hit = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]
    if hit:
        return hit[-1], False
    if cls is not None:
        hit = [n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]
        if hit:
            return hit[-1], True
    return None, False


def _span(n) -> tuple[int, int]:
    return min([d.lineno for d in getattr(n, "decorator_list", [])] + [n.lineno]), n.end_lineno


def _indent_of(line: str) -> str:
    return line[:len(line) - len(line.lstrip())]


def _one_def(code: str, name: str):
    code = textwrap.dedent(code or "").strip("\n")
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise _Bad(f"the code for {name} does not parse: {e.msg} (line {e.lineno})")
    if len(tree.body) != 1 or not isinstance(tree.body[0], (ast.FunctionDef, ast.AsyncFunctionDef)):
        raise _Bad(f"the code for {name} must be exactly one function definition")
    fn = tree.body[0]
    if fn.name != name.split(".")[-1]:
        raise _Bad(f"the function is called {fn.name}, but the op names {name}")
    return code, fn


def _replace_def(source: str, name: str, code: str) -> str:
    tree = ast.parse(source)
    node, _in = _find_def(tree, name)
    if node is None:
        raise _Bad(f"no function “{name}” in this design", "Functions: " + ", ".join(_def_names(tree)) + ".")
    code, _fn = _one_def(code, name)
    lines = source.splitlines()
    a, b = _span(node)
    new = textwrap.indent(code, _indent_of(lines[node.lineno - 1])).splitlines()
    return "\n".join(lines[:a - 1] + new + lines[b:]) + "\n"


def _def_names(tree) -> list:
    out = [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    c = _class(tree)
    if c is not None:
        out += [n.name for n in c.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    return out


def _insert_def(source: str, name: str, code: str, after: str = "") -> str:
    tree = ast.parse(source)
    if _find_def(tree, name)[0] is not None:
        raise _Bad(f"the design already has a function “{name}”", "Use replace, or pick another name.")
    code, fn = _one_def(code, name)
    lines = source.splitlines()
    cls = _class(tree)
    method = bool(fn.args.args) and fn.args.args[0].arg == "self"
    if after:
        node, in_cls = _find_def(tree, after)
        if node is None:
            raise _Bad(f"no function “{after}” to put {name} after")
        end = _span(node)[1]
        new = [""] + textwrap.indent(code, _indent_of(lines[node.lineno - 1])).splitlines()
        return "\n".join(lines[:end] + new + lines[end:]) + "\n"
    if method:
        if cls is None:
            raise _Bad(f"{name} takes self, but the design has no class to put it in")
        ind = featureprog._class_indent(lines, cls)
        feats = featureprog.method_spans(source)
        first = min((a for a, _b in feats.values()), default=None)
        if first:                                         # before the first feature: helpers stay out of the build order
            new = textwrap.indent(code, ind).splitlines() + [""]
            return "\n".join(lines[:first - 1] + new + lines[first - 1:]) + "\n"
        new = [""] + textwrap.indent(code, ind).splitlines()
        return "\n".join(lines[:cls.end_lineno] + new + lines[cls.end_lineno:]) + "\n"
    at = (_span(cls)[0] - 1) if cls is not None else len(lines)
    while at > 0 and not lines[at - 1].strip():
        at -= 1
    new = ["", ""] + code.splitlines() + ["", ""]
    rest = lines[at:]
    while rest and not rest[0].strip():
        rest = rest[1:]
    return "\n".join(lines[:at] + new + rest) + "\n"


def _delete_def(source: str, name: str) -> str:
    tree = ast.parse(source)
    node, _in = _find_def(tree, name)
    if node is None:
        raise _Bad(f"no function “{name}” in this design")
    lines = source.splitlines()
    a, b = _span(node)
    while a > 1 and not lines[a - 2].strip():
        a -= 1
    return "\n".join(lines[:a - 1] + lines[b:]) + "\n"


# ---- parameters ----------------------------------------------------------------------------------------------------

def _param_calls(tree) -> tuple[object, dict]:
    """(the `params = [...]` list node, {key: its Param(...) call}) of the design class."""
    cls = _class(tree)
    if cls is None:
        return None, {}
    for n in cls.body:
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "params" for t in n.targets) \
                and isinstance(n.value, (ast.List, ast.Tuple)):
            calls = {}
            for e in n.value.elts:
                if isinstance(e, ast.Call) and featureprog._base_name(e.func) == "Param":
                    k = e.args[0] if e.args else next((x.value for x in e.keywords if x.arg == "key"), None)
                    if isinstance(k, ast.Constant) and isinstance(k.value, str):
                        calls[k.value] = e
            return n.value, calls
    return None, {}


def _offsets(source: str) -> list:
    out, at = [], 0
    for ln in source.splitlines(keepends=True):
        out.append(at)
        at += len(ln.encode("utf-8"))
    return out


def _cut(source: str, node, new: str) -> str:
    """source with the text of one syntax node replaced."""
    raw = source.encode("utf-8")
    off = _offsets(source)
    a = off[node.lineno - 1] + node.col_offset
    b = off[node.end_lineno - 1] + node.end_col_offset
    return (raw[:a] + new.encode("utf-8") + raw[b:]).decode("utf-8")


def _param_fields(call) -> dict:
    out = {}
    for i, a in enumerate(call.args):
        if i < len(PARAM_FIELDS):
            out[PARAM_FIELDS[i]] = a
    for k in call.keywords:
        if k.arg:
            out[k.arg] = k.value
    return out


def _param_text(fields: dict) -> str:
    """Param(...) from {field: value or syntax node}: positional up to the last field given, as designs write it."""
    def lit(v):
        return ast.unparse(v) if isinstance(v, ast.AST) else repr(v)
    defaults = {"step": 0.1, "unit": "mm", "group": "form", "feature": "", "doc": "", "provenance": "assumed"}
    last = max(i for i, f in enumerate(PARAM_FIELDS) if f in fields)
    args = []
    for f in PARAM_FIELDS[:last + 1]:
        if f in fields:
            args.append(lit(fields[f]))
        elif f in defaults:
            args.append(repr(defaults[f]))
        else:
            raise _Bad(f"a parameter needs {f}")
    return "Param(" + ", ".join(args) + ")"


def _num(x, what: str) -> float:
    if isinstance(x, bool) or not isinstance(x, (int, float)) or x != x or x in (float("inf"), float("-inf")):
        raise _Bad(f"{what} must be a finite number")
    return float(x)


def _g(x: float):
    return int(x) if float(x).is_integer() and abs(x) < 1e15 else x


def _set_param(source: str, op: dict, values: dict) -> str:
    key = op.get("param")
    if not isinstance(key, str) or not key:
        raise _Bad("set_param needs param: the parameter's key")
    tree = ast.parse(source)
    _lst, calls = _param_calls(tree)
    decl = {f: op[f] for f in PARAM_FIELDS[1:] if f in op}
    if "value" not in op and not decl:
        raise _Bad(f"set_param {key} changes nothing", "Give value (this revision's value) or default, min, max, "
                   "step, label, unit, group, feature, doc (the declaration).")
    if "value" in op:
        values[key] = _num(op["value"], f"{key}: value")
    elif "default" in decl:
        values[key] = _num(decl["default"], f"{key}: default")
    for f in ("default", "min", "max", "step"):
        if f in decl:
            decl[f] = _g(_num(decl[f], f"{key}: {f}"))
    if not decl:
        if calls and key not in calls:
            raise _Bad(f"no parameter “{key}”", "Parameters: " + ", ".join(calls) + ".")
        return source
    if key not in calls:
        raise _Bad(f"no parameter “{key}” declared as Param(\"{key}\", ...) in params",
                   "Parameters: " + ", ".join(calls) + ". insert adds one.")
    fields = {**_param_fields(calls[key]), **decl}
    lo = fields.get("min"), fields.get("max")
    try:
        lo = [float(ast.literal_eval(x)) if isinstance(x, ast.AST) else float(x) for x in lo]
        if lo[0] > lo[1]:
            raise _Bad(f"{key}: min {lo[0]:g} is above max {lo[1]:g}")
        v = values.get(key)
        if v is not None and not (lo[0] - 1e-9 <= v <= lo[1] + 1e-9):
            raise _Bad(f"{key} = {v:g} is outside {lo[0]:g} to {lo[1]:g}", "Widen min or max in the same op.")
    except (ValueError, TypeError, SyntaxError):
        pass                                             # a limit written as an expression: the build validates it
    return _cut(source, calls[key], _param_text(fields))


def _insert_param(source: str, spec) -> str:
    if not isinstance(spec, dict) or not isinstance(spec.get("key"), str):
        raise _Bad("insert param needs {key, label, default, min, max} (and step, unit, group, feature, doc)")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,47}", spec["key"]):
        raise _Bad(f"“{spec['key']}” cannot be a parameter key")
    unknown = [k for k in spec if k not in PARAM_FIELDS]
    if unknown:
        raise _Bad("unknown parameter field(s): " + ", ".join(unknown), "Fields: " + ", ".join(PARAM_FIELDS) + ".")
    f = dict(spec)
    f.setdefault("label", spec["key"].replace("_", " ").capitalize())
    for k in ("default", "min", "max"):
        if k not in f:
            raise _Bad(f"parameter {spec['key']} needs {k}")
        f[k] = _g(_num(f[k], f"{spec['key']}: {k}"))
    if "step" in f:
        f["step"] = _g(_num(f["step"], f"{spec['key']}: step"))
    if not f["min"] <= f["default"] <= f["max"]:
        raise _Bad(f"{spec['key']}: default {f['default']:g} is outside {f['min']:g} to {f['max']:g}")
    tree = ast.parse(source)
    lst, calls = _param_calls(tree)
    if lst is None:
        raise _Bad("the design has no literal `params = [...]` list to add a parameter to",
                   "Add it with a text replace on the params line.")
    if spec["key"] in calls:
        raise _Bad(f"parameter “{spec['key']}” already exists", "Use set_param to change it.")
    text = _param_text(f)
    if not lst.elts:
        return _cut(source, lst, "[" + text + "]")
    last = lst.elts[-1]
    lines = source.splitlines()
    ind = _indent_of(lines[last.lineno - 1])
    one_line = lst.lineno == lst.end_lineno
    sep = ", " if one_line else ",\n" + ind
    return _cut(source, last, ast.get_source_segment(source, last) + sep + text)


def _delete_param(source: str, key) -> str:
    tree = ast.parse(source)
    lst, calls = _param_calls(tree)
    if not isinstance(key, str) or key not in calls:
        raise _Bad(f"no parameter “{key}”", "Parameters: " + ", ".join(calls) + ".")
    elts = lst.elts
    i = elts.index(calls[key])
    raw = source.encode("utf-8")
    off = _offsets(source)

    def pos(n, end=False):
        return off[(n.end_lineno if end else n.lineno) - 1] + (n.end_col_offset if end else n.col_offset)
    if i + 1 < len(elts):
        a, b = pos(elts[i]), pos(elts[i + 1])
    elif i:
        a, b = pos(elts[i - 1], True), pos(elts[i], True)
    else:
        a, b = pos(elts[i]), pos(elts[i], True)
    return (raw[:a] + raw[b:]).decode("utf-8")


# ---- applying ops --------------------------------------------------------------------------------------------------

def _targets(op: dict) -> list:
    return [k for k in ("feature", "def", "find", "param") if k in op]


def _apply_one(source: str, op: dict, values: dict) -> str:
    if not isinstance(op, dict):
        raise _Bad("an op is an object: {op, target, ...}")
    kind = op.get("op")
    if kind not in OPS:
        raise _Bad(f"unknown op “{kind}”", "Ops: " + ", ".join(OPS) + ".")
    if kind == "set_param":
        return _set_param(source, op, values)
    t = _targets(op)
    if len(t) != 1:
        raise _Bad(f"{kind} needs exactly one target", "feature, def, find (replace only) or param.")
    t = t[0]
    from .studio import StudioError
    try:
        if t == "feature":
            fid = op["feature"]
            if not featureprog.is_feature_design(source):
                raise _Bad(f"this design has no feature methods, so “{fid}” cannot be addressed",
                           "Use a def or find target, or send the design as a FeatureDesign with update_design.")
            if kind == "replace":
                return featureprog.replace_feature(source, fid, op.get("code", ""))
            if kind == "insert":
                return featureprog.insert_feature(source, fid, op.get("code", ""), op.get("label", ""),
                                                  op.get("role", "structure"), op.get("after", ""))
            return featureprog.delete_feature(source, fid)
        if t == "def":
            if kind == "replace":
                return _replace_def(source, op["def"], op.get("code", ""))
            if kind == "insert":
                return _insert_def(source, op["def"], op.get("code", ""), op.get("after", ""))
            return _delete_def(source, op["def"])
        if t == "param":
            if kind == "insert":
                return _insert_param(source, op["param"])
            if kind == "delete":
                return _delete_param(source, op["param"])
            raise _Bad("replace does not take a param", "Use set_param to change a parameter.")
        if kind != "replace":
            raise _Bad(f"{kind} does not take find", "Text is changed with replace: {find, with}.")
        old, new = op.get("find"), op.get("with")
        if not isinstance(old, str) or not old or not isinstance(new, str):
            raise _Bad("replace by text needs find (non-empty) and with")
        n = source.count(old)
        if n != 1 and not (op.get("all") and n > 1):
            raise _Bad(f"the text to find occurs {n} times" + (": " + repr(old[:60]) if n == 0 else ""),
                       "Give more of the surrounding text so it is found once, or pass \"all\": true.")
        return source.replace(old, new)
    except StudioError as e:
        raise _Bad(str(e), e.hint)


def apply(source: str, ops: list) -> tuple[str, dict]:
    """(the source after every op, {"values", "features": {changed, added, removed}, "shared", "source_changed"}).
    Raises one StudioError that lists every op that cannot be applied."""
    if not isinstance(ops, list) or not ops:
        raise _err("ops is a list of at least one op.", "For example [{\"op\": \"set_param\", \"param\": \"wall\", "
                   "\"value\": 2.4}].")
    source = featureprog.strip_partial(source or "")
    values: dict = {}
    cur = source
    problems = []
    for i, op in enumerate(ops, 1):
        try:
            cur = _apply_one(cur, op, values)
        except _Bad as e:
            problems.append({"op": i, "message": str(e), **({"hint": e.hint} if e.hint else {})})
    if cur != source:
        try:
            ast.parse(cur)
        except SyntaxError as e:
            problems.append({"op": 0, "message": f"the edited source does not parse: {e.msg} (line {e.lineno})"})
    if problems:
        raise _err(f"{len(problems)} of {len(ops)} op(s) cannot be applied: "
                   + "; ".join(f"op {x['op']}: {x['message']}" for x in problems),
                   " ".join(x["hint"] for x in problems if x.get("hint"))[:900] or
                   "Nothing was changed. Fix the ops and send them all again.", status=422, problems=problems)
    return cur, {"values": values, **diff(source, cur)}


def diff(a: str, b: str) -> dict:
    """Which features an edit touched, read from the two sources (no build)."""
    def parts(s):
        spans = featureprog.method_spans(s)
        lines = s.splitlines()
        codes = {k: "\n".join(lines[x - 1:y]) for k, (x, y) in spans.items()}
        rest = "\n".join(ln for i, ln in enumerate(lines, 1) if not any(x <= i <= y for x, y in spans.values())
                         and ln.strip())
        return codes, rest
    ca, ra = parts(a)
    cb, rb = parts(b)
    return {"features": {"changed": [k for k in cb if k in ca and ca[k] != cb[k]],
                         "added": [k for k in cb if k not in ca], "removed": [k for k in ca if k not in cb]},
            "shared": ra != rb, "source_changed": a != b}


# ---- the canonical source of a project ---------------------------------------------------------------------------

def _same(a: dict, b: dict) -> dict:
    box = max((abs(x - y) for p, q in zip(a["bbox"], b["bbox"]) for x, y in zip(p, q)), default=0.0)
    return {"volume": abs(a["volume_mm3"] - b["volume_mm3"]) <= 1e-6 * max(1.0, abs(a["volume_mm3"])),
            "faces": a["faces"] == b["faces"], "bbox": box <= 1e-4}


def canonical(st, p: dict, verify: bool = True) -> dict:
    """The head's source in canonical form: {"source", "mode", "features", "why", "verified", "rid"}.

    mode native: the head already is a FeatureDesign. features / skeleton: lifted (form/canon.py) and, with verify,
    built once and compared with the head (volume, face count, bounding box: computed); a lift that differs or does
    not build is dropped for the next weaker form. none: the head's source as it is. The verdict is kept under
    .cache/canon/, keyed by the source, the values and the kernel, so it is measured once."""
    from .recipes import SCAD_PREFIX, is_source, source_id
    from .studio import BUILD_TIMEOUT, H, StudioError
    rid = st.rid(p)
    src = st.source_text(p) or ""
    if rid.startswith(SCAD_PREFIX) or not is_source(rid):
        return {"source": src, "mode": "none", "features": [], "verified": False, "rid": rid,
                "why": "an OpenSCAD design" if rid.startswith(SCAD_PREFIX) else "a built-in building block"}
    src = featureprog.strip_partial(src)
    first = canon.lift(src)
    if first["mode"] in ("native", "none"):
        return {**first, "verified": first["mode"] == "native", "rid": rid}
    if not verify:
        return {**first, "verified": False, "rid": source_id(first["source"])}
    vals = st.rev(p)["values"]
    cache = st.root / ".cache" / "canon" / f"{H(VERIFY_VERSION, rid, vals, st.kernel_id())}.json"
    try:
        hit = json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        hit = None
    tries = [first]
    if first["mode"] == "features":
        from .refine import adapter
        w = adapter.wrap(src)
        if w:
            tries.append({"mode": "skeleton", "source": w, "why": "the split did not keep the solid",
                          "features": ["recipe_stages"]})
    if hit:
        t = next((x for x in tries if x["mode"] == hit.get("mode")), None)
        if hit.get("mode") == "none":
            return {"source": src, "mode": "none", "features": [], "verified": True, "rid": rid, "why": hit.get("why", "")}
        if t is not None:
            return {**t, "verified": True, "rid": source_id(t["source"]), "why": hit.get("why", t["why"])}
    base = st.head_summary(p)
    why = ""
    out = None
    for t in tries:
        try:
            rid2 = st._load_design(t["source"], "python")
            s = st._k("summary", key="pv-" + H(rid2, vals), recipe_id=rid2, values=vals, tol=0.1, p=p,
                      timeout=BUILD_TIMEOUT)
        except StudioError as e:
            why = f"the {t['mode']} form does not build: {str(e)[:160]}"
            continue
        same = _same(base, s)
        if s.get("skipped") or not all(same.values()):
            why = (f"the {t['mode']} form does not keep the solid ("
                   + (", ".join(k for k, ok in same.items() if not ok) or "a feature was skipped") + " differ)")
            continue
        out = {**t, "verified": True, "rid": rid2, "why": why or t["why"]}
        break
    if out is None:
        out = {"source": src, "mode": "none", "features": [], "verified": True, "rid": rid, "why": why}
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"mode": out["mode"], "why": out["why"]}), encoding="utf-8")
    except OSError:
        pass
    return out


# ---- one edit: one build, one revision ---------------------------------------------------------------------------

def edit(st, p: dict, ops: list, expect_head: int | None = None, note: str = "", origin: str = "agent",
         partial: bool = False, draft: str | None = None, preflight: str = "block") -> dict:
    """Apply ops to the head's canonical source and save the result as one revision.

    Returns {"project" (the saved project), "head", "source_sha", "changed": [{feature, status, s, dvol}] (only the
    features that were built again), "edit": what the ops touched, "canonical": the form they were applied to,
    "preflight": findings that did not block}. A value-only edit is a commit (no new source). preflight: "block"
    refuses on errors before any kernel time (form/preflight.py), "warn" reports them, "off" skips it."""
    from .studio import StudioError
    p = st.load(p["id"])
    if expect_head is not None and p["head"] != expect_head:
        raise StudioError(f"The design moved on: head is r{p['head']}, not r{expect_head}.",
                          "Read the project again, then re-apply your edit.", status=409, head=p["head"])
    needs_src = any(isinstance(o, dict) and (o.get("op") != "set_param" or any(f in o for f in PARAM_FIELDS[1:]))
                    for o in (ops or []))
    c = canonical(st, p, verify=needs_src)
    if not needs_src:
        c = {**c, "source": featureprog.strip_partial(st.source_text(p) or ""), "mode": c["mode"]}
    new, info = apply(c["source"], ops)
    head0 = p["head"]
    findings: list = []
    if info["source_changed"] and preflight != "off":
        from . import preflight as pf
        vals = {**st.rev(p)["values"], **info["values"]}
        findings = pf.check(new, values=vals, project=p, strict_values=False)["findings"]
        # an edit is refused for what it introduces, never for what the design already had
        was = pf.check(st.source_text(p) or "", values=st.rev(p)["values"], project=p, strict_values=False)["findings"]
        errs = [f for f in pf.new_findings(findings, was) if f["severity"] == "error"]
        if errs and preflight == "block":
            raise StudioError(pf.message(errs), "Nothing was built. Fix every one in the same edit and send it "
                              "again; preflight=\"warn\" builds anyway.", status=422, kind="preflight",
                              findings=findings)
    if not info["source_changed"]:
        if not info["values"]:
            raise StudioError("The ops change nothing.", "Check the op list.")
        p = st.commit(p, info["values"], note, origin, expect_head=head0)
    else:
        p = st.update_design(p, new, note or _note(info), info["values"] or None, origin, head0, "python",
                             partial=partial, draft=draft)
    head = st.rev(p)
    log = head.get("build_log") or []
    out = {"project": p, "head": p["head"], "source_sha": st.rid(p).split(":", 1)[-1],
           "changed": [e for e in log if e.get("status") != "checkpoint"],
           "reused": [e["feature"] for e in log if e.get("status") == "checkpoint"],
           "edit": {k: info[k] for k in ("features", "shared", "values")},
           "canonical": {k: c[k] for k in ("mode", "why") if c.get(k)}}
    if findings:
        out["preflight"] = findings
    if head.get("partial"):
        out["partial"] = head["partial"]
    return out


def _note(info: dict) -> str:
    f = info["features"]
    bits = [f"changed {', '.join(f['changed'])}" if f["changed"] else "", f"added {', '.join(f['added'])}" if f["added"] else "",
            f"removed {', '.join(f['removed'])}" if f["removed"] else "",
            "set " + ", ".join(f"{k}={v:g}" for k, v in info["values"].items()) if info["values"] else ""]
    text = "; ".join(b for b in bits if b)
    return ("Edit: " + text) if text else "Design code edited"


# ---- the ops that turn one source into another -------------------------------------------------------------------

def _method_text(source: str, span: tuple) -> str:
    return textwrap.dedent("\n".join(source.splitlines()[span[0] - 1:span[1]]))


def _hunk(cur: str, target: str):
    """One find/with op that brings cur a step closer to target: the first run of lines that differs, with as many
    lines of context as it takes for the text to be found exactly once. None when they are equal."""
    import difflib
    a, b = cur.splitlines(keepends=True), target.splitlines(keepends=True)
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        lo, hi = i1, i2
        while True:
            find = "".join(a[lo:hi])
            if find and cur.count(find) == 1:
                return {"op": "replace", "find": find, "with": "".join(a[lo:i1]) + "".join(b[j1:j2]) + "".join(a[i2:hi])}
            if lo == 0 and hi == len(a):
                return {"op": "replace", "find": cur, "with": target}
            if lo > 0:
                lo -= 1
            if hi < len(a) and (not find or cur.count("".join(a[lo:hi])) != 1):
                hi += 1
    return None


def delta(a: str, b: str, structural: bool = True) -> list:
    """Ops that turn source a into source b exactly (apply(a, delta(a, b))[0] == b).

    structural: features that changed are replaced, added or removed by name and other functions that changed
    are replaced by name, as an agent would send them; what is left (parameters, class attributes, imports) is
    text replaced where it differs. structural=False: only text. Used to measure what an edit costs as ops
    (scripts/bench_edits.py) and to check the protocol against real edits; it is not how agents write ops."""
    if not b.endswith("\n"):
        b += "\n"
    ops: list = []
    cur = a if a.endswith("\n") else a + "\n"
    if cur == b:
        return ops
    if structural and featureprog.is_feature_design(cur) and featureprog.is_feature_design(b):
        sa, sb = featureprog.method_spans(cur), featureprog.method_spans(b)
        common = [k for k in sa if k in sb]
        if common == [k for k in sb if k in sa]:           # the same order: features can be addressed one by one
            try:
                for k in [k for k in sa if k not in sb]:
                    if len(featureprog.method_spans(cur)) > 1:
                        op = {"op": "delete", "feature": k}
                        cur = _apply_one(cur, op, {})
                        ops.append(op)
                prev = ""
                for k in sb:
                    code = _method_text(b, sb[k])
                    have = featureprog.method_spans(cur)
                    if k not in have:
                        op = {"op": "insert", "feature": k, "code": code, **({"after": prev} if prev else {})}
                        if prev or not have:
                            cur = _apply_one(cur, op, {})
                            ops.append(op)
                    elif _method_text(cur, have[k]) != code:
                        op = {"op": "replace", "feature": k, "code": code}
                        cur = _apply_one(cur, op, {})
                        ops.append(op)
                    prev = k
            except _Bad:
                pass
    if structural:
        try:
            ta, tb = ast.parse(cur), ast.parse(b)
            feats = set(featureprog.method_spans(b))
            for name in _def_names(tb):
                if name in feats or _def_names(tb).count(name) != 1 or _def_names(ta).count(name) != 1:
                    continue
                na, nb = _find_def(ast.parse(cur), name)[0], _find_def(tb, name)[0]
                if na is None or nb is None:
                    continue
                old = _method_text(cur, _span(na))
                new = _method_text(b, _span(nb))
                if old != new:
                    op = {"op": "replace", "def": name, "code": new}
                    cur = _apply_one(cur, op, {})
                    ops.append(op)
        except (SyntaxError, _Bad):
            pass
    for _ in range(400):
        op = _hunk(cur, b)
        if op is None:
            break
        cur = cur.replace(op["find"], op["with"])
        ops.append(op)
    if cur != b:
        return [{"op": "replace", "find": a, "with": b}]
    return ops


def _hunks(cur: str, target: str) -> list | None:
    out = []
    for _ in range(400):
        op = _hunk(cur, target)
        if op is None:
            return out
        cur = cur.replace(op["find"], op["with"])
        out.append(op)
    return None


def tighten(a: str, ops: list) -> list:
    """The same edit with each whole-function replace swapped for the lines that differ inside it, where that is
    shorter: what a careful agent sends (a small fix as text, a rewritten feature by name)."""
    cur = a if a.endswith("\n") else a + "\n"
    out = []
    for op in ops:
        nxt = _apply_one(cur, op, {})
        if op.get("op") == "replace" and ("feature" in op or "def" in op):
            alt = _hunks(cur, nxt)
            if alt is not None and len(json.dumps(alt)) < len(json.dumps([op])):
                out += alt
                cur = nxt
                continue
        out.append(op)
        cur = nxt
    return out
