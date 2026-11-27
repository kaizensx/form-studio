"""Mass properties from the B-rep: mass, centre of mass, inertia tensor and principal axes, per part and assembled.

Two halves, so a change of material or pose never rebuilds anything:

* **Geometry (kernel worker, ``op_massprops``).** OCCT ``BRepGProp.VolumeProperties`` on each solid: volume, centroid
  and the inertia tensor about the centroid at unit density (mm, mm³, mm⁵). Exact on the B-rep for planes, cylinders,
  cones, spheres and tori (Gauss integration of the face parametrisation); a body with free-form faces is integrated
  adaptively and its relative error estimate is reported. A mesh design (``Recipe.mesh``) is integrated from its closed
  triangle mesh and is labelled so. Stored under ``artifacts/mass/geom-<key>.json``, keyed by the geometry key.
* **Material and pose (here, plain Python).** Each part's density comes from its material
  (``form.material_library.density``: a sourced datasheet value, or the bd_materials typical value, named as such).
  Parts are moved to the assembled frame at a pose (joint values, as the assembly view moves them), rotated
  (``I' = R I Rᵀ``) and combined with the parallel-axis theorem. A part without a material has no mass: the total is
  then left out (never guessed) and the volume centroid is given instead, labelled as such.

Units: mm, g, g·mm² (also kg·m²), kg/m³. Evidence class ``computed (B-rep)`` or ``computed (closed mesh)``; a printed
part's mass is for a solid part (100 % infill): the slicer's grams are the print's.

    from form import massprops
    r = massprops.compute(st, p)                       # the design as built (or assembled, if it declares an assembly)
    r = massprops.compute(st, p, pose={"lid_hinge": 90})
    r = massprops.compute(st, p, material="AL-6061")   # "what if it were aluminium", nothing saved
    massprops.BENCH                                    # the Bench entry (form/studies.py registers it)
"""
from __future__ import annotations

import json
import math

import numpy as np

VERSION = 1                       # part of every key: change the computation, change this
EVIDENCE_BREP = "computed (B-rep)"
EVIDENCE_MESH = "computed (closed mesh)"
G_MM2_TO_KG_M2 = 1e-9             # 1 g·mm² = 1e-3 kg · 1e-6 m²


# ── kernel side (worker process only) ─────────────────────────────────────────────────────────────────────────

_ANALYTIC = {"PLANE", "CYLINDER", "CONE", "SPHERE", "TORUS"}


def _freeform(shape) -> bool:
    """Whether any face is not one of the analytic surfaces (B-spline, Bézier, revolution, extrusion, offset...)."""
    for f in shape.faces():
        if str(getattr(f.geom_type, "name", f.geom_type)).upper() not in _ANALYTIC:
            return True
    return False


def unit_props(shape) -> dict:
    """Volume (mm³), centroid (mm) and inertia about the centroid at density 1 (mm⁵) of a solid or compound."""
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    g = GProp_GProps()
    err = None
    method = "exact (Gauss integration of analytic faces)"
    if _freeform(shape):
        err = float(BRepGProp.VolumeProperties_s(shape.wrapped, g, 1e-7, True))
        method = "adaptive integration (free-form faces)"
    else:
        BRepGProp.VolumeProperties_s(shape.wrapped, g, True)
    vol = float(g.Mass())
    c = g.CentreOfMass()
    M = g.MatrixOfInertia()
    inertia = [[float(M.Value(i, j)) for j in (1, 2, 3)] for i in (1, 2, 3)]
    if vol < 0:                    # an inside-out solid: the integrals change sign together
        vol, inertia = -vol, [[-x for x in row] for row in inertia]
    return {"volume_mm3": vol, "centroid_mm": [float(c.X()), float(c.Y()), float(c.Z())], "inertia_mm5": inertia,
            "method": method, **({"relative_error": err} if err is not None else {})}


