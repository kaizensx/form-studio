"""The canonical form of a design: one method per feature.

A plain Recipe builds everything in one build() and returns its Stages. An agent that wants to change one feature of
it has to send the whole file again. lift() rewrites such a source as a FeatureDesign whose feature methods are the
pieces of build() between its Stage boundaries, so every later edit names one feature (form/edits.py) and the kernel
rebuilds that feature and the ones after it only (form/featureprog.py keeps a checkpoint per feature).

    r = canon.lift(source)
    r["mode"]      "native"    already a FeatureDesign (source unchanged)
                   "features"  build() split into r["features"] methods
                   "skeleton"  build() could not be split safely: it is one feature (form/refine/adapter.py wrap)
                   "none"      not liftable at all (r["why"]): a mesh design, a cage source, no single Recipe class
    r["source"]    the lifted source (the original for native and none)

How build() is split. Its top-level statements are cut after every statement that makes a Stage. A piece becomes a
method `def <stage name>(self, v, <body>)`: the body it receives is the shape the piece before it staged, and it
returns the shape it staged. What a piece reads from earlier pieces, other than that body, is recomputed inside it:
the earlier statements that bind those names are copied in (a backward slice). A slice is only valid when replaying
it gives the same values and costs nothing, so a piece is merged with the ones before it when its slice would have
to rebind the body it receives (a value measured on an earlier body, for example), touch the stage list, or make
geometry again (only arithmetic and the design's own numeric helpers are replayed). Merged pieces, conditional
stages that are not in tail position, loops that stage and stage names that cannot be method names are kept verbatim
in a method marked @feature(..., stages=True), which returns its Stages as build() did. When everything merges into
one piece the result is the skeleton form.

The split is conservative, not proven: Studio accepts a lifted source only after building it once and finding the
same volume, bounding box and face count as the original (form/edits.py canonical()). Plain syntax-tree work: no
kernel, no imports of the design.
"""
from __future__ import annotations

import ast
import re

from .featureprog import RESERVED, _ID

MARK = "# form.canon: lifted from a plain Recipe's build(), one method per Stage (form/canon.py)"
IMPORT = "from form.featureprog import FeatureDesign, feature  " + MARK
_UNSAFE_NAMES = {"locals", "globals", "vars", "exec", "eval", "nonlocal"}


class Unliftable(Exception):
    """build() cannot be split into feature methods (the reason is the message); the skeleton form is used."""


class _SharedLines(Unliftable):
    """Two statements of build() share a line (a; b): lift() writes build() one statement per line and tries again."""


def is_lifted(source: str) -> bool:
    return MARK in (source or "")


# ---- reading statements ------------------------------------------------------------------------------------------

def _is_stage_call(n) -> bool:
    return isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "Stage"


def _stage_calls(n) -> list:
    return [x for x in ast.walk(n) if _is_stage_call(x)]


def _stage_item(call):
    """(feature name or None when it is not a constant, the shape expression) of one Stage(...) call."""
    args = list(call.args)
    kw = {k.arg: k.value for k in call.keywords}
    name = args[0] if args else kw.get("feature")
    shape = args[1] if len(args) > 1 else kw.get("shape")
    if name is None or shape is None or len(args) > 2:
        raise Unliftable("a Stage(...) call that is not Stage(feature, shape)")
    return (name.value if isinstance(name, ast.Constant) and isinstance(name.value, str) else None), shape


def _inner(n):
    """Walk a statement without entering nested functions, lambdas and classes (their names are their own)."""
    todo = [n]
    while todo:
        x = todo.pop()
        yield x
        for c in ast.iter_child_nodes(x):
            if isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)) and c is not n:
                yield c                                   # the def itself (it binds a name), not its body
                continue
            todo.append(c)


def _base(t):
    while isinstance(t, (ast.Subscript, ast.Attribute, ast.Starred)):
        t = t.value
    return t.id if isinstance(t, ast.Name) else None


