"""Preflight: what is wrong with a design source that needs no kernel to find, all of it at once.

    r = preflight.check(source, values=None, project=None, contract=None)
    r["findings"]   [{id, rule, severity, line, message, hint, evidence}], errors first
    r["ok"]         no finding of severity "error"
    r["kernel_s"]   0.0, always: nothing here builds geometry

A design used to meet these mistakes one build at a time: a constraint its own defaults violate, a polygon wound
the wrong way, a keyword argument build123d does not have, a thread whose pair never engages. Each cost a kernel
build and a model turn. Here they are found before the kernel is asked for anything.

Two passes.

1. The syntax tree (rules: syntax, contract, api, params, index_selector, finish_order, parts, threads):
   names imported from build123d, form.craft, form.parts and form.patterns and the keyword arguments passed to
   them, against form/preflight_api.json (written by scripts/gen_preflight_api.py from the installed libraries);
   v["key"] reads of a parameter that is not declared; edges()[3]-style selectors; a broad fillet or chamfer
   before a pattern; parts declared by features against `solids`.

2. A dry run (rules: constraints, winding, threads, assembly, names): the source is executed with its own
   arithmetic and control flow, but every geometry module (build123d, form.craft, form.parts, ...) is replaced by
   ghosts that build nothing. Numbers stay real numbers, so the points of every Polygon and the arguments of
   every parts.thread are the ones the kernel would get. A dry run that stops for a reason the ghosts may have
   caused says so as a note and decides nothing.

Severity: "error" is certain to fail or to build the wrong solid (a violated constraint, an unknown name or
keyword, a clockwise Polygon extruded with a positive amount); "warn" is likely a mistake (an index selector, a
loose thread pair); "note" is something the dry run could not follow. Evidence is "static" (read from the text) or
"dry-run" (computed from the design's own numbers, no geometry). Nothing here is measured on a solid.

Standard library only. The design's module-level code and its build() run in this process, as they already do
when a design is loaded (form/recipes load_source); the dry run has a line budget and a time limit.
"""
from __future__ import annotations

import ast
import builtins
import difflib
import json
import math
import sys
import threading
import time
from pathlib import Path

RULES = ("syntax", "contract", "constraints", "api", "params", "names", "winding", "index_selector", "finish_order",
         "threads", "parts", "assembly", "dry_run")
API_FILE = Path(__file__).with_name("preflight_api.json")
LINE_BUDGET = 400_000          # lines of the design the dry run may execute
GHOST_BUDGET = 200_000         # ghost values it may make
TIME_BUDGET = 4.0              # seconds
FREE_FIT_PLAY = 0.6            # mm diametral: what form.parts.thread gives a pair by default (0.3 mm each side)
ISO_MINOR = 1.0825             # ISO 68-1: internal minor diameter = major - 1.0825 pitch
ISO_DEPTH = 0.5413             # ISO 68-1: basic thread depth = 5/8 H = 0.5413 pitch
SELECTORS = ("edges", "faces", "vertices", "wires", "solids")
ORDERING = ("sort_by", "group_by", "filter_by", "filter_by_position", "sort_by_distance")
PATTERN_CALLS = ("PolarLocations", "GridLocations", "HexLocations", "Locations", "hex_vents", "perforation_grid",
                 "slot_array", "grip_ribs", "knurl", "emboss_cells", "wrapped_ribs", "rib_grid", "boss_array")
FINISH_CALLS = ("fillet", "chamfer", "safe_fillet", "safe_chamfer", "variable_fillet")
VALUE_METHODS = ("build", "recipe_build", "constraints", "derived", "measure", "statics", "companions", "assembly",
                 "appearance", "setup", "mesh_texture", "test_piece")
GHOST_MODULES = ("build123d", "bd_warehouse", "OCP", "ocp_vscode", "py_gearworks", "trimesh", "manifold3d")
REAL_FORM = ("form.recipes", "form.featureprog", "form.contract")

_api_cache: dict = {}


def api() -> dict:
    if "api" not in _api_cache:
        try:
            data = json.loads(API_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {"modules": {}, "build123d_version": ""}
        try:
            from importlib import metadata
            data["current"] = metadata.version("build123d") == data.get("build123d_version")
        except Exception:                                # noqa: BLE001 - not installed here: the snapshot only advises
            data["current"] = False
        _api_cache["api"] = data
    return _api_cache["api"]


def _finding(rule: str, severity: str, message: str, hint: str = "", line: int | None = None,
             evidence: str = "static", **extra) -> dict:
    return {"id": f"{rule}:{line or 0}", "rule": rule, "severity": severity, "line": line, "message": message,
            "hint": hint, "evidence": evidence, **extra}


# ---- pass 1: the syntax tree ---------------------------------------------------------------------------------------

def _dotted(n) -> str:
    parts = []
    while isinstance(n, ast.Attribute):
        parts.append(n.attr)
        n = n.value
    if isinstance(n, ast.Name):
        parts.append(n.id)
        return ".".join(reversed(parts))
    return ""


def _design_class(tree):
    bases = ("Recipe", "FeatureDesign")
    found = [n for n in tree.body if isinstance(n, ast.ClassDef)
             and any((b.id if isinstance(b, ast.Name) else getattr(b, "attr", "")) in bases for b in n.bases)]
    return found


def _imports(tree) -> dict:
    """{local name: (snapshot module, name in it or None for the module itself)} for what the API snapshot covers."""
    known = {"build123d": "build123d", "form.craft": "form.craft", "form.parts": "form.parts",
             "form.patterns": "form.patterns"}
    out = {}
    nodes = sorted((n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))), key=lambda n: n.lineno)
    for n in nodes:
        for a in n.names:                                  # a later import of the same name from elsewhere wins
            out.pop(a.asname or a.name.split(".")[0], None)
        if isinstance(n, ast.ImportFrom) and n.level == 0:
            if n.module in known:
                for a in n.names:
                    if a.name != "*":
                        out[a.asname or a.name] = (known[n.module], a.name, n.lineno)
            elif n.module == "form":
                for a in n.names:
                    if f"form.{a.name}" in known:
                        out[a.asname or a.name] = (f"form.{a.name}", None, n.lineno)
        elif isinstance(n, ast.Import):
            for a in n.names:
                if a.name in known and (a.asname or "." not in a.name):
                    out[a.asname or a.name] = (known[a.name], None, n.lineno)
    return out


