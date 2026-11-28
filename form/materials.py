"""Colours and materials of a design: for the whole design, or per part.

Kept in the project file in the fields the slicer integration reads too (form/adapters picks the filament per plate
from them)::

    "color": "#d8d3c8" | null,  "material": "PETG" | null,
    "parts": {"<part id>": {"color": "#...", "material": "PLA", ...other per-part print settings...}}

A part's own colour or material wins over the design's. Part ids are the assembly's (``lid``, ``body``, or
``part1``… for separate bodies with no declaration); a single-body design uses the design entry only. Material keys
are PLA, PETG, ABS, ASA, TPU, PA, PC and the fibre-filled PLA-CF, PETG-CF, PA-CF; input is read case-insensitively
("nylon" is PA).

Form Studio uses the material for the material notes in the checks (heat, sunlight, warping, flexible filament,
fibre-filled), the solid-mass estimate and the names in the 3MF it writes. Property values are typical figures from
filament datasheets; brands differ. They feed heuristics, never a computed result.

A design that is not printed (CNC, casting, rendering) can also take an engineering material: aluminium 6061 and
7075, mild and stainless steel, brass, copper, titanium, woods and engineering plastics (ENGINEERING, from
form/material_library.py: bd_materials' typical density and look). It gives the design its colour and finish and the
computed mass (volume x typical density); it never picks a filament, and the filament list above is unchanged.
"""
from __future__ import annotations

import re
from pathlib import Path

MATERIALS = {
    "PLA": {"label": "PLA", "process": "fdm", "density_g_cm3": 1.24, "heat_c": 55, "nozzle_c": [190, 220], "bed_c": [50, 60],
            "color": "#e9e5dc", "warp": "low", "uv": "poor", "flex": "rigid",
            "note": "Easy to print and stiff. Softens from about 55 °C and creeps under a constant load when warm."},
    "PETG": {"label": "PETG", "process": "fdm", "density_g_cm3": 1.27, "heat_c": 70, "nozzle_c": [230, 250], "bed_c": [70, 85],
             "color": "#cfe3e8", "warp": "low", "uv": "fair", "flex": "tough",
             "note": "Tougher than PLA and fine in warm water. Strings; bridges sag a little more."},
    "ABS": {"label": "ABS", "process": "fdm", "density_g_cm3": 1.04, "heat_c": 95, "nozzle_c": [240, 260], "bed_c": [95, 110],
            "color": "#e4e1da", "warp": "high", "uv": "poor", "flex": "tough",
            "note": "Heat resistant and tough. Shrinks as it cools: large flat parts lift without an enclosure."},
    "ASA": {"label": "ASA", "process": "fdm", "density_g_cm3": 1.07, "heat_c": 95, "nozzle_c": [240, 260], "bed_c": [90, 110],
            "color": "#dcdad5", "warp": "high", "uv": "good", "flex": "tough",
            "note": "Like ABS with good resistance to sunlight. Needs an enclosure for large parts."},
    "TPU": {"label": "TPU", "process": "fdm", "density_g_cm3": 1.21, "heat_c": 60, "nozzle_c": [220, 240], "bed_c": [30, 60],
            "color": "#3b3f44", "warp": "low", "uv": "fair", "flex": "flexible",
            "note": "Flexible and impact resistant (95A). Print slowly; bridges and steep overhangs droop."},
    "PA": {"label": "Nylon (PA)", "process": "fdm", "density_g_cm3": 1.14, "heat_c": 80, "nozzle_c": [250, 280], "bed_c": [70, 90],
           "color": "#efeadc", "warp": "high", "uv": "fair", "flex": "tough",
           "note": "Tough and wear resistant. Absorbs moisture: dry it before printing. Warps on large flat parts."},
    "PC": {"label": "Polycarbonate (PC)", "process": "fdm", "density_g_cm3": 1.20, "heat_c": 115, "nozzle_c": [260, 300], "bed_c": [100, 120],
           "color": "#d6dde2", "warp": "high", "uv": "fair", "flex": "tough",
           "note": "Strongest and most heat resistant of the common filaments. Needs a hot, enclosed printer."},
    "PLA-CF": {"label": "PLA-CF (carbon fibre)", "process": "fdm", "density_g_cm3": 1.29, "heat_c": 60, "nozzle_c": [210, 240], "bed_c": [50, 60],
               "color": "#3a3c3f", "warp": "low", "uv": "poor", "flex": "rigid", "fibre": True,
               "note": "Stiffer than PLA with a matte finish. Abrasive: needs a hardened nozzle."},
    "PETG-CF": {"label": "PETG-CF (carbon fibre)", "process": "fdm", "density_g_cm3": 1.30, "heat_c": 75, "nozzle_c": [240, 260], "bed_c": [70, 80],
                "color": "#35383b", "warp": "low", "uv": "fair", "flex": "tough", "fibre": True,
                "note": "Stiff and dimensionally stable. Abrasive: needs a hardened nozzle."},
    "PA-CF": {"label": "PA-CF (carbon fibre)", "process": "fdm", "density_g_cm3": 1.20, "heat_c": 150, "nozzle_c": [270, 300], "bed_c": [80, 100],
              "color": "#2f3134", "warp": "high", "uv": "fair", "flex": "tough", "fibre": True,
              "note": "Very stiff and heat resistant. Abrasive and hygroscopic: hardened nozzle, dry filament, enclosure."},
}
_ALIASES = {"NYLON": "PA", "PA/NYLON": "PA", "PA6": "PA", "PA12": "PA", "TPU95A": "TPU", "TPU 95A": "TPU",
            "POLYCARBONATE": "PC", "PLA+CF": "PLA-CF", "PETG+CF": "PETG-CF", "PA+CF": "PA-CF", "PACF": "PA-CF"}

