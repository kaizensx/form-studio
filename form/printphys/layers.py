"""Layer-aware strength: a static strength study of a printed part as a transversely isotropic solid.

    r = study_call(st, pid, study="s1a2b3c")                       # the loads of an existing static study, layered
    r = study_call(st, pid, definition={"fixtures": [...], "loads": [...], "material": "PLA"},
                   orientation="setup", sweep="auto", assume={"poisson_z": 0.3})

The study is an ordinary strength study (form/fea/study.py) with a `layers` block: it is stored in the project, keyed
by the geometry, the loads, the material's numbers, the orientation and the engine, runs in the background, and is
read with get_strength_study. What the block adds to the solve (form/fea/core.py, solve.py):

* **The material.** In the layers: the datasheet's X-Y modulus and strength. Across them: the datasheet's Z modulus
  and Z strength (form/material_library.py). Poisson's ratio is in no filament datasheet: a value measured on printed
  specimens of the same polymer is used where a paper gives one (form/printphys/sources.py), named as such; else it
  must be given. The Poisson's ratio across the layers and the shear modulus between them are in no source at all:
  they are given by the caller, or assumed by a stated rule (equal to the in-plane ratio; Huber's approximation), and
  the result lists every assumed value under `layers.material.assumed`.
* **The orientation.** The build direction is the design's print setup ("setup": the study goes stale when the
  setup changes) or an orientation id. The elasticity tensor is turned to it.
* **The verdict.** Tension across the layers against the Z strength (the weak direction, with its own stated error),
  von Mises stress against the in-plane strength, and the lower of the two as the safety factor.
* **The other orientations.** The same mesh, supports and loads solved again with the material turned to each of the
  six axis orientations (or those named): `layers.by_orientation`.

Verified against closed forms: form/fea/verify.py `layered_tension` (Lekhnitskii's off-axis modulus) and
`layered_cantilever` (a Timoshenko beam in three build directions); docs/STRENGTH.md has the table.
"""
from __future__ import annotations

import math


def _err(msg: str, hint: str = "", status: int = 400):
    from ..studio import StudioError
    return StudioError(msg, hint, status=status)


def _with_poisson(st, p: dict, material):
    """The material with a printed-specimen Poisson's ratio from the literature, when the library has none for a
    filament and the caller gave none. Returns (material, note | None)."""
    from .. import material_library as ml
    from .. import materials
    from . import sources
    given = dict(material) if isinstance(material, dict) else {}
    key = given.get("key") or given.get("material") or (material if isinstance(material, str) else None) \
        or materials.resolved(p).get("material")
    if not key or "poisson" in given or "nu" in given:
        return material, None
    k = materials._key(key)
    if k is None:
        return material, None
    try:
        if ml.prop(k, "poisson").get("status") != "unsourced":
            return material, None
    except KeyError:
        return material, None
    s = sources.get(k, "poisson")
    if s is None:
        return material, None
    src = f"{s['source']} ({s['basis']}: {s['condition']}; not this filament's own datasheet)"
    return {**given, "key": k, "poisson": s["value"], "source": (given.get("source") + "; " if given.get("source") else "") + src}, \
        (f"Poisson's ratio {s['value']:g} is from printed specimens of the same polymer in another document, since the "
         "filament's datasheet states none.")


def _copy(d: dict) -> dict:
    """A stored static definition as a body clean() takes again."""
    loads = []
    for ld in d.get("loads") or []:
        if ld["type"] == "gravity":
            v = ld["vector"]
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            loads.append({"type": "gravity", "g": ld.get("g", 1.0), "direction": [x / n for x in v]})
        else:
            loads.append(dict(ld))
    return {"kind": "static", "fixtures": [dict(f) for f in d.get("fixtures") or []], "loads": loads,
            "material": d.get("material"), "materials": {}, "mesh": dict(d.get("mesh") or {})}


def study_call(st, project: str, study: str = "", definition: dict | None = None, orientation: str = "setup",
               sweep="auto", assume: dict | None = None, name: str = "", run: bool = True, force: bool = False,
               by: str = "agent") -> dict:
    """Define a layered study (from a definition, or from the loads of static study `study`) and start it."""
    from ..fea import study as fstudy
    from ..fea import tools as ftools
    p = st.load(project)
    sid = None
    if definition is None:
        if not study:
            layered = [d for d in fstudy.definitions(p) if d.get("layers")]
            return {"studies": [fstudy.state(st, p, d["id"]) for d in layered],
                    "engine_installed": fstudy.python(st.cfg) is not None,
                    "next": "Give study=\"<id of a static strength study>\" to solve its loads on the printed, layered "
                            "material, or fixtures and loads to define one."}
        src = fstudy.get(p, study)
        if src["kind"] != "static":
            raise _err(f"Study “{study}” is a {src['kind']} study; a layered study is static.")
        body = _copy(src)
        if src.get("layers"):                           # already layered: this call replaces its layers block
            sid = src["id"]
            body["name"] = src["name"]
        else:
            twin = next((d for d in fstudy.definitions(p) if (d.get("layers") or {}).get("of") == src["id"]), None)
            sid = twin["id"] if twin else None
            body["name"] = name or f"{src['name']}, layered"
        of = src["id"] if not src.get("layers") else (src.get("layers") or {}).get("of")
    else:
        body = {**definition, "kind": "static"}
        body["name"] = name or definition.get("name") or ""
        sid = study or None
        of = None
    body["material"], note = _with_poisson(st, p, body.get("material"))
    body["layers"] = {"orientation": orientation or "setup", "sweep": sweep, "assume": assume or {}}
    d = fstudy.define(st, p, body, by=by, sid=sid)
    if of:
        with st.lock(project):
            cur = st.load(project)
            cur["strength"][d["id"]]["layers"]["of"] = of
            st.save(cur)
        d["layers"]["of"] = of
    out = ftools.study_call(st, project, None, d["id"], run, force, False, by)
    if note:
        out["material_note"] = note
    out["read_with"] = f"get_strength_study(project='{project}', study='{d['id']}', wait_s=60): result.layers"
    return out


def summary(res: dict | None) -> dict | None:
    """The layered part of a stored result, short."""
    if not res or not res.get("layers"):
        return None
    lay = res["layers"]
    return {"orientation": lay.get("orientation"), "orientation_label": lay.get("orientation_label"),
            "safety_factor": res.get("safety_factor"), "governing": lay.get("governing"),
            "across_layers": lay.get("across_layers"), "in_plane": lay.get("in_plane"),
            "interlayer_shear": lay.get("interlayer_shear"), "by_orientation": lay.get("by_orientation"),
            "assumed": (lay.get("material") or {}).get("assumed"), "knockdown": (lay.get("material") or {}).get("knockdown"),
            "evidence": lay.get("evidence"), "converged": res.get("converged")}