def _binds(stmt) -> set:
    """The local names a statement may bind or change: assignment targets (also through a subscript or an
    attribute), defs, imports, loop targets, and a name a bare method call is made on (pts.append(...))."""
    out = set()
    for x in _inner(stmt):
        if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(x.name)
        elif isinstance(x, ast.Name) and isinstance(x.ctx, (ast.Store, ast.Del)):
            out.add(x.id)
        elif isinstance(x, (ast.Subscript, ast.Attribute)) and isinstance(x.ctx, (ast.Store, ast.Del)):
            b = _base(x)
            if b:
                out.add(b)
        elif isinstance(x, (ast.Import, ast.ImportFrom)):
            out.update((a.asname or a.name.split(".")[0]) for a in x.names)
        elif isinstance(x, ast.Expr) and isinstance(x.value, ast.Call) and isinstance(x.value.func, ast.Attribute):
            b = _base(x.value.func)
            if b:
                out.add(b)
    return out


def _reads(stmt) -> set:
    """Every name a statement reads, nested functions included (what they close over is read when they run)."""
    out = set()
    for x in ast.walk(stmt):
        if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Load):
            out.add(x.id)
        elif isinstance(x, ast.AugAssign):
            b = _base(x.target)
            if b:
                out.add(b)
    return out


def _definite(stmt) -> set:
    """Names a top-level statement certainly binds before the next statement runs."""
    if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {stmt.name}
    if isinstance(stmt, (ast.Import, ast.ImportFrom)):
        return {(a.asname or a.name.split(".")[0]) for a in stmt.names}
    targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target] if isinstance(stmt, ast.AnnAssign) \
        and stmt.value is not None else []
    out = set()
    for t in targets:
        if isinstance(t, ast.Name):
            out.add(t.id)
        elif isinstance(t, (ast.Tuple, ast.List)) and all(isinstance(e, ast.Name) for e in t.elts):
            out.update(e.id for e in t.elts)
    return out


def _live_in(stmts) -> set:
    """Names read by a run of statements before the run itself certainly binds them."""
    seen, out = set(), set()
    for s in stmts:
        out |= _reads(s) - seen
        seen |= _definite(s)
    return out


# ---- what is cheap to replay -------------------------------------------------------------------------------------

_LIGHT_NAMES = {"min", "max", "abs", "int", "float", "round", "len", "range", "sum", "sorted", "tuple", "list", "dict",
                "set", "zip", "enumerate", "bool", "str", "any", "all", "map", "reversed", "divmod", "pow", "isinstance"}
_LIGHT_MODULES = {"math", "np", "numpy"}
_LIGHT_METHODS = {"get", "items", "keys", "values", "append", "extend", "insert", "copy", "index", "count", "sort",
                  "reverse", "join", "format", "split", "strip", "lower", "upper", "update", "pop", "setdefault"}


class _Light:
    """Is a statement cheap to run again: only arithmetic and calls that make no geometry? A call is light when it
    is a numeric builtin, math or numpy, a plain container method, or a function of this source (module level,
    a method of the design class, a def inside build()) whose own calls are all light. Everything else, and so
    every build123d or form.craft call, is heavy: a slice never replays it."""

    def __init__(self, tree, cls, build):
        self.fns = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
        self.methods = {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}
        self.local = {n.name: n for n in ast.walk(build) if isinstance(n, ast.FunctionDef) and n is not build}
        self.selfn = build.args.args[0].arg
        self._memo: dict = {}

    def fn(self, node) -> bool:
        k = id(node)
        if k not in self._memo:
            self._memo[k] = False                         # a function that calls itself is not followed
            self._memo[k] = all(self.call(c) for c in ast.walk(node) if isinstance(c, ast.Call))
        return self._memo[k]

    def call(self, c) -> bool:
        f = c.func
        if isinstance(f, ast.Name):
            if f.id in self.local:
                return self.fn(self.local[f.id])
            if f.id in self.fns:
                return self.fn(self.fns[f.id])
            return f.id in _LIGHT_NAMES
        if isinstance(f, ast.Attribute):
            if isinstance(f.value, ast.Name) and f.value.id in _LIGHT_MODULES:
                return True
            if isinstance(f.value, ast.Name) and f.value.id == self.selfn:
                return f.attr in self.methods and f.attr != "build" and self.fn(self.methods[f.attr])
            return f.attr in _LIGHT_METHODS
        return False

    def stmt(self, s) -> bool:
        if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return True                                   # defining a helper costs nothing; calling it is judged
        return all(self.call(c) for c in ast.walk(s) if isinstance(c, ast.Call))


