"""Design refinement: named, reversible features added after the functional build, kept only when the function
checks still hold. This module is the operator interface; the search lives in form/refine/engine.py, the measures in
form/refine/analyze.py, the style tables in form/refine/styles.py and the local learning record in
form/refine/ledger.py.

How it fits together

    analysis = analyze.analyze(measurement)          # Analysis: deficits {key: 0..1}, raw measures, total
    for op in candidates ranked by deficit x style weight x ledger prior:
        ok = op.preconditions(design, analysis)      # can it run on this design at all?
        patch = op.apply(design, analysis, params)   # one feature method as source code (or a source edit)
    the engine inserts each patch as @feature(label, role="refine", doc=reason + delta), builds the candidates in
    parallel (form/candidates.run), measures them again, and keeps a candidate only when every hard gate holds:
    the function checks are not worse, the frozen features' faces are identical, the walls stay above the minimum
    and, for game assets, the validator and the triangle budgets pass.

Writing an operator (form/refine/ops_cad.py, form/refine/ops_cage.py)

    from form.refine import Operator, Patch

    class EdgeBreak(Operator):
        name = "edge_break"                       # unique, lower_snake; the feature id becomes refine_edge_break
        domain = "cad"                            # "cad" (build123d solids), "cage" (subdivision cages), "material"
        targets = ("edge_hierarchy", "touch_points")   # deficit keys (DEFICITS) this operator is meant to lower
        cost = 0.5                                # complexity it adds (0.25 a small break .. 3 a whole kit of parts)
        label = "Edge break"
        params = {"r": 0.3}                       # defaults; a style (styles.py) may override them

        def preconditions(self, design, analysis):
            if design.purpose == "game":
                return False, "a CAD fillet has no meaning on a cage"
            return analysis.deficits.get("edge_hierarchy", 0) > 0.2, "edges already have a hierarchy"

        def apply(self, design, analysis, params):
            boxes = design.frozen_boxes_literal()          # frozen features' bounding boxes, as source text
            return Patch(
                code=f'''
    def edge_break(self, v, body):
        from form import craft
        from form.refine import frozen_boxes, keep_clear
        edges = keep_clear(body.edges(), frozen_boxes(self, {boxes}), margin=0.5)
        return craft.safe_fillet(body, edges, {params["r"]!r})
    ''',
                reason=f"Break the remaining sharp edges with a {params['r']} mm radius so they catch light.")

The contract

  * name, domain, targets, cost, label and params are class attributes. targets name keys of DEFICITS.
  * preconditions(design, analysis) returns True / False, or (bool, why). It must be cheap and never build.
  * apply(design, analysis, params) returns a Patch, a plain string of code (one method), or None (nothing to do).
    The method must take (self, v, body) and return the body after the feature; its name does not matter (the engine
    renames it to the feature id it chooses). Leave out the @feature decorator: the engine writes it with
    role="refine" and doc = the patch's reason plus the measured change.
  * Frozen geometry: features whose role is in FROZEN_ROLES (fit, access, mechanism, interface) and the faces they
    made must not change. design.frozen lists their ids and design.frozen_boxes their bounding boxes; keep_clear()
    drops edges and faces whose centre lies in one of those boxes. frozen_boxes(self, literal) gives the boxes
    measured in the build itself (they follow a parameter change), the literal when the build has none. The engine does not trust the operator: a
    candidate whose frozen faces moved (area, face count or bounding box) is rejected whatever its score.
  * An operator never reads files, the network or the clock, and never imports OCCT at module level: the module is
    imported by the engine, which runs without a kernel. The code it returns runs in the kernel worker.
  * Determinism: the same design and analysis give the same patch.
  * A "material" operator changes no geometry: it returns Patch(edit=callable) that takes the source and returns
    the source with new appearance() zones (or materials() for a game asset).

Registration: a module exposes OPERATORS = [EdgeBreak(), ...]; operators() collects form.refine.ops_cad,
form.refine.ops_cage and form.refine.ops_material when they exist, plus anything passed to register().
"""
from __future__ import annotations

import ast
import importlib
import re
from dataclasses import dataclass, field
from typing import Any, Callable

