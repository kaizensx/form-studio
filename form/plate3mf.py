"""A 3MF with every plate of a plate plan, in the form each slicer reads as several plates.

    from form import plate3mf
    files = plate3mf.write_all(folder, "box_r03", plates, meshes, "bbl", bed)   # [Path]: one file, or several
    plate3mf.read(path)                       # {"dialect", "bed_mm", "plates": [{"n", "objects": [names]}]}

Each placed part is one 3MF object (its mesh already lying as it prints, centred on its own origin) with one build
item that puts it where the plan says on its plate. How a slicer tells plates apart differs:

  bbl     Bambu Studio, OrcaSlicer and the Orca forks (ElegooSlicer, Snapmaker Orca). Metadata/model_settings.config
          holds one <plate> per plate listing its objects (plater_id, model_instance object_id / instance_id), and
          each object sits on its plate in the program's plate grid: plate i (from 0) at column i % cols, row
          i // cols, cols = ceil-ish sqrt(n) (PartPlate.hpp compute_colum_count), origin (col * 1.2 * width,
          -row * 1.2 * depth) (PartPlate.cpp, LOGICAL_PART_PLATE_GAP = 1/5). Read for real by Bambu Studio 2.9 and
          OrcaSlicer's CLI: each plate sliced to its own plate_<n>.gcode (tests/test_plate3mf.py, real-slicer class).
  prusa   PrusaSlicer 2.9+ and its forks. PrusaSlicer stores no bed number: it puts an object on the bed whose
          area holds it, beds laid out in its grid (src/libslic3r/MultipleBeds.cpp, version_2.9.2: bed i at
          BedsGrid::index2grid_coords(i) times (bed size + gap), gap = min(100, 0.3 * the bed's diagonal)), up to
          9 beds. More than 9 plates are written as several files, 9 plates each. A PrusaSlicer older than 2.9 has
          one bed: it shows the other plates' parts beside it.

Nothing here is a slicer's own project: no print settings are in the file (form/slicer_open.py writes those through
the slicer itself). Coordinates are millimetres, the bed's lower-left corner at 0, 0.
"""
from __future__ import annotations

import math
import zipfile
from pathlib import Path
from xml.etree import ElementTree
from xml.sax.saxutils import escape

import numpy as np

BBL_KINDS = ("bambu", "orca", "elegoo", "snapmaker")
PRUSA_KINDS = ("prusa", "superslicer", "qidi")
BBL_GAP = 1.0 / 5.0
PRUSA_MAX_BEDS = 9
NS_CORE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"


def dialect(kind: str) -> str:
    """bbl or prusa: how this slicer (form/adapters kind) reads plates. Unknown kinds get bbl."""
    return "prusa" if (kind or "") in PRUSA_KINDS else "bbl"


def bbl_columns(n: int) -> int:
    """Bambu Studio / OrcaSlicer compute_colum_count: sqrt(n) rounded, plus one when rounding went down."""
    value = math.sqrt(float(max(1, n)))
    r = round(value)
    return int(r + 1 if value > r else r)


def prusa_grid(i: int) -> tuple[int, int]:
    """PrusaSlicer BedsGrid::index2grid_coords for the first quadrant: bed 0 at (0, 0), 1 (1, 0), 2 (0, 1), 3 (1, 1),
    4 (2, 0), 5 (2, 1), 6 (0, 2), 7 (1, 2), 8 (2, 2)."""
    if i <= 0:
        return 0, 0
    k = i + 1
    a = 1
    while (a + 1) * (a + 1) < k:
        a += 1
    k -= a * a
    x = y = a
    if k <= a:
        y = k - 1
    else:
        x = k - a - 1
    return x, y


def prusa_gap(bed) -> float:
    return min(100.0, math.hypot(float(bed[0]), float(bed[1])) * 0.3)