def op_massprops(key, recipe_id, values, tol=0.1):
    """Unit-density mass properties of every part (print frame) and the assembly declaration, resolved."""
    from . import assembly as asm
    from . import kernel
    model = kernel._get_near(key, recipe_id, values, tol)
    mesh = bool(getattr(model["recipe"], "mesh", False))
    a = asm.get(model)
    parts, spec, err = [], None, None
    if a is not None and not a.get("error"):
        for pt, s in zip(a["spec"].parts, a["printed"]):
            parts.append({"id": pt.id, "label": pt.label, "solid": pt.solid, "material": pt.material, **unit_props(s)})
        spec = a["spec"].public()
    else:
        err = a.get("error") if a else None
        parts.append({"id": "", "label": "Design", "solid": None, "material": "", **unit_props(model["shape"])})
    return {"version": VERSION, "parts": parts, "assembly": spec, "assembly_error": err, "mesh": mesh,
            "evidence": EVIDENCE_MESH if mesh else EVIDENCE_BREP}


KERNEL_OPS = {"massprops": op_massprops}


# ── studio side (no OCCT) ─────────────────────────────────────────────────────────────────────────────────────

def _geom_path(st, p: dict, rev: int | None = None):
    from .studio import H
    r = st.rev(p, rev)
    key = H("mass", VERSION, st.keys(p, r["n"])["geometry"])
    return r, key, st.dir(p["id"]) / "artifacts" / "mass" / f"geom-{key}.json"


def stored(st, p: dict, rev: int | None = None) -> bool:
    """Whether the geometry of this revision is already measured (so compute() needs no kernel call)."""
    try:
        return _geom_path(st, p, rev)[2].exists()
    except Exception:                           # noqa: BLE001 - a project without a head: nothing stored
        return False


def geometry(st, p: dict, rev: int | None = None) -> dict:
    """The unit-density properties of a revision (head by default), from the store or computed once."""
    from . import fsutil
    r, key, path = _geom_path(st, p, rev)
    gk = st.keys(p, r["n"])["geometry"]
    if path.exists():
        try:
            out = json.loads(path.read_text(encoding="utf-8"))
            out["key"] = key
            return out
        except ValueError:
            pass
    out = st._k("massprops", timeout=300, key=gk, recipe_id=st.rid(p, r["n"]), values=r["values"], p=p, rev=r["n"])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(out), encoding="utf-8")
    fsutil.replace(tmp, path)
    out["key"] = key
    return out


def _assembly(public: dict):
    """An Assembly rebuilt from its public form (parts with their solids resolved), for poses."""
    from dataclasses import fields
    from .recipes.assembly import Assembly, Joint, Part
    pf = {f.name for f in fields(Part)}
    jf = {f.name for f in fields(Joint)}
    parts = [Part(**{k: (tuple(v) if isinstance(v, list) else v) for k, v in d.items() if k in pf}) for d in public["parts"]]
    joints = [Joint(**{k: (tuple(v) if isinstance(v, list) else v) for k, v in d.items() if k in jf}) for d in public["joints"]]
    return Assembly(parts=parts, joints=joints, derived=bool(public.get("derived")))


def clean_pose(spec, pose) -> dict:
    """{joint id: value} checked against the declaration: unknown joints and values outside a joint's range are refused."""
    from .studio import StudioError
    if not pose:
        return {}
    if not isinstance(pose, dict):
        raise StudioError("A pose is {joint id: value}.", 'For example {"lid_hinge": 90} (degrees for a hinge, mm for a slide).')
    if spec is None:
        raise StudioError("This design declares no assembly, so it has no joints to pose.", "Leave pose out.")
    js = {j.id: j for j in spec.joints if j.kind != "fixed"}
    out = {}
    for k, v in pose.items():
        if k not in js:
            raise StudioError(f"Unknown joint “{k}”.", "Joints: " + (", ".join(js) or "none that move") + ".")
        try:
            v = float(v)
        except (TypeError, ValueError):
            raise StudioError(f"The value of joint “{k}” is not a number.")
        lo, hi = js[k].range
        if not (min(lo, hi) - 1e-9 <= v <= max(lo, hi) + 1e-9):
            unit = "°" if js[k].kind == "hinge" else " mm"
            raise StudioError(f"{v:g}{unit} is outside the range of joint “{k}” ({lo:g} to {hi:g}{unit}).")
        out[k] = v
    return out


def shift(inertia, mass, d) -> np.ndarray:
    """Parallel-axis term: the inertia of a point mass `mass` at offset d from the reference point."""
    d = np.asarray(d, float)
    return mass * (float(d @ d) * np.eye(3) - np.outer(d, d))