API_VERSION = 1
FROZEN_ROLES = ("fit", "access", "mechanism", "interface")
REFINE_ROLE = "refine"
DOMAINS = ("cad", "cage", "material")

# the deficit vector: every key is 0 (nothing to improve) .. 1 (as bad as it gets); see form/refine/analyze.py
DEFICITS = (
    "silhouette",          # the outline at 64 px from six views is convex (a blob) or shredded
    "interior_read",       # too few value regions of 12 px or more inside the outline of a small lit render
    "proportion",          # bounding ratios far from a classic ratio
    "balance",             # projected centre of area outside or near the edge of the support, and mirror mismatch
    "detail_scales",       # fewer than three bands of feature size (primary, secondary, tertiary)
    "edge_hierarchy",      # fewer than three radius tiers, many sharp creases
    "surface_breaks",      # one unbroken face takes a large share of the surface
    "material_zones",      # one or two materials
    "material_contrast",   # value contrast between the zones under 0.15
    "wear",                # (game) worn share on convex edges outside 2-12 %
    "touch_points",        # sharp edges where the hand goes
    "fairness",            # (game cage) the shell's curvature is lumpy: it wobbles against its own smooth trend
)


@dataclass
class Design:
    """What an operator may read about the design it refines. Plain data: no kernel objects."""
    source: str
    purpose: str = "model"                       # "print" | "model" | "game"
    values: dict = field(default_factory=dict)
    brief: str = ""
    product_class: str | None = None
    style: str = "clean_consumer"
    features: dict = field(default_factory=dict)         # {feature id: {"role", "label", "doc"}} in build order
    frozen_boxes: dict = field(default_factory=dict)     # {frozen feature id: ((x0, y0, z0), (x1, y1, z1))}
    bbox: tuple | None = None                            # ((x0, y0, z0), (x1, y1, z1)) of the whole design
    checks: dict = field(default_factory=dict)           # {check id: status} of the base build (form/checks.py)

    @property
    def feature_ids(self) -> list[str]:
        return list(self.features)

    @property
    def frozen(self) -> set:
        return {k for k, f in self.features.items() if f.get("role") in FROZEN_ROLES}

    @property
    def refined(self) -> list[str]:
        """Features the refinement already added (role="refine"), in order."""
        return [k for k, f in self.features.items() if f.get("role") == REFINE_ROLE]

    def has_check(self, *prefixes: str, status: str | None = "PASS") -> bool:
        """True when the base build has a check whose id starts with one of prefixes (with that status)."""
        return any(k.startswith(prefixes) and (status is None or v == status) for k, v in (self.checks or {}).items())

    def frozen_boxes_literal(self) -> str:
        """The frozen boxes as a Python literal to paste into generated code."""
        return repr([tuple(tuple(round(float(c), 4) for c in corner) for corner in box)
                     for _k, box in sorted(self.frozen_boxes.items())])

    def size(self) -> tuple[float, float, float] | None:
        if not self.bbox:
            return None
        (a, b, c), (d, e, f) = self.bbox
        return d - a, e - b, f - c

    @classmethod
    def from_source(cls, source: str, **kw) -> "Design":
        return cls(source=source, features=parse_features(source), **kw)


@dataclass
class Analysis:
    """The deficit vector of one built design (form/refine/analyze.py)."""
    deficits: dict                                 # {key of DEFICITS: 0..1}, only the applicable keys
    measures: dict = field(default_factory=dict)   # the raw numbers each deficit was computed from
    weights: dict = field(default_factory=dict)    # the weight each deficit had in total
    total: float = 0.0                             # weighted mean of the deficits (the search objective)

    def worst(self, n: int = 3) -> list[tuple[str, float]]:
        return sorted(self.deficits.items(), key=lambda kv: (-kv[1], kv[0]))[:n]


@dataclass
class Patch:
    """One refinement step an operator proposes."""
    code: str = ""                                 # one method `def anything(self, v, body): ...` (no decorator)
    reason: str = ""                               # why, in one sentence (it becomes the feature's doc)
    label: str = ""                                # the feature's label; default the operator's label
    after: str = ""                                # insert after this feature (default: the last one)
    edit: Callable[[str], str] | None = None       # instead of code: source -> source (material operators)
    params: dict = field(default_factory=dict)     # the parameters it used (recorded with the result)