def origin(dial: str, i: int, n: int, bed) -> tuple[float, float]:
    """Where plate i (from 0) of n starts, in the slicer's scene, for its dialect."""
    w, d = float(bed[0]), float(bed[1])
    if dial == "prusa":
        gx, gy = prusa_grid(i)
        g = prusa_gap(bed)
        return gx * (w + g), gy * (d + g)
    cols = bbl_columns(n)
    return (i % cols) * w * (1 + BBL_GAP), -(i // cols) * d * (1 + BBL_GAP)


def plate_of(dial: str, x: float, y: float, n: int, bed) -> int:
    """Which plate (from 0) a point of the scene is on, for its dialect; -1 off every plate."""
    for i in range(max(1, n)):
        ox, oy = origin(dial, i, n, bed)
        if ox - 1e-6 <= x <= ox + bed[0] + 1e-6 and oy - 1e-6 <= y <= oy + bed[1] + 1e-6:
            return i
    return -1


def mesh_of(triangles) -> tuple[np.ndarray, np.ndarray]:
    """(vertices, faces) of an (n, 3, 3) triangle array, vertices welded at 1e-5 mm."""
    t = np.asarray(triangles, dtype=np.float64).reshape(-1, 3)
    P, inv = np.unique(np.round(t, 5), axis=0, return_inverse=True)
    return P, inv.reshape(-1, 3)


def _placement(q: dict) -> tuple[np.ndarray, np.ndarray]:
    """Rotation and translation that put a mesh centred on the origin at q on its plate (bed coordinates)."""
    R = np.array([[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]]) if q.get("rotated") else np.eye(3)
    return R, np.array([q["x"] + q["w"] / 2, q["y"] + q["h"] / 2, 0.0])


def write(path: Path, plates: list, meshes: dict, dial: str, bed, title: str = "", app: str = "Form Studio",
          first: int = 0, total: int | None = None) -> dict:
    """Write one 3MF of these plates. plates: [{"n", "parts": [{"id", "label", "x", "y", "w", "h", "rotated",
    "material", "color"}]}]; meshes: {part id: (P, T)} each lying as it prints, centred on the origin, on z = 0 (a copy
    "<id>#k" uses the mesh of <id>). first/total: where these plates sit in the slicer's grid (several files).
    Returns {"path", "plates", "objects"}."""
    bed = [float(v) for v in bed]
    total = len(plates) if total is None else total
    mats, objs, items, plate_rows = [], [], [], []
    oid = 1
    for k, plate in enumerate(plates):
        ox, oy = origin(dial, first + k, total, bed)
        ids = []
        for q in plate["parts"]:
            P, T = meshes[q["id"]] if q["id"] in meshes else meshes[str(q["id"]).split("#")[0]]
            R, t = _placement(q)
            V = np.asarray(P, dtype=np.float64) @ R.T                 # turned on the plate; the build item moves it
            col = (q.get("color") or "#d8d3c8").upper()
            col = (col if len(col) == 9 else col + "FF") if col.startswith("#") else "#D8D3C8FF"
            name = q.get("label") or q["id"]
            mats.append(f'<base name="{escape((q.get("material") or "Unassigned") + " · " + name)}" displaycolor="{col}"/>')
            vs = "".join(f'<vertex x="{x:.5f}" y="{y:.5f}" z="{z:.5f}"/>' for x, y, z in V)
            ts = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in np.asarray(T, dtype=np.int64))
            objs.append((oid, name, len(mats) - 1, vs, ts, len(T)))
            items.append(f'<item objectid="{oid}" transform="1 0 0 0 1 0 0 0 1 {t[0] + ox:.4f} {t[1] + oy:.4f} {t[2]:.4f}" '
                         'printable="1"/>')
            ids.append((oid, name))
            oid += 1
        plate_rows.append((plate["n"], ids, plate.get("material") or ""))
    head = ['<?xml version="1.0" encoding="UTF-8"?>',
            f'<model unit="millimeter" xml:lang="en-US" xmlns="{NS_CORE}"'
            + (' xmlns:BambuStudio="http://schemas.bambulab.com/package/2021"' if dial == "bbl" else "")
            + (' xmlns:slic3rpe="http://schemas.slic3r.org/3mf/2017/06"' if dial == "prusa" else "") + '>',
            f'<metadata name="Title">{escape(title)}</metadata>', f'<metadata name="Application">{escape(app)}</metadata>',
            f'<metadata name="FormStudio:Plates">{len(plates)}</metadata>',
            f'<metadata name="FormStudio:Bed">{bed[0]:g} {bed[1]:g}</metadata>',
            f'<metadata name="FormStudio:Dialect">{dial}</metadata>']
    if dial == "bbl":
        head.append('<metadata name="BambuStudio:3mfVersion">1</metadata>')
    model = head + ['<resources>', '<basematerials id="1000000">' + "".join(mats) + '</basematerials>']
    for o, name, k, vs, ts, _ in objs:
        model.append(f'<object id="{o}" type="model" name="{escape(name)}" pid="1000000" pindex="{k}"><mesh>'
                     f'<vertices>{vs}</vertices><triangles>{ts}</triangles></mesh></object>')
    model.append('</resources><build>' + "".join(items) + '</build></model>')
    types = ('<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
             '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
             '<Default Extension="config" ContentType="text/xml"/>')
    path = Path(path)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8"?><Types '
                   f'xmlns="http://schemas.openxmlformats.org/package/2006/content-types">{types}</Types>')
        z.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships '
                   'xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship '
                   'Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
                   '</Relationships>')
        z.writestr("3D/3dmodel.model", "".join(model))
        if dial == "bbl":
            z.writestr("Metadata/model_settings.config", _bbl_config(objs, plate_rows))
        else:
            z.writestr("Metadata/Slic3r_PE_model.config", _prusa_config(objs))
    return {"path": str(path), "plates": len(plates), "objects": len(objs)}