def _close(name: str, names) -> str:
    c = difflib.get_close_matches(name, list(names), n=3, cutoff=0.6)
    return ("Closest: " + ", ".join(c) + ".") if c else ""


def _check_api(tree, out: list) -> None:
    data = api()
    mods = data.get("modules") or {}
    if not mods:
        return
    sev = "error" if data.get("current") else "warn"
    imp = _imports(tree)
    star = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and any(a.name == "*" for a in n.names)}
    shadow = set()                                         # a design may define its own Box or thread
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            shadow.add(n.name)
        elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            shadow.add(n.id)
        elif isinstance(n, ast.arg):
            shadow.add(n.arg)
    for n in ast.walk(tree):                               # a name imported from anywhere else is that other thing
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            shadow.update((a.asname or a.name.split(".")[0]) for a in n.names if (a.asname or a.name) not in imp)
    for local, (mod, name, line) in imp.items():
        if name is not None and name not in mods.get(mod, {}):
            out.append(_finding("api", sev, f"{mod} has no {name}", _close(name, mods.get(mod, {})), line))

    def resolve(func):
        """(module, name) of a call target the snapshot covers, or None."""
        d = _dotted(func)
        if not d:
            return None
        head, _, rest = d.partition(".")
        if head in shadow:
            return None
        if head in imp:
            mod, name, _ln = imp[head]
            if name is None:
                return (mod, rest) if rest and "." not in rest else None
            return (mod, name) if not rest else (mod, name, rest)
        if not rest and "build123d" in star and head in mods.get("build123d", {}) and head not in dir(builtins):
            return ("build123d", head)
        return None
    for n in ast.walk(tree):
        if isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Load):
            r = resolve(n)
            if r and len(r) == 3 and "." not in r[2]:      # Align.MIDDLE: a member of an enum
                ent = mods.get(r[0], {}).get(r[1]) or {}
                if ent.get("kind") == "enum" and r[2] not in ent.get("members", []) and not r[2].startswith("_") \
                        and r[2] not in ("name", "value"):
                    out.append(_finding("api", sev, f"{r[1]} has no member {r[2]}",
                                        "Members: " + ", ".join(ent["members"]) + ".", n.lineno))
            elif r and len(r) == 2 and r[1] not in mods.get(r[0], {}) and imp.get(_dotted(n).partition(".")[0], ("", 0))[1] is None:
                out.append(_finding("api", sev, f"{r[0]} has no {r[1]}", _close(r[1], mods.get(r[0], {})), n.lineno))
        if not isinstance(n, ast.Call):
            continue
        r = resolve(n.func)
        if not r or len(r) != 2:
            continue
        ent = mods.get(r[0], {}).get(r[1])
        if not ent or not ent.get("sig"):
            continue
        s = ent["sig"]
        if not s["kw"]:
            for k in n.keywords:
                if k.arg and k.arg not in s["params"]:
                    out.append(_finding("api", sev, f"{r[1]}() has no argument {k.arg}",
                                        (_close(k.arg, s["params"]) + " " if _close(k.arg, s["params"]) else "")
                                        + "Arguments: " + ", ".join(s["params"]) + ".", n.lineno))
        if s["pos"] is not None and not any(isinstance(a, ast.Starred) for a in n.args) and len(n.args) > s["pos"]:
            out.append(_finding("api", sev, f"{r[1]}() takes at most {s['pos']} positional arguments, {len(n.args)} given",
                                "Arguments: " + ", ".join(s["params"]) + ".", n.lineno))


def _param_keys(cls) -> tuple[set, bool]:
    """(declared parameter keys, whether every one could be read) from a literal params list."""
    for n in cls.body:
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "params" for t in n.targets):
            if not isinstance(n.value, (ast.List, ast.Tuple)):
                return set(), False
            keys, whole = set(), True
            for e in n.value.elts:
                k = None
                if isinstance(e, ast.Call):
                    k = e.args[0] if e.args else next((x.value for x in e.keywords if x.arg == "key"), None)
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    keys.add(k.value)
                else:
                    whole = False
            return keys, whole
    return set(), False


