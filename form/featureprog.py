"""Designs built one feature at a time, and builds that keep what was built when a later feature fails.

Two things live here.

1. FeatureDesign: a design written as one method per feature. Each method takes the values and the body so far and
   returns the body after that feature; the first one gets body=None and makes the skeleton:

       from form import craft
       from form.featureprog import FeatureDesign, feature
       from form.recipes.base import Param

       class Design(FeatureDesign):
           params = [Param("w", "Width", 60, 20, 200, 1, "mm", "form", "body")]

           def setup(self, v):                  # optional: shared values, read as self.ctx (computed once, lazily)
               return {"r": v["w"] / 2}

           @feature("Body", role="structure")
           def body(self, v, body):
               return Box(v["w"], v["w"], 20)

           @feature("Bore", role="interface")
           def bore(self, v, body):
               return craft.cut(body, Cylinder(5, 40))

   Features are the decorated methods, in the order they are written. A feature that raises or returns something
   that is not a valid solid is skipped: the body stays as it was, the build goes on with the next feature, and the
   skip is reported with its diagnosis (the revision is then partial and release is blocked until it builds). The
   first feature (the skeleton) must build.

   Every feature's result is kept as a B-rep checkpoint (in memory and on disk) under a key made of the code of the
   feature, the code every feature shares (the file without the feature methods), the values and the key of the
   feature before it. Changing one feature rebuilds that feature and those after it; the ones before load from
   their checkpoints. Features talk to each other only through the body (and setup()): a feature that loads from
   its checkpoint does not run, so state it would have set on self is not there.

   update_design(feature=, code=), add_feature(kind="code") and remove_feature edit one method in the source
   (replace_feature, insert_feature, delete_feature below), so an agent sends one feature, not the whole file.

2. Partial builds of any design (FeatureDesign or a plain Recipe): when build() raises after some stages were made,
   or the result fails the final check, the kernel knows the stages made so far (form/recipes/base.py records every
   Stage). partial_source() writes a block at the end of the source that keeps the first `keep` stages; that source
   is a design like any other, so every view, export and check works on it, and its revision is flagged partial.
   The stages it keeps are saved as checkpoints when the failure is found, so building the partial design does not
   build them again.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import sys
import textwrap
import time
from pathlib import Path

from .recipes.base import Feature, Recipe, RecipeError, Stage, recording

# names a feature method may not take: they are the Recipe contract's own methods and attributes
RESERVED = {"build", "constraints", "derived", "measure", "statics", "companions", "test_piece", "reference",
            "assembly", "appearance", "public", "validate", "defaults", "spec", "setup", "ctx", "mesh_texture",
            "params", "features", "fit", "solids", "category", "tags", "legacy", "id", "title", "summary", "mesh",
            "partial"}
_ID = re.compile(r"[a-z_][a-z0-9_]{0,47}")
MEMORY = 48                      # checkpoints kept in a worker's memory
DISK_MAX = 600                   # checkpoint files kept on disk (the oldest go first; a miss only costs a rebuild)


def _h(*parts) -> str:
    return hashlib.sha1(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:24]


# ---- the feature decorator and the design base ---------------------------------------------------------------------

def feature(label: str = "", role: str = "structure", doc: str = ""):
    """Mark a method of a FeatureDesign as a feature: `@feature("Eye openings", role="access")`."""
    def deco(fn):
        fn._form_feature = {"label": label, "role": role, "doc": doc}
        return fn
    return deco


class FeatureDesign(Recipe):
    """A design built one feature at a time (see the module docstring)."""

    _form_steps: list = []

    def __init_subclass__(cls, **kw):
        super().__init_subclass__(**kw)
        own = [(n, f) for n, f in cls.__dict__.items() if callable(f) and hasattr(f, "_form_feature")]
        if not own:
            return
        for n, _f in own:
            if n in RESERVED:
                raise TypeError(f"A feature method cannot be called “{n}”: that name belongs to the Recipe contract. "
                                f"Name it after the feature, for example “{n}_feature”.")
        declared = {f.id: f for f in cls.__dict__.get("features", []) or []}
        feats = []
        for n, f in own:
            m = f._form_feature
            feats.append(declared.get(n) or Feature(n, m["label"] or n.replace("_", " ").capitalize(), m["role"], m["doc"]))
        cls.features = feats
        cls._form_steps = [n for n, _f in own]
        # a parameter may name a planned feature that is not written yet (skeleton first: every Param is declared
        # up front); it drives no feature until that method is added, and then links to it with no source change
        ids = {f.id for f in feats}
        if any(p.feature and p.feature not in ids for p in cls.__dict__.get("params", []) or []):
            import dataclasses
            cls.params = [p if not p.feature or p.feature in ids else dataclasses.replace(p, feature="")
                          for p in cls.params]

    # optional: shared values for every feature, read as self.ctx
    def setup(self, v: dict):
        return {}

    @property
    def ctx(self):
        c = getattr(self, "_form_ctx", None)
        if c is None or c[0] is not self._form_values:
            c = (self._form_values, self.setup(self._form_values))
            self._form_ctx = c
        return c[1]

    def build(self, v: dict) -> list[Stage]:
        self._form_values = v
        self._form_ctx = None
        steps = list(type(self)._form_steps)
        if not steps:
            raise RecipeError("This FeatureDesign has no features.", "", "Mark each feature method with @feature(...).")
        codes, shared = code_map(type(self))
        key = _h("featureprog/1", shared, v, _context_fingerprint())
        mesh = bool(getattr(self, "mesh", False))
        stages: list[Stage] = []
        body = None
        rep = _REPORT
        for i, fid in enumerate(steps):
            key = _h(key, fid, codes.get(fid, ""))
            t0 = time.perf_counter()
            got = checkpoint_get(key)
            if got is not None:
                body = got
                stages.append(Stage(fid, body))
                rep["log"].append({"feature": fid, "status": "checkpoint", "s": round(time.perf_counter() - t0, 3)})
                continue
            try:
                out = getattr(self, fid)(v, body)
                if isinstance(out, Stage):
                    out = out.shape
                if out is None:
                    out = body
                problem = _problem(out, mesh)
                if problem:
                    raise RecipeError(f"The {fid} feature {problem}.", fid,
                                      "Check the operands of its last boolean: they must overlap by a few tenths of a "
                                      "millimetre, not touch.")
            except Exception as e:
                if i == 0:                                   # nothing to keep: the skeleton itself did not build
                    raise
                d = _diagnosis(e, self, fid)
                rep["skipped"].append(d)
                rep["log"].append({"feature": fid, "status": "skipped", "s": round(time.perf_counter() - t0, 3)})
                key = _h(key, "skipped")
                continue
            checkpoint_put(key, out)
            body = out
            stages.append(Stage(fid, body))
            rep["log"].append({"feature": fid, "status": "built", "s": round(time.perf_counter() - t0, 3)})
        return stages


def _problem(out, mesh: bool) -> str:
    if not hasattr(out, "solids"):
        return f"returned {type(out).__name__}, not a solid"
    try:
        n = len(out.solids())
        vol = float(out.volume)
    except Exception as e:
        return f"returned a shape that cannot be measured ({type(e).__name__})"
    if n == 0 or vol <= 1e-9:
        return "left no solid (a boolean failed and returned nothing)"
    if not mesh:
        try:
            if not out.is_valid:
                return "returned a solid that is not valid (a boolean or a loft failed part-way)"
        except Exception:
            pass
    return ""


def _diagnosis(e: BaseException, recipe, fid: str) -> dict:
    """What a skipped feature reports: its id, the message, the hint and the build diagnosis (form/build_diag.py)."""
    try:
        from . import build_diag
        err = build_diag.wrap(e, recipe) if isinstance(e, RecipeError) else build_diag.error(e, recipe)
        pub = err.public()
    except Exception:
        pub = e.public() if isinstance(e, RecipeError) else {"message": f"{type(e).__name__}: {e}"[:600], "hint": ""}
    diag = pub.get("diagnosis") or {}
    return {"feature": fid, "message": str(pub.get("message", ""))[:700], "hint": str(pub.get("hint", ""))[:900],
            "diagnosis": {k: diag[k] for k in ("summary", "operation", "line", "code", "cause", "fixes", "safe")
                          if k in diag}}


# ---- what one build did (read by the kernel after build()) ---------------------------------------------------------

_REPORT: dict = {"log": [], "skipped": []}


def begin() -> None:
    _REPORT["log"] = []
    _REPORT["skipped"] = []


def report() -> dict:
    return {"log": list(_REPORT["log"]), "skipped": list(_REPORT["skipped"])}


# ---- code of a FeatureDesign: per feature, and what they share -----------------------------------------------------

_codes: dict = {}
_BLOCK = re.compile(r"^# ---- Form Studio: .*?^# ---- end of [^\n]*$", re.S | re.M)


def code_map(cls) -> tuple[dict, str]:
    """({feature id: its method's code}, the rest of the file) for a FeatureDesign class. Form Studio's own blocks
    (text, standard features, partial build) are left out of the shared code: they act after the features."""
    mod = sys.modules.get(cls.__module__)
    path = getattr(mod, "__file__", None)
    if not path:                     # design sources are imported without a sys.modules entry (recipes.load_source):
        for n in getattr(cls, "_form_steps", []) or []:      # read the file the feature methods were compiled from
            co = getattr(getattr(cls, n, None), "__code__", None)
            if co is not None and os.path.isfile(co.co_filename):
                path = co.co_filename
                break
    try:
        st = os.stat(path) if path else None
    except OSError:
        st = None
    ck = (cls.__module__, cls.__qualname__, path, st.st_mtime_ns if st else None, st.st_size if st else None)
    if ck in _codes:
        return _codes[ck]
    try:
        text = Path(path).read_text(encoding="utf-8") if path else ""
    except OSError:
        text = ""
    if not text:
        import inspect
        try:
            text = inspect.getsource(cls)
        except (OSError, TypeError):
            text = ""
    spans = method_spans(text, cls.__name__) if text else {}
    lines = text.splitlines()
    codes = {n: textwrap.dedent("\n".join(lines[a - 1:b])).strip() for n, (a, b) in spans.items()}
    keep = [ln for i, ln in enumerate(lines, 1) if not any(a <= i <= b for a, b in spans.values())]
    shared = _BLOCK.sub("", "\n".join(keep))
    shared = "\n".join(ln.rstrip() for ln in shared.splitlines() if ln.strip())
    _codes[ck] = (codes, shared)
    return codes, shared


def _feature_class(tree: ast.Module, name: str | None = None):
    classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
    if name:
        classes = [n for n in classes if n.name == name]
    else:
        classes = [n for n in classes if any(_base_name(b) == "FeatureDesign" for b in n.bases)]
    return classes[-1] if classes else None


def _base_name(b) -> str:
    return b.id if isinstance(b, ast.Name) else (b.attr if isinstance(b, ast.Attribute) else "")


def _is_feature(fn) -> bool:
    for d in fn.decorator_list:
        target = d.func if isinstance(d, ast.Call) else d
        if _base_name(target) == "feature":
            return True
    return False


def method_spans(text: str, cls_name: str | None = None) -> dict:
    """{feature id: (first line, last line)} of the @feature methods (decorators included), in order."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return {}
    c = _feature_class(tree, cls_name)
    if c is None:
        return {}
    out = {}
    for n in c.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_feature(n):
            out[n.name] = (min([d.lineno for d in n.decorator_list] + [n.lineno]), n.end_lineno)
    return out


# ---- checkpoints ---------------------------------------------------------------------------------------------------

_mem: dict = {}


def _dir() -> Path | None:
    d = os.environ.get("FORM_CHECKPOINTS")
    if d:
        return Path(d)
    s = os.environ.get("FORM_SOURCES")
    return Path(s).parent / ".cache" / "checkpoints" if s else None


def _context_fingerprint() -> str:
    """What a build reads besides its code and values: label text (form/marks.py) and imported parts."""
    out = []
    try:
        from . import marks
        out.append({k: v for k, v in marks.context().items() if k != "nozzle"})   # the nozzle shapes no solid
    except Exception:
        pass
    try:
        from .recipes import meshsolid
        refs = []
        for k, p in sorted(meshsolid._paths.items()):
            try:
                s = os.stat(p)
                refs.append((k, p, s.st_size, s.st_mtime_ns))
            except OSError:
                refs.append((k, p))
        out.append(refs)
    except Exception:
        pass
    try:
        from .kernel import kernel_id
        out.append(kernel_id())
    except Exception:
        pass
    return _h(out)


def checkpoint_get(key: str):
    hit = _mem.get(key)
    if hit is not None:
        _mem[key] = _mem.pop(key)
        return hit
    d = _dir()
    if d is None:
        return None
    f = d / f"{key}.bin"
    if not f.is_file():
        return None
    try:
        import build123d
        from OCP.BinTools import BinTools
        from OCP.TopoDS import TopoDS_Shape
        meta = json.loads((d / f"{key}.json").read_text(encoding="utf-8"))
        raw = TopoDS_Shape()
        BinTools.Read_s(raw, str(f))
        if raw.IsNull():
            return None
        cls = getattr(build123d, meta.get("type", ""), None)
        shape = cls(raw) if isinstance(cls, type) else build123d.Shape.cast(raw)
        os.utime(f)
    except Exception:
        return None
    _remember(key, shape)
    return shape


def checkpoint_put(key: str, shape) -> None:
    _remember(key, shape)
    d = _dir()
    if d is None:
        return
    try:
        from OCP.BinTools import BinTools
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / f"{key}.tmp"
        if BinTools.Write_s(shape.wrapped, str(tmp)):
            (d / f"{key}.json").write_text(json.dumps({"type": type(shape).__name__, "ts": time.time()}), encoding="utf-8")
            os.replace(tmp, d / f"{key}.bin")
        files = list(d.glob("*.bin"))
        if len(files) > DISK_MAX:
            files.sort(key=lambda x: x.stat().st_mtime)
            for old in files[:len(files) - DISK_MAX]:
                old.unlink(missing_ok=True)
                old.with_suffix(".json").unlink(missing_ok=True)
    except Exception:
        pass


def _remember(key, shape):
    _mem[key] = shape
    while len(_mem) > MEMORY:
        _mem.pop(next(iter(_mem)))


# ---- partial builds of any design ----------------------------------------------------------------------------------

P_START = "# ---- Form Studio: partial build (delete this block once every feature builds) ----"
P_END = "# ---- end of partial build ----"
P_TEMPLATE = '''
{start}
# Only the first {keep} stage(s) of the build above built ({built}); {failed_text}
# Form Studio keeps them so the design is saved and shown. Fix the feature that failed and submit the source without
# this block (update_design does that), and the whole design builds again.
from form import featureprog as _form_fp
{cls} = _form_fp.partial({cls}, keep={keep}, solids={solids}, origin={origin!r}, failed={failed!r},
                        stages={stages!r}, valid={valid!r})
{end}
'''


def _class_name(source: str) -> str:
    tree = ast.parse(source)
    names = [n.name for n in tree.body if isinstance(n, ast.ClassDef)
             and any(_base_name(b) in ("Recipe", "FeatureDesign") for b in n.bases)]
    if len(names) != 1:
        raise ValueError(f"expected one design class, found {len(names)}")
    return names[0]


def strip_partial(source: str) -> str:
    """The source without a partial-build block."""
    i = source.find(P_START)
    if i < 0:
        return source
    j = source.find(P_END, i)
    rest = source[:i].rstrip() + "\n" + (source[j + len(P_END):].lstrip("\n") if j >= 0 else "")
    return rest.rstrip() + "\n"


def partial_info(source: str) -> dict | None:
    """{"keep": n, "origin": rid} of a partial-build block, or None."""
    i = source.find(P_START)
    if i < 0:
        return None
    m = re.search(r"keep=(\d+), solids=(\d+), origin='([^']*)'", source[i:])
    return {"keep": int(m.group(1)), "origin": m.group(3)} if m else {}


def partial_source(source: str, keep: int, solids: int, origin: str, features: list, failed: str,
                   valid: bool = True) -> str:
    base = strip_partial(source)
    failed_text = f"the next one, {failed}, failed." if failed else "the result failed the final check."
    return base.rstrip() + "\n" + P_TEMPLATE.format(start=P_START, end=P_END, cls=_class_name(base), keep=int(keep),
                                                    solids=int(solids), origin=origin, failed=failed or "",
                                                    stages=list(features[:keep]), valid=bool(valid),
                                                    built=", ".join(features[:keep]) or "none", failed_text=failed_text)


def prefix_key(origin: str, v: dict) -> str:
    return _h("partial/1", origin, v, _context_fingerprint())


def save_prefix(origin: str, v: dict, stages: list) -> None:
    """Keep the stages of a failed build, so its partial design loads them instead of building them again."""
    k = prefix_key(origin, v)
    for i, s in enumerate(stages):
        checkpoint_put(f"{k}-{i}", s.shape)


class _Stop(Exception):
    pass


def partial(cls, keep: int, solids: int, origin: str = "", failed: str = "", stages: list | None = None,
            valid: bool = True):
    """The design class, changed to build only its first `keep` stages (used by the partial-build block)."""
    build = cls.build
    declared_solids = getattr(cls, "solids", 1)

    def partial_build(self, v):
        k = prefix_key(origin, v)
        shapes = [checkpoint_get(f"{k}-{i}") for i in range(keep)] if origin else [None]
        if shapes and all(s is not None for s in shapes):
            feats = list(stages or [])
            return [Stage(feats[i] if i < len(feats) else f"stage_{i + 1}", s) for i, s in enumerate(shapes)]

        def stop(stage):
            if len(rec) >= keep:
                raise _Stop()
        with recording(on_stage=stop) as rec:
            try:
                build(self, v)
            except _Stop:
                pass
            except Exception:
                pass
        if len(rec) < keep:
            raise RecipeError(f"The partial build stops before its {keep} stage(s) now.", failed,
                              "Submit the design's source again without the partial-build block.")
        return rec[:keep]

    cls.build = partial_build
    cls.solids = int(solids)
    if not valid:                                    # kept although OCCT's check fails: shown, flagged, never released
        cls.allow_invalid = True
    cls.partial = {"keep": int(keep), "failed": failed, "origin": origin}
    if int(solids) != int(declared_solids):          # a declared assembly names parts the partial build lacks
        cls.assembly = lambda self, v: None
    measure = cls.measure

    def safe_measure(self, v, faces):
        try:
            return measure(self, v, faces)
        except Exception:
            return []
    cls.measure = safe_measure
    return cls


# ---- editing one feature of a FeatureDesign's source ---------------------------------------------------------------

def is_feature_design(source: str) -> bool:
    try:
        return _feature_class(ast.parse(source)) is not None
    except SyntaxError:
        return False


def feature_ids(source: str) -> list[str]:
    return list(method_spans(source).keys())


def _err(msg: str, hint: str = ""):
    from .studio import StudioError
    return StudioError(msg, hint)


def _one_function(code: str, fid: str):
    code = textwrap.dedent(code).strip("\n")
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise _err(f"The code for {fid} does not parse: {e.msg} (line {e.lineno}).",
                   "Send one method: `def <feature>(self, v, body): ...` returning the body after the feature.")
    fns = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    if len(fns) != 1 or len(tree.body) != 1:
        raise _err(f"The code for {fid} must be exactly one method definition.",
                   f"Send `def {fid}(self, v, body): ...` (with @feature(...) above it if you want to set the label).")
    fn = fns[0]
    if fn.name != fid:
        raise _err(f"The method is called {fn.name}, but the feature is {fid}.", f"Name the method {fid}.")
    args = [a.arg for a in fn.args.args]
    if len(args) != 3 or args[0] != "self":
        raise _err(f"{fid} must take (self, v, body).", "v: the values; body: the solid so far (None for the first).")
    return code, fn


def _class_indent(lines: list, cls_node) -> str:
    for n in cls_node.body:
        ln = lines[n.lineno - 1]
        return ln[:len(ln) - len(ln.lstrip())]
    return "    "


def _decorate(code: str, fn, label: str = "", role: str = "structure") -> str:
    if _is_feature(fn):
        return code
    return f"@feature({label or fn.name.replace('_', ' ').capitalize()!r}, role={role!r})\n" + code


def replace_feature(source: str, fid: str, code: str) -> str:
    """The source with one feature method replaced. A method sent without @feature keeps the old decorator."""
    source = strip_partial(source)
    tree = ast.parse(source)
    c = _feature_class(tree)
    if c is None:
        raise _err("Only a FeatureDesign can be changed one feature at a time.",
                   "Send the whole source with update_design(source=...), or write the design as a FeatureDesign.")
    spans = method_spans(source)
    if fid not in spans:
        raise _err(f"No feature “{fid}” in this design.", "Features: " + ", ".join(spans) + ". add_feature(kind=\"code\") adds one.")
    code, fn = _one_function(code, fid)
    lines = source.splitlines()
    a, b = spans[fid]
    if not _is_feature(fn):
        old = [ln for ln in lines[a - 1:b] if ln.strip().startswith("@")]
        code = "\n".join(textwrap.dedent("\n".join(old)).splitlines()) + "\n" + code if old else _decorate(code, fn)
    ind = _class_indent(lines, c)
    new = textwrap.indent(code, ind).splitlines()
    return "\n".join(lines[:a - 1] + new + lines[b:]) + "\n"


def insert_feature(source: str, fid: str, code: str, label: str = "", role: str = "structure", after: str = "") -> str:
    """The source with a new feature method, after `after` (default: the last feature)."""
    source = strip_partial(source)
    if not _ID.fullmatch(fid or "") or fid in RESERVED:
        raise _err(f"“{fid}” cannot be a feature id.", "Use lower-case letters, digits and _ (not a Recipe method name).")
    tree = ast.parse(source)
    c = _feature_class(tree)
    if c is None:
        raise _err("Code features can be added to a FeatureDesign only.",
                   "Write the design as a FeatureDesign (form.featureprog) or send the whole source with update_design.")
    spans = method_spans(source)
    if fid in spans:
        raise _err(f"The design already has a feature “{fid}”.", "Change it with update_design(feature=..., code=...).")
    if any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == fid for n in c.body):
        raise _err(f"The design already has a method called {fid}.", "Pick another feature id.")
    if after and after not in spans:
        raise _err(f"No feature “{after}” to add it after.", "Features: " + ", ".join(spans) + ".")
    code, fn = _one_function(code, fid)
    code = _decorate(code, fn, label, role)
    lines = source.splitlines()
    end = spans[after][1] if after else (max(b for _a, b in spans.values()) if spans else c.end_lineno)
    new = [""] + textwrap.indent(code, _class_indent(lines, c)).splitlines()
    return "\n".join(lines[:end] + new + lines[end:]) + "\n"


def delete_feature(source: str, fid: str) -> str:
    source = strip_partial(source)
    spans = method_spans(source)
    if fid not in spans:
        raise _err(f"No feature “{fid}” in this design.", "Features: " + ", ".join(spans) + ".")
    if len(spans) == 1:
        raise _err("A design keeps at least one feature.", "Change it instead (update_design with feature and code).")
    lines = source.splitlines()
    a, b = spans[fid]
    while a > 1 and not lines[a - 2].strip():                # the blank line above it goes too
        a -= 1
    return "\n".join(lines[:a - 1] + lines[b:]) + "\n"


# ---- one-feature edits of a project (a new revision through Studio.update_design) -----------------------------------

def _source(st, p) -> str:
    from .recipes import SCAD_PREFIX, is_source
    rid = st.rid(p)
    if rid.startswith(SCAD_PREFIX) or not is_source(rid):
        raise _err("This design is not a Python design written as code.",
                   "Feature edits work on designs made with create_design in Python.")
    return st.source_text(p) or ""


def update_feature(st, p, fid: str, code: str, note: str = "", values: dict | None = None, origin: str = "agent",
                   expect_head: int | None = None, partial: bool = False, draft: str | None = None) -> dict:
    src = replace_feature(_source(st, p), fid, code)
    return st.update_design(p, src, note or f"Changed feature {fid}", values, origin, expect_head, "python",
                            partial=partial, draft=draft)


def add_code_feature(st, p, fid: str, code: str, label: str = "", role: str = "structure", after: str = "",
                     origin: str = "agent", expect_head: int | None = None, partial: bool = False,
                     draft: str | None = None) -> dict:
    src = insert_feature(_source(st, p), fid, code, label, role, after)
    return st.update_design(p, src, f"Added feature {fid}", None, origin, expect_head, "python", partial=partial,
                            draft=draft)


def remove_code_feature(st, p, fid: str, origin: str = "agent", expect_head: int | None = None) -> dict:
    src = delete_feature(_source(st, p), fid)
    return st.update_design(p, src, f"Removed feature {fid}", None, origin, expect_head, "python")