# Engineering materials for designs that are not printed: id -> (form/material_library name, label, note). Density,
# colour and finish come from the library (bd_materials typical values); the note is a rule of thumb.
ENGINEERING_SPEC = {
    "AL-6061": ("alu_g6061_t6", "Aluminium 6061-T6",
                "The general-purpose machining aluminium: light, stiff for its weight, anodises well."),
    "AL-7075": ("alu_g7075_t6", "Aluminium 7075-T6",
                "High-strength aluminium for stressed parts; anodises well, poor to weld."),
    "STEEL": ("mild_steel", "Mild steel", "Strong, cheap, easy to machine and weld; rusts unless plated or painted."),
    "STAINLESS": ("stainless", "Stainless steel 304", "Resists corrosion; slower to machine than mild steel."),
    "BRASS": ("brass", "Brass C360", "Free-machining; fittings, bushings and decorative parts."),
    "COPPER": ("copper", "Copper C110", "Conducts heat and electricity best; soft and gummy to machine."),
    "TITANIUM": ("titanium", "Titanium grade 5", "Strong and light, resists corrosion; slow and costly to machine."),
    "OAK": ("oak", "Oak", "Hard, open-grained hardwood; cuts cleanly along the grain."),
    "WALNUT": ("walnut", "Walnut", "Dark, fine-grained hardwood; machines and finishes well."),
    "MAPLE": ("maple", "Maple", "Pale, dense hardwood; holds small detail."),
    "PINE": ("pine", "Pine", "Light softwood; dents easily, cheap for jigs and furniture."),
    "POM": ("pom", "Acetal (POM)", "Low friction and dimensionally stable; machines cleanly. Gears and bushings."),
    "PTFE": ("ptfe", "PTFE", "Very low friction and chemically inert; soft, creeps under load."),
    "PEEK": ("peek", "PEEK", "High-temperature engineering plastic; strong, stiff and costly."),
    "PMMA": ("pmma", "Acrylic (PMMA)", "Clear; laser-cuts with polished edges; brittle under impact."),
}
ENGINEERING_ALIASES = {"ALUMINIUM": "AL-6061", "ALUMINUM": "AL-6061", "ALU": "AL-6061", "6061": "AL-6061",
                       "AL6061": "AL-6061", "ALUMINIUM 6061": "AL-6061", "ALUMINUM 6061": "AL-6061",
                       "7075": "AL-7075", "AL7075": "AL-7075", "ALUMINIUM 7075": "AL-7075", "ALUMINUM 7075": "AL-7075",
                       "MILD STEEL": "STEEL", "MILD_STEEL": "STEEL", "STAINLESS STEEL": "STAINLESS", "SS304": "STAINLESS",
                       "304": "STAINLESS", "TI": "TITANIUM", "TI6AL4V": "TITANIUM", "ACETAL": "POM", "DELRIN": "POM",
                       "TEFLON": "PTFE", "ACRYLIC": "PMMA", "PLEXIGLASS": "PMMA"}


