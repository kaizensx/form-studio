from .base import Feature, Param, Recipe, RecipeError, Stage  # noqa: F401

# The built-in library, in the order it is shown. Each module is named after its recipe's id (Studio.recipe_sha
# hashes form/recipes/<id>.py) and defines one Recipe subclass with that id.
LIBRARY = ("gridfinity_bin", "gridfinity_baseplate", "storage_box", "pegboard", "device_stand", "cable_organizer",
           "desk_hanger", "shelf_bracket", "hose_adapter", "plant_pot", "vase", "battery_holder",
           "enclosure", "coupon")
# Retired recipes: never listed, but every design that names one still opens, builds and releases as before.
LEGACY = ("dock", "gridfinity", "hook", "planter", "gear_pair", "knob", "hinged_box")


def _load(name: str) -> Recipe:
    import importlib
    mod = importlib.import_module(f"{__name__}.{name}")
    for v in vars(mod).values():
        if isinstance(v, type) and issubclass(v, Recipe) and v.__module__ == mod.__name__ and v.id == name:
            return v()
    raise ImportError(f"form/recipes/{name}.py defines no Recipe with id {name!r}")


def registry() -> dict:
    """Every built-in recipe, listed and legacy, by id."""
    return {r.id: r for r in (_load(n) for n in LIBRARY + LEGACY)}


def listed(recipes: dict | None = None) -> dict:
    """The recipes the library shows: built-in, not legacy."""
    recipes = registry() if recipes is None else recipes
    return {k: r for k, r in recipes.items() if not getattr(r, "legacy", False)}


# ---- designs written as code (by an agent or a person) ---------------------------------------
# A design source is a Python file defining one Recipe subclass. It is stored content-addressed
# (<data>/.sources/<sha>.py) so every revision keeps the exact code it was built from.
import hashlib as _hashlib
import importlib.util as _ilu
import os as _os
import re as _re
from pathlib import Path as _Path

SOURCE_PREFIX = "src:"
SCAD_PREFIX = "scad:"            # OpenSCAD designs: <data>/.sources/<sha>.scad (see recipes/scad.py)
_SOURCE_KEY = _re.compile(r"[0-9a-f]{1,64}")


def is_source(rid: str) -> bool:
    """A design written as code (Python or OpenSCAD), as opposed to a built-in recipe."""
    return isinstance(rid, str) and rid.startswith((SOURCE_PREFIX, SCAD_PREFIX))


def source_path(store: _Path, rid: str) -> _Path:
    """The file of a design source. Ids are content hashes, so anything else (a path, '..') is refused."""
    scad = rid.startswith(SCAD_PREFIX)
    key = rid[len(SCAD_PREFIX if scad else SOURCE_PREFIX):]
    if not _SOURCE_KEY.fullmatch(key):
        raise KeyError(rid)
    return store / f"{key}.{'scad' if scad else 'py'}"


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
            r = load_source(source_path(self.store, key), key)
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
            try:
                return source_path(self.store, key).exists()
            except KeyError:
                return False
        return False

    def builtins(self):
        """The built-in recipes the library lists (legacy ones are left out; they still build by id)."""
        return {k: v for k, v in self.items() if not is_source(k) and not getattr(v, "legacy", False)}

    def all_builtins(self):
        """Every built-in recipe, legacy ones included: for naming what an existing design was made from."""
        return {k: v for k, v in self.items() if not is_source(k)}


_book = None


def resolve(recipe_id: str) -> Recipe:
    """Used by the kernel worker; FORM_SOURCES is set by the Studio before the worker starts."""
    global _book
    if _book is None:
        store = _os.environ.get("FORM_SOURCES")
        _book = RecipeBook(_Path(store) if store else None)
    return _book[recipe_id]
