"""Material operators for the refinement engine: they change how a design looks, never its geometry.

  material_zones   zone assignment by region: features (CAD appearance()) or cage regions (game materials()) that no
                   zone names are grouped by what they are (the main body, trims and grips, the functional parts:
                   fit, access, mechanism, interface) and each group takes the style's look for it.
  contrast_pair    the lightest and darkest zone pushed apart (in linear light, keeping their hue) until their
                   luminance differs by min_contrast (0.15 by default), so the zones read as different materials.
  edge_wear        (game) the materials' wear moved toward the 2-12 % worn-surface band the bake measured: raised
                   to amount when too little of the surface wears, lowered when too much does.

Each returns Patch(edit=source -> source). The source is read and written with ast and a literal, never run:
appearance() becomes `return [ {...}, ... ]`, materials() `return {...}` (form/game/materials.source_method).
Colours are art choices per style, not material data.
"""
from __future__ import annotations

import ast
import pprint

from . import FROZEN_ROLES, Operator, Patch

# per style: the look of each group. CAD: (finish, colour); game: (kind, tint)
CAD_LOOKS = {
    "clean_consumer": {"body": ("matte", "#e9e6df"), "accent": ("rubber", "#2a2c2f"), "function": ("silk", "#8d949b")},
    "rugged_tool": {"body": ("matte", "#d9a21b"), "accent": ("rubber", "#1e1f21"), "function": ("metal", "#9aa0a6")},
    "scifi_hard_surface": {"body": ("matte", "#c9ccd0"), "accent": ("gloss", "#2d3238"),
                           "function": ("metal", "#6f7780")},
    "stylised_fantasy": {"body": ("matte", "#7a4a2a"), "accent": ("metal", "#c9982f"), "function": ("matte", "#3a3633")},
    "organic": {"body": ("matte", "#d8cfc0"), "accent": ("matte", "#5f6e4f"), "function": ("silk", "#4a4038")},
}
GAME_LOOKS = {
    "clean_consumer": {"body": ("plastic", "#d9d6cf"), "accent": ("rubber", "#2a2c2f"),
                       "function": ("brushed_metal", "#a9aeb4")},
    "rugged_tool": {"body": ("painted_metal", "#c9961c"), "accent": ("rubber", "#1e1f21"),
                    "function": ("bare_metal", "#8d9196")},
    "scifi_hard_surface": {"body": ("painted_metal", "#b9bdc2"), "accent": ("painted_metal", "#2d3238"),
                           "function": ("emissive", "#7fd6ff")},
    "stylised_fantasy": {"body": ("wood", "#8a5a32"), "accent": ("bare_metal", "#3e3c3a"),
                         "function": ("bare_metal", "#c9982f")},
    "organic": {"body": ("leather", "#5a3622"), "accent": ("fabric", "#6b5b45"), "function": ("bare_metal", "#8d9196")},
}
ACCENT_ROLES = {"finish", "detail", "refine", "texture", "grip", "trim", "decor", "decoration", "accent"}
ACCENT_WORDS = ("trim", "grip", "band", "strap", "button", "pad", "rim", "edge", "accent", "stripe", "handle", "visor",
                "tread", "tire", "tyre", "knob", "inlay", "rivet", "bolt", "emblem")
FUNCTION_WORDS = ("hinge", "latch", "lock", "clip", "screw", "port", "socket", "lens", "light", "lamp", "glow",
                  "mount", "axle", "hub", "plug")
NO_WEAR = ("emissive",)


# ---- colour ---------------------------------------------------------------------------------------------------------

def _lin(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _srgb(c: float) -> float:
    c = min(max(c, 0.0), 1.0)
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def _rgb(hexcol: str) -> list[float]:
    s = hexcol.lstrip("#")
    return [_lin(int(s[i:i + 2], 16) / 255) for i in (0, 2, 4)]


def _hex(rgb) -> str:
    return "#" + "".join(f"{round(_srgb(c) * 255):02x}" for c in rgb)


def lum(hexcol: str) -> float:
    r, g, b = _rgb(hexcol)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _with_lum(hexcol: str, target: float) -> str:
    """The colour scaled in linear light to luminance target (as near as the 0..1 range allows), hue kept; past
    white it blends toward white."""
    rgb = _rgb(hexcol)
    L = lum(hexcol)
    target = min(max(target, 0.0), 1.0)
    if L <= 1e-6:
        return _hex([target] * 3)
    k = target / L
    out = [c * k for c in rgb]
    if max(out) > 1.0:                                    # cannot scale further: mix toward white
        out = [min(c, 1.0) for c in out]
        cur = 0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2]
        if cur < target and cur < 1.0:
            t = (target - cur) / (1.0 - cur)
            out = [c + (1.0 - c) * t for c in out]
    return _hex(out)


