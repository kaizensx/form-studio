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

   Every feature's result is kept as a B-rep checkpoint (in memory and on disk, with the part names of a
   craft.parts() result) under a key made of the feature's own code, only the code it uses from the rest of the file
   (helpers it calls, methods and attributes it reads through self, setup() when it reads self.ctx; feature_codes),
   only the values it reads (recorded while it runs) and the key of the feature before it. So changing `solids`,
   mesh_texture(), appearance(), a parameter no feature reads, or one feature rebuilds that feature and those after
   it only; the ones before load from their checkpoints. Features talk to each other only through the body (and
   setup()): a feature that loads from its checkpoint does not run, so state it would have set on self is not there.

   Every feature is checked when it is made: a valid solid, its volume change, and its solid count (against the
   running part total when features say how many parts they add, @feature(..., parts=N); otherwise no more than the
   design declares). A design whose features have built fewer parts than it declares (skeleton first: the parts not
   written yet) is saved as a partial revision, release blocked, never refused. Each feature has a time budget
   (FEATURE_BUDGET, or @feature(..., budget=s)): past it an alarm stops it, and when it hangs in OCCT's C++ the
   kernel's supervisor (form/worker.py) stops the kernel; either way the feature is written down so the next build
   leaves it out at once, and Studio keeps the features built before it as a partial revision.

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

def feature(label: str = "", role: str = "structure", doc: str = "", parts: int | None = None,
            budget: float | None = None):
    """Mark a method of a FeatureDesign as a feature: `@feature("Eye openings", role="access")`.

    parts: how many separate parts (solids) this feature adds (a lens feature that makes two lenses: parts=2; the
    first feature: how many it makes). When any feature of a design says parts=, the solid count is checked after
    every feature against the running total, and a feature that splits or fuses a part is skipped with the counts.
    budget: seconds this feature may take (default FEATURE_BUDGET); past it the feature is stopped and left out."""
    if parts is not None and (not isinstance(parts, int) or parts < 0):
        raise TypeError("feature(parts=) is a whole number of parts the feature adds (0 or more).")
    if budget is not None and not (isinstance(budget, (int, float)) and budget > 0):
        raise TypeError("feature(budget=) is a number of seconds above 0.")

    def deco(fn):
        fn._form_feature = {"label": label, "role": role, "doc": doc, "parts": parts, "budget": budget}
        return fn
    return deco


class FeatureDesign(Recipe):
    """A design built one feature at a time (see the module docstring)."""

    _form_steps: list = []
    _form_meta: dict = {}

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
        cls._form_meta = {n: dict(f._form_feature) for n, f in own}
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
            reads = _Reads(self._form_values)
            c = (self._form_values, self.setup(reads))
            self._form_ctx = c
            self._form_setup_reads = reads.used()
        t = getattr(self, "_form_tracking", None)
        if t is not None:                    # the running feature reads what setup() read
            t.update(getattr(self, "_form_setup_reads", None) or {"*"})
        return c[1]

    def build(self, v: dict) -> list[Stage]:
        return _build_features(self, v)


# ---- building a FeatureDesign: one feature at a time, each checked, timed and kept --------------------------------

FEATURE_BUDGET = float(os.environ.get("FORM_FEATURE_BUDGET") or 90.0)   # seconds per feature on a quiet machine
GRACE = 10.0          # form/worker.py stops the kernel this long past a feature's budget (a hang in OCCT's C++)
HANG_TTL = 24 * 3600.0   # a hang mark expires after a day (and with any new Form build: hang_path follows build_id)
STRETCH = 1.0         # set per kernel call (form/worker.py): budgets stretch with the call's timeout under load


_DEADLINE: list = []                  # monotonic deadline of the feature being built (form/craft/boolean.py reads it)


def time_left() -> float | None:
    """Seconds left in the budget of the feature being built now, or None outside a feature."""
    return (_DEADLINE[-1] - time.monotonic()) if _DEADLINE else None


class FeatureTimeout(Exception):
    """A feature ran past its budget (raised in the kernel worker by an alarm, between Python steps)."""


