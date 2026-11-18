"""Colours and materials of a design: for the whole design, or per part.

Kept in the project file as::

    "appearance": {"color": "#d8d3c8" | null, "material": "petg" | null,
                   "parts": {"<part id>": {"color": "#...", "material": "..."}}}

A part's own colour or material wins over the design's. Part ids are the assembly's (``lid``, ``body``, or
``part1``… for separate bodies with no declaration); a single-body design uses the design entry only.

The material is a plain id from MATERIALS. Form Studio uses it for the material notes in the checks (heat, sunlight,
warping, flexible filament, resin), the solid-mass estimate and the colours in the 3MF it writes. Choosing the
slicer's filament profile from it is the slicer integration's job (form/adapters): it reads ``material`` per part from
here and nothing else.

Property values are typical figures from filament and resin datasheets; brands differ. They feed heuristics, never a
computed result.
"""
from __future__ import annotations

import re

MATERIALS = {
    "pla": {"label": "PLA", "process": "fdm", "density_g_cm3": 1.24, "heat_c": 55, "nozzle_c": [190, 220], "bed_c": [50, 60],
            "color": "#e9e5dc", "warp": "low", "uv": "poor", "flex": "rigid",
            "note": "Easy to print and stiff. Softens from about 55 °C and creeps under a constant load when warm."},
    "petg": {"label": "PETG", "process": "fdm", "density_g_cm3": 1.27, "heat_c": 70, "nozzle_c": [230, 250], "bed_c": [70, 85],
             "color": "#cfe3e8", "warp": "low", "uv": "fair", "flex": "tough",
             "note": "Tougher than PLA and fine in warm water. Strings; bridges sag a little more."},
    "abs": {"label": "ABS", "process": "fdm", "density_g_cm3": 1.04, "heat_c": 95, "nozzle_c": [240, 260], "bed_c": [95, 110],
            "color": "#e4e1da", "warp": "high", "uv": "poor", "flex": "tough",
            "note": "Heat resistant and tough. Shrinks as it cools: large flat parts lift without an enclosure."},
    "asa": {"label": "ASA", "process": "fdm", "density_g_cm3": 1.07, "heat_c": 95, "nozzle_c": [240, 260], "bed_c": [90, 110],
            "color": "#dcdad5", "warp": "high", "uv": "good", "flex": "tough",
            "note": "Like ABS with good resistance to sunlight. Needs an enclosure for large parts."},
    "tpu": {"label": "TPU 95A", "process": "fdm", "density_g_cm3": 1.21, "heat_c": 60, "nozzle_c": [220, 240], "bed_c": [30, 60],
            "color": "#3b3f44", "warp": "low", "uv": "fair", "flex": "flexible",
            "note": "Flexible and impact resistant. Print slowly; bridges and steep overhangs droop."},
    "pa": {"label": "Nylon (PA)", "process": "fdm", "density_g_cm3": 1.14, "heat_c": 80, "nozzle_c": [250, 280], "bed_c": [70, 90],
           "color": "#efeadc", "warp": "high", "uv": "fair", "flex": "tough",
           "note": "Tough and wear resistant. Absorbs moisture: dry it before printing. Warps on large flat parts."},
    "pc": {"label": "Polycarbonate", "process": "fdm", "density_g_cm3": 1.20, "heat_c": 115, "nozzle_c": [260, 300], "bed_c": [100, 120],
           "color": "#d6dde2", "warp": "high", "uv": "fair", "flex": "tough",
           "note": "Strongest and most heat resistant of the common filaments. Needs a hot, enclosed printer."},
    "resin": {"label": "Resin (standard)", "process": "resin", "density_g_cm3": 1.12, "heat_c": 50, "nozzle_c": None, "bed_c": None,
              "color": "#9aa3ab", "warp": "low", "uv": "poor", "flex": "brittle",
              "note": "Fine detail on an MSLA printer. Brittle; yellows in sunlight."},
    "resin_tough": {"label": "Resin (tough)", "process": "resin", "density_g_cm3": 1.15, "heat_c": 60, "nozzle_c": None, "bed_c": None,
                    "color": "#8d969e", "warp": "low", "uv": "poor", "flex": "tough",
                    "note": "ABS-like resin for parts that take knocks. Printed on an MSLA printer."},
}

# colours offered in the app; any #rrggbb is accepted
SWATCHES = ["#e9e5dc", "#2b2d30", "#8a9097", "#c8483c", "#e08a2c", "#e6c34a", "#5e9e5a", "#3f7fbf", "#6d5bd0", "#d9708f", "#7a5a3c", "#d4e4ec"]