def _check_params(cls, out: list) -> None:
    keys, whole = _param_keys(cls)
    if not whole or not keys:
        return
    seen = set()
    for fn in cls.body:
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) or len(fn.args.args) < 2:
            continue
        vn = fn.args.args[1].arg
        if fn.name not in VALUE_METHODS and not _is_feature(fn):
            continue                                       # only the methods Form Studio calls with the values
        rebound = any(isinstance(x, ast.Name) and x.id == vn and isinstance(x.ctx, ast.Store) for x in ast.walk(fn))
        if rebound or fn.name in ("reference", "spec"):
            continue
        for x in ast.walk(fn):
            if isinstance(x, ast.Subscript) and isinstance(x.value, ast.Name) and x.value.id == vn \
                    and isinstance(x.ctx, ast.Load) and isinstance(x.slice, ast.Constant) \
                    and isinstance(x.slice.value, str) and x.slice.value not in keys \
                    and (fn.name, x.slice.value) not in seen:
                seen.add((fn.name, x.slice.value))
                out.append(_finding("params", "error", f"{fn.name}() reads {vn}[{x.slice.value!r}], which is not a parameter",
                                    (_close(x.slice.value, keys) + " " if _close(x.slice.value, keys) else "")
                                    + "Declare it in params or use a declared key.", x.lineno))


def _is_feature(fn) -> bool:
    for d in fn.decorator_list:
        t = d.func if isinstance(d, ast.Call) else d
        if (t.id if isinstance(t, ast.Name) else getattr(t, "attr", "")) == "feature":
            return True
    return False


def _check_selectors(tree, out: list) -> None:
    for n in ast.walk(tree):
        if not isinstance(n, ast.Subscript) or not isinstance(n.value, ast.Call):
            continue
        f = n.value.func
        if not isinstance(f, ast.Attribute) or f.attr not in SELECTORS or n.value.args or n.value.keywords:
            continue
        idx = n.slice
        if isinstance(idx, ast.UnaryOp) and isinstance(idx.op, ast.USub):
            idx = idx.operand
        if not (isinstance(idx, ast.Constant) and isinstance(idx.value, int)):
            continue
        if f.attr == "solids":                             # parts are listed in a documented order (left to right)
            continue
        what = ast.unparse(n)
        out.append(_finding(
            "index_selector", "warn",
            f"{what[:80]} picks a {f.attr[:-1]} by its place in the kernel's list",
            f"That place is not a property of the design: it moves when a parameter or an earlier feature changes. "
            f"Select by what made it: craft.made_by(after, before, \"{'faces' if f.attr == 'faces' else 'edges'}\") "
            f"gives what the last operation made (Form Studio's own feature attribution); or by geometry: "
            f".{f.attr}().filter_by(Axis.Z), .sort_by(Axis.Z)[-1], .group_by(Axis.Z)[-1].", n.lineno))


def _calls(node) -> list:
    return [(x, (x.func.id if isinstance(x.func, ast.Name) else getattr(x.func, "attr", ""))) for x in ast.walk(node)
            if isinstance(x, ast.Call)]


def _broad_finish(node):
    """The first fillet or chamfer in node that takes every edge of the body (edges() with no narrowing but an
    axis filter), or None."""
    for call, name in _calls(node):
        if name not in FINISH_CALLS:
            continue
        for a in call.args[:2]:
            chain = []
            x = a
            while isinstance(x, (ast.Call, ast.Attribute, ast.Subscript)):
                if isinstance(x, ast.Call) and isinstance(x.func, ast.Attribute):
                    chain.append(x.func.attr)
                    x = x.func.value
                elif isinstance(x, ast.Call):
                    chain.append(getattr(x.func, "id", "?"))
                    break
                else:
                    if isinstance(x, ast.Subscript):
                        chain.append("[]")
                    x = x.value
            if chain and chain[-1] == "edges" and all(c in ("edges", "filter_by") for c in chain):
                return call
    return None


def _check_finish_order(cls, out: list) -> None:
    """A fillet or chamfer of every edge, then a pattern: the pattern's own edges stay sharp and its booleans run
    on rounded faces. Read per feature method of a FeatureDesign, or per Stage of a plain build()."""
    units = []
    feats = [n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_feature(n)]
    if feats:
        units = [(f.name, [f]) for f in feats]
    else:
        build = next((n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "build"), None)
        if build is None:
            return
        cur, name = [], None
        for s in build.body:
            cur.append(s)
            st = [x for x in ast.walk(s) if isinstance(x, ast.Call) and getattr(x.func, "id", "") == "Stage"]
            if st:
                a = st[-1].args[0] if st[-1].args else None
                name = a.value if isinstance(a, ast.Constant) else "stage"
                units.append((str(name), cur))
                cur = []
    first = None
    for name, nodes in units:
        fin = next((c for n in nodes for c in [_broad_finish(n)] if c is not None), None)
        pat = next(((c, nm) for n in nodes for c, nm in _calls(n) if nm in PATTERN_CALLS), None)
        if first is not None and pat is not None and name != first[0]:
            out.append(_finding(
                "finish_order", "warn",
                f"{first[0]} rounds every edge of the body before {name} adds a pattern ({pat[1]})",
                f"The pattern's edges get no finish, and its cuts run on rounded faces (slower, and where they cross "
                f"a fillet they can leave slivers). Put {first[0]} after {name}, or keep the order and round only "
                f"what a feature made: craft.made_by(after, before).", first[1].lineno, features=[first[0], name]))
            return
        if fin is not None and first is None and (pat is None or pat[0].lineno > fin.lineno):
            first = (name, fin)


def _check_parts(cls, out: list) -> None:
    solids = None
    for n in cls.body:
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "solids" for t in n.targets) \
                and isinstance(n.value, ast.Constant) and isinstance(n.value.value, int):
            solids = (n.value.value, n.lineno)
    total, said = 0, False
    for f in cls.body:
        if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for d in f.decorator_list:
                if isinstance(d, ast.Call):
                    for k in d.keywords:
                        if k.arg == "parts" and isinstance(k.value, ast.Constant) and isinstance(k.value.value, int):
                            total += k.value.value
                            said = True
    if said and total > (solids[0] if solids else 1):
        out.append(_finding("parts", "error", f"the features add {total} parts (@feature(parts=)), but the design "
                            f"declares solids = {solids[0] if solids else 1}",
                            f"Set solids = {total} on the class, or correct the parts= of the feature that is wrong.",
                            solids[1] if solids else cls.lineno))