def push_apart(hexes: dict, min_contrast: float) -> dict:
    """{key: colour} with the darkest and lightest moved apart until their luminance differs by min_contrast (the
    darkest goes down first, at most to a third of its luminance; the lightest makes up the rest). Unchanged when
    the spread is already there or there are fewer than two."""
    if len(hexes) < 2:
        return dict(hexes)
    L = {k: lum(v) for k, v in hexes.items()}
    lo = min(sorted(L), key=lambda k: L[k])
    hi = max(sorted(L), key=lambda k: L[k])
    gap = L[hi] - L[lo]
    if gap >= min_contrast or lo == hi:
        return dict(hexes)
    need = min_contrast - gap + 0.005
    down = min(need * 0.4, L[lo] * 2 / 3)
    out = dict(hexes)
    out[lo] = _with_lum(hexes[lo], L[lo] - down)
    out[hi] = _with_lum(hexes[hi], L[hi] + (need - down))
    if lum(out[hi]) - lum(out[lo]) < min_contrast:        # the light one hit white: darken the dark one further
        out[lo] = _with_lum(hexes[lo], max(lum(out[hi]) - min_contrast - 0.005, 0.0))
    return out


# ---- reading and writing the source ---------------------------------------------------------------------------------

def _tree(source: str):
    try:
        return ast.parse(source or "")
    except SyntaxError:
        return None


def _design_class(tree):
    cls = [n for n in tree.body if isinstance(n, ast.ClassDef)]
    return cls[-1] if cls else None


def _method(cls, name):
    return next((n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name), None)


def _returned_literal(fn):
    body = [b for b in fn.body if not (isinstance(b, ast.Expr) and isinstance(b.value, ast.Constant))]
    if len(body) == 1 and isinstance(body[0], ast.Return) and body[0].value is not None:
        try:
            return ast.literal_eval(body[0].value)
        except (ValueError, TypeError, SyntaxError):
            return None
    return None


def feature_roles(source: str, features: dict | None = None) -> dict:
    """{feature id: role} in build order: the FeatureDesign features the engine parsed, else the Recipe's
    `features = [Feature("id", "label", "role"), ...]` list."""
    if features:
        return {k: str(v.get("role") or "structure") for k, v in features.items()}
    tree = _tree(source)
    out: dict = {}
    if tree is None:
        return out
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", "")) == "Feature":
            try:
                args = [ast.literal_eval(a) for a in node.args[:3]]
            except (ValueError, TypeError, SyntaxError):
                continue
            if args and isinstance(args[0], str):
                out.setdefault(args[0], str(args[2]) if len(args) > 2 else "structure")
    return out


def appearance_in_source(source: str) -> list | None:
    """The literal list appearance() returns, or None (no method, or not a plain literal)."""
    tree = _tree(source)
    cls = _design_class(tree) if tree is not None else None
    fn = _method(cls, "appearance") if cls is not None else None
    if fn is None:
        return None
    val = _returned_literal(fn)
    return val if isinstance(val, list) else None


def _replace_method(source: str, name: str, text: str) -> str:
    """source with method `name` of the design class replaced by text (a 4-space-indented method), or text added at
    the end of the class."""
    tree = _tree(source)
    cls = _design_class(tree) if tree is not None else None
    if cls is None:
        raise ValueError("no design class in the source")
    lines = source.splitlines(keepends=True)
    fn = _method(cls, name)
    if fn is not None:
        start = min([fn.lineno] + [d.lineno for d in fn.decorator_list]) - 1
        lines[start:fn.end_lineno] = [text if text.endswith("\n") else text + "\n"]
    else:
        end = cls.end_lineno
        if end > 0 and not lines[end - 1].endswith("\n"):
            lines[end - 1] += "\n"
        lines[end:end] = ["\n", text if text.endswith("\n") else text + "\n"]
    out = "".join(lines)
    ast.parse(out)                                        # never hand back a source that does not parse
    return out