# ---- the design class ----------------------------------------------------------------------------------------------

def _design_class(tree: ast.Module):
    found = [n for n in tree.body if isinstance(n, ast.ClassDef)
             and any((b.id if isinstance(b, ast.Name) else getattr(b, "attr", "")) == "Recipe" for b in n.bases)]
    return found[0] if len(found) == 1 else None


def _declared(cls) -> dict:
    """{feature id: (label, role)} from a literal `features = [Feature("id", "Label", "role"), ...]`."""
    out = {}
    for n in cls.body:
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "features" for t in n.targets) \
                and isinstance(n.value, (ast.List, ast.Tuple)):
            for e in n.value.elts:
                if isinstance(e, ast.Call) and getattr(e.func, "id", getattr(e.func, "attr", "")) == "Feature":
                    a = [x.value if isinstance(x, ast.Constant) else None for x in e.args]
                    kw = {k.arg: k.value.value for k in e.keywords if isinstance(k.value, ast.Constant)}
                    fid = a[0] if a else kw.get("id")
                    if isinstance(fid, str):
                        out[fid] = (str((a[1] if len(a) > 1 else kw.get("label")) or fid),
                                    str((a[2] if len(a) > 2 else kw.get("role")) or "structure"))
    return out


class _Piece:
    """A run of build()'s top-level statements that ends with the statement that stages (or with a return)."""

    def __init__(self):
        self.stmts: list = []          # every statement of the piece, the staging ones included
        self.close = None              # the statement that stages, when the piece is a simple one
        self.kind = "verbatim"         # simple | cond | virtual | verbatim
        self.name = None               # the one stage name of a simple, cond or virtual piece
        self.expr = None               # its shape expression
        self.carry = None              # the local name that holds the body after the piece (None: not a plain name)
        self.slice: list = []
        self.first_line = 0


def _list_use_ok(stmt, L: str) -> bool:
    """Every use of the stage list inside a statement is one that only adds stages to it."""
    ok = set()
    for x in ast.walk(stmt):
        if isinstance(x, ast.Call) and isinstance(x.func, ast.Attribute) and x.func.attr in ("append", "extend") \
                and isinstance(x.func.value, ast.Name) and x.func.value.id == L:
            ok.add(id(x.func.value))
        elif isinstance(x, ast.AugAssign) and isinstance(x.target, ast.Name) and x.target.id == L \
                and isinstance(x.op, ast.Add):
            ok.add(id(x.target))
        elif isinstance(x, ast.Assign) and len(x.targets) == 1 and isinstance(x.targets[0], ast.Name) \
                and x.targets[0].id == L and isinstance(x.value, ast.List):
            ok.add(id(x.targets[0]))
    return all(id(x) in ok for x in ast.walk(stmt) if isinstance(x, ast.Name) and x.id == L)


def _tail_appends(stmt, L: str):
    """The `L.append(Stage(...))` statements of an if statement when each is the last statement on its path
    (so it can become a return), else None."""
    found = []

    def block(body) -> bool:
        for i, s in enumerate(body):
            last = i == len(body) - 1
            calls = _stage_calls(s)
            if not calls:
                continue
            if not last:
                return False
            if isinstance(s, ast.If):
                if not block(s.body) or not block(s.orelse):
                    return False
            elif isinstance(s, ast.Expr) and isinstance(s.value, ast.Call) and len(calls) == 1 \
                    and isinstance(s.value.func, ast.Attribute) and s.value.func.attr == "append" \
                    and isinstance(s.value.func.value, ast.Name) and s.value.func.value.id == L \
                    and s.value.args and s.value.args[0] is calls[0]:
                found.append(s)
            else:
                return False
        return True
    if not isinstance(stmt, ast.If) or not block(stmt.body) or not block(stmt.orelse):
        return None
    return found