class _Reads(dict):
    """The values, recording which keys are read: a feature's checkpoint is keyed on the values it reads only."""

    def __init__(self, d):
        super().__init__(d)
        self._read: set = set()
        self._all = False

    def __getitem__(self, k):
        self._read.add(k)
        return super().__getitem__(k)

    def get(self, k, default=None):
        self._read.add(k)
        return super().get(k, default)

    def __contains__(self, k):
        self._read.add(k)
        return super().__contains__(k)

    def __iter__(self):
        self._all = True
        return super().__iter__()

    def keys(self):
        self._all = True
        return super().keys()

    def items(self):
        self._all = True
        return super().items()

    def values(self):
        self._all = True
        return super().values()

    def copy(self):
        self._all = True
        return dict.copy(self)

    # every other way to look at the values reads them all (conservative: a checkpoint may rebuild, never go stale)
    def setdefault(self, k, default=None):
        self._read.add(k)
        return super().setdefault(k, default)

    def pop(self, k, *default):
        self._read.add(k)
        return super().pop(k, *default)

    def _whole(name):                                        # noqa: N805 (builds methods below)
        base = getattr(dict, name)

        def m(self, *a, **kw):
            self._all = True
            return base(self, *a, **kw)
        m.__name__ = name
        return m

    for _n in ("popitem", "update", "__or__", "__ror__", "__ior__", "__eq__", "__ne__", "__repr__", "__str__",
               "__len__", "__reversed__", "__reduce__", "__reduce_ex__", "__format__", "__getstate__"):
        if hasattr(dict, _n):
            locals()[_n] = _whole(_n)
    del _n, _whole
    __hash__ = None

    def used(self) -> set:
        return {"*"} if self._all else set(self._read)


def _key(idx: str, v: dict, used: set) -> str:
    if "*" in used:
        return _h(idx, "*", v)
    return _h(idx, sorted(((str(k), v.get(k)) for k in used), key=lambda kv: kv[0]))


def _emit(ev: dict) -> None:
    """A progress event for the kernel's caller (form/worker.py reads feature_start / feature_done)."""
    k = sys.modules.get((__package__ or "form") + ".kernel")
    cb = getattr(k, "PROGRESS", None) if k is not None else None
    if cb is not None:
        try:
            cb(ev)
        except Exception:
            pass


def _measure(shape) -> tuple[int, float]:
    if shape is None or not hasattr(shape, "solids"):
        return 0, 0.0
    try:
        return len(shape.solids()), float(shape.volume)
    except Exception:
        return 0, 0.0


def _alarm_on(budget: float, fid: str):
    import signal
    import threading
    if not budget or budget <= 0 or not hasattr(signal, "setitimer") \
            or threading.current_thread() is not threading.main_thread():
        return None

    def ring(_sig, _frame):
        raise FeatureTimeout(fid)
    try:
        old = signal.signal(signal.SIGALRM, ring)
        signal.setitimer(signal.ITIMER_REAL, float(budget))
    except (ValueError, OSError):
        return None
    return (old,)


def _alarm_off(tok) -> None:
    if tok is None:
        return
    import signal
    try:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, tok[0] if tok[0] is not None else signal.SIG_DFL)
    except (ValueError, OSError):
        pass


# the values each feature read (deps), skipped features and hangs: in memory and on disk next to the checkpoints
_deps_mem: dict = {}
_skip_mem: dict = {}