def engineering() -> dict:
    """The engineering materials, {id: {"label", "kind": "engineering", "category", "density_g_cm3", "color",
    "finish", "note", "source"}}, read from form/material_library.py (once). A material the library cannot give is
    left out, never guessed."""
    global _ENG
    if _ENG is None:
        from . import material_library as ml
        out = {}
        for k, (name, label, note) in ENGINEERING_SPEC.items():
            try:
                m = ml.get(name)
            except KeyError:
                continue
            out[k] = {"label": label, "kind": "engineering", "process": "machined", "category": m["category"],
                      "density_g_cm3": round(m["density_kg_m3"] / 1000.0, 3), "color": m["color"],
                      "finish": m["finish"], "note": note, "source": m["source"]}
        _ENG = out
    return _ENG


_ENG = None


def info(m) -> dict | None:
    """A material by its stored key: a printing filament or an engineering material; None when unknown."""
    if m in MATERIALS:
        return {"kind": "filament", **MATERIALS[m]}
    return engineering().get(m)


# colours offered in the app; any #rrggbb is accepted
SWATCHES = ["#e9e5dc", "#2b2d30", "#8a9097", "#c8483c", "#e08a2c", "#e6c34a", "#5e9e5a", "#3f7fbf", "#6d5bd0", "#d9708f", "#7a5a3c", "#d4e4ec"]

_HEX = re.compile(r"#[0-9a-fA-F]{6}")


def catalogue() -> dict:
    return {"materials": [{"id": k, "kind": "filament", **v} for k, v in MATERIALS.items()]
            + [{"id": k, **v} for k, v in engineering().items()], "swatches": SWATCHES,
            "source": "Typical values from filament datasheets; brands differ. Engineering materials: bd_materials "
                      "typical values (form/material_library.py)."}


def known() -> str:
    return "Filaments: " + ", ".join(MATERIALS) + ". Engineering (not printed): " + ", ".join(engineering()) + "."


def clean_color(c):
    if c in (None, ""):
        return None
    c = str(c).strip()
    if not _HEX.fullmatch(c):
        raise ValueError("A colour is #rrggbb.")
    return c.lower()


def clean_material(m):
    if m in (None, ""):
        return None
    k = str(m).strip().upper()
    k = _ALIASES.get(k, k)
    if k in MATERIALS:
        return k
    k = ENGINEERING_ALIASES.get(k, k.replace(" ", "-"))
    if k in engineering():
        return k
    raise ValueError("Unknown material. " + known())


def _key(m):
    """A stored material, normalised (another tool may have written "petg" or "Nylon"); None if unknown."""
    try:
        return clean_material(m)
    except ValueError:
        return None


def appearance(p: dict) -> dict:
    """{color, material, parts: {id: {color, material}}} read from the project's own fields."""
    parts = {}
    for k, v in (p.get("parts") or {}).items():
        if isinstance(v, dict) and (v.get("color") or v.get("material")):
            parts[k] = {x: v.get(x) for x in ("color", "material") if v.get(x)}
    return {"color": p.get("color"), "material": p.get("material"), "parts": parts}


def resolved(p: dict, part: str = "") -> dict:
    """The colour and material a part is shown and printed in: its own, else the design's, else the material's colour."""
    a = appearance(p)
    own = (a["parts"].get(part) or {}) if part else {}
    mat = _key(own.get("material")) or _key(a.get("material"))
    col = own.get("color") or a.get("color") or ((info(mat) or {}).get("color") if mat else None)
    return {"color": col, "material": mat}