def write_appearance(source: str, zones: list) -> str:
    body = pprint.pformat(zones, indent=1, width=100, sort_dicts=True).replace("\n", "\n" + " " * 15)
    text = ("    def appearance(self, v):\n"
            "        \"\"\"Material zones for photos (refined: zone assignment by region).\"\"\"\n"
            f"        return {body}\n")
    return _replace_method(source, "appearance", text)


def write_materials(source: str, mats: dict) -> str:
    """source with its materials() (or module-level MATERIALS) replaced by mats, or a materials() method added."""
    from ..game import materials as matlib
    tree = _tree(source)
    if tree is None:
        raise ValueError("the source does not parse")
    cls = _design_class(tree)
    node = next((n for n in tree.body if isinstance(n, ast.Assign)
                 and any(getattr(t, "id", "") == "MATERIALS" for t in n.targets)), None)
    if node is None or (cls is not None and _method(cls, "materials") is not None):
        return _replace_method(source, "materials", matlib.source_method(mats))
    lines = source.splitlines(keepends=True)
    lines[node.lineno - 1:node.end_lineno] = ["MATERIALS = " + pprint.pformat(mats, indent=1, width=100,
                                                                              sort_dicts=True) + "\n"]
    out = "".join(lines)
    ast.parse(out)
    return out


def game_regions(source: str) -> list[str]:
    """The named regions of the design's cages, in a fixed order (sorted)."""
    try:
        from ..game import pipeline
        cages = pipeline.cages_in_source(source or "")
    except Exception:                                     # noqa: BLE001 - no cage, no regions
        return []
    return sorted({r for c in cages for r in (c.regions or {})})


def _group(name: str, role: str, first: bool) -> str:
    n = name.lower()
    if role in FROZEN_ROLES or any(w in n for w in FUNCTION_WORDS):
        return "function"
    if role in ACCENT_ROLES or any(w in n for w in ACCENT_WORDS):
        return "accent"
    return "body" if first or role in ("structure", "form", "body", "shell") else "accent"


def _style(design) -> str:
    return design.style if design.style in CAD_LOOKS else "clean_consumer"


# ---- operators ------------------------------------------------------------------------------------------------------

class MaterialZones(Operator):
    name = "material_zones"
    domain = "material"
    targets = ("material_zones", "material_contrast")
    cost = 0.4
    label = "Material zones"
    params = {}

    def preconditions(self, design, analysis):
        if analysis.deficits.get("material_zones", 0.0) <= 0.0:
            return False, "the design already has three or more looks"
        return True, ""

    def apply(self, design, analysis, params):
        style = _style(design)
        if design.purpose == "game":
            from ..game import materials as matlib
            mats, _note = matlib.materials_in_source(design.source)
            mats = dict(mats or {})
            free = [r for r in game_regions(design.source) if r not in mats]
            if not free:
                return None
            looks = GAME_LOOKS[style]
            used = {(m.get("material"), str(m.get("tint", "")).lower()) for m in mats.values()}
            added = {}
            for r in free:
                g = _group(r, "", first=False)
                kind, tint = next((looks[x] for x in (g, "accent", "function", "body") if looks[x] not in used),
                                  looks[g])
                used.add((kind, tint))
                added[r] = {"material": kind, "tint": tint}
            new = {**mats, **added}
            if "default" not in new:
                k, t = looks["body"]
                new["default"] = {"material": k, "tint": t}
            return Patch(edit=lambda src, new=new: write_materials(src, new),
                         reason=f"Give the regions {', '.join(sorted(added))} their own materials ({style} looks), so "
                                "the asset reads as made of parts.", params={"regions": sorted(added)})
        roles = feature_roles(design.source, design.features)
        if len(roles) < 2:
            return None                                     # one feature: zones need geometry first
        zones = list(appearance_in_source(design.source) or [])
        covered = {f for z in zones for f in z.get("features", [])}
        groups: dict = {}
        for i, (fid, role) in enumerate(roles.items()):
            if fid not in covered:
                groups.setdefault(_group(fid, role, first=i == 0 and not covered), []).append(fid)
        if not groups:
            return None
        if list(groups) == ["body"] and len(groups["body"]) > 1:   # all body: the first stays body, the rest accent
            groups = {"body": groups["body"][:1], "accent": groups["body"][1:]}
        looks = CAD_LOOKS[style]
        have = {(z.get("finish"), str(z.get("color", "")).lower()) for z in zones}
        for g in ("body", "accent", "function"):
            if g in groups:
                fin, col = looks[g]
                if (fin, col) in have:
                    continue
                zones.append({"features": groups[g], "finish": fin, "color": col, "label": g})
                have.add((fin, col))
        if len(have) < 2:
            return None
        return Patch(edit=lambda src, zones=zones: write_appearance(src, zones),
                     reason="Assign material zones by region: the body, the trims and grips, the functional parts "
                            f"({style} looks).", params={"groups": {g: v for g, v in groups.items()}})


