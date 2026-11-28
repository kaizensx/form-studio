"""Engineering calculators that write real geometry.

A calculator sizes a part from requirements with the equations of a named standard or design guide, says where every
number comes from, and hands back the geometry as a design with parameters:

    from form import calc
    r = calc.run("snapfit", {"material": "PETG", "length": 15, "width": 6, "undercut": 1.0, "mu": 0.3})
    r["values"]      # every number: {"key", "label", "value", "unit", "evidence", "equation", "source", "note"}
    r["checks"]      # PASS / WARN / FAIL rows, each with the equation that decided it
    r["equations"]   # every equation used, as text, with the source it is from
    r["sources"]     # every source: the standard, the guide, the datasheet (title, url)
    r["geometry"]    # the design it writes: a recipe of form.calc.design (kind, values)

Evidence is one of three words, on every number (principle 2 of the plan):

    computed    from the equations named, with the other numbers of the sheet
    specified   given by the person, or published: a standard's table, a design guide, a material's datasheet
    assumed     a default Form Studio chose because nothing was given and nothing sourced exists; always said

Nothing is made up. A material value comes from the sourced library (form/material_library.py) or from the request;
when neither has it, the number that needs it is left out and the sheet says what to give. A guide's value keeps the
guide's name and its condition (moulded resin, steel wire), and a printed part gets the caveat that goes with it.

The calculators (form/calc/<name>.py, each a `spec()` and a `run(inputs)`), with what they follow:

    snapfit   cantilever and annular snap joints      Bayer, Snap-Fit Joints for Plastics
    hinge     living hinge                            pure bending of a strip; Protolabs and moulders' dimensions
    spring    compression, extension, torsion         EN 13906-1/-2/-3; Shigley for end types and wire strength
    fastener  bolted joint, boss, heat-set insert     VDI 2230-1 (simplified), ISO 898-1, ISO 273
    gear      involute spur, helical, internal, rack  ISO 21771 geometry, Lewis bending (AGMA/ISO factors left out)
    cam       plate cam from a motion law             Norton, Cam Design and Manufacturing Handbook
    fit       ISO 286 fit over a temperature span     ISO 286-1/-2, ISO 1 (20 °C), the materials' sourced expansion

This package imports no CAD kernel: the MCP server, the CLI and the app call run() directly. Geometry is built in the
kernel worker from form/calc/design.py (the design's source) and form/calc/shapes.py (the solids).
docs/CALCULATORS.md has the equations and the verification table.
"""
from __future__ import annotations

import importlib
import math

VERSION = 1
EVIDENCE = ("computed", "specified", "assumed")
CALCULATORS = ("snapfit", "hinge", "spring", "fastener", "gear", "cam", "fit")
GIVEN = "given in the request"


class CalcError(Exception):
    """A calculation that cannot be done as asked, with what to change."""

    def __init__(self, message: str, hint: str = "", params: list | None = None):
        super().__init__(message)
        self.hint = hint
        self.params = list(params or [])

    def public(self) -> dict:
        return {"message": str(self), "hint": self.hint, "params": self.params}


def need(cond, message: str, hint: str = "", params: list | None = None) -> None:
    if not cond:
        raise CalcError(message, hint, params)


def number(inputs: dict, key: str, default=None, lo=None, hi=None, label: str = "", whole: bool = False):
    """One numeric input: the request's value, else the default (None = not given). Range-checked."""
    x = inputs.get(key)
    if x is None or x == "":
        return default
    try:
        v = float(x)
    except (TypeError, ValueError):
        raise CalcError(f"{label or key} must be a number (got {x!r}).", "", [key]) from None
    if v != v or abs(v) == math.inf:
        raise CalcError(f"{label or key} must be a finite number.", "", [key])
    if lo is not None and v < lo or hi is not None and v > hi:
        rng = f"{lo:g} to {hi:g}" if lo is not None and hi is not None else f"at least {lo:g}" if lo is not None else f"at most {hi:g}"
        raise CalcError(f"{label or key} = {v:g} is outside the supported range ({rng}).", "", [key])
    if whole:
        need(abs(v - round(v)) < 1e-9, f"{label or key} must be a whole number (got {v:g}).", "", [key])
        return int(round(v))
    return v