def _bbl_config(objs, plate_rows) -> str:
    out = ['<?xml version="1.0" encoding="UTF-8"?>', "<config>"]
    for o, name, _, _, _, nt in objs:
        out.append(f'  <object id="{o}">\n    <metadata key="name" value="{escape(name)}"/>\n'
                   f'    <metadata key="extruder" value="1"/>\n    <part id="1" subtype="normal_part">\n'
                   f'      <metadata key="name" value="{escape(name)}"/>\n    </part>\n  </object>')
    for n, ids, material in plate_rows:
        out.append(f'  <plate>\n    <metadata key="plater_id" value="{n}"/>\n'
                   f'    <metadata key="plater_name" value="{escape(f"Plate {n}" + (f" · {material}" if material else ""))}"/>\n'
                   '    <metadata key="locked" value="false"/>')
        for o, _ in ids:
            out.append(f'    <model_instance>\n      <metadata key="object_id" value="{o}"/>\n'
                       '      <metadata key="instance_id" value="0"/>\n    </model_instance>')
        out.append("  </plate>")
    out.append("</config>")
    return "\n".join(out) + "\n"


def _prusa_config(objs) -> str:
    out = ['<?xml version="1.0" encoding="UTF-8"?>', "<config>"]
    for o, name, _, _, _, nt in objs:
        out.append(f' <object id="{o}" instances_count="1">\n  <metadata type="object" key="name" value="{escape(name)}"/>\n'
                   f'  <volume firstid="0" lastid="{max(0, nt - 1)}">\n'
                   f'   <metadata type="volume" key="name" value="{escape(name)}"/>\n  </volume>\n </object>')
    out.append("</config>")
    return "\n".join(out) + "\n"


def write_all(folder: Path, stem: str, plates: list, meshes: dict, dial: str, bed, title: str = "") -> list:
    """Every plate in as few files as the dialect allows: one for bbl; for prusa one per 9 plates
    (<stem>.3mf, or <stem>_plates1-9.3mf, <stem>_plates10-12.3mf, ...). [Path]."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    if dial != "prusa" or len(plates) <= PRUSA_MAX_BEDS:
        p = folder / f"{stem}.3mf"
        write(p, plates, meshes, dial, bed, title)
        return [p]
    out = []
    for s in range(0, len(plates), PRUSA_MAX_BEDS):
        chunk = plates[s:s + PRUSA_MAX_BEDS]
        p = folder / f"{stem}_plates{chunk[0]['n']}-{chunk[-1]['n']}.3mf"
        write(p, chunk, meshes, dial, bed, title)
        out.append(p)
    return out


def read(path: Path, bed=None) -> dict:
    """The plates a 3MF holds, read the way its dialect is read: bbl from Metadata/model_settings.config, prusa
    (or a plain 3MF) from where each build item sits in PrusaSlicer's bed grid. bed: the bed size (else the file's
    FormStudio:Bed). {"dialect", "bed_mm", "plates": [{"n", "objects": [names]}], "outside": [names]}."""
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        root = ElementTree.fromstring(z.read("3D/3dmodel.model"))
        cfg = z.read("Metadata/model_settings.config") if "Metadata/model_settings.config" in names else None
    ns = {"m": NS_CORE}
    meta = {m.get("name"): (m.text or "") for m in root.findall("m:metadata", ns)}
    objects = {o.get("id"): o.get("name") or f"object {o.get('id')}" for o in root.iter(f"{{{NS_CORE}}}object")}
    if bed is None and meta.get("FormStudio:Bed"):
        bed = [float(v) for v in meta["FormStudio:Bed"].split()]
    if cfg is not None:
        c = ElementTree.fromstring(cfg)
        for o in c.findall("object"):                       # the program's own names win
            nm = next((m.get("value") for m in o.findall("metadata") if m.get("key") == "name"), None)
            if nm:
                objects[o.get("id")] = nm
        plates = []
        for pl in c.findall("plate"):
            m = {x.get("key"): x.get("value") for x in pl.findall("metadata")}
            objs = []
            for mi in pl.findall("model_instance"):
                mm = {x.get("key"): x.get("value") for x in mi.findall("metadata")}
                objs.append(objects.get(mm.get("object_id"), mm.get("object_id")))
            plates.append({"n": int(m.get("plater_id") or len(plates) + 1), "objects": objs})
        return {"dialect": "bbl", "bed_mm": bed, "plates": sorted(plates, key=lambda r: r["n"]), "outside": []}
    if not bed:
        raise ValueError("The bed size is needed to read a PrusaSlicer-style 3MF's beds.")
    items = []
    for it in root.iter(f"{{{NS_CORE}}}item"):
        tr = [float(v) for v in (it.get("transform") or "1 0 0 0 1 0 0 0 1 0 0 0").split()]
        items.append((objects.get(it.get("objectid")), tr[9], tr[10]))
    by, outside = {}, []
    for name, x, y in items:
        i = plate_of("prusa", x, y, PRUSA_MAX_BEDS, bed)
        if i < 0:
            outside.append(name)
        else:
            by.setdefault(i, []).append(name)
    return {"dialect": "prusa", "bed_mm": bed, "plates": [{"n": i + 1, "objects": by[i]} for i in sorted(by)],
            "outside": outside}