def _static(source: str, out: list):
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        out.append(_finding("syntax", "error", f"the source does not parse: {e.msg}", "Fix the syntax.", e.lineno))
        return None
    classes = _design_class(tree)
    if len(classes) != 1:
        out.append(_finding("contract", "error", f"a design defines exactly one subclass of Recipe or FeatureDesign; "
                            f"found {len(classes)}", "Define `class Design(FeatureDesign): ...` once.",
                            classes[1].lineno if len(classes) > 1 else None))
        if not classes:
            return tree
    cls = classes[0]
    names = {t.id for n in cls.body if isinstance(n, (ast.Assign, ast.AnnAssign))
             for t in (n.targets if isinstance(n, ast.Assign) else [n.target]) if isinstance(t, ast.Name)}
    feat = any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_feature(n) for n in cls.body)
    inherits = len(cls.bases) > 1 or any(isinstance(n, ast.ClassDef) and n is not cls for n in tree.body)
    if "params" not in names and not inherits:
        out.append(_finding("contract", "error", "the design declares no params", "A design needs at least one "
                            "Param: params = [Param(\"w\", \"Width\", 60, 20, 200, 1, \"mm\", \"form\", \"body\")].",
                            cls.lineno))
    if "features" not in names and not feat and not inherits:
        out.append(_finding("contract", "error", "the design declares no features", "Write one @feature(...) method "
                            "per feature (a FeatureDesign), or features = [Feature(...)] with Stages.", cls.lineno))
    _check_api(tree, out)
    _check_params(cls, out)
    _check_selectors(tree, out)
    _check_finish_order(cls, out)
    _check_parts(cls, out)
    return tree


# ---- pass 2: the dry run -------------------------------------------------------------------------------------------

class _Abort(BaseException):
    """The dry run went over its budget."""


class _MissingParam(KeyError):
    pass


class _Run:
    """What one dry run saw."""

    def __init__(self, filename: str):
        self.filename = filename
        self.ghosts = 0
        self.lines = 0
        self.deadline = time.monotonic() + TIME_BUDGET
        self.polygons: list = []
        self.threads: list = []
        self.findings: list = []
        self.star = False

    def tick(self) -> None:
        self.ghosts += 1
        if self.ghosts > GHOST_BUDGET or (self.ghosts % 512 == 0 and time.monotonic() > self.deadline):
            raise _Abort("budget")

    def where(self) -> list:
        """The design's own lines on the stack, innermost first."""
        out = []
        f = sys._getframe(1)
        while f is not None:
            if f.f_code.co_filename == self.filename:
                out.append(f.f_lineno)
            f = f.f_back
        return out


class _Runs(threading.local):
    """The dry run of this thread (the MCP server checks sources on worker threads, several at a time)."""

    def __init__(self):
        self.stack: list = []


_RUNS = _Runs()


def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x == x


class Ghost:
    """A stand-in for any geometry value: every operation on it works and gives another ghost."""

    def __init__(self, kind: str = "shape", **data):
        if _RUNS.stack:
            _RUNS.stack[-1].tick()
        object.__setattr__(self, "_kind", kind)
        object.__setattr__(self, "_data", data)

    def __getattr__(self, name):
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        d = object.__getattribute__(self, "_data")
        if name in d.get("attrs", {}):
            return d["attrs"][name]
        return Ghost(f"{object.__getattribute__(self, '_kind')}.{name}")

    def __setattr__(self, name, value):
        object.__getattribute__(self, "_data").setdefault("attrs", {})[name] = value

    def __call__(self, *a, **kw):
        return Ghost("value")

    def __iter__(self):
        return iter(())

    def __len__(self):
        return 0

    def __bool__(self):
        return True

    def __getitem__(self, k):
        return Ghost("value")

    def __setitem__(self, k, v):
        pass

    def __contains__(self, k):
        return False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __float__(self):
        return 1.0

    def __int__(self):
        return 1

    __index__ = __int__

    def __round__(self, n=None):
        return 1.0

    def __hash__(self):
        return id(self)

    def __eq__(self, other):
        return self is other

    def __ne__(self, other):
        return self is not other

    def __lt__(self, other):
        return False

    __gt__ = __le__ = __ge__ = __lt__

    def __repr__(self):
        return f"<ghost {object.__getattribute__(self, '_kind')}>"

    def _keep(self, other):
        """A placed polygon is still that polygon: Pos(...) * Polygon(...) keeps its winding."""
        for a, b in ((self, other), (other, self)):
            if isinstance(a, Ghost) and isinstance(b, Ghost) and object.__getattribute__(a, "_kind") == "polygon" \
                    and object.__getattribute__(b, "_kind") == "place":
                return Ghost("polygon", **object.__getattribute__(a, "_data"))
        return Ghost("shape")

    def __mul__(self, other):
        return self._keep(other)

    __rmul__ = __mul__

    def _op(self, *a):
        return Ghost("shape")

    __add__ = __radd__ = __sub__ = __rsub__ = __and__ = __rand__ = __or__ = __ror__ = __xor__ = __truediv__ = _op
    __rtruediv__ = __floordiv__ = __mod__ = __pow__ = __rpow__ = __matmul__ = __neg__ = __pos__ = __abs__ = _op
    __invert__ = __lshift__ = __rshift__ = _op