class ContrastPair(Operator):
    name = "contrast_pair"
    domain = "material"
    targets = ("material_contrast",)
    cost = 0.25
    label = "Contrast pair"
    params = {"min_contrast": 0.15}

    def preconditions(self, design, analysis):
        if analysis.deficits.get("material_contrast", 0.0) <= 0.0:
            return False, "the zones already differ in value"
        return True, ""

    def apply(self, design, analysis, params):
        mc = float(params.get("min_contrast", 0.15))
        if design.purpose == "game":
            from ..game import materials as matlib
            mats, _note = matlib.materials_in_source(design.source)
            if not mats:
                return None
            tints = {}
            for k, m in mats.items():
                kind = m.get("material") or "plastic"
                tints[k] = str(m.get("tint") or matlib.KINDS.get(kind, matlib.KINDS["plastic"])["tint"]).lower()
            new_t = push_apart(tints, mc)
            if new_t == tints:
                return None
            new = {k: ({**m, "tint": new_t[k]} if new_t[k] != tints[k] else m) for k, m in mats.items()}
            return Patch(edit=lambda src, new=new: write_materials(src, new),
                         reason=f"Push the lightest and darkest materials apart to a value contrast of {mc:g}.",
                         params={"min_contrast": mc})
        zones = appearance_in_source(design.source)
        if not zones or len(zones) < 2:
            return None
        cols = {i: str(z.get("color", "#eeece6")).lower() for i, z in enumerate(zones)}
        new_c = push_apart(cols, mc)
        if new_c == cols:
            return None
        out = [{**z, "color": new_c[i]} for i, z in enumerate(zones)]
        return Patch(edit=lambda src, out=out: write_appearance(src, out),
                     reason=f"Push the lightest and darkest zones apart to a value contrast of {mc:g}.",
                     params={"min_contrast": mc})


class EdgeWear(Operator):
    name = "edge_wear"
    domain = "material"
    targets = ("wear",)
    cost = 0.25
    label = "Edge wear"
    params = {"amount": 0.5}

    def preconditions(self, design, analysis):
        if design.purpose != "game":
            return False, "wear is baked into game textures only"
        if analysis.deficits.get("wear", 0.0) <= 0.0:
            return False, "the worn share is already in the 2-12 % band"
        return True, ""

    def apply(self, design, analysis, params):
        from ..game import materials as matlib
        from .analyze import WEAR_BAND
        share = ((analysis.measures or {}).get("wear") or {}).get("share")
        mats, _note = matlib.materials_in_source(design.source)
        if share is None or not mats:
            return None
        amount = float(params.get("amount", 0.5))
        lo, hi = WEAR_BAND
        new = {}
        for k, m in mats.items():
            kind = m.get("material") or "plastic"
            if kind in NO_WEAR:
                new[k] = m
                continue
            cur = float(m.get("wear", matlib.KINDS.get(kind, matlib.KINDS["plastic"])["wear"]))
            w = min(1.0, max(cur + 0.15, amount)) if share < lo else round(cur * 0.7, 3) if share > hi else cur
            new[k] = {**m, "wear": round(w, 3)}
        if new == mats:
            return None
        way = "raise" if share < lo else "lower"
        return Patch(edit=lambda src, new=new: write_materials(src, new),
                     reason=f"{way.capitalize()} the materials' wear: {share:.1%} of the surface wore through, the "
                            f"band is {lo:.0%}-{hi:.0%}.", params={"amount": amount, "share": share})


OPERATORS = [MaterialZones(), ContrastPair(), EdgeWear()]