def set_appearance(st, pid: str, part: str = "", color="keep", material="keep", by: str = "you") -> dict:
    """Set (or clear, with None) the colour and/or material of the design (part "") or of one part. Other per-part
    settings in project["parts"] (written by the print setup) are kept."""
    from .studio import StudioError
    try:
        c = clean_color(color) if color != "keep" else "keep"
        m = clean_material(material) if material != "keep" else "keep"
    except ValueError as e:
        raise StudioError(str(e), known())
    part = re.sub(r"[^a-zA-Z0-9_-]", "", str(part or ""))[:40]
    with st.lock(pid):
        p = st.load(pid)
        from . import purpose as purpose_mod
        if m not in ("keep", None) and m not in MATERIALS and not purpose_mod.is_model(p):
            raise StudioError(f"{info(m)['label']} is not a printing filament, and this design is made for 3D printing.",
                              "Pick a filament (" + ", ".join(MATERIALS) + "), or make the design a 3D model "
                              "(purpose \"model\", e.g. for CNC) to give it an engineering material.")
        if part:
            if not isinstance(p.get("parts"), dict):
                p["parts"] = {}
            slot = p["parts"].setdefault(part, {})
        else:
            slot = p
        for k, v in (("color", c), ("material", m)):
            if v == "keep":
                continue
            if v:
                slot[k] = v
            elif part:
                slot.pop(k, None)
            else:
                slot[k] = None
        if part and not p["parts"][part]:
            del p["parts"][part]
        p.pop("appearance", None)
        st.save(p)
    what = []
    if c != "keep":
        what.append(f"colour {c}" if c else "colour cleared")
    if m != "keep":
        what.append(f"material {info(m)['label']}" if m else "material cleared")
    if what:
        st.activity(pid, "appearance", (f"Part {part}: " if part else "Design: ") + ", ".join(what) + ".", by=by)
    return appearance(p)


def fingerprint(p: dict):
    """What the material notes in the checks depend on, or None when no material is chosen (checks keys unchanged)."""
    a = appearance(p)
    mats = sorted({x for x in [_key(a.get("material"))] + [_key(v.get("material")) for v in a["parts"].values()] if x})
    if not mats:
        return None
    return [mats, sorted((k, _key(v.get("material"))) for k, v in a["parts"].items() if v.get("material")), _key(a.get("material")),
            (p.get("brief") or {}).get("text", ""), p.get("name", "")]


# words in the brief or the name that say where the part lives
_HOT = re.compile(r"\b(shower|bath|dishwasher|kettle|coffee|hot water|steam|sauna|oven|radiator|heater)\b", re.I)
_CAR = re.compile(r"\b(car|dashboard|dash|windscreen|windshield|vehicle)\b", re.I)
_SUN = re.compile(r"\b(outdoor|outdoors|outside|garden|sun|sunlight|balcony|uv|weather)\b", re.I)


