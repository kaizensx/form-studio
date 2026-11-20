"""3MF files built in the layout Bambu Studio, Orca Slicer and MakerWorld write (production extension).

    3D/3dmodel.model                 build items placing components objects; no meshes of its own
    3D/Objects/object_1.model        the meshes, referenced from the root with p:path
    3D/_rels/3dmodel.model.rels      the relationship from the root model to the object file
    Metadata/model_settings.config   object and part names, part kinds (a modifier), plates, extruders
    Metadata/project_settings.config filament colours

Each object is a box; its world bounding box is known exactly, so a reader can be checked to 0.001 mm.
"""
from __future__ import annotations

import json
import uuid
import zipfile
from pathlib import Path

CORE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
PROD = "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"


def _box(sx, sy, sz, ox=0.0, oy=0.0, oz=0.0) -> tuple[list, list]:
    V = [(ox + x * sx, oy + y * sy, oz + z * sz) for z in (0, 1) for y in (0, 1) for x in (0, 1)]
    F = [(0, 2, 1), (1, 2, 3), (4, 5, 6), (5, 7, 6), (0, 1, 4), (1, 5, 4),
         (2, 6, 3), (3, 6, 7), (0, 4, 2), (2, 4, 6), (1, 3, 5), (3, 7, 5)]
    return V, F


def _mesh_xml(oid: int, V, F, name: str = "") -> str:
    vs = "".join(f'<vertex x="{x:g}" y="{y:g}" z="{z:g}"/>' for x, y, z in V)
    ts = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in F)
    nm = f' name="{name}"' if name else ""
    return (f'<object id="{oid}" p:UUID="{uuid.uuid4()}" type="model"{nm}><mesh><vertices>{vs}</vertices>'
            f'<triangles>{ts}</triangles></mesh></object>')


# (name, size, world offset of its min corner, plate, extruder); "Bracket" also carries a modifier volume
OBJECTS = [("Base plate", (40.0, 30.0, 4.0), (10.0, 20.0, 0.0), 1, 1),
           ("Bracket", (12.0, 8.0, 25.0), (70.5, 15.25, 0.0), 1, 2),
           ("Knob", (10.0, 10.0, 6.0), (130.0, 140.0, 0.0), 2, 1)]
COLOURS = ["#F2F2F2", "#E8461E"]


def expected() -> list[dict]:
    """name, bbox (world, mm), plate, colour for each object of bambu_style()."""
    out = []
    for name, (sx, sy, sz), (ox, oy, oz), plate, ex in OBJECTS:
        out.append({"name": name, "bbox": [[ox, oy, oz], [ox + sx, oy + sy, oz + sz]], "plate": plate,
                    "colour": COLOURS[ex - 1], "triangles": 12})
    return out


def bambu_style(path: Path) -> Path:
    """Write the multi-object, production-extension 3MF described above."""
    sub, root_objs, items, settings = [], [], [], []
    mesh_id = 1
    for i, (name, (sx, sy, sz), (ox, oy, oz), plate, ex) in enumerate(OBJECTS):
        # mesh centred on its own origin, as slicers store it; the build item moves it into place
        V, F = _box(sx, sy, sz, -sx / 2, -sy / 2, -sz / 2)
        sub.append(_mesh_xml(mesh_id, V, F))
        comps = [f'<component p:path="/3D/Objects/object_1.model" objectid="{mesh_id}" p:UUID="{uuid.uuid4()}" '
                 f'transform="1 0 0 0 1 0 0 0 1 0 0 0"/>']
        parts = [f'<part id="{mesh_id}" subtype="normal_part"><metadata key="name" value="{name}"/></part>']
        main_mesh = mesh_id
        mesh_id += 1
        if name == "Bracket":                        # a modifier volume: settings only, not geometry
            V2, F2 = _box(30, 30, 30, -15, -15, -15)
            sub.append(_mesh_xml(mesh_id, V2, F2))
            comps.append(f'<component p:path="/3D/Objects/object_1.model" objectid="{mesh_id}" p:UUID="{uuid.uuid4()}" '
                         f'transform="1 0 0 0 1 0 0 0 1 0 0 0"/>')
            parts.append(f'<part id="{mesh_id}" subtype="modifier_part"><metadata key="name" value="Infill modifier"/></part>')
            mesh_id += 1
        rid = 100 + i
        root_objs.append(f'<object id="{rid}" p:UUID="{uuid.uuid4()}" type="model"><components>{"".join(comps)}</components></object>')
        cx, cy, cz = ox + sx / 2, oy + sy / 2, oz + sz / 2
        items.append(f'<item objectid="{rid}" p:UUID="{uuid.uuid4()}" transform="1 0 0 0 1 0 0 0 1 {cx:g} {cy:g} {cz:g}" printable="1"/>')
        settings.append((rid, name, ex, parts, plate, main_mesh))
    root = (f'<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xml:lang="en-US" xmlns="{CORE}" '
            f'xmlns:p="{PROD}" requiredextensions="p"><metadata name="Application">BambuStudio-02.03.00</metadata>'
            f'<resources>{"".join(root_objs)}</resources><build p:UUID="{uuid.uuid4()}">{"".join(items)}</build></model>')
    objfile = (f'<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xml:lang="en-US" xmlns="{CORE}" '
               f'xmlns:p="{PROD}" requiredextensions="p"><resources>{"".join(sub)}</resources><build/></model>')
    ms = ['<?xml version="1.0" encoding="UTF-8"?>\n<config>']
    for rid, name, ex, parts, _plate, _m in settings:
        ms.append(f'<object id="{rid}"><metadata key="name" value="{name}"/><metadata key="extruder" value="{ex}"/>'
                  + "".join(parts) + "</object>")
    for plate in sorted({s[4] for s in settings}):
        ms.append(f'<plate><metadata key="plater_id" value="{plate}"/>')
        for rid, *_rest, pl, _m in settings:
            if pl == plate:
                ms.append(f'<model_instance><metadata key="object_id" value="{rid}"/>'
                          '<metadata key="instance_id" value="0"/></model_instance>')
        ms.append("</plate>")
    ms.append("</config>")
    path = Path(path)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/'
                   'content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
                   'relationships+xml"/><Default Extension="model" ContentType="application/vnd.ms-package.'
                   '3dmanufacturing-3dmodel+xml"/><Default Extension="config" ContentType="text/xml"/></Types>')
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="http://'
                   'schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
        z.writestr("3D/3dmodel.model", root)
        z.writestr("3D/_rels/3dmodel.model.rels",
                   '<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/relationships"><Relationship Target="/3D/Objects/object_1.model" Id="rel-1" Type="'
                   'http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
        z.writestr("3D/Objects/object_1.model", objfile)
        z.writestr("Metadata/model_settings.config", "".join(ms))
        z.writestr("Metadata/project_settings.config", json.dumps({"filament_colour": COLOURS}))
    return path