def principal(inertia) -> dict:
    """Principal moments (ascending) and axes (unit vectors, a right-handed set) of a symmetric 3x3 tensor."""
    I = np.asarray(inertia, float)
    I = (I + I.T) / 2
    w, V = np.linalg.eigh(I)
    if np.linalg.det(V) < 0:
        V[:, 2] = -V[:, 2]
    for k in range(3):                       # a stable sign: the largest component of each axis is positive
        if V[np.argmax(np.abs(V[:, k])), k] < 0:
            V[:, k] = -V[:, k]
    if np.linalg.det(V) < 0:
        V[:, 2] = -V[:, 2]
    scale = max(abs(float(w[-1])), 1e-30)
    repeated = [[i, j] for i in range(3) for j in range(i + 1, 3) if abs(float(w[i] - w[j])) <= 1e-9 * scale]
    return {"moments": [float(x) for x in w], "axes": [[float(V[i, k]) for i in range(3)] for k in range(3)],
            "repeated": repeated}


def combine(rows: list) -> dict | None:
    """Total of [{"mass", "com", "inertia"}] (inertia about each row's own centre): mass, centre and inertia about it."""
    M = sum(r["mass"] for r in rows)
    if M <= 0:
        return None
    C = sum(r["mass"] * np.asarray(r["com"], float) for r in rows) / M
    I = np.zeros((3, 3))
    for r in rows:
        I += np.asarray(r["inertia"], float) + shift(None, r["mass"], np.asarray(r["com"], float) - C)
    return {"mass": M, "com": C, "inertia": I}


def _r(x, n=10):
    """Rounded to n significant digits (10: far below any input tolerance), for the record (the computation keeps full precision)."""
    if isinstance(x, (list, tuple, np.ndarray)):
        return [_r(v, n) for v in x]
    x = float(x)
    if x == 0 or not math.isfinite(x):
        return 0.0 if x == 0 else x
    return float(f"{x:.{n}g}")


def _block(mass_g, com, inertia_g_mm2) -> dict:
    I = np.asarray(inertia_g_mm2, float)
    pr = principal(I)
    c = np.asarray(com, float)
    origin = I + shift(None, mass_g, c)
    out = {"mass_g": _r(mass_g), "com_mm": _r(c), "inertia_g_mm2": _r(I), "inertia_origin_g_mm2": _r(origin),
           "inertia_kg_m2": _r(I * G_MM2_TO_KG_M2),
           "principal": {"moments_g_mm2": _r(pr["moments"]), "axes": _r(pr["axes"]), "repeated": pr["repeated"]},
           "gyration_mm": _r([math.sqrt(max(m, 0.0) / mass_g) for m in pr["moments"]]) if mass_g > 0 else None}
    if pr["repeated"]:
        out["principal"]["note"] = ("Two or more principal moments are equal: the axes in that plane are not unique "
                                    "(any pair at right angles is principal); the ones given are one choice.")
    return out


def _material_of(p: dict, part: dict, override: str | None, override_part: str, assume: str | None):
    """(material key or None, where it came from) for one part."""
    from . import materials
    if override and (not override_part or override_part == part["id"]):
        return materials.clean_material(override), "what if (not saved)"
    own = ((p.get("parts") or {}).get(part["id"]) or {}).get("material") if part["id"] else None
    m = materials._key(own)
    if m:
        return m, "chosen for this part"
    m = materials._key(part.get("material"))
    if m:
        return m, "declared in the design's code"
    m = materials._key(p.get("material"))
    if m:
        return m, "chosen for the design"
    if assume:
        return materials.clean_material(assume), "assumed (no material chosen)"
    return None, None