def _jread(f):
    try:
        return json.loads(Path(f).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None


def _jwrite(f, data) -> None:
    try:
        f = Path(f)
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_name(f.name + ".tmp")
        tmp.write_text(json.dumps(data, default=str), encoding="utf-8")
        os.replace(tmp, f)
    except OSError:
        pass


def _deps_get(idx: str) -> list:
    got = _deps_mem.get(idx)
    if got is None:
        d = _dir()
        got = [set(x) for x in (_jread(d / f"{idx}.deps.json") or [])] if d else []
        _deps_mem[idx] = got
    return got


def _deps_add(idx: str, used: set) -> None:
    got = _deps_get(idx)
    if used in got:
        return
    got.insert(0, set(used))
    del got[8:]
    d = _dir()
    if d:
        _jwrite(d / f"{idx}.deps.json", [sorted(map(str, x)) for x in got])


def _skip_get(key: str):
    hit = _skip_mem.get(key)
    if hit is None:
        d = _dir()
        hit = _jread(d / f"{key}.skip.json") if d else None
        if hit is not None:
            _skip_mem[key] = hit
    return hit


def _skip_put(key: str, diag: dict) -> None:
    _skip_mem[key] = diag
    while len(_skip_mem) > MEMORY:
        _skip_mem.pop(next(iter(_skip_mem)))
    d = _dir()
    if d:
        _jwrite(d / f"{key}.skip.json", diag)


def _skip_key(key: str, count) -> str:
    """A skipped feature's record also follows the part count it was checked against (declared `solids`, the count
    expected after it, the parts it adds): raising `solids` must build a feature that failed only on the count."""
    return _h(key, "skip/2", count)


def _lookup(idx: str, v: dict, skips: bool = True, count=None):
    """(key, "body", shape) or (key, "skip", diagnosis) of a feature built before with the same code, upstream and
    values it read (a skip also with the same part count); None when it must be built."""
    for used in _deps_get(idx):
        key = _key(idx, v, used)
        got = checkpoint_get(key)
        if got is not None:
            return key, "body", got
        if skips:
            sk = _skip_get(_skip_key(key, count))
            if sk is not None:
                return key, "skip", sk
    return None


def hang_path(idx: str, v: dict):
    """Where a feature that ran out of time is written down (by the alarm here, or by form/worker.py when it had to
    stop the kernel), so the next build leaves it out at once instead of waiting for it again."""
    d = _dir()
    return d / f"{_h('hang/1', idx, v)}.hung.json" if d else None


def _hang_live(info: dict) -> bool:
    """A hang mark counts for HANG_TTL seconds: a busy machine, since quieter, may well build the feature now."""
    ts = info.get("ts") if isinstance(info, dict) else None
    return isinstance(ts, (int, float)) and time.time() - float(ts) <= HANG_TTL


def _timeout_diag(fid: str, info: dict) -> dict:
    s, b, kind = info.get("s"), info.get("budget"), info.get("kind", "budget")
    s_t = f"{float(s):.1f} s" if isinstance(s, (int, float)) else "an unknown time"
    b_t = f"{float(b):g} s" if isinstance(b, (int, float)) else "its"
    if kind == "crash":
        msg = f"The {fid} feature crashed the geometry kernel after {s_t}"
        cause = "crash"
    elif kind == "kill":
        msg = f"The {fid} feature did not finish: the kernel was stopped after {s_t} (budget {b_t}) and restarted"
        cause = "time"
    else:
        msg = f"The {fid} feature did not finish within its {b_t} budget (stopped after {s_t})"
        cause = "time"
    if info.get("again"):
        msg += "; it was left out without building it again"
    hint = ("Simplify it (fewer instances, a coarser pattern, an analytic shape instead of a loft), split it into two "
            "features, or give it more time with @feature(..., budget=seconds). Changing its code or values builds it "
            "again.")
    return {"feature": fid, "message": msg + ".", "hint": hint,
            "hung": {k: info[k] for k in ("s", "budget", "kind") if k in info},
            "diagnosis": {"summary": msg + ".", "cause": cause, "operation": fid}}


def _build_features(self, v: dict) -> list[Stage]:
    cls = type(self)
    self._form_values = v
    self._form_ctx = None
    self._form_setup_reads = None
    self._form_tracking = None
    for a in ("solids", "assembly"):                # what an earlier, incomplete build of this instance set
        self.__dict__.pop(a, None)
    steps = list(cls._form_steps)
    if not steps:
        raise RecipeError("This FeatureDesign has no features.", "", "Mark each feature method with @feature(...).")
    codes = feature_codes(cls)
    meta = getattr(cls, "_form_meta", {}) or {}
    declared = max(1, int(getattr(cls, "solids", 1) or 1))
    counted = any((meta.get(f) or {}).get("parts") is not None for f in steps)
    mesh = bool(getattr(self, "mesh", False))
    up = _h("featureprog/2", _context_fingerprint(), mesh)
    stages: list[Stage] = []
    body = None
    expect = 0
    rep = _REPORT
    for i, fid in enumerate(steps):
        m = meta.get(fid) or {}
        idx = _h(up, fid, codes.get(fid, ""))
        budget = float(m.get("budget") or FEATURE_BUDGET) * max(1.0, float(STRETCH or 1.0))
        hang = hang_path(idx, v)
        n0, v0 = _measure(body)
        adds = m.get("parts")
        want = (expect + adds) if adds is not None else (expect if i else None)
        _emit({"kind": "feature_start", "feature": fid, "i": i, "of": len(steps), "budget": round(budget, 1),
               "hang_file": str(hang) if hang else ""})
        t0 = time.perf_counter()
        count = (declared, want if counted else None, adds)
        hit = _lookup(idx, v, skips=i > 0, count=count)
        diag = None
        status = "built"
        if hit is not None and hit[1] == "body":
            up, body, status = hit[0], hit[2], "checkpoint"
            stages.append(Stage(fid, body))
        else:
            if hit is not None:
                diag = {**hit[2], "cached": True}
            else:
                old = _jread(hang) if hang else None
                if old and not _hang_live(old):
                    old = None
                    try:
                        Path(hang).unlink(missing_ok=True)
                    except OSError:
                        pass
                if old:
                    diag = _timeout_diag(fid, {**old, "again": True})
            if diag is None:
                reads: set = set()
                self._form_tracking = reads
                tv = _Reads(v)
                err = None
                out = None
                tok = _alarm_on(budget, fid)
                _DEADLINE.append(time.monotonic() + budget)
                try:
                    try:
                        out = getattr(self, fid)(tv, body)
                    finally:
                        _alarm_off(tok)
                        _DEADLINE.pop()
                    if isinstance(out, Stage):
                        out = out.shape
                    if out is None:
                        out = body
                    problem, hint = _problem(out, mesh, i, n0, v0, want if counted else None, declared, adds)
                    if problem:
                        raise RecipeError(f"The {fid} feature {problem}.", fid, hint)
                except FeatureTimeout:
                    info = {"feature": fid, "s": round(time.perf_counter() - t0, 1), "budget": round(budget, 1),
                            "kind": "budget", "ts": time.time()}
                    if hang:
                        _jwrite(hang, info)
                    err = ("timeout", info)
                except Exception as e:
                    if i == 0:                       # nothing to keep: the skeleton itself did not build
                        self._form_tracking = None
                        raise
                    err = ("error", e)
                finally:
                    self._form_tracking = None
                used = reads | tv.used()
                key = _key(idx, v, used)
                if err is None:
                    checkpoint_put(key, out)
                    _deps_add(idx, used)
                    up, body = key, out
                    stages.append(Stage(fid, body))
                elif err[0] == "timeout":
                    diag = _timeout_diag(fid, err[1])
                else:
                    diag = _diagnosis(err[1], self, fid)
                    _skip_put(_skip_key(key, count), diag)
                    _deps_add(idx, used)
            if diag is not None:
                if i == 0:
                    raise RecipeError(diag["message"], fid, diag.get("hint", ""))
                rep["skipped"].append(diag)
                status = "skipped"
        n1, v1 = _measure(body)
        if status != "skipped":
            expect = want if (counted and want is not None) else n1
        e = {"feature": fid, "status": status, "s": round(time.perf_counter() - t0, 3), "solids": n1,
             "dvol": round(v1 - v0, 3) if status != "skipped" else 0.0}
        if diag is not None and diag.get("cached"):
            e["cached"] = True
        if diag is not None and diag.get("hung"):
            e["hung"] = diag["hung"]
        if status == "built" and i and abs(v1 - v0) <= 1e-6 * max(1.0, abs(v0)):
            e["unchanged"] = True                    # a boolean that silently did nothing looks like this
        rep["log"].append(e)
        _emit({"kind": "feature_done", "feature": fid, "i": i, "status": status, "s": e["s"], "solids": n1})
    final, _vol = _measure(body)
    exp = expect if counted else (final if final < declared else declared)
    if exp < declared:                               # skeleton first: parts not written yet are not missing parts
        rep["parts"] = {"built": int(exp), "declared": declared}
        self.solids = int(exp)
        self.assembly = lambda _v: None
    return stages


def _problem(out, mesh: bool, i: int = 1, n0: int = 0, v0: float = 0.0, want: int | None = None,
             declared: int = 1, adds: int | None = None) -> tuple[str, str]:
    """(what is wrong with a feature's result, a hint for that measured cause), or ("", "")."""
    if not hasattr(out, "solids"):
        return (f"returned {type(out).__name__}, not a solid",
                "Return the body after the feature (a build123d Part or Solid); the first feature returns the "
                "skeleton itself.")
    try:
        n = len(out.solids())
        vol = float(out.volume)
    except Exception as e:
        return (f"returned a shape that cannot be measured ({type(e).__name__})",
                "Return a closed solid: a Compound of faces or an open shell has no volume.")
    if n == 0 or vol <= 1e-9:
        if i == 0:
            return ("made no solid", "Check that the skeleton's profile is closed and that its extrude, revolve or "
                    "loft has a non-zero length.")
        return ("left no solid (a boolean failed and returned nothing)",
                "Overlap the operands of its boolean by a few tenths of a millimetre instead of touching, or use "
                "craft.safe_union / craft.safe_cut, which repair and measure the gap.")
    if not mesh:
        try:
            bad = not out.is_valid
        except Exception:
            bad = False
        if bad:
            if i == 0:
                return ("made a solid that is not valid (OCCT's check fails)",
                        "A loft or sweep folds over itself or a section crosses itself; craft.inspect(body) names "
                        "the fault, and craft.safe_loft re-seams the sections.")
            return ("returned a solid that is not valid (a boolean or a loft failed part-way)",
                    "craft.inspect(body) names the fault. Use craft.safe_union / craft.safe_cut, or move the tool "
                    "off a seam or a tangent face.")
    if want is not None and n != want:
        if n < want:
            hint = ("Two parts touched or overlapped and fused: keep separate parts apart with craft.parts(..., "
                    "clearance=) instead of a fuse.")
        else:
            hint = ("A cut split a part in two, or a new piece does not reach the body it should join. A feature that "
                    "adds parts says how many with @feature(..., parts=N).")
        return f"left {n} solid(s) where {want} are expected ({n0} before it; it adds {adds or 0} part(s))", hint
    if n > declared:
        return (f"left {n} solids; the design declares {declared}",
                "A cut split the body, or a new piece does not reach the body it should join. If the design has more "
                "parts, raise solids and say how many each feature adds with @feature(..., parts=N).")
    if i and v0 > 0 and vol < 0.01 * v0:
        return (f"left {100 * vol / v0:.2f} % of the volume before it ({vol:.0f} of {v0:.0f} mm³)",
                "A cut removed nearly the whole body: check that its tool is the region to remove, not a box "
                "around the body.")
    return "", ""


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
    _REPORT.pop("parts", None)


def report() -> dict:
    out = {"log": list(_REPORT["log"]), "skipped": list(_REPORT["skipped"])}
    if _REPORT.get("parts"):
        out["parts"] = dict(_REPORT["parts"])
    return out


# ---- code of a FeatureDesign: per feature, and what they share -----------------------------------------------------

_codes: dict = {}
_BLOCK = re.compile(r"^# ---- Form Studio: .*?^# ---- end of [^\n]*$", re.S | re.M)


def _class_source(cls) -> tuple[tuple, str]:
    """(a cache key that changes with the file, the text of the file) a FeatureDesign class was compiled from."""
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
    if ("text", ck) in _codes:
        return ck, _codes[("text", ck)]
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
    _codes[("text", ck)] = text
    return ck, text


def code_map(cls) -> tuple[dict, str]:
    """({feature id: its method's code}, the rest of the file) for a FeatureDesign class. Form Studio's own blocks
    (text, standard features, partial build) are left out of the shared code: they act after the features."""
    ck, text = _class_source(cls)
    if ("map", ck) in _codes:
        return _codes[("map", ck)]
    spans = method_spans(text, cls.__name__) if text else {}
    lines = text.splitlines()
    codes = {n: textwrap.dedent("\n".join(lines[a - 1:b])).strip() for n, (a, b) in spans.items()}
    keep = [ln for i, ln in enumerate(lines, 1) if not any(a <= i <= b for a, b in spans.values())]
    shared = _BLOCK.sub("", "\n".join(keep))
    shared = "\n".join(ln.rstrip() for ln in shared.splitlines() if ln.strip())
    _codes[("map", ck)] = (codes, shared)
    return codes, shared


def _binds(n) -> list | None:
    """The names a top-level (or class-level) statement binds; None for one that cannot be read that way (a star
    import, an if or a loop at top level): such a statement is part of every feature's key."""
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return [n.name]
    if isinstance(n, ast.Import):
        return [a.asname or a.name.split(".")[0] for a in n.names]
    if isinstance(n, ast.ImportFrom):
        if any(a.name == "*" for a in n.names):
            return None
        return [a.asname or a.name for a in n.names]
    targets = n.targets if isinstance(n, ast.Assign) else [n.target] if isinstance(n, (ast.AnnAssign, ast.AugAssign)) \
        else None
    if targets is None:
        return None
    out = []
    for t in targets:
        for x in ast.walk(t):
            if isinstance(x, ast.Name):
                out.append(x.id)
    return out


def _is_self(x) -> bool:
    """self, cls, type(self) or self.__class__: an expression whose attributes are the design class's members."""
    if isinstance(x, ast.Name):
        return x.id in ("self", "cls")
    if isinstance(x, ast.Call) and isinstance(x.func, ast.Name) and x.func.id == "type" and len(x.args) == 1:
        return _is_self(x.args[0])
    if isinstance(x, ast.Attribute) and x.attr == "__class__":
        return _is_self(x.value)
    return False


def _refs(n) -> tuple[set, set]:
    """(names, members of the class) a statement reads. Members are read through self, cls, type(self) or
    self.__class__, or by getattr with a constant name; any other use of self (passed to a function, getattr with a
    computed name, vars(self)) may read any member: "*"."""
    names, attrs = set(), set()
    owned = set()                                     # self Names whose attribute is read (accounted for)
    for x in ast.walk(n):
        if isinstance(x, ast.Attribute) and _is_self(x.value):
            attrs.add(x.attr)
            for y in ast.walk(x.value):
                owned.add(id(y))
        elif isinstance(x, ast.Call) and isinstance(x.func, ast.Name) and x.func.id in ("getattr", "hasattr") \
                and x.args and _is_self(x.args[0]):
            if len(x.args) > 1 and isinstance(x.args[1], ast.Constant) and isinstance(x.args[1].value, str):
                attrs.add(x.args[1].value)
            else:
                attrs.add("*")
            for y in ast.walk(x.args[0]):
                owned.add(id(y))
    for x in ast.walk(n):
        if isinstance(x, ast.Name):
            names.add(x.id)
            if x.id in ("self", "cls") and id(x) not in owned and isinstance(x.ctx, ast.Load):
                attrs.add("*")
    return names, attrs


def feature_codes(cls) -> dict:
    """{feature id: the code its checkpoint is keyed on}: the feature's own method plus only what it uses from the
    rest of the file (module-level helpers, imports and constants, methods and attributes of the class it reads
    through self, setup() when it reads self.ctx), followed transitively. So a change to `solids`, to a parameter
    list, to another feature or to a helper it does not call leaves its checkpoint valid. Statements that cannot be
    attributed (a star import, an if at top level) are part of every feature's key."""
    ck, text = _class_source(cls)
    if ("deps", ck) in _codes:
        return _codes[("deps", ck)]
    out: dict = {}
    clean = _BLOCK.sub("", text) if text else ""
    try:
        tree = ast.parse(clean) if clean else None
    except SyntaxError:
        tree = None
    c = _feature_class(tree, cls.__name__) if tree is not None else None
    if c is None:
        codes, shared = code_map(cls)
        out = {k: code + "\n# shared\n" + shared for k, code in codes.items()}
        _codes[("deps", ck)] = out
        return out

    def seg(n) -> str:
        return textwrap.dedent(ast.get_source_segment(clean, n) or ast.dump(n)).strip()
    mod: dict = {}
    always: list = []
    for n in tree.body:
        if n is c or (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)):
            continue
        names = _binds(n)
        if names is None:
            always.append(n)
        for nm in names or []:
            mod.setdefault(nm, []).append(n)
    mem: dict = {}
    feats: dict = {}
    for n in c.body:
        if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant):
            continue
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_feature(n):
            feats.setdefault(n.name, []).append(n)
            continue
        for nm in _binds(n) or []:
            mem.setdefault(nm, []).append(n)
    # bases defined in this file (mixins): their members are the class's members too, read through self
    todo = [b for b in c.bases]
    seen_bases: set = set()
    while todo:
        b = _base_name(todo.pop())
        if not b or b in seen_bases:
            continue
        seen_bases.add(b)
        for bn in mod.get(b, []):
            if not isinstance(bn, ast.ClassDef):
                continue
            todo += list(bn.bases)
            for n in bn.body:
                if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant):
                    continue
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_feature(n):
                    continue
                for nm in _binds(n) or []:
                    mem.setdefault(nm, []).insert(0, n)     # the subclass's own definition stays last
    lines = clean.splitlines()
    base = "\n".join(seg(n) for n in always)
    for fid, nodes in feats.items():
        own = nodes[-1]
        a = min([d.lineno for d in own.decorator_list] + [own.lineno])
        own_code = textwrap.dedent("\n".join(lines[a - 1:own.end_lineno])).strip()
        seen = {id(own)}
        deps = []
        work = [own]
        while work:
            n = work.pop()
            names, attrs = _refs(n)
            nxt = [x for nm in names for x in mod.get(nm, [])]
            if cls.__name__ in names:                 # the class by name: everything it holds may matter
                nxt += [x for xs in mem.values() for x in xs]
            if "*" in attrs:                         # self used in a way that may read any member
                nxt += [x for xs in mem.values() for x in xs] + [x for xs in feats.values() for x in xs]
            for at in attrs:
                at = "setup" if at == "ctx" else at
                nxt += mem.get(at, []) + feats.get(at, [])
            for x in nxt:
                if id(x) not in seen:
                    seen.add(id(x))
                    deps.append(x)
                    work.append(x)
        out[fid] = own_code + "\n# uses\n" + "\n".join(sorted(seg(x) for x in deps)) + "\n# always\n" + base
    _codes[("deps", ck)] = out
    return out


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
    out.append(build_id())
    return _h(out)


