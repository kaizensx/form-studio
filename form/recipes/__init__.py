from .base import Feature, Param, Recipe, RecipeError, Stage  # noqa: F401


def registry() -> dict:
    from .coupon import Coupon
    from .dock import Dock
    from .gridfinity import GridfinityBin
    from .hook import WallHook
    from .planter import TwistPlanter
    return {r.id: r for r in (Dock(), GridfinityBin(), WallHook(), TwistPlanter(), Coupon())}


# ---- designs written as code (by an agent or a person) ---------------------------------------
# A design source is a Python file defining one Recipe subclass. It is stored content-addressed
# (<data>/.sources/<sha>.py) so every revision keeps the exact code it was built from.
import hashlib as _hashlib
import importlib.util as _ilu
import os as _os
from pathlib import Path as _Path

SOURCE_PREFIX = "src:"
SCAD_PREFIX = "scad:"            # OpenSCAD designs: <data>/.sources/<sha>.scad (see recipes/scad.py)


def is_source(rid: str) -> bool:
    """A design written as code (Python or OpenSCAD), as opposed to a built-in recipe."""
    return isinstance(rid, str) and rid.startswith((SOURCE_PREFIX, SCAD_PREFIX))


def source_path(store: _Path, rid: str) -> _Path:
    if rid.startswith(SCAD_PREFIX):
        return store / f"{rid[len(SCAD_PREFIX):]}.scad"
    return store / f"{rid[len(SOURCE_PREFIX):]}.py"


def source_id(text: str) -> str:
    return SOURCE_PREFIX + _hashlib.sha256(text.encode()).hexdigest()[:16]


def store_source(store: _Path, text: str, language: str = "python") -> str:
    rid = source_id(text) if language == "python" else SCAD_PREFIX + source_id(text)[len(SOURCE_PREFIX):]
    store.mkdir(parents=True, exist_ok=True)
    f = source_path(store, rid)
    if not f.exists():
        f.write_text(text, encoding="utf-8")
    return rid


def load_source(path: _Path, rid: str) -> Recipe:
    """Import a design file and return its Recipe. Load errors become RecipeErrors an agent can act on."""
    import traceback
    name = "form_design_" + rid[len(SOURCE_PREFIX):]
    try:
        spec = _ilu.spec_from_file_location(name, path)
        mod = _ilu.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except FileNotFoundError:
        raise RecipeError(f"Design source {rid} is missing from the source store.", "",
                          "Restore the project's .sources folder, or submit the source again.")
    except Exception as e:
        tb = traceback.extract_tb(e.__traceback__)
        line = next((f.lineno for f in reversed(tb) if f.filename == str(path)), getattr(e, "lineno", None))
        raise RecipeError(f"Design source does not load: {type(e).__name__}: {e}" + (f" (line {line})" if line else ""), "",
                          "Fix the source and submit it again. It must define one subclass of Recipe.")
    found = [v for v in vars(mod).values() if isinstance(v, type) and issubclass(v, Recipe) and v is not Recipe
             and v.__module__ == name]
    if len(found) != 1:
        raise RecipeError(f"Design source must define exactly one Recipe subclass; found {len(found)}.", "",
                          "Define `class Design(Recipe): ...` once.")
    r = found[0]()
    r.id = rid
    if not r.params or not r.features:
        raise RecipeError("A design needs at least one Param and one Feature.", "", "Declare params and features on the class.")
    ids = [f.id for f in r.features]
    for p in r.params:
        if p.feature and p.feature not in ids:
            raise RecipeError(f"Parameter {p.key} names unknown feature “{p.feature}”.", "", f"Features: {', '.join(ids)}.")
    return r


class RecipeBook(dict):
    """Built-in recipes plus design sources, loaded on first use."""

    def __init__(self, store: _Path | None = None):
        super().__init__(registry())
        self.store = store

    def __missing__(self, key):
        if isinstance(key, str) and key.startswith(SOURCE_PREFIX) and self.store is not None:
            r = load_source(self.store / f"{key[len(SOURCE_PREFIX):]}.py", key)
            self[key] = r
            return r
        if isinstance(key, str) and key.startswith(SCAD_PREFIX) and self.store is not None:
            from .scad import ScadRecipe
            r = ScadRecipe(source_path(self.store, key), key)
            self[key] = r
            return r
        raise KeyError(key)

    def __contains__(self, key):
        if dict.__contains__(self, key):
            return True
        if isinstance(key, str) and key.startswith(SCAD_PREFIX) and self.store is not None:
            return source_path(self.store, key).exists()
        return False

    def builtins(self):
        return {k: v for k, v in self.items() if not is_source(k)}


_book = None


def resolve(recipe_id: str) -> Recipe:
    """Used by the kernel worker; FORM_SOURCES is set by the Studio before the worker starts."""
    global _book
    if _book is None:
        store = _os.environ.get("FORM_SOURCES")
        _book = RecipeBook(_Path(store) if store else None)
    return _book[recipe_id]