def _split(source: str, cls, build) -> tuple[list, str, str | None]:
    """(pieces, the name of the values argument, the stage list's name) of a build() method."""
    a = build.args
    if len(a.args) != 2 or a.vararg or a.kwarg or a.kwonlyargs or a.defaults or build.decorator_list:
        raise Unliftable("build() does not take exactly (self, values)")
    selfn, vn = a.args[0].arg, a.args[1].arg
    body = list(build.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
            and isinstance(body[0].value.value, str):
        body = body[1:]
    if not body or not isinstance(body[-1], ast.Return) or body[-1].value is None:
        raise Unliftable("build() does not end with a return of its stages")
    lines_used: set = set()
    for s in body:
        span = set(range(s.lineno, s.end_lineno + 1))
        if span & lines_used:
            raise _SharedLines("two statements share a line")
        lines_used |= span
    for x in ast.walk(build):
        if isinstance(x, (ast.Nonlocal, ast.Global, ast.Yield, ast.YieldFrom, ast.Await)):
            raise Unliftable("build() uses nonlocal, global, yield or await")
        if isinstance(x, ast.Name) and x.id in _UNSAFE_NAMES:
            raise Unliftable(f"build() uses {x.id}()")
        if isinstance(x, ast.Return) and x is not body[-1] and not _in_nested(build, x):
            raise Unliftable("build() returns early")
        if isinstance(x, ast.Attribute) and isinstance(x.ctx, (ast.Store, ast.Del)) and _base(x) == selfn:
            raise Unliftable("build() keeps state on self")
    ret = body[-1]
    L = ret.value.id if isinstance(ret.value, ast.Name) else None
    if L is None and not (isinstance(ret.value, ast.List) and ret.value.elts
                          and all(_is_stage_call(e) for e in ret.value.elts)):
        raise Unliftable("build() returns something other than its stage list or a list of Stage(...)")
    pieces: list = []
    cur = _Piece()
    stmts = body[:-1]
    if L is None:                                        # return [Stage("a", a), Stage("b", b)]: cut after each name
        items = [_stage_item(e) for e in ret.value.elts]
        if any(n is None or not isinstance(x, ast.Name) for n, x in items) or any(_stage_calls(s) for s in stmts):
            raise Unliftable("the returned Stage list does not name one plain variable per stage")
        last = {}
        for i, s in enumerate(stmts):
            for nm in _binds(s):
                last[nm] = i
        cuts = [last.get(x.id) for _n, x in items]
        if any(c is None for c in cuts) or cuts != sorted(set(cuts)) or len({x.id for _n, x in items}) != len(items):
            raise Unliftable("the returned stages are not made one after the other")
        cuts[-1] = len(stmts) - 1                       # what follows the last body belongs to the last piece
        at = 0
        for (nm, x), c in zip(items, cuts):
            p = _Piece()
            p.stmts, p.kind, p.name, p.expr, p.carry = stmts[at:c + 1], "virtual", nm, x, x.id
            at = c + 1
            pieces.append(p)
        return pieces, vn, None
    seen_list = False
    for s in stmts:
        calls = _stage_calls(s)
        uses = any(isinstance(x, ast.Name) and x.id == L for x in ast.walk(s))
        if not calls:
            if uses:
                if isinstance(s, (ast.Assign, ast.AnnAssign)) and not seen_list and _definite(s) == {L} \
                        and isinstance(s.value, (ast.List, ast.Call)) and not _reads(s.value) - {"list"}:
                    seen_list = True                     # L = []: the method that needs a list makes its own
                    continue
                raise Unliftable(f"build() reads its stage list {L} between stages")
            cur.stmts.append(s)
            continue
        if not _list_use_ok(s, L):
            raise Unliftable(f"build() uses its stage list {L} for more than adding stages")
        seen_list = True
        cur.stmts.append(s)
        items = [_stage_item(c) for c in calls]
        one = len(calls) == 1 and items[0][0] is not None
        simple = one and (
            (isinstance(s, ast.Expr) and isinstance(s.value, ast.Call) and s.value.args[:1] == [calls[0]]
             and getattr(s.value.func, "attr", "") == "append")
            or (isinstance(s, ast.Assign) and isinstance(s.value, ast.List) and s.value.elts == [calls[0]])
            or (isinstance(s, ast.AugAssign) and isinstance(s.value, ast.List) and s.value.elts == [calls[0]]))
        tails = None if simple else _tail_appends(s, L)
        if simple:
            cur.kind, cur.close, cur.name, cur.expr = "simple", s, items[0][0], items[0][1]
            cur.carry = items[0][1].id if isinstance(items[0][1], ast.Name) else None
        elif tails and len({(_stage_item(_stage_calls(t)[0])[0]) for t in tails}) == 1 \
                and all(isinstance(_stage_item(_stage_calls(t)[0])[1], ast.Name) for t in tails) \
                and len({_stage_item(_stage_calls(t)[0])[1].id for t in tails}) == 1 \
                and _stage_item(_stage_calls(tails[0])[0])[0] is not None:
            nm, x = _stage_item(_stage_calls(tails[0])[0])
            cur.kind, cur.close, cur.name, cur.expr, cur.carry = "cond", s, nm, x, x.id
            cur.tails = tails
        else:
            last = items[-1][1]
            cur.kind, cur.carry = "verbatim", (last.id if isinstance(last, ast.Name) else None)
        pieces.append(cur)
        cur = _Piece()
    if cur.stmts:
        raise Unliftable("build() does work after its last stage")
    if not pieces:
        raise Unliftable("build() makes no Stage at its top level")
    return pieces, vn, L


def _in_nested(fn, node) -> bool:
    for x in ast.walk(fn):
        if x is not fn and isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            if any(y is node for y in ast.walk(x)):
                return True
    return False


def _merge(a: _Piece, b: _Piece) -> _Piece:
    m = _Piece()
    m.stmts, m.kind, m.carry = a.stmts + b.stmts, "verbatim", b.carry
    return m


def _plan(pieces: list, build, vn: str, L: str | None, light: "_Light | None" = None) -> list:
    """Give every piece its slice (the earlier statements it replays); merge a piece into the one before it when
    no valid slice exists. Returns the final pieces."""
    selfn = build.args.args[0].arg
    i = 0
    while i < len(pieces):
        p = pieces[i]
        prior = [s for q in pieces[:i] for s in q.stmts]
        local = set().union(*[_binds(s) for s in prior]) if prior else set()
        carry_in = pieces[i - 1].carry if i else None
        need = (_live_in(p.stmts) & local) - {selfn, vn, L}
        if carry_in:
            need.discard(carry_in)
        chosen: list = []
        ok = True
        grew = True
        while grew and ok:
            grew = False
            for s in prior:
                if s in chosen or not (_binds(s) & need):
                    continue
                if _stage_calls(s) or (L and any(isinstance(x, ast.Name) and x.id == L for x in ast.walk(s))):
                    ok = False
                    break
                if light is not None and not light.stmt(s):   # replaying it would build geometry twice
                    ok = False
                    break
                chosen.append(s)
                more = (_reads(s) & local) - {selfn, vn, L} - need
                if more:
                    need |= more
                grew = True
        if ok and carry_in and carry_in in need:         # a value measured on an earlier body: it cannot be replayed
            ok = False
        if ok and carry_in and any(carry_in in _binds(s) for s in chosen):
            ok = False
        if not ok:
            if i == 0:
                raise Unliftable("the first stage depends on something that cannot be replayed")
            pieces[i - 1:i + 1] = [_merge(pieces[i - 1], p)]
            i -= 1
            continue
        p.slice = [s for s in prior if s in chosen]       # in the order build() ran them
        i += 1
    return pieces


# ---- writing the methods ------------------------------------------------------------------------------------------

def _text(lines: list, a: int, b: int) -> list:
    return lines[a - 1:b]


def _expr_text(source: str, node) -> str:
    t = ast.get_source_segment(source, node) or ast.unparse(node)
    return f"({t})" if "\n" in t else t


def _label(name: str, declared: dict) -> tuple[str, str]:
    lab, role = declared.get(name, (name.replace("_", " ").capitalize(), "structure"))
    return lab, role


def _methods(source: str, cls, build, pieces: list, vn: str, L: str | None, declared: dict) -> tuple[list, list]:
    lines = source.splitlines()
    selfn = build.args.args[0].arg
    b0 = build.body[0]
    ind = lines[b0.lineno - 1][:len(lines[b0.lineno - 1]) - len(lines[b0.lineno - 1].lstrip())]
    dind = lines[build.lineno - 1][:len(lines[build.lineno - 1]) - len(lines[build.lineno - 1].lstrip())]
    taken = {n.name for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))} - {"build"}
    for n in cls.body:
        taken |= _definite(n)
    names_all = [p.name for p in pieces if p.kind != "verbatim"]
    locals_ = set().union(*[_binds(s) for p in pieces for s in p.stmts])
    out: list = []
    ids: list = []
    used: set = set()
    prev_end = None
    for k, p in enumerate(pieces):
        carry_in = pieces[k - 1].carry if k else None
        param = carry_in or ("body" if "body" not in locals_ else "prev_body")
        plain = p.kind != "verbatim" and _ID.fullmatch(p.name or "") and p.name not in RESERVED \
            and p.name not in taken and names_all.count(p.name) == 1 and p.name not in used \
            and p.name not in ("recipe_build", "recipe_stages")
        first = p.stmts[0].lineno if p.stmts else None
        start = (prev_end + 1) if prev_end else (b0.lineno if not (isinstance(b0, ast.Expr) and isinstance(
            getattr(b0, "value", None), ast.Constant)) else b0.end_lineno + 1)
        end = p.stmts[-1].end_lineno if p.stmts else start - 1
        prev_end = end
        seg = _text(lines, start, end) if first else []
        skip = {s for s in build.body if s.lineno >= start and s.end_lineno <= end and s not in p.stmts}
        drop: dict = {}                                   # line -> replacement lines (None: remove)
        for s in skip:                                    # `st = []`
            for ln in range(s.lineno, s.end_lineno + 1):
                drop[ln] = None
        if plain:
            if p.kind == "simple":
                c = p.close
                cind = lines[c.lineno - 1][:len(lines[c.lineno - 1]) - len(lines[c.lineno - 1].lstrip())]
                drop[c.lineno] = [cind + "return " + _expr_text(source, p.expr)]
                for ln in range(c.lineno + 1, c.end_lineno + 1):
                    drop[ln] = None
            elif p.kind == "cond":
                for t in p.tails:
                    tind = lines[t.lineno - 1][:len(lines[t.lineno - 1]) - len(lines[t.lineno - 1].lstrip())]
                    drop[t.lineno] = [tind + "return " + _expr_text(source, _stage_item(_stage_calls(t)[0])[1])]
                    for ln in range(t.lineno + 1, t.end_lineno + 1):
                        drop[ln] = None
            mid = p.name
            lab, role = _label(p.name, declared)
            head = [f"{dind}@feature({lab!r}, role={role!r})", f"{dind}def {mid}({selfn}, {vn}, {param}):"]
            tail = [] if p.kind == "simple" else [ind + "return " + (p.carry or param)]
        else:
            base = next((n for s in p.stmts for c in _stage_calls(s) for n in [_stage_item(c)[0]] if n), None) or "part"
            mid = re.sub(r"[^a-z0-9_]", "_", base.lower())[:36] + "_stages"
            if not _ID.fullmatch(mid):
                mid = "f_" + mid[:40]
            n = 2
            while mid in taken or mid in used or mid in RESERVED:
                mid = f"{mid.rstrip('0123456789')}{n}"
                n += 1
            staged = [nm for s in p.stmts for c in _stage_calls(s) for nm in [_stage_item(c)[0]] if nm]
            lab = " + ".join(_label(x, declared)[0] for x in dict.fromkeys(staged)) or "Stages"
            head = [f"{dind}@feature({lab[:80]!r}, role='structure', stages=True)",
                    f"{dind}def {mid}({selfn}, {vn}, {param}):"]
            if p.kind in ("virtual",):
                tail = [ind + f"return [Stage({p.name!r}, {_expr_text(source, p.expr)})]"]
            else:
                lst = L or "stages_made"
                head.append(ind + f"{lst} = []")
                tail = [ind + f"return {lst} or {p.carry or param}"]
        body_lines: list = []
        for s in p.slice:
            body_lines += _text(lines, s.lineno, s.end_lineno)
        for j, ln in enumerate(seg, start):
            if j in drop:
                if drop[j]:
                    body_lines += drop[j]
                continue
            body_lines.append(ln)
        while body_lines and not body_lines[-1].strip():
            body_lines.pop()
        out.append(head + body_lines + tail)
        ids.append(mid)
        used.add(mid)
    return out, ids