CRAFT_REV = 1        # bump on any change to how form/craft or this module builds a solid (a fix must reach old checkpoints)
_BUILD_ID = None


def build_id() -> str:
    """This Form build: its version, CRAFT_REV and a hash of the code that shapes solids (form/craft and this module).
    A checkpoint, skip record or hang mark made by another build is never reused, so a fix in a new app version
    reaches designs that were checkpointed before it."""
    global _BUILD_ID
    if _BUILD_ID is not None:
        return _BUILD_ID
    try:
        from . import __version__ as ver
    except Exception:
        ver = "?"
    h = hashlib.sha1()
    import importlib.util
    import marshal
    pkg = __package__ or "form"
    names = [f"{pkg}.featureprog"]
    try:
        import pkgutil
        from . import craft
        names += sorted(f"{pkg}.craft.{m.name}" for m in pkgutil.iter_modules(craft.__path__))
        names.append(f"{pkg}.craft")
    except Exception:
        pass
    for n in names:
        h.update(n.encode())
        try:
            spec = importlib.util.find_spec(n)
            origin = getattr(spec, "origin", None) if spec else None
            if origin and os.path.isfile(origin) and origin.endswith(".py"):
                h.update(Path(origin).read_bytes())
            elif spec is not None and spec.loader is not None and hasattr(spec.loader, "get_code"):
                code = spec.loader.get_code(n)                    # a frozen app: no sources, the compiled code
                h.update(marshal.dumps(code) if code is not None else b"")
        except Exception:
            h.update(b"?")
    _BUILD_ID = f"{ver}/{CRAFT_REV}/{h.hexdigest()[:12]}"
    return _BUILD_ID


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
        _restore_names(shape, meta)
        os.utime(f)
    except Exception:
        return None
    _remember(key, shape)
    return shape