def _flat_points(args) -> list | None:
    pts = list(args)
    if len(pts) == 1 and isinstance(pts[0], (list, tuple)) and pts[0] and isinstance(pts[0][0], (list, tuple)):
        pts = list(pts[0])
    out = []
    for p in pts:
        if not isinstance(p, (list, tuple)) or len(p) not in (2, 3) or not all(_num(c) for c in p):
            return None
        if len(p) == 3 and abs(p[2]) > 1e-12:
            return None
        out.append((float(p[0]), float(p[1])))
    return out if len(out) >= 3 else None


def _area(pts: list) -> float:
    return sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1])) / 2.0


class _Fn:
    """A callable name of a ghost module (Box, extrude, craft.shell, parts.thread); also an enum (Align.MIN)."""

    def __init__(self, module: str, name: str):
        self._module, self._name = module, name

    def __getattr__(self, name):
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        return _Fn(self._module, f"{self._name}.{name}")

    def __mro_entries__(self, bases):                      # class Mine(Box): a ghost base is no base
        return ()

    def __iter__(self):
        return iter(())

    def _op(self, *a):
        return Ghost("value")

    __add__ = __radd__ = __sub__ = __rsub__ = __mul__ = __rmul__ = __truediv__ = __rtruediv__ = __neg__ = _op
    __and__ = __rand__ = __or__ = __ror__ = __pow__ = __rpow__ = __floordiv__ = __mod__ = _op

    def __float__(self):
        return 1.0

    def __call__(self, *a, **kw):
        run = _RUNS.stack[-1] if _RUNS.stack else None
        mod, name = self._module, self._name
        if run is None:
            return Ghost("shape")
        if mod == "build123d" and name == "Polygon":
            pts = _flat_points(a)
            if pts is not None:
                return Ghost("polygon", pts=pts, lines=run.where())
            return Ghost("shape")
        if mod == "build123d" and name in ("Pos", "Location", "Locations"):
            return Ghost("place")
        if mod == "build123d" and name == "extrude":
            obj = a[0] if a else kw.get("to_extrude")
            amount = a[1] if len(a) > 1 else kw.get("amount")
            if isinstance(obj, Ghost) and object.__getattribute__(obj, "_kind") == "polygon" and _num(amount) \
                    and amount > 0 and not kw.get("both") and kw.get("dir") is None and len(a) < 3:
                d = object.__getattribute__(obj, "_data")
                ar = _area(d["pts"])
                if ar < -1e-9:
                    run.polygons.append({"pts": d["pts"], "area": ar, "amount": float(amount),
                                         "lines": run.where(), "made": d.get("lines") or []})
            return Ghost("shape")
        if (mod == "form.parts" and name == "thread") or name.endswith("IsoThread"):
            if name == "thread":
                major, pitch, length = (list(a) + [None] * 3)[:3]
                major, pitch = kw.get("major_d", major), kw.get("pitch", pitch)
                ext = a[3] if len(a) > 3 else kw.get("external", True)
                cl = a[4] if len(a) > 4 else kw.get("clearance", 0.3)
            else:
                major, pitch = kw.get("major_diameter", a[0] if a else None), kw.get("pitch", a[1] if len(a) > 1 else None)
                ext = kw.get("external", a[3] if len(a) > 3 else True)
                cl = 0.0
            if _num(major) and _num(pitch) and _num(cl) and isinstance(ext, bool):
                run.threads.append({"major": float(major), "pitch": float(pitch), "external": ext,
                                    "clearance": float(cl), "lines": run.where(), "via": name})
            if name == "thread" and isinstance(ext, bool):
                return Ghost("thread", attrs={"kind": "add" if ext else "cut", "shape": Ghost("shape"),
                                              "name": "thread", "dims": {}})
        return Ghost("shape")


class _GhostModule:
    def __init__(self, name: str):
        self.__name__ = name
        self._name = name

    def __getattr__(self, name):
        if name == "__all__":                              # from build123d import *
            names = (api().get("modules") or {}).get(self._name)
            if not names:
                raise AttributeError(name)
            if _RUNS.stack:
                _RUNS.stack[-1].star = True
            return [n for n in names if not n.startswith("_")]
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        ent = ((api().get("modules") or {}).get(self._name) or {}).get(name) or {}
        if ent.get("kind") == "value":
            return Ghost("value")
        full = f"{self._name}.{name}"
        if full in ("form.craft.patterns",):
            return _GhostModule("form.patterns")
        if name in ("RecipeError",):
            from .recipes.base import RecipeError
            return RecipeError
        if name == "pi":
            return math.pi
        return _Fn(self._name, name)


class _FormPackage:
    """`form` as a design sees it in a dry run: its data modules are real, its geometry modules are ghosts."""

    def __getattr__(self, name):
        full = f"form.{name}"
        if full.startswith(REAL_FORM):
            import importlib
            return importlib.import_module(full)
        return _GhostModule(full)


def _importer(real_import):
    def imp(name, globals=None, locals=None, fromlist=(), level=0):
        if level:
            return real_import(name, globals, locals, fromlist, level)
        root = name.split(".")[0]
        if root in GHOST_MODULES:
            return _GhostModule(name if fromlist else root)
        if root == "form":
            if any(name == r or name.startswith(r + ".") for r in REAL_FORM):
                return real_import(name, globals, locals, fromlist, level)
            if name == "form":
                return _FormPackage()
            return _GhostModule(name) if fromlist else _FormPackage()
        return real_import(name, globals, locals, fromlist, level)
    return imp