class Operator:
    """Base class of a refinement operator (see the module docstring for the contract)."""
    name: str = ""
    domain: str = "cad"
    targets: tuple = ()
    cost: float = 1.0
    label: str = ""
    params: dict = {}

    def preconditions(self, design: Design, analysis: Analysis):
        return True

    def apply(self, design: Design, analysis: Analysis, params: dict) -> Patch | str | None:
        raise NotImplementedError

    # helpers the engine uses
    def check(self, design: Design, analysis: Analysis) -> tuple[bool, str]:
        try:
            r = self.preconditions(design, analysis)
        except Exception as e:                                    # noqa: BLE001 - a broken operator is skipped
            return False, f"preconditions raised {type(e).__name__}: {e}"[:200]
        if isinstance(r, tuple):
            return bool(r[0]), str(r[1] if len(r) > 1 else "")
        return bool(r), ""

    def __repr__(self) -> str:
        return f"<Operator {self.name} ({self.domain})>"


def frozen_boxes(design_self, fallback=()) -> list:
    """The frozen features' boxes measured in this build (form/featureprog.made_box: the faces each fit, access,
    mechanism or interface feature made, so they follow a parameter change), else `fallback` (the boxes measured when
    the refine feature was written). Generated refine code calls it: frozen_boxes(self, [((x0, y0, z0), ...)])."""
    got = getattr(design_self, "_form_frozen_boxes", None) or {}
    if got and len(got) >= len(fallback or ()):
        return [got[k] for k in sorted(got)]
    return list(fallback or ())


def keep_clear(items, boxes, margin: float = 0.5) -> list:
    """The edges or faces of `items` whose centre lies outside every box (boxes: [((x0, y0, z0), (x1, y1, z1))],
    each grown by margin mm). Generated refine code calls it so it never touches a frozen feature."""
    out = []
    for it in items:
        c = it.center()
        p = (float(c.X), float(c.Y), float(c.Z))
        inside = False
        for lo, hi in boxes or ():
            if all(lo[i] - margin <= p[i] <= hi[i] + margin for i in range(3)):
                inside = True
                break
        if not inside:
            out.append(it)
    return out


# ---- reading features from a source ----------------------------------------------------------------------------

def _const(n) -> Any:
    try:
        return ast.literal_eval(n)
    except Exception:                                            # noqa: BLE001 - not a literal
        return None


def parse_features(source: str) -> dict:
    """{feature id: {"role", "label", "doc"}} of a FeatureDesign source, in build order (empty when it is not one).
    Read with ast, so nothing is imported or built."""
    try:
        tree = ast.parse(source or "")
    except SyntaxError:
        return {}
    classes = [n for n in tree.body if isinstance(n, ast.ClassDef)
               and any((b.id if isinstance(b, ast.Name) else getattr(b, "attr", "")) == "FeatureDesign" for b in n.bases)]
    if not classes:
        return {}
    out = {}
    declared = declared_features(classes[-1])
    for n in classes[-1].body:
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for d in n.decorator_list:
            target = d.func if isinstance(d, ast.Call) else d
            nm = target.id if isinstance(target, ast.Name) else getattr(target, "attr", "")
            if nm != "feature":
                continue
            meta = {"role": "structure", "label": "", "doc": ""}
            stages = False
            if isinstance(d, ast.Call):
                if d.args:
                    meta["label"] = _const(d.args[0]) or ""
                for kw in d.keywords:
                    if kw.arg in ("role", "label", "doc"):
                        meta[kw.arg] = _const(kw.value) or meta[kw.arg]
                    if kw.arg == "stages":
                        stages = bool(_const(kw.value))
            if stages:                                  # a wrapped Recipe (form/refine/adapter.py): its own features
                for k, f in declared.items():
                    out.setdefault(k, {**f, "stage_of": n.name})
            else:
                out[n.name] = meta
            break
    return out