def check_items(p: dict, analysis: dict, ctx: dict) -> list:
    """Material notes as check rows (evidence heuristic), one per material in use. Empty when no material is chosen."""
    a = appearance(p)
    groups = {}
    for pid_ in [""] + sorted(a["parts"]):                 # "" = the design, and every part without its own material
        m = resolved(p, pid_)["material"]
        if m in MATERIALS:                                 # filament notes; an engineering material has none here
            groups.setdefault(m, []).append(pid_)
    if not groups:
        return []
    text = " ".join([(p.get("brief") or {}).get("text", ""), p.get("name", "")])
    row = next((r for r in analysis.get("orientation_table", []) if r["id"] == ctx.get("orientation")), None)
    out = []
    for m, parts in groups.items():
        M = MATERIALS[m]
        names = [x for x in parts if x] + (["other parts"] if "" in parts and a["parts"] else [])
        who = f" ({', '.join(names)})" if len(groups) > 1 and names else ""
        sid = f"material_{m.lower()}"
        notes, warn = [], False
        if M.get("fibre"):
            notes.append("Fibre-filled filament wears a brass nozzle quickly: print it with a hardened one.")
        if _CAR.search(text) and M["heat_c"] < 80:
            warn = True
            notes.append(f"A car interior in the sun passes 70 °C; {M['label']} softens from about {M['heat_c']} °C. ASA or PC hold their shape.")
        elif _HOT.search(text) and M["heat_c"] < 65:
            warn = True
            notes.append(f"The brief puts it near hot water or steam; {M['label']} softens from about {M['heat_c']} °C and creeps under load when warm. "
                         "PETG or ASA keep their shape better.")
        if _SUN.search(text) and M["uv"] == "poor":
            warn = True
            notes.append(f"It lives outdoors; {M['label']} degrades in sunlight. ASA is made for it.")
        if row and M["warp"] == "high":
            fp = max(row["footprint_mm"])
            if fp > 100 or row["contact_mm2"] > 5000:
                warn = True
                notes.append(f"{M['label']} shrinks as it cools; a {fp:.0f} mm footprint is likely to lift at the corners. "
                             "Print in an enclosure, with a brim.")
        if row and M["flex"] == "flexible" and (row["steep_mm2"] >= 1 or row["ceiling_mm2"] >= 1):
            warn = True
            notes.append(f"Flexible filament droops: {row['steep_mm2']:.0f} mm² of steep overhang and {row['ceiling_mm2']:.0f} mm² of flat "
                         "ceiling in this orientation. Reorient or add support.")
        thin = analysis.get("thin")
        if thin and M.get("fibre") and thin["t"] < 1.2:
            warn = True
            notes.append(f"Fibre-filled filament needs walls of three lines or more; the thinnest wall is {thin['t']:.2f} mm.")
        if not notes:
            notes.append(M["note"])
        out.append({"id": sid, "label": f"{M['label']} suits the part{who}", "status": "WARN" if warn else "PASS",
                    "value": f"{M['label']} · softens ~{M['heat_c']} °C",
                    "detail": " ".join(notes) + " Rule of thumb from typical datasheet values and the brief; brands differ.",
                    "evidence": "heuristic", "material": m, "parts": [x for x in parts if x]})
    return out


def mass_g(volume_mm3: float, material: str | None):
    """Solid mass: volume x typical density (for a filament, if printed 100% dense: an upper bound). None without a
    material."""
    m = _key(material)
    if m is None:
        return None
    return round(volume_mm3 / 1000.0 * info(m)["density_g_cm3"], 2)


def mass(p: dict, volume_mm3: float | None, part: str = "") -> dict | None:
    """The computed mass of a design (or part) in its material: {"grams", "material", "label", "density_g_cm3",
    "evidence", "source"}. None without a material or a volume."""
    m = resolved(p, part)["material"]
    if not m or not volume_mm3:
        return None
    i = info(m)
    return {"grams": mass_g(volume_mm3, m), "material": m, "label": i["label"], "density_g_cm3": i["density_g_cm3"],
            "evidence": "computed", "source": "modelled volume x typical density from "
            + ("filament datasheets, if printed solid" if i["kind"] == "filament" else i["source"].split(" (")[0])}


# ── 3MF with colours ────────────────────────────────────────────────────────

def op_parts_mesh(key, recipe_id, values, orientation="as_modelled", tol=0.01, ang=0.1):
    """Each printed body as a triangle mesh in the print orientation, placed as the STL places them (worker only).
    Bodies are numbered like form/assembly.py numbers them, so part ids line up."""
    import numpy as np
    from build123d import Compound
    from . import assembly, kernel
    model = kernel._get_near(key, recipe_id, values, 0.05)
    solids = assembly._ordered_solids(model["shape"])
    # one compound in that order, oriented and placed as the whole is (the compound keeps its children's order)
    whole = kernel._oriented(Compound(solids), orientation) if len(solids) > 1 else kernel._oriented(model["shape"], orientation)
    out = []
    for s in (whole.solids() if len(solids) > 1 else [whole]):
        verts, tris = s.tessellate(tol, ang)
        P = np.array([(v.X, v.Y, v.Z) for v in verts], dtype=np.float64)
        out.append({"P": P.round(5).tolist(), "T": [list(t) for t in tris]})
    return {"bodies": out}