def _names(shape) -> dict:
    """What a B-rep file does not keep: the shape's label and, for craft.parts(), the part names and measured gaps."""
    out = {}
    for k in ("label", "part_names", "part_gaps"):
        val = getattr(shape, k, None)
        if val:
            out[k] = val
    return out


def _restore_names(shape, meta: dict) -> None:
    for k in ("label", "part_names", "part_gaps"):
        if meta.get(k):
            try:
                setattr(shape, k, meta[k])
            except Exception:
                pass
    names = meta.get("part_names")
    if names:
        try:
            for sol, n in zip(shape.solids(), names):
                sol.label = n
        except Exception:
            pass


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
            (d / f"{key}.json").write_text(json.dumps({"type": type(shape).__name__, "ts": time.time(),
                                                       **_names(shape)}, default=str), encoding="utf-8")
            os.replace(tmp, d / f"{key}.bin")
        prune(d)
    except Exception:
        pass


def prune(d: Path | None = None) -> None:
    """Keep the checkpoint folder bounded: at most DISK_MAX checkpoints (*.bin with its *.json, oldest go first) and
    at most DISK_MAX of each record kept next to them (*.skip.json, *.hung.json, *.deps.json); expired hang marks go
    at once."""
    d = d or _dir()
    if d is None or not d.is_dir():
        return

    def mtime(x):
        try:
            return x.stat().st_mtime
        except OSError:
            return 0.0
    files = sorted(d.glob("*.bin"), key=mtime)
    for old in files[:max(0, len(files) - DISK_MAX)]:
        old.unlink(missing_ok=True)
        old.with_suffix(".json").unlink(missing_ok=True)
    now = time.time()
    for pat in ("*.skip.json", "*.hung.json", "*.deps.json"):
        recs = sorted(d.glob(pat), key=mtime)
        for i, old in enumerate(recs):
            if i < len(recs) - DISK_MAX:
                old.unlink(missing_ok=True)
            elif pat == "*.hung.json" and now - mtime(old) > HANG_TTL:
                old.unlink(missing_ok=True)


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
                        stages={stages!r}, valid={valid!r}{extra})
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
                   valid: bool = True, upto: int | None = None, why: str = "failed") -> str:
    """upto (a FeatureDesign): build only its first `upto` features (they load from their checkpoints); the ones
    after it are left out. why: what happened to `failed` ("failed", or "did not finish" for a hang)."""
    base = strip_partial(source)
    failed_text = f"the next one, {failed}, {why}." if failed else "the result failed the final check."
    return base.rstrip() + "\n" + P_TEMPLATE.format(start=P_START, end=P_END, cls=_class_name(base), keep=int(keep),
                                                    solids=int(solids), origin=origin, failed=failed or "",
                                                    stages=list(features[:keep]), valid=bool(valid),
                                                    built=", ".join(features[:keep]) or "none", failed_text=failed_text,
                                                    extra=f", upto={int(upto)}" if upto is not None else "")


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
            valid: bool = True, upto: int | None = None):
    """The design class, changed to build only its first `keep` stages (used by the partial-build block). upto: a
    FeatureDesign builds its first `upto` features as usual (each from its checkpoint) and leaves out the rest."""
    build = cls.build
    declared_solids = getattr(cls, "solids", 1)
    if upto is not None and getattr(cls, "_form_steps", None):
        cls._form_steps = list(cls._form_steps)[:max(1, int(upto))]
        cls.solids = int(solids)
        cls.partial = {"keep": int(keep), "failed": failed, "origin": origin, "upto": int(upto)}
        if int(solids) != int(declared_solids):
            cls.assembly = lambda self, v: None
        if not valid:
            cls.allow_invalid = True
        return cls

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
