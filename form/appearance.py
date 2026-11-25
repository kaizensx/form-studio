"""Material zones for photos: a design says which features are which material, and render_photo gives each its own.

    class Design(Recipe):
        def appearance(self, v):
            return [{"features": ["visor"], "finish": "smoke", "color": "#1b2026"},
                    {"features": ["trim"], "finish": "rubber", "color": "#151617"},
                    {"features": ["shell", "spoiler"], "finish": "carbon", "color": "#2a2c30"}]

A zone may name an engineering material instead of a finish and colour: {"features": ["body"], "material":
"aluminium 6061"} takes the material's finish and colour from form/material_library.py (bd_materials' typical look:
aluminium 6061/7075, steel, stainless, brass, copper, titanium, oak, walnut, POM, PTFE, ...); a finish or colour
given beside it wins. The zone keeps the material id and its density (g/cm³), so a part's mass can be computed.

Features no zone names take the material and colour asked for in render_photo. Finishes are the Blender adapter's
(form/adapters/blender.py FINISHES): matte, petg, silk, gloss, carbon, smoke, rubber, metal. A zone is an
illustration choice, like the photo itself: it is not evidence of any material property.

op_photo_zones runs in the kernel worker: it textures the mesh (the design's mesh textures, as the exported STL has
them) and writes one STL per zone, in the design's own frame.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np

HEX = re.compile(r"#[0-9a-fA-F]{6}")


def validate(zones, features: set, finishes) -> list[dict]:
    """Clean a design's appearance() list. Raises ValueError naming the zone that is wrong."""
    out = []
    for i, z in enumerate(zones or []):
        if not isinstance(z, dict):
            raise ValueError(f"appearance()[{i}] is not a dict")
        fs = [str(f) for f in (z.get("features") or [])]
        if not fs:
            raise ValueError(f"appearance()[{i}] names no features")
        unknown = [f for f in fs if f not in features]
        if unknown:
            raise ValueError(f"appearance()[{i}] names unknown features: {', '.join(unknown)}")
        mat = None
        if z.get("material"):
            from . import material_library
            try:
                mat = material_library.get(str(z["material"]))
            except KeyError as e:
                raise ValueError(f"appearance()[{i}]: {e.args[0] if e.args else e}")
        fin = str(z.get("finish") or (mat["finish"] if mat else "matte"))
        if fin not in finishes:
            raise ValueError(f"appearance()[{i}]: unknown finish {fin!r} (finishes: {', '.join(finishes)})")
        col = str(z.get("color") or (mat["color"] if mat else "#eeece6"))
        if not HEX.fullmatch(col):
            raise ValueError(f"appearance()[{i}]: colour {col!r} is not #rrggbb")
        row = {"features": fs, "finish": fin, "color": col.lower(),
               "label": str(z.get("label") or (mat["name"] if mat else fin))}
        if mat:
            row.update(material=mat["id"], density_g_cm3=round(mat["density_kg_m3"] / 1000.0, 3))
        out.append(row)
    return out


def declared(recipe, values) -> list[dict]:
    from .adapters.blender import FINISHES
    fn = getattr(recipe, "appearance", None)
    if fn is None:
        return []
    try:
        zones = fn(values) or []
    except Exception as e:                       # a broken appearance() must not hide the photo
        raise ValueError(f"appearance() raised {type(e).__name__}: {e}")
    return validate(zones, {f.id for f in recipe.features}, FINISHES)


def op_photo_zones(key, recipe_id, values, out_dir, tol=0.05):
    """One binary STL per material zone (and "rest" for features no zone names). Returns {"zones": [{stl, finish,
    color, features, triangles}], "bbox": [lo, hi]} or {"zones": []} when the design declares none."""
    from . import kernel
    from .craft import meshtex
    model = kernel._get(key, recipe_id, values, tol)
    zones = declared(model["recipe"], model["values"])
    if not zones:
        return {"zones": []}
    tex = kernel._textured(model, meshtex.EXPORT_BUDGET)
    if tex is not None:
        V, F, tags, _info = tex
    else:
        P, T = kernel._mesh_arrays(model)
        V, F = P, T
        tags = np.concatenate([np.full(len(f["T"]), f["feature"], dtype=object) for f in model["faces"]])
    tags = np.asarray(tags).astype(str)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    assigned = np.zeros(len(F), bool)
    res = []
    for i, z in enumerate(zones):
        sel = np.isin(tags, z["features"]) & ~assigned
        assigned |= sel
        if not sel.any():
            continue
        f = out / f"zone{i}.stl"
        meshtex.write_stl(f, V, F[sel], name=f"Form Studio zone {i}")
        res.append({**z, "stl": str(f), "triangles": int(sel.sum())})
    if (~assigned).any():
        f = out / "rest.stl"
        meshtex.write_stl(f, V, F[~assigned], name="Form Studio zone rest")
        res.append({"features": sorted(set(tags[~assigned].tolist())), "finish": None, "color": None, "label": "rest",
                    "stl": str(f), "triangles": int((~assigned).sum())})
    lo, hi = V[np.unique(F)].min(0), V[np.unique(F)].max(0)
    return {"zones": res, "bbox": [lo.tolist(), hi.tolist()]}


KERNEL_OPS = {"photo_zones": op_photo_zones}