def compute(st, p: dict, part: str = "", pose: dict | None = None, material: str | None = None,
            frame: str | None = None, rev: int | None = None, assume: str | None = None) -> dict:
    """Mass properties of a revision (head by default): every part and the total, at a pose.

    part: report only this part (the total is still that of the whole). pose: {joint id: value} (assembled frame).
    material: a what-if material for every part (or for `part`), nothing saved. frame: "assembled" (default for a
    declared assembly) or "as_built" (the solids where the design builds them). assume: a material for parts that have
    none (labelled assumed); without it such parts have no mass."""
    from . import material_library as ml
    from . import materials
    from .studio import H, StudioError
    try:
        if material:
            materials.clean_material(material)
    except ValueError as e:
        raise StudioError(str(e), materials.known())
    r = st.rev(p, rev)
    g = geometry(st, p, r["n"])
    spec = _assembly(g["assembly"]) if g.get("assembly") else None
    declared = spec is not None and not spec.derived
    if frame not in (None, "", "assembled", "as_built"):
        raise StudioError("frame is \"assembled\" or \"as_built\".")
    fr = frame or ("assembled" if declared else "as_built")
    if fr == "assembled" and spec is None:
        fr = "as_built"
    if fr == "assembled":
        pose = clean_pose(spec, pose)
    elif pose:
        raise StudioError("A pose moves the parts of an assembly; this is the design as built.",
                          "Leave pose out, or pass frame=\"assembled\" for a design that declares an assembly.")
    else:
        pose = {}
    ids = [x["id"] for x in g["parts"]]
    if part and part not in ids:
        raise StudioError(f"Unknown part “{part}”.", "Parts: " + (", ".join(i for i in ids if i) or "this design is one body") + ".")
    rows, out_parts, missing, dens_used = [], [], [], {}
    for x in g["parts"]:
        mk, why = _material_of(p, x, material, part if material else "", assume)
        if fr == "assembled" and spec is not None and x["id"]:
            W = spec.world(x["id"], pose)
        else:
            W = np.eye(4)
        R, t = W[:3, :3], W[:3, 3]
        c = R @ np.asarray(x["centroid_mm"], float) + t
        I1 = R @ np.asarray(x["inertia_mm5"], float) @ R.T          # mm⁵ at density 1
        row = {"id": x["id"], "label": x["label"], "volume_mm3": _r(x["volume_mm3"]), "centroid_mm": _r(c),
               "method": x.get("method"), **({"relative_error": x["relative_error"]} if "relative_error" in x else {})}
        if mk:
            d = ml.density(mk)
            rho = d["value"] * 1e-6                                  # kg/m³ -> g/mm³
            info = materials.info(mk) or {}
            row["material"] = {"id": mk, "label": info.get("label", mk), "kind": info.get("kind"), "why": why,
                               "density_kg_m3": d["value"], "density_source": d["source"],
                               "density_evidence": d["evidence"], **({"density_url": d["url"]} if d.get("url") else {})}
            dens_used[mk] = d
            m = x["volume_mm3"] * rho
            row.update(_block(m, c, I1 * rho))
            if info.get("kind") == "filament":
                row["note"] = "Mass of a solid part (100 % infill); a print with infill weighs less: the slicer's grams are the print's (simulated)."
            rows.append({"mass": m, "com": c, "inertia": I1 * rho})
        else:
            row["material"] = None
            missing.append(x["id"])
        row["_I1"], row["_c"], row["_v"] = I1, c, x["volume_mm3"]
        out_parts.append(row)
    total = None
    if not missing:
        tot = combine(rows)
        if tot:
            total = _block(tot["mass"], tot["com"], tot["inertia"])
    V = sum(x["_v"] for x in out_parts)
    cv = sum(x["_v"] * x["_c"] for x in out_parts) / V if V > 0 else np.zeros(3)
    for x in out_parts:
        for k in ("_I1", "_c", "_v"):
            x.pop(k)
    notes = []
    if missing:
        names = [x["label"] for x in out_parts if x["id"] in missing]
        notes.append(("No material is chosen" if len(out_parts) == 1 else f"No material for {', '.join(names)}")
                     + ": no mass is given (never a default). Choose one with set_appearance (or form appearance "
                       "--material), or ask with material= for a what-if.")
    if any(x.get("material") and x["material"]["kind"] == "filament" for x in out_parts):
        notes.append("Printed parts are taken as solid (100 % infill) and isotropic: the slicer's grams are the print's.")
    if fr == "assembled" and spec is not None:
        notes.append("Assembled frame" + (f" at {', '.join(f'{k} = {v:g}' for k, v in pose.items())}" if pose else
                                          " with every joint at 0") + ".")
    sl = st._sliced_mass(p, r["n"]) if hasattr(st, "_sliced_mass") else None
    shown = [x for x in out_parts if x["id"] == part] if part else out_parts
    key = H("massprops", g["key"], fr, pose, [(x["id"], (x["material"] or {}).get("id"), (x["material"] or {}).get("density_kg_m3"))
                                               for x in out_parts])
    res = {"project": p["id"], "rev": r["n"], "key": key, "geometry_key": g["key"], "evidence": g["evidence"],
           "frame": fr, "pose": pose, "joints": [{"id": j.id, "label": j.label, "kind": j.kind, "range": list(j.range)}
                                                 for j in (spec.joints if spec else []) if j.kind != "fixed"],
           "units": {"length": "mm", "mass": "g", "inertia": "g·mm² (inertia_kg_m2: kg·m²)", "density": "kg/m³"},
           "volume_mm3": _r(V), "volume_centroid_mm": _r(cv), "total": total, "parts": shown, "missing_material": missing,
           "materials": {k: v for k, v in dens_used.items()}, "notes": notes,
           **({"slice_filament_g": sl, "slice_note": "the slicer's estimate for the print (simulated), with its infill"} if sl else {})}
    res["text"] = text(res)
    return res


