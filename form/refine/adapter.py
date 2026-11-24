"""A plain Recipe made refinable: its whole build() becomes the skeleton feature of a FeatureDesign, so refine
features can follow it, each one a method that delete_feature takes out again.

    src2 = adapter.wrap(src)          # None when the source cannot be wrapped (and why: adapter.why_not(src))
    src  = adapter.unwrap(src2)       # back to the plain Recipe, once no refine feature is left

What wrap() changes, and nothing else:
  * the design class's base `Recipe` becomes `FeatureDesign` (imported from form.featureprog);
  * its `build` method is renamed `recipe_build`;
  * one feature method is added, `recipe_stages`, decorated @feature(..., stages=True): it returns recipe_build(v),
    the original list of Stages. featureprog keeps every stage under its own declared feature (so a bore is still the
    interface feature it was, and its faces stay frozen), and later features get the last stage's shape as the body.

The geometry of the wrapped design is the original's (the same build runs); its parameters, features, derived values,
statics, appearance() and everything else on the class are untouched. A design that already is a FeatureDesign, has
no build method, builds a mesh (mesh = True), or is a game cage source (CAGES literals) is not wrapped.
"""
from __future__ import annotations

import ast
import re

MARK = "# form.refine adapter: the Recipe's build() is the skeleton feature (form/refine/adapter.py)"
IMPORT = "from form.featureprog import FeatureDesign, feature  " + MARK
STAGES = '''
    @feature("The design as written", role="structure", stages=True)
    def recipe_stages(self, v, body):
        return self.recipe_build(v)
'''


def _design_class(tree: ast.Module):
    found = [n for n in tree.body if isinstance(n, ast.ClassDef)
             and any((b.id if isinstance(b, ast.Name) else getattr(b, "attr", "")) == "Recipe" for b in n.bases)]
    return found[0] if len(found) == 1 else None


def why_not(source: str) -> str:
    """Why source cannot be wrapped ("" when it can)."""
    try:
        tree = ast.parse(source or "")
    except SyntaxError as e:
        return f"the source does not parse ({e.msg})"
    if MARK in (source or ""):
        return "already wrapped"
    if re.search(r"^CAGES\s*=", source or "", re.M):
        return "a game cage source is refined through its cage, not as a solid"
    cls = _design_class(tree)
    if cls is None:
        return "no single class derived from Recipe"
    names = {n.name for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    if "build" not in names:
        return "the design class has no build() method"
    if {"recipe_build", "recipe_stages"} & names:
        return "the design already has a recipe_build or recipe_stages method"
    for n in cls.body:
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "mesh" for t in n.targets):
            try:
                if ast.literal_eval(n.value):
                    return "a mesh design (mesh = True) has no B-rep edges to refine"
            except ValueError:
                pass
    return ""


def wrap(source: str) -> str | None:
    """The plain Recipe source as a FeatureDesign whose skeleton feature is its build() (None when why_not)."""
    if why_not(source):
        return None
    tree = ast.parse(source)
    cls = _design_class(tree)
    lines = source.splitlines()
    # the class line: Recipe -> FeatureDesign (only in the bases of this class line)
    head = cls.lineno - 1
    end_head = (cls.body[0].lineno - 2) if cls.body else head
    for i in range(head, max(head, end_head) + 1):
        if re.search(r"\bRecipe\b", lines[i]):
            lines[i] = re.sub(r"\bRecipe\b", "FeatureDesign", lines[i], count=1)
            break
    build = next(n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "build")
    i = build.lineno - 1
    lines[i] = re.sub(r"\bdef\s+build\s*\(", "def recipe_build(", lines[i], count=1)
    # the stages feature goes right after the class's last line
    last = cls.end_lineno
    lines[last:last] = STAGES.rstrip("\n").splitlines()
    # the import goes after the last top-level import (the class may sit below helpers)
    imports = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    at = imports[-1].end_lineno if imports else 0
    lines.insert(at, IMPORT)
    return "\n".join(lines) + "\n"


def unwrap(source: str) -> str:
    """wrap() undone (the source as it was before), when the wrapped design has no other feature methods left."""
    if MARK not in (source or ""):
        return source
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source
    cls = next((n for n in tree.body if isinstance(n, ast.ClassDef)
                and any((b.id if isinstance(b, ast.Name) else getattr(b, "attr", "")) == "FeatureDesign"
                        for b in n.bases)), None)
    if cls is None:
        return source
    feats = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.decorator_list
             and any("feature" in ast.unparse(d) for d in n.decorator_list)]
    if [f.name for f in feats] != ["recipe_stages"]:
        return source                                    # refine features are still there
    lines = source.splitlines()
    st = feats[0]
    a = min(d.lineno for d in st.decorator_list) - 1
    b = st.end_lineno
    # the blank line wrap() put before it
    if a > 0 and not lines[a - 1].strip():
        a -= 1
    del lines[a:b]
    out = "\n".join(lines) + "\n"
    out = out.replace(IMPORT + "\n", "", 1)
    out = re.sub(r"\bdef\s+recipe_build\s*\(", "def build(", out, count=1)
    m = re.search(rf"^class\s+{re.escape(cls.name)}\s*\(([^)]*)\)", out, re.M)
    if m:
        out = out[:m.start(1)] + re.sub(r"\bFeatureDesign\b", "Recipe", m.group(1), count=1) + out[m.end(1):]
    return out


def is_wrapped(source: str) -> bool:
    return MARK in (source or "")