_HEX = re.compile(r"#[0-9a-fA-F]{6}")


def catalogue() -> dict:
    return {"materials": [{"id": k, **v} for k, v in MATERIALS.items()], "swatches": SWATCHES,
            "source": "Typical values from filament and resin datasheets; brands differ."}


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
    m = str(m).strip().lower()
    if m not in MATERIALS:
        raise ValueError("Unknown material. Known: " + ", ".join(MATERIALS) + ".")
    return m


def appearance(p: dict) -> dict:
    a = p.get("appearance") or {}
    return {"color": a.get("color"), "material": a.get("material"), "parts": dict(a.get("parts") or {})}


def resolved(p: dict, part: str = "") -> dict:
    """The colour and material a part is shown and printed in: its own, else the design's, else the material's colour."""
    a = appearance(p)
    own = a["parts"].get(part) or {} if part else {}
    mat = own.get("material") or a.get("material")
    col = own.get("color") or a.get("color") or (MATERIALS[mat]["color"] if mat in MATERIALS else None)
    return {"color": col, "material": mat}


def set_appearance(st, pid: str, part: str = "", color="keep", material="keep", by: str = "you") -> dict:
    """Set (or clear, with None) the colour and/or material of the design (part "") or of one part."""
    from .studio import StudioError
    try:
        c = clean_color(color) if color != "keep" else "keep"
        m = clean_material(material) if material != "keep" else "keep"
    except ValueError as e:
        raise StudioError(str(e), "Materials: " + ", ".join(MATERIALS) + ".")
    part = re.sub(r"[^a-zA-Z0-9_-]", "", str(part or ""))[:40]
    with st.lock(pid):
        p = st.load(pid)
        a = appearance(p)
        slot = a if not part else a["parts"].setdefault(part, {})
        if c != "keep":
            slot["color"] = c
        if m != "keep":
            slot["material"] = m
        if part:
            a["parts"][part] = {k: v for k, v in slot.items() if v}
            if not a["parts"][part]:
                del a["parts"][part]
        p["appearance"] = {"color": a.get("color"), "material": a.get("material"), "parts": a["parts"]}
        st.save(p)
    what = []
    if c != "keep":
        what.append(f"colour {c}" if c else "colour cleared")
    if m != "keep":
        what.append(f"material {MATERIALS[m]['label']}" if m else "material cleared")
    if what:
        st.activity(pid, "appearance", (f"Part {part}: " if part else "Design: ") + ", ".join(what) + ".", by=by)
    return p["appearance"]


def fingerprint(p: dict):
    """What the material notes in the checks depend on, or None when no material is chosen (checks keys unchanged)."""
    a = appearance(p)
    mats = sorted({x for x in [a.get("material")] + [v.get("material") for v in a["parts"].values()] if x})
    if not mats:
        return None
    return [mats, sorted((k, v.get("material")) for k, v in a["parts"].items() if v.get("material")), a.get("material"),
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
        if m:
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
        sid = f"material_{m}"
        notes, warn = [], False
        if M["process"] == "resin":
            warn = True
            notes.append("Resin prints on an MSLA printer: the FDM slice, nozzle and bridge checks here do not describe how it will print.")
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
        if thin and M["flex"] == "brittle" and thin["t"] < 1.5:
            warn = True
            notes.append(f"Standard resin is brittle; the thinnest wall is {thin['t']:.2f} mm. Thicken it or use a tough resin.")
        if not notes:
            notes.append(M["note"])
        out.append({"id": sid, "label": f"{M['label']} suits the part{who}", "status": "WARN" if warn else "PASS",
                    "value": f"{M['label']} · softens ~{M['heat_c']} °C",
                    "detail": " ".join(notes) + " Rule of thumb from typical datasheet values and the brief; brands differ.",
                    "evidence": "heuristic", "material": m, "parts": [x for x in parts if x]})
    return out


def mass_g(volume_mm3: float, material: str | None):
    """Solid mass if printed 100% dense: an upper bound. None without a material."""
    if material not in MATERIALS:
        return None
    return round(volume_mm3 / 1000.0 * MATERIALS[material]["density_g_cm3"], 2)


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


def threemf(st, p: dict) -> bytes:
    """A 3MF of the head revision as printed, one object per body, each with its colour and material name
    (3MF core basematerials). Slicers that read 3MF colours show them; the geometry is the exported STL's."""
    import io
    import zipfile
    from xml.sax.saxutils import escape
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
        name = (MATERIALS[rv["material"]]["label"] if rv["material"] else "Unassigned") + (f" · {label}" if label else "")
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