class _Values(dict):
    def __missing__(self, key):
        raise _MissingParam(key)


def _last_line(e: BaseException, filename: str) -> int | None:
    import traceback
    frames = [f for f in traceback.extract_tb(e.__traceback__) if f.filename == filename]
    return frames[-1].lineno if frames else getattr(e, "lineno", None)


def _dry(source: str, values: dict | None, out: list, strict: bool = True) -> dict:
    """Execute the design with ghost geometry. Returns {"ran": what was reached, "threads": [...]}."""
    filename = f"<design {abs(hash(source)) % 10**10}>"
    run = _Run(filename)
    info = {"ran": [], "threads": run.threads, "stopped": ""}
    try:
        code = compile(source, filename, "exec")
    except SyntaxError:
        return info
    b = dict(vars(builtins))
    b["__import__"] = _importer(builtins.__import__)
    ns = {"__name__": "form_preflight_design", "__builtins__": b, "__file__": filename}

    def trace(frame, event, arg):
        if frame.f_code.co_filename != filename:
            return None

        def line(fr, ev, a):
            run.lines += 1
            if run.lines > LINE_BUDGET or (run.lines % 4096 == 0 and time.monotonic() > run.deadline):
                raise _Abort("budget")
            return line
        return line
    old = sys.gettrace()
    _RUNS.stack.append(run)
    sys.settrace(trace)
    try:
        try:
            exec(code, ns)                                 # noqa: S102 - what load_source does, with ghost geometry
        except _Abort:
            info["stopped"] = "the module's own code ran past the dry run's budget"
            return info
        except Exception as e:                             # noqa: BLE001 - the loader reports load errors itself
            info["stopped"] = f"the module did not load in the dry run: {type(e).__name__}: {e}"[:300]
            if isinstance(e, NameError):
                out.append(_finding("names", "error", f"{type(e).__name__}: {e}", "Define or import the name.",
                                    _last_line(e, filename), "dry-run"))
            return info
        from .recipes.base import Recipe, RecipeError
        found = [v for v in ns.values() if isinstance(v, type) and issubclass(v, Recipe) and v is not Recipe
                 and v.__module__ == "form_preflight_design"]
        if len(found) != 1:
            return info
        cls = found[0]
        try:
            inst = cls()
        except Exception as e:                             # noqa: BLE001
            info["stopped"] = f"the design class could not be made: {type(e).__name__}: {e}"[:300]
            return info
        inst.reference = lambda name: Ghost("reference")
        info["ran"].append("load")
        from .recipes.base import Param
        params = list(getattr(inst, "params", None) or [])
        if not all(isinstance(q, Param) for q in params):   # parameters made by a geometry helper: not readable here
            info["stopped"] = "the parameters are made by a helper the dry run replaces: values were not checked"
            return info
        feats = [getattr(f, "id", "") for f in getattr(inst, "features", None) or []]
        if not getattr(cls, "_form_steps", None):
            for q in params:
                if q.feature and q.feature not in feats:
                    out.append(_finding("contract", "error", f"parameter {q.key} names unknown feature “{q.feature}”",
                                        "Features: " + ", ".join(feats) + ".", None, "dry-run"))
        # values: ranges and the design's own constraints, every one
        v = _Values()
        bad = False
        given = dict(values or {})
        for q in params:
            x = given.get(q.key, q.default)
            if not _num(x) or x in (float("inf"), float("-inf")):
                out.append(_finding("constraints", "error", f"{q.label} ({q.key}) is not a finite number", "", None,
                                    "dry-run", params=[q.key]))
                bad = True
                continue
            if x < q.min - 1e-9 or x > q.max + 1e-9:
                src = "its default" if q.key not in given else "the value"
                out.append(_finding("constraints", "error",
                                    f"{q.label} ({q.key}) = {x:g} {q.unit} is outside {q.min:g} to {q.max:g} {q.unit} "
                                    f"({src})", "Change the value, or widen the Param's min/max.", None, "dry-run",
                                    params=[q.key]))
                bad = True
            v[q.key] = float(x)
        unknown = [k for k in given if k not in {q.key for q in params}]
        if unknown and params and strict:
            out.append(_finding("constraints", "error", "values for parameters the design does not declare: "
                                + ", ".join(unknown), "Declared: " + ", ".join(q.key for q in params) + ".", None,
                                "dry-run", params=unknown))
        try:
            probs = inst.constraints(v) or []
            info["ran"].append("constraints")
        except _Abort:
            raise
        except _MissingParam as e:
            probs = []
            out.append(_finding("params", "error", f"constraints() reads a parameter that is not declared: {e.args[0]!r}",
                                "Declare it in params.", _last_line(e, filename), "dry-run"))
        except Exception as e:                             # noqa: BLE001
            probs = []
            out.append(_finding("dry_run", "note", f"constraints() raised {type(e).__name__}: {e}"[:300], "",
                                _last_line(e, filename), "dry-run"))
        for pr in probs:
            if isinstance(pr, RecipeError):
                bad = True
                out.append(_finding("constraints", "error",
                                    f"the design's own constraint fails with these values: {pr}",
                                    (pr.hint + " " if pr.hint else "") + (
                                        "Values: " + ", ".join(f"{k} = {v[k]:g}" for k in pr.params if k in v) + "."
                                        if pr.params else ""), None, "dry-run",
                                    params=list(pr.params), feature=pr.feature))
        # the assembly declaration: plain data
        try:
            spec = inst.assembly(v)
            if spec is not None and hasattr(spec, "validate"):
                for pr in spec.validate(getattr(inst, "solids", 1)) or []:
                    out.append(_finding("assembly", "error", f"the assembly declaration cannot be used: {pr}",
                                        "Fix assembly(); the parts it names are the design's solids, left to right.",
                                        None, "dry-run"))
                info["ran"].append("assembly")
        except _Abort:
            raise
        except Exception:                                  # noqa: BLE001 - Studio reports assembly() errors itself
            pass
        if bad:
            info["stopped"] = "values do not pass the design's constraints: build() was not run"
            return info
        # build
        steps = list(getattr(cls, "_form_steps", None) or [])
        if steps:
            inst._form_values, inst._form_ctx, inst._form_tracking = v, None, None
            body = None
            for fid in steps:
                try:
                    r = getattr(inst, fid)(v, body)
                    if isinstance(r, (list, tuple)) and r:
                        r = getattr(r[-1], "shape", r[-1])
                    body = getattr(r, "shape", r) if r is not None else body
                    info["ran"].append(fid)
                except _Abort:
                    raise
                except Exception as e:                     # noqa: BLE001
                    _dry_error(e, fid, filename, out)
        else:
            try:
                inst.build(v)
                info["ran"].append("build")
            except _Abort:
                raise
            except Exception as e:                         # noqa: BLE001
                _dry_error(e, "build", filename, out)
    except _Abort:
        info["stopped"] = (f"the dry run stopped at its budget ({LINE_BUDGET:,} lines, {TIME_BUDGET:g} s): what it "
                           "had seen until then is reported")
    finally:
        sys.settrace(old)
        _RUNS.stack.pop()
    _report_polygons(run, out)
    return info


