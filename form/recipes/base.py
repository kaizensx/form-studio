"""Recipe contract: a parametric object family with named features.

A recipe is the single editable source for a design. It declares typed
parameters (with units and limits), builds the solid as an ordered list of
feature stages, and declares the interfaces that must survive styling.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Callable

from .assembly import Access, Assembly, Hardware, Joint, Part, hinge, slide  # noqa: F401  (part of the recipe contract)


@dataclass(frozen=True)
class Param:
    key: str
    label: str
    default: float
    min: float
    max: float
    step: float = 0.1
    unit: str = "mm"
    group: str = "form"          # brief | interface | form | process
    feature: str = ""            # feature this parameter primarily drives
    doc: str = ""
    provenance: str = "assumed"  # default provenance of the default value

    def public(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Feature:
    id: str
    label: str
    role: str   # interface | structure | finish | access
    doc: str = ""


@dataclass
class Stage:
    feature: str
    shape: Any


class RecipeError(Exception):
    """A build failure attributable to a feature, with a way forward."""

    def __init__(self, message: str, feature: str = "", hint: str = "", params: list[str] | None = None):
        super().__init__(message)
        self.feature = feature
        self.hint = hint
        self.params = params or []

    def public(self) -> dict:
        return {"message": str(self), "feature": self.feature, "hint": self.hint, "params": self.params}


class Recipe:
    id = ""
    title = ""
    summary = ""
    params: list[Param] = []
    features: list[Feature] = []
    #: parameters whose pairing forms the fit interface: (cavity_param, mating_param, clearance_param)
    fit: dict | None = None
    #: number of separate printed bodies the final stage contains (e.g. 2 for a case base + lid on one plate)
    solids: int = 1

    def defaults(self) -> dict:
        return {p.key: p.default for p in self.params}

    def spec(self, key: str) -> Param:
        for p in self.params:
            if p.key == key:
                return p
        raise KeyError(key)

    def validate(self, values: dict) -> dict:
        """Range-check and complete a value set. Raises RecipeError."""
        out = {}
        for p in self.params:
            v = values.get(p.key, p.default)
            if not isinstance(v, (int, float)) or isinstance(v, bool) or v != v or v in (float("inf"), float("-inf")):
                raise RecipeError(f"{p.label} is not a finite number", p.feature, params=[p.key])
            if v < p.min - 1e-9 or v > p.max + 1e-9:
                raise RecipeError(
                    f"{p.label} = {v:g} {p.unit} is outside {p.min:g}–{p.max:g} {p.unit}",
                    p.feature, f"Keep {p.label.lower()} within its supported range.", [p.key])
            out[p.key] = float(v)
        problems = self.constraints(out)
        if problems:
            raise problems[0]
        return out

    # --- to implement -----------------------------------------------------
    def constraints(self, v: dict) -> list[RecipeError]:
        return []

    def build(self, v: dict) -> list[Stage]:
        raise NotImplementedError

    def derived(self, v: dict) -> list[dict]:
        """Dimensions that follow from parameters (never edited directly)."""
        return []

    def measure(self, v: dict, faces_by_feature: dict) -> list[dict]:
        """Audit interface dimensions on the built solid: intended vs as-modelled."""
        return []

    def statics(self, v: dict, solid_volume_mm3: float, com: tuple) -> dict | None:
        return None

    def companions(self, v: dict) -> list[dict]:
        """Mating objects to show as ghosts: boxes with a size, position and X-rotation."""
        return []

    def test_piece(self, v: dict, shape: Any):
        """A small coupon cut from the real geometry around the fit interface."""
        return None

    def reference(self, name: str):
        """A part imported into this project (STEP as its B-rep, STL as a sewn mesh), in its own coordinates.

        Use it for clearance cuts around a real board or device: `body - offset(self.reference("pi5.step"), 0.5)`.
        Import the file first (MCP import_reference, or Brief > Import part in the app).
        """
        from .meshsolid import load
        return load(name)

    def assembly(self, v: dict):
        """How the printed parts go together: an Assembly (form.recipes.assembly), or None for a single part.

        Parts are the result's solids (numbered left to right on the plate), each with its assembled placement,
        an exploded-view offset, optional joints (hinge/slide) and purchased hardware. Designs without it
        behave exactly as before.
        """
        return None

    def public(self) -> dict:
        return {
            "id": self.id, "title": self.title, "summary": self.summary,
            "params": [p.public() for p in self.params],
            "features": [asdict(f) for f in self.features],
            "fit": self.fit,
        }
