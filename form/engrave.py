"""Text on a face: raised or sunk lettering added to a design as a real CAD feature, through its source.

A point picked on a flat face (and that face's normal, from ``form.selection``) becomes a mark: text, cap height,
depth, raised or sunk. The marks live in a block at the end of the design's Python source, between two marker lines,
so they are part of the source an agent reads, in every revision, and travel with the design:

    # ---- Form Studio: text on faces (edit in the app or with `form engrave`) ----
    _FORM_TEXT = [{'id': 'text_1', 'text': 'DESK', 'at': (0.0, -20.0, 8.0), 'normal': (0.0, -1.0, 0.0), ...}]
    ...
    # ---- end of text on faces ----

The block wraps the design class's build(): after the design's own stages it adds one Stage per mark, built with
``form.marks`` (the font that ships with Form Studio), so each mark is a named feature in the viewport and the checks.
Adding, changing or removing a mark is ``Studio.update_design``: a new revision, built in the kernel before it is saved.
Printability (cap height, thinnest stroke against the nozzle) comes from ``marks.analyse`` (computed on the glyphs).

Only Python designs carry marks this way; a built-in recipe or an OpenSCAD design is refused with the reason.
"""
from __future__ import annotations

import ast
import re

START = "# ---- Form Studio: text on faces (edit in the app or with `form engrave`) ----"
END = "# ---- end of text on faces ----"
MAX_MARKS = 12

TEMPLATE = '''
{start}
from form import marks as _form_marks
from form.recipes.base import Feature as _FormFeature, Stage as _FormStage
_FORM_TEXT = {marks}


def _form_text(cls):
    build = cls.build

    def with_text(self, v):
        stages = list(build(self, v))
        s = stages[-1].shape
        for m in _FORM_TEXT:
            put = _form_marks.deboss_text if m["sunk"] else _form_marks.emboss_text
            s = put(s, m["text"], on=m["at"], normal=m["normal"], up=m.get("up"), height=m["height"], depth=m["depth"])
            stages.append(_FormStage(m["id"], s))
        return stages
    cls.build = with_text
    cls.features = [f for f in cls.features if not f.id.startswith("text_")] + [
        _FormFeature(m["id"], ("Sunk" if m["sunk"] else "Raised") + " text “" + m["text"] + "”", "finish") for m in _FORM_TEXT]
    return cls


{cls} = _form_text({cls})
{end}
'''


def _err(msg, hint=""):
    from .studio import StudioError
    return StudioError(msg, hint)


def split(source: str) -> tuple[str, list]:
    """(the source without the block, the marks it holds)."""
    i = source.find(START)
    if i < 0:
        return source, []
    j = source.find(END, i)
    block = source[i:j if j >= 0 else len(source)]
    m = re.search(r"^_FORM_TEXT = (.*)$", block, re.M)
    marks = ast.literal_eval(m.group(1)) if m else []
    rest = source[:i].rstrip() + "\n" + (source[j + len(END):].lstrip("\n") if j >= 0 else "")
    return rest.rstrip() + "\n", marks


def design_class(source: str) -> str:
    tree = ast.parse(source)
    names = [n.name for n in tree.body if isinstance(n, ast.ClassDef)
             and any((isinstance(b, ast.Name) and b.id in ("Recipe", "FeatureDesign")) or (isinstance(b, ast.Attribute) and b.attr in ("Recipe", "FeatureDesign")) for b in n.bases)]
    if len(names) != 1:
        raise _err("Text can be added to a design with one Recipe class; this source has " + str(len(names)) + ".")
    return names[0]


def join(source: str, marks: list) -> str:
    base, _old = split(source)
    if not marks:
        return base
    return base.rstrip() + "\n" + TEMPLATE.format(start=START, end=END, cls=design_class(base), marks=repr(marks))


def _vec(x, what):
    try:
        v = tuple(round(float(t), 4) for t in x)
    except (TypeError, ValueError):
        v = ()
    if len(v) != 3:
        raise _err(f"{what} must be three numbers (x, y, z).")
    return v


def mark(text: str, at, normal, height: float = 6.0, depth: float = 0.6, sunk: bool = False, up=None, id: str = "") -> dict:
    from . import marks as m
    t = m.clean(text)
    if not t:
        raise _err("Type the text to put on the face.")
    if not (1.0 <= float(height) <= 200.0):
        raise _err("Cap height must be between 1 and 200 mm.")
    if not (0.1 <= float(depth) <= 20.0):
        raise _err("Depth must be between 0.1 and 20 mm.")
    n = _vec(normal, "The face normal")
    if sum(c * c for c in n) < 0.5:
        raise _err("The face normal is not a direction.", "Pick a point on a flat face again.")
    out = {"id": id or "", "text": t, "at": _vec(at, "The point"), "normal": n, "height": round(float(height), 3),
           "depth": round(float(depth), 3), "sunk": bool(sunk)}
    if up is not None:
        out["up"] = _vec(up, "The up direction")
    return out


def printability(text: str, height: float, depth: float, sunk: bool, nozzle: float | None) -> dict:
    """Cap height, text width and the thinnest stroke, computed on the glyphs, with check rows against the nozzle."""
    from . import marks as m
    info = m.analyse(m.clean(text) or "?", float(height), float(depth))
    return {**info, "checks": m.checks(info, nozzle, raised=not sunk)}


def _python_source(st, p) -> str:
    from .recipes import SCAD_PREFIX, is_source
    rid = st.rid(p)
    if rid.startswith(SCAD_PREFIX):
        raise _err("Text on faces works on Python designs; this one is OpenSCAD.", "Ask the agent to add the text in the OpenSCAD source.")
    if not is_source(rid):
        raise _err("This design is a built-in recipe, so its source cannot carry text.",
                   "Ask the agent to turn it into a design of its own (create_design), then add the text.")
    return st.source_text(p)


def list_marks(st, p) -> list:
    try:
        return split(_python_source(st, p))[1]
    except Exception:
        return []


def _commit(st, p, marks: list, note: str, expect_head, origin):
    for i, mk in enumerate(marks):
        mk["id"] = f"text_{i + 1}"
    src = join(_python_source(st, p), marks)
    p = st.update_design(p, src, note=note, origin=origin, expect_head=expect_head)
    return {"head": p["head"], "marks": marks}


def add(st, p, text, at, normal, height=6.0, depth=0.6, sunk=False, up=None, expect_head=None, origin="you") -> dict:
    marks = split(_python_source(st, p))[1]
    if len(marks) >= MAX_MARKS:
        raise _err(f"A design carries at most {MAX_MARKS} texts.", "Remove one first.")
    mk = mark(text, at, normal, height, depth, sunk, up)
    word = "Sunk" if mk["sunk"] else "Raised"
    return _commit(st, p, marks + [mk], f"{word} text “{mk['text']}”, {mk['height']:g} mm high, {mk['depth']:g} mm "
                   + ("deep" if mk["sunk"] else "proud"), expect_head, origin)


def remove(st, p, mark_id: str, expect_head=None, origin="you") -> dict:
    marks = split(_python_source(st, p))[1]
    left = [m for m in marks if m.get("id") != mark_id]
    if len(left) == len(marks):
        raise _err(f"No text “{mark_id}” on this design.", "List them with `form engrave <project> --list`.")
    gone = next(m for m in marks if m.get("id") == mark_id)
    return _commit(st, p, left, f"Removed text “{gone['text']}”", expect_head, origin)