def _rewrite(source: str, tree, cls, build, methods: list) -> str:
    lines = source.splitlines()
    head = cls.lineno - 1
    end_head = (cls.body[0].lineno - 2) if cls.body else head
    for i in range(head, max(head, end_head) + 1):
        if re.search(r"\bRecipe\b", lines[i]):
            lines[i] = re.sub(r"\bRecipe\b", "FeatureDesign", lines[i], count=1)
            break
    new: list = []
    for i, m in enumerate(methods):
        new += ([""] if i else []) + m
    lines[build.lineno - 1:build.end_lineno] = new
    imports = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom)) and n.lineno < cls.lineno]
    at = imports[-1].end_lineno if imports else 0
    lines.insert(at, IMPORT)
    return "\n".join(lines) + "\n"


def _one_per_line(source: str, cls, build):
    """The source with build() written one statement per line (comments inside build() are lost; nothing else is)."""
    import textwrap
    lines = source.splitlines()
    ind = lines[build.lineno - 1][:len(lines[build.lineno - 1]) - len(lines[build.lineno - 1].lstrip())]
    lines[build.lineno - 1:build.end_lineno] = textwrap.indent(ast.unparse(build), ind).splitlines()
    source = "\n".join(lines) + "\n"
    tree = ast.parse(source)
    cls = _design_class(tree)
    build = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "build")
    return source, tree, cls, build