KERNEL_OPS = {"parts_mesh": op_parts_mesh}


def threemf(st, p: dict, copies: int = 1) -> bytes:
    """A 3MF of the head revision as printed, one object per body, each with its colour and material name
    (3MF core basematerials). Slicers that read 3MF colours show them; the geometry is the exported STL's.

    A design made for printing is laid out on its printer's plates (form/plates.py), every part on a plate and as many
    plates as it takes, written the way the design's slicer reads several plates (form/plate3mf.py). A design whose
    slicer needs several files for that (PrusaSlicer, more than 9 plates) raises StudioError: `form pack <p> --3mf
    DIR` writes them all. A 3D model (purpose "model") is written as modelled, one plate-less scene."""
    import io
    import zipfile
    from xml.sax.saxutils import escape
    from . import purpose as purpose_mod
    if not purpose_mod.is_model(p) or copies > 1:
        import shutil
        import tempfile
        from . import plates
        from .studio import StudioError
        tmp = Path(tempfile.mkdtemp(prefix="form-3mf-", dir=str(st.dir(p["id"]))))
        try:
            out = plates.write_3mf(st, p, tmp, copies)
            if len(out["files"]) != 1:
                if not out["files"]:
                    b = out["too_big"][0] if out["too_big"] else None
                    raise StudioError((f"{b['label']} is larger than the plate however it lies." if b else
                                       "Nothing fits the plate."), " ".join(b["suggestions"]) if b else "", status=409)
                raise StudioError(f"These {out['plates']} plates take {len(out['files'])} files for {out['slicer']}.",
                                  f"Write them all with: form pack {p['id']} --3mf <folder>", status=409)
            return Path(out["files"][0]).read_bytes()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    r = st.rev(p)
    res = st._k("parts_mesh", timeout=300, key=st.keys(p, r["n"])["geometry"], recipe_id=st.rid(p, r["n"]), values=r["values"],
                orientation=p["orientation"], p=p)
    bodies = res["bodies"]
    try:
        v = st.view(p)
        ids = [x["id"] for x in (v.get("assembly") or {}).get("parts", [])] if v.get("assembly") and not v["assembly"].get("error") else []
        by_solid = {x["solid"]: x for x in (v.get("assembly") or {}).get("parts", [])} if ids else {}
    except Exception:
        by_solid = {}
    mats, objs = [], []
    for i, b in enumerate(bodies):
        part = by_solid.get(i, {}).get("id", "") if by_solid else ""
        label = by_solid.get(i, {}).get("label", "") if by_solid else ""
        rv = resolved(p, part)
        col = (rv["color"] or "#d8d3c8").upper() + "FF"
        name = (info(rv["material"])["label"] if rv["material"] else "Unassigned") + (f" · {label}" if label else "")
        mats.append(f'<base name="{escape(name)}" displaycolor="{col}"/>')
        vs = "".join(f'<vertex x="{x:.5f}" y="{y:.5f}" z="{z:.5f}"/>' for x, y, z in b["P"])
        ts = "".join(f'<triangle v1="{a}" v2="{c}" v3="{d}"/>' for a, c, d in b["T"])
        objs.append((i + 2, label or (part or f"Body {i + 1}"), i, vs, ts))
    model = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">',
             f'<metadata name="Title">{escape(p["name"])} r{r["n"]:02d}</metadata>',
             '<metadata name="Application">Form Studio</metadata>',
             '<resources>', '<basematerials id="1">' + "".join(mats) + '</basematerials>']
    for oid, name, k, vs, ts in objs:
        model.append(f'<object id="{oid}" type="model" name="{escape(name)}" pid="1" pindex="{k}"><mesh><vertices>{vs}</vertices>'
                     f'<triangles>{ts}</triangles></mesh></object>')
    model.append('</resources><build>' + "".join(f'<item objectid="{o[0]}"/>' for o in objs) + '</build></model>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
        z.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
        z.writestr("3D/3dmodel.model", "".join(model))
    return buf.getvalue()