def _dry_error(e: BaseException, where: str, filename: str, out: list) -> None:
    line = _last_line(e, filename)
    star = bool(_RUNS.stack and _RUNS.stack[-1].star and not api().get("current"))
    if isinstance(e, _MissingParam):
        out.append(_finding("params", "error", f"{where}() reads a parameter that is not declared: {e.args[0]!r}",
                            "Declare it in params or use a declared key.", line, "dry-run"))
    elif isinstance(e, NameError):
        out.append(_finding("names", "warn" if star else "error", f"{where}(): {type(e).__name__}: {e}", "Define or import the name; a "
                            "value from another feature is not visible here (features share only the body and "
                            "setup()).", line, "dry-run"))
    else:
        from .recipes.base import RecipeError
        if isinstance(e, RecipeError):
            return                                         # a helper refusing ghost numbers decides nothing
        out.append(_finding("dry_run", "note", f"the dry run could not follow {where}() past line {line}: "
                            f"{type(e).__name__}: {e}"[:300], "Nothing is concluded from it; the build decides.",
                            line, "dry-run"))


def _report_polygons(run: _Run, out: list) -> None:
    seen = set()
    for pg in run.polygons:
        lines = pg["lines"]
        key = tuple(lines)
        if key in seen:
            continue
        seen.add(key)
        at = lines[-1] if lines else None                  # the outermost design line: where the points are written
        via = f" (through line {lines[0]})" if len(lines) > 1 else ""
        pts = ", ".join(f"({x:g}, {y:g})" for x, y in pg["pts"][:6]) + (", ..." if len(pg["pts"]) > 6 else "")
        out.append(_finding(
            "winding", "error",
            f"the Polygon extruded at line {at}{via} winds clockwise (signed area {pg['area']:.1f} mm²): "
            f"extrude(amount={pg['amount']:g}) goes toward -Z, not +Z",
            f"Its face normal points down, so the solid lands at z = {-pg['amount']:g}..0. List the points "
            f"counter-clockwise (reverse them), or extrude with dir=(0, 0, 1). Points: {pts}.", at, "dry-run",
            lines=lines))


def _thread_pairs(threads: list, out: list, contract: list | None) -> None:
    ext = [t for t in threads if t["external"]]
    inn = [t for t in threads if not t["external"]]

    def size(t):
        return f"M{t['major']:g}x{t['pitch']:g}"
    seen = set()
    for e in ext:
        line = e["lines"][-1] if e["lines"] else None
        if not inn:
            if ("lone", size(e)) in seen:
                continue
            seen.add(("lone", size(e)))
            out.append(_finding("threads", "warn", f"an external {size(e)} thread (line {line}) has no internal thread "
                                "in this design", "If its hole is part of this design, cut the thread: "
                                "parts.thread(major_d, pitch, length, external=False) gives the cutter. A plain bore "
                                "does not hold a bolt.", line, "dry-run"))
            continue
        same = [i for i in inn if abs(i["pitch"] - e["pitch"]) < 1e-9]
        if not same:
            k = ("pitch", size(e))
            if k not in seen:
                seen.add(k)
                out.append(_finding("threads", "error", f"the external {size(e)} thread (line {line}) has no internal "
                                    f"thread of the same pitch (internal: {', '.join(sorted({size(i) for i in inn}))})",
                                    "A bolt and its hole share one pitch.", line, "dry-run"))
            continue
        i = min(same, key=lambda t: abs(t["major"] - e["major"]))
        d_ext = e["major"] - e["clearance"]                # modelled major diameter of the bolt
        d_int = i["major"] + i["clearance"]                # modelled major diameter of the hole
        play = d_int - d_ext
        engage = (d_ext - (d_int - ISO_MINOR * e["pitch"])) / 2.0
        depth = ISO_DEPTH * e["pitch"]
        k = ("pair", size(e), size(i))
        if k in seen:
            continue
        seen.add(k)
        il = i["lines"][-1] if i["lines"] else None
        facts = {"bolt_major_mm": round(d_ext, 3), "hole_major_mm": round(d_int, 3), "play_mm": round(play, 3),
                 "engagement_mm": round(engage, 3), "basic_depth_mm": round(depth, 3)}
        if play < -1e-9:
            out.append(_finding("threads", "error", f"thread pair {size(e)} (line {line}) / {size(i)} (line {il}): the "
                                f"bolt is {-play:.2f} mm larger than its hole on the diameter",
                                "The hole's major diameter must be the bolt's plus the play.", line, "dry-run", **facts))
        elif play > 1.5 * FREE_FIT_PLAY + 1e-9 or engage < 0.5 * depth:
            out.append(_finding(
                "threads", "warn",
                f"thread pair {size(e)} (line {line}) / {size(i)} (line {il}): {play:.2f} mm of play on the diameter "
                f"leaves {engage:.2f} mm of flank overlap, {100 * engage / depth:.0f} % of the basic thread depth "
                f"({depth:.2f} mm)",
                f"parts.thread already takes its clearance off the bolt and adds it to the hole ({FREE_FIT_PLAY:g} mm "
                f"of play for a pair at the defaults): give both the same nominal major_d and set the play with "
                f"clearance=, not by enlarging major_d as well. Anything that trims the crests afterwards removes "
                f"more of the overlap.", line, "dry-run", **facts))
    for c in contract or []:
        if c.get("kind") == "thread" and not threads:
            out.append(_finding("threads", "warn", f"the contract asks for a thread ({c.get('text') or c.get('id')}), "
                                "and nothing in the source makes one", "A hole meant to be threaded is a plain bore "
                                "until a thread is cut: parts.thread(..., external=False), or a heat-set insert hole "
                                "if that is what is meant (then change the requirement).", None, "static",
                                contract=c.get("id")))