def lift(source: str, skeleton: bool = True) -> dict:
    """The canonical form of a design source (see the module docstring). Never raises for a source that parses:
    what cannot be split is the skeleton form, what cannot be wrapped is returned as it is with the reason."""
    from . import featureprog
    from .refine import adapter
    source = featureprog.strip_partial(source or "")
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return {"mode": "none", "source": source, "why": f"the source does not parse ({e.msg}, line {e.lineno})",
                "features": []}
    if featureprog._feature_class(tree) is not None:
        return {"mode": "native", "source": source, "why": "", "features": featureprog.feature_ids(source),
                "lifted": is_lifted(source) or adapter.is_wrapped(source)}
    why = adapter.why_not(source)
    if why:
        return {"mode": "none", "source": source, "why": why, "features": []}
    cls = _design_class(tree)
    build = next(n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "build")
    reason = ""
    try:
        if isinstance(build, ast.AsyncFunctionDef):
            raise Unliftable("build() is async")
        if any(isinstance(t, ast.Name) and t.id in ("feature", "FeatureDesign") and isinstance(t.ctx, ast.Store)
               for t in ast.walk(tree)) or any(n.name in ("feature", "FeatureDesign") for n in ast.walk(tree)
                                               if isinstance(n, (ast.FunctionDef, ast.ClassDef))):
            raise Unliftable("the source uses the names feature or FeatureDesign for something else")
        try:
            pieces, vn, L = _split(source, cls, build)
        except _SharedLines:
            source, tree, cls, build = _one_per_line(source, cls, build)
            pieces, vn, L = _split(source, cls, build)
        pieces = _plan(pieces, build, vn, L, _Light(tree, cls, build))
        if len(pieces) < 2:
            raise Unliftable("build() is one piece (its stages depend on each other's values)" if L else
                             "build() makes one stage")
        methods, ids = _methods(source, cls, build, pieces, vn, L, _declared(cls))
        out = _rewrite(source, tree, cls, build, methods)
        ast.parse(out)                                   # what was written must at least be Python
        if featureprog.feature_ids(out) != ids:
            raise Unliftable("the lifted source does not read back as the same features")
        return {"mode": "features", "source": out, "why": "", "features": ids}
    except Unliftable as e:
        reason = str(e)
    except (SyntaxError, IndexError, KeyError, AttributeError, TypeError, ValueError) as e:   # never worse than skeleton
        reason = f"the split failed ({type(e).__name__}: {e})"
    if not skeleton:
        return {"mode": "none", "source": source, "why": reason, "features": []}
    wrapped = adapter.wrap(source)
    if wrapped is None:
        return {"mode": "none", "source": source, "why": reason, "features": []}
    return {"mode": "skeleton", "source": wrapped, "why": reason, "features": ["recipe_stages"]}