def choice(inputs: dict, key: str, options: tuple, default: str) -> str:
    v = inputs.get(key)
    if v is None or v == "":
        return default
    v = str(v).strip().lower().replace("-", "_").replace(" ", "_")
    need(v in options, f"{key} is one of {', '.join(options)} (got {inputs.get(key)!r}).", "", [key])
    return v


def sig(x, n: int = 7):
    """A number rounded to n significant figures (what the sheet shows; the arithmetic keeps full precision)."""
    if not isinstance(x, (int, float)) or isinstance(x, bool) or x == 0 or x != x or abs(x) == math.inf:
        return x
    return round(x, max(0, n - 1 - int(math.floor(math.log10(abs(x))))))


class Sheet:
    """What a calculator returns, built row by row."""

    def __init__(self, calculator: str, title: str, standard: str, inputs: dict):
        self.d = {"calculator": calculator, "title": title, "standard": standard, "version": VERSION,
                  "inputs": {k: v for k, v in inputs.items() if v is not None},
                  "values": [], "checks": [], "equations": [], "sources": [], "notes": [], "caveats": [],
                  "headline": "", "status": "PASS", "geometry": None}
        self._v: dict = {}

    # -- sources and equations ----------------------------------------------------------------------------------
    def source(self, sid: str, title: str, url: str = "", note: str = "") -> str:
        if not any(s["id"] == sid for s in self.d["sources"]):
            self.d["sources"].append({"id": sid, "title": title, "url": url, "note": note})
        return sid

    def eq(self, eid: str, text: str, source: str = "", note: str = "") -> str:
        """Register an equation as text ("eps = 1.5 h y / l^2") with the source it is from."""
        if not any(e["id"] == eid for e in self.d["equations"]):
            if source:
                assert any(s["id"] == source for s in self.d["sources"]), f"equation {eid}: unknown source {source}"
            self.d["equations"].append({"id": eid, "text": text, "source": source, "note": note})
        return eid

    # -- numbers ------------------------------------------------------------------------------------------------
    def add(self, key: str, label: str, value, unit: str, evidence: str, equation: str = "", source: str = "",
            note: str = ""):
        assert evidence in EVIDENCE, evidence
        if evidence == "computed":
            assert equation, f"{key}: a computed number names its equation"
        if evidence == "specified":
            assert source, f"{key}: a specified number names its source"
        if evidence == "assumed":
            assert note, f"{key}: an assumed number says why"
        row = {"key": key, "label": label, "value": sig(value) if isinstance(value, float) else value, "unit": unit,
               "evidence": evidence, "equation": equation, "source": source, "note": note}
        self.d["values"] = [r for r in self.d["values"] if r["key"] != key] + [row]
        self._v[key] = value
        return value

    def given(self, key: str, label: str, value, unit: str, note: str = ""):
        return self.add(key, label, value, unit, "specified", source=self.source("request", GIVEN), note=note)

    def computed(self, key: str, label: str, value, unit: str, equation: str, note: str = ""):
        return self.add(key, label, value, unit, "computed", equation=equation, note=note)

    def assumed(self, key: str, label: str, value, unit: str, note: str, source: str = ""):
        return self.add(key, label, value, unit, "assumed", source=source, note=note)

    def __getitem__(self, key: str):
        return self._v[key]

    def get(self, key: str, default=None):
        return self._v.get(key, default)

    # -- checks, notes ------------------------------------------------------------------------------------------
    def check(self, cid: str, label: str, status: str, value: str, detail: str, equation: str = "",
              evidence: str = "computed") -> None:
        assert status in ("PASS", "WARN", "FAIL", "INFO"), status
        self.d["checks"].append({"id": cid, "label": label, "status": status, "value": value, "detail": detail,
                                 "equation": equation, "evidence": evidence})

    def note(self, text: str) -> None:
        if text not in self.d["notes"]:
            self.d["notes"].append(text)

    def caveat(self, text: str) -> None:
        """Something the result does not cover; shown with the headline, never hidden."""
        if text not in self.d["caveats"]:
            self.d["caveats"].append(text)

    def missing(self, key: str, label: str, what_to_give: str) -> None:
        """A number that could not be computed because an input has no source: said, not guessed."""
        self.d.setdefault("not_computed", []).append({"key": key, "label": label, "why": what_to_give})

    def geometry(self, kind: str, values: dict, name: str, text: dict | None = None, place: dict | None = None) -> None:
        self.d["geometry"] = {"kind": kind, "values": {k: float(v) for k, v in values.items()}, "name": name,
                              "text": dict(text or {}), **({"place": place} if place else {})}

    def done(self, headline: str) -> dict:
        st = [c["status"] for c in self.d["checks"]]
        self.d["status"] = "FAIL" if "FAIL" in st else "WARN" if "WARN" in st else "PASS"
        self.d["headline"] = headline
        self.d["evidence"] = ("computed from " + self.d["standard"] + "; inputs specified or assumed as labelled")
        return self.d