def headline(res: dict) -> str:
    """One line for the size line, the Bench and concept cards: '412 g · computed: volume × 2700 kg/m³ (AL-6061)'."""
    t = res.get("total")
    if not t:
        return "no material chosen"
    mats = {x["material"]["id"]: x["material"] for x in res["parts"] if x.get("material")}
    if len(mats) == 1:
        m = next(iter(mats.values()))
        return f"{t['mass_g']:.4g} g · computed: volume × {m['density_kg_m3']:g} kg/m³ ({m['label']})"
    return f"{t['mass_g']:.4g} g · computed: volume × density of {len(mats)} materials"


def text(res: dict) -> str:
    """The result in sentences, for agents and the CLI."""
    out = []
    t = res.get("total")
    if t:
        c = t["com_mm"]
        pm = t["principal"]["moments_g_mm2"]
        out.append(f"Mass {t['mass_g']:.6g} g, centre of mass at ({c[0]:.4g}, {c[1]:.4g}, {c[2]:.4g}) mm "
                   f"({res['frame'].replace('_', ' ')}), principal moments {pm[0]:.5g}, {pm[1]:.5g}, {pm[2]:.5g} g·mm², "
                   f"{res['evidence']}.")
    else:
        c = res["volume_centroid_mm"]
        out.append(f"Volume {res['volume_mm3']:.6g} mm³, centroid of the volume at ({c[0]:.4g}, {c[1]:.4g}, {c[2]:.4g}) mm "
                   "(the centre of mass only if the density is uniform).")
    for x in res["parts"]:
        if x.get("material"):
            m = x["material"]
            out.append(f"{x['label']}: {x['mass_g']:.6g} g = {x['volume_mm3']:.6g} mm³ × {m['density_kg_m3']:g} kg/m³ "
                       f"({m['label']}, {m['why']}; density: {m['density_source']}, {m['density_evidence']}).")
    out += res.get("notes", [])
    return " ".join(out)


# ── the Bench (form/studies.py, Wave A) ───────────────────────────────────────────────────────────────────────

def study_key(st, p: dict, rev: int | None = None) -> str:
    """The study's key for a revision at rest: geometry, method version and every part's material and density."""
    from . import material_library as ml
    from .studio import H
    r = st.rev(p, rev)
    mats = [p.get("material"), sorted(((k, (v or {}).get("material")) for k, v in (p.get("parts") or {}).items()
                                       if isinstance(v, dict)), key=str)]
    dens = [ml.density(m)["value"] if m else None for m in [p.get("material")] if m]
    return H("massprops", VERSION, st.keys(p, r["n"])["geometry"], mats, dens)


def run_study(st, p: dict, **inputs) -> dict:
    """What the Bench runs: compute() with its inputs (part, pose, material, frame), plus the headline."""
    res = compute(st, p, **{k: v for k, v in inputs.items() if k in ("part", "pose", "material", "frame", "rev")})
    res["headline"] = headline(res)
    return res


BENCH = {"id": "mass", "group": "studies", "label": "Mass & inertia", "stage": "review",
         "needs": ["geometry"], "inputs": ["part", "pose", "material", "frame"],
         "evidence": EVIDENCE_BREP, "key": study_key, "run": run_study, "headline": headline,
         "mcp": "mass_properties", "cli": "form mass <project>"}