# ---- the check -----------------------------------------------------------------------------------------------------

_ORDER = {"error": 0, "warn": 1, "note": 2}


def check(source: str, values: dict | None = None, project: dict | None = None, contract: list | None = None,
          dry_run: bool = True, strict_values: bool = True) -> dict:
    """Every finding for one source (see the module docstring). values: the values it will be built with (default:
    the design's defaults). strict_values=False: values for parameters the source no longer declares are ignored
    (an edit carries the head's values over). project: its contract is read from it. Never raises for a source
    that is text."""
    t0 = time.perf_counter()
    out: list = []
    source = source or ""
    if contract is None and project:
        from . import contract as contract_mod
        contract = (contract_mod.of(project) or {}).get("assertions") or []
    tree = _static(source, out)
    info = {"ran": [], "threads": [], "stopped": ""}
    if tree is not None and dry_run:
        try:
            info = _dry(source, values, out, strict_values)
        except RecursionError:
            info = {"ran": [], "threads": [], "stopped": "the dry run recursed too deep"}
        _thread_pairs(info["threads"], out, contract)
        if info["stopped"]:
            out.append(_finding("dry_run", "note", info["stopped"], "", None, "dry-run"))
    if contract and tree is not None:
        for c in contract:
            if c.get("kind") == "part_count":
                cls = (_design_class(tree) or [None])[0]
                decl = 1
                for n in (cls.body if cls else []):
                    if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "solids" for t in n.targets) \
                            and isinstance(n.value, ast.Constant):
                        decl = n.value.value
                if isinstance(decl, int) and decl != c.get("count"):
                    out.append(_finding("parts", "warn", f"the contract asks for {c.get('count')} part(s) "
                                        f"({c.get('text') or c.get('id')}); the design declares solids = {decl}",
                                        "Set solids to the number of separate parts, or correct the requirement.",
                                        None, "static", contract=c.get("id")))
    notes = [f for f in out if f["rule"] == "dry_run"]
    if len(notes) > 1:                                    # one note says the dry run was incomplete; the rest repeat it
        out = [f for f in out if f["rule"] != "dry_run"] + [{**notes[0], "more": len(notes) - 1}]
    uniq, seen = [], set()
    for f in out:
        k = (f["rule"], f["line"], f["message"])
        if k not in seen:
            seen.add(k)
            uniq.append(f)
    uniq.sort(key=lambda f: (_ORDER.get(f["severity"], 3), f["line"] or 0))
    for n, f in enumerate(uniq, 1):
        f["id"] = f"{f['rule']}-{n}"
    return {"ok": not any(f["severity"] == "error" for f in uniq), "findings": uniq,
            "counts": {s: sum(1 for f in uniq if f["severity"] == s) for s in ("error", "warn", "note")},
            "dry_run": {"ran": info["ran"], "stopped": info["stopped"]}, "kernel_s": 0.0,
            "seconds": round(time.perf_counter() - t0, 4)}


def key(f: dict) -> tuple:
    """What makes two findings the same one in two versions of a source (the line may have moved)."""
    import re
    return f["rule"], re.sub(r"\bline \d+", "line", f["message"])


def new_findings(findings: list, before: list) -> list:
    """The findings an edit introduced: those the source it started from did not already have."""
    old = {key(f) for f in before}
    return [f for f in findings if key(f) not in old]


def message(findings: list) -> str:
    """Findings as one refusal: every one, numbered, with its line."""
    rows = [f"{i}. [{f['rule']}" + (f", line {f['line']}" if f.get("line") else "") + f"] {f['message']}"
            + (f" Fix: {f['hint']}" if f.get("hint") else "") for i, f in enumerate(findings, 1)]
    return (f"Preflight found {len(findings)} problem(s) before building (no kernel time used):\n" + "\n".join(rows))[:6000]