# ---- materials: sourced or said to be missing -------------------------------------------------------------------
def material_prop(sheet: Sheet, material: str | None, name: str, key: str, label: str, override=None,
                  direction: str = "", scale: float = 1.0, unit: str | None = None):
    """One material number on the sheet: the request's value (specified), else the sourced library's (specified, with
    the datasheet), else None, with a row in "not_computed" naming what is missing. Never a default."""
    if override is not None:
        return sheet.given(key, label, float(override), unit or "")
    if not material:
        return None
    from .. import material_library as ml
    try:
        p = ml.prop(material, name, direction)
    except KeyError as e:
        raise CalcError(str(e).strip("'\""), "form materials lists them; or give the numbers themselves.", ["material"]) from None
    if p.get("status") or p.get("value") is None:
        return None
    sid = sheet.source("mat:" + material + ":" + p["name"], p["source"], p.get("url") or "",
                       (p.get("condition") or "") + (f" Quote: “{p['quote']}”" if p.get("quote") else ""))
    return sheet.add(key, label + f" ({material})", float(p["value"]) * scale, unit if unit is not None else p.get("unit", ""),
                     "specified", source=sid, note=p.get("condition", ""))


def material_kind(material: str | None) -> dict:
    """{"kind": "filament" | "engineering" | "", "category", "label"} of a library key (kernel-free)."""
    if not material:
        return {"kind": "", "category": "", "label": ""}
    from .. import materials
    k = materials._key(material)
    need(k is not None, f"Unknown material “{material}”.", materials.known() + " Or give the numbers themselves.", ["material"])
    info = materials.info(k) or {}
    return {"id": k, "kind": info.get("kind") or "", "category": info.get("category", "plastic"), "label": info.get("label", k)}


# ---- the registry ---------------------------------------------------------------------------------------------
def module(name: str):
    need(name in CALCULATORS, f"Unknown calculator “{name}”.", "Calculators: " + ", ".join(CALCULATORS) + ".", ["calculator"])
    return importlib.import_module(f"{__name__}.{name}")


def spec(name: str) -> dict:
    """What a calculator takes: {"id", "title", "standard", "doc", "inputs": [{key, label, unit, default, doc,
    choices}], "writes": the geometry it makes}."""
    return module(name).spec()


def catalogue() -> list:
    return [spec(n) for n in CALCULATORS]


def run(name: str, inputs: dict | None = None) -> dict:
    """Run one calculator. inputs are plain numbers and words (mm, N, degrees, °C); unknown keys are refused so a
    typo is never silently ignored."""
    m = module(name)
    inputs = dict(inputs or {})
    known = {i["key"] for i in m.spec()["inputs"]}
    unknown = sorted(k for k in inputs if k not in known)
    need(not unknown, f"{name}: unknown input(s) {', '.join(unknown)}.",
         "Inputs: " + ", ".join(sorted(known)) + ".", unknown)
    return m.run(inputs)


def I(key: str, label: str, unit: str = "", default=None, doc: str = "", choices: tuple = ()) -> dict:   # noqa: E743
    return {"key": key, "label": label, "unit": unit, "default": default, "doc": doc,
            **({"choices": list(choices)} if choices else {})}