def declared_features(cls: ast.ClassDef) -> dict:
    """{id: {"role", "label", "doc"}} of a class's literal `features = [Feature("id", "Label", "role"), ...]`."""
    out = {}
    for s in cls.body:
        if not (isinstance(s, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "features" for t in s.targets)
                and isinstance(s.value, (ast.List, ast.Tuple))):
            continue
        for e in s.value.elts:
            if not (isinstance(e, ast.Call) and (getattr(e.func, "id", "") or getattr(e.func, "attr", "")) == "Feature"):
                continue
            args = [_const(a) for a in e.args]
            kw = {k.arg: _const(k.value) for k in e.keywords if k.arg}
            fid = args[0] if args else kw.get("id")
            if isinstance(fid, str):
                out[fid] = {"label": (args[1] if len(args) > 1 else kw.get("label")) or fid,
                            "role": (args[2] if len(args) > 2 else kw.get("role")) or "structure",
                            "doc": (args[3] if len(args) > 3 else kw.get("doc")) or ""}
    return out


_DEF = re.compile(r"^(\s*)def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", re.M)


def rename_method(code: str, fid: str) -> str:
    """The method's code with its def renamed to fid (the first def only)."""
    return _DEF.sub(lambda m: f"{m.group(1)}def {fid}(", code, count=1)


# ---- registry -----------------------------------------------------------------------------------------------------

_EXTRA: list = []
MODULES = ("form.refine.ops_cad", "form.refine.ops_cage", "form.refine.ops_form", "form.refine.ops_material")


def register(*ops: Operator) -> None:
    """Add operators (tests, plugins) to the ones the modules declare."""
    for op in ops:
        if not isinstance(op, Operator) or not op.name:
            raise TypeError("register() takes Operator instances with a name.")
        _EXTRA[:] = [o for o in _EXTRA if o.name != op.name] + [op]


def unregister(name: str | None = None) -> None:
    _EXTRA[:] = [] if name is None else [o for o in _EXTRA if o.name != name]


def operators(domain: str | None = None) -> list[Operator]:
    """Every known operator (module OPERATORS lists, then registered ones), one per name, filtered by domain."""
    found: dict = {}
    for mod in MODULES:
        try:
            m = importlib.import_module(mod)
        except ImportError:
            continue
        for op in getattr(m, "OPERATORS", []) or []:
            if isinstance(op, Operator) and op.name:
                found.setdefault(op.name, op)
    for op in _EXTRA:
        found[op.name] = op
    return [o for o in found.values() if domain is None or o.domain == domain]


# ---- the example operator (also the smallest working one) -------------------------------------------------------

class ExampleEdgeBreak(Operator):
    """Breaks the sharp edges that are left with a small radius, keeping clear of frozen features. An example of
    the contract; the real CAD operators live in form/refine/ops_cad.py."""
    name = "example_edge_break"
    domain = "cad"
    targets = ("edge_hierarchy", "touch_points")
    cost = 0.5
    label = "Edge break"
    params = {"r": 0.3}

    def preconditions(self, design, analysis):
        if design.purpose == "game":
            return False, "a CAD fillet has no meaning on a cage"
        if analysis.deficits.get("edge_hierarchy", 0.0) <= 0.2:
            return False, "the edges already have a hierarchy"
        return True, ""

    def apply(self, design, analysis, params):
        r = float(params.get("r", 0.3))
        return Patch(code=(
            "def edge_break(self, v, body):\n"
            "    from form import craft\n"
            "    from form.refine import frozen_boxes, keep_clear\n"
            f"    edges = keep_clear(body.edges(), frozen_boxes(self, {design.frozen_boxes_literal()}), margin=0.5)\n"
            f"    return craft.safe_fillet(body, edges, {r!r}, min_fraction=0.5)\n"),
            reason=f"Break the remaining sharp edges with a {r:g} mm radius so they catch light.", params={"r": r})


__all__ = ["API_VERSION", "Analysis", "DEFICITS", "DOMAINS", "Design", "ExampleEdgeBreak", "FROZEN_ROLES",
           "Operator", "Patch", "REFINE_ROLE", "frozen_boxes", "keep_clear", "operators", "parse_features", "register",
           "rename_method", "unregister"]
