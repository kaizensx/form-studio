"""Triage: look at whatever the person brought, say what it is, and choose the route. One step, any input.

    triage(source)              a file path, a link or plain words -> {"input", "facts", "class", "route", "why",
                                "steps", "prepare", "alternates", "ask", "cannot", "seconds"}
    python -m form.triage X     the same as JSON (`form triage X`)

A mesh (STL, OBJ, 3MF, PLY, OFF, AMF, glTF, Collada, X3D, VRML, VTK; form/formats.py is the list) is read, welded,
repaired on a copy (form/meshrepair.py) and measured: triangles, size, a guess at its units (or the units the file
states, converted), open and non-manifold edges before and after the safe repairs, loose pieces, genus, and how much of its
surface is the flat and ruled geometry a CAD program makes (see `mechanical_share`). From that it is classed
mechanical, organic or mixed, and one route is chosen:

    parametric      a mechanical or mixed part that closes: reconstruct() reads sketches, holes and fillets off it
    surface_body    a smooth organic body of one piece without handles: a closed NURBS solid with a cage to edit
    mesh_body       an organic body with fine detail, handles or too many triangles for a surface: the repaired mesh
                    as the design's body (a lighter working copy when heavy), cut and added to exactly
    assembly        several separate closed bodies: one design with one part per body
    reference_only  a surface that does not close (a large opening that is not flat): kept as a reference to design
                    around; nothing is guessed

A point cloud (XYZ, PTS, LAS, E57, a PLY of vertices) first becomes a surface (form/pointcloud.py: normals, a signed
distance, marching tetrahedra; bounded, a few seconds) and is then assessed and routed like a mesh, with the
reconstruction in its facts. Other inputs get their route too: STEP, IGES or BREP (cad_reference), a DXF or SVG
drawing (profile), a zip (archive: unpacked safely, each file triaged), a photo (photo_reference), a Form Studio
sketch (sketch), a PDF (document), a link (link), plain words (describe or concepts). A format Form Studio does not
read gets one message naming what it does read (formats.unsupported). The route names the tool calls, in
order. `ask` is one question, present only when the answer changes the result and cannot be read from the file (the
units of a mesh whose size makes no sense in millimetres, the wall of a surface that does not close, the scale of a
photo). `cannot` lists what this route will not give, said before the work and not after.

reconstruct() runs this itself and takes the route (form/recon/project.py), so an agent that calls reconstruct on
anything gets the right result or a refusal that names the next call. Nothing here moves, uploads or changes a file.

numpy and scipy; no kernel.
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import numpy as np

from . import formats

MESH = formats.extensions("mesh", "pointcloud")
CAD = formats.extensions("brep")
PHOTO = formats.extensions("photo")
DOCUMENT = formats.extensions("document")
VECTOR = formats.extensions("2d")
ARCHIVE = formats.extensions("archive")
MAX_ARCHIVE_TRIAGE = 12     # files of a zip assessed in one triage; the rest are listed with their kind

MECHANICAL_PCT = 70.0       # at least this share of the surface is CAD-like: mechanical
ORGANIC_PCT = 30.0          # under this: organic; between: mixed
FLAT_SPREAD = 2e-5          # a patch whose normals spread less than this (about a quarter of a degree) is flat
RULED_RATIO = 0.02          # a patch whose normals spread this much less in one direction than the other is ruled
DOMINANT_DEG = 8.0          # a normal within this angle of a dominant direction counts for it
SURFACE_MAX_GENUS = 0       # a closed quad cage of sphere topology cannot follow a handle
SURFACE_MAX_CREASE_PCT = 4.0  # more of the edges sharper than 40 degrees: detail a smooth surface would erase
PARAMETRIC_TRIANGLES = 300_000  # above this a mechanical mesh is simplified within a quarter of the tolerance first
UNIT_SMALL_MM = 3.0         # a part smaller than this in its largest dimension is probably not in millimetres
UNIT_LARGE_MM = 20_000.0    # nor one larger than this
PART_AREA_FRAC = 0.02       # a loose piece with at least this share of the surface is a part, not debris
MAX_PARTS = 12              # form/multipart.py takes at most this many meshes in one design

ROUTES = {
    "parametric": "Editable CAD: sketches, extrusions, holes and fillets read off the mesh, verified against it.",
    "surface_body": "A closed NURBS solid with a cage to edit, within a measured distance of the mesh; exports STEP.",
    "mesh_body": "The repaired mesh as the design's body: scale it, cut and add exact CAD features; exports STL and "
                 "3MF, not STEP.",
    "assembly": "One design with one part per body, each reconstructed and placed where the file has it.",
    "reference_only": "Kept as a reference to design around or measure against; it is not turned into a body.",
    "cad_reference": "Already CAD: imported as a reference a design can read, cut around and build on.",
    "photo_reference": "A photo to design from: sizes come from a reference object in it and stay assumed.",
    "sketch": "A Form Studio sketch: its JSON dimensions are authoritative over the picture.",
    "document": "A drawing or datasheet: read the pages, take dimensions as specified.",
    "profile": "A 2D drawing: its outlines are the profile of a part (extruded, revolved or cut) at the drawing's sizes.",
    "archive": "A zip: unpacked safely; each file in it has its own route.",
    "link": "A link: fetch it, then triage what it holds.",
    "describe": "A specification in words: design it directly.",
    "concepts": "An idea in words: offer a few different approaches as real designs and let the person pick.",
    "unknown": "Not something Form Studio reads.",
}


# ---- meshes ----------------------------------------------------------------------------------------------------------

def mechanical_share(V: np.ndarray, F: np.ndarray, samples: int = 40_000, k: int = 24, seed: int = 0) -> dict:
    """How much of a mesh's surface looks like what a CAD program makes, two ways (area shares, percent):

    developable  points whose neighbourhood (the k nearest of `samples` points spread evenly over the surface: a
                 patch of about k / samples of the surface, whatever the triangle size) is flat, or curved in one
                 direction only (a cylinder, a cone, an extrusion, a crease between two flat faces: its normals lie on
                 one great circle). A sculpted or scanned surface curves both ways almost everywhere.
    dominant     triangles whose normal is within DOMINANT_DEG of one of the six most common directions. A scanned
                 bracket is noisy (no patch is exactly flat) and still mostly a few flat sides; a figure is not.

    mechanical_pct is the larger of the two. Also the share of edges sharper than 40 degrees (crease_pct)."""
    from scipy.spatial import cKDTree
    from .recon import mesh as meshmod
    rng = np.random.default_rng(seed)
    N, area = meshmod.tri_normals(V, F)
    tot = float(area.sum()) or 1.0
    _E, tri, eo, _he = meshmod.edges(F)
    order = np.argsort(eo, kind="stable")
    eo_s, tri_s = eo[order], tri[order]
    pair = eo_s[1:] == eo_s[:-1]
    cos = np.einsum("ij,ij->i", N[tri_s[:-1][pair]], N[tri_s[1:][pair]])
    crease = 100.0 * float((cos < np.cos(np.radians(40.0))).mean()) if len(cos) else 0.0
    # points spread evenly over the surface (a triangle is drawn in proportion to its area), with their normals
    m = int(min(samples, max(2000, 8 * len(F))))
    pick = rng.choice(len(F), size=m, p=area / tot)
    r1, r2 = rng.random(m), rng.random(m)
    s1 = np.sqrt(r1)
    P = (1 - s1)[:, None] * V[F[pick, 0]] + (s1 * (1 - r2))[:, None] * V[F[pick, 1]] + (s1 * r2)[:, None] * V[F[pick, 2]]
    n = N[pick]
    kk = int(min(k, m))
    _d, nb = cKDTree(P).query(P, k=kk)
    nn = n[nb]                                            # (m, k, 3)
    nn = nn - nn.mean(axis=1, keepdims=True)
    S = np.einsum("mki,mkj->mij", nn, nn) / kk
    # ascending. The smallest is along the patch's own normal (about zero); the other two are how much the normals
    # turn in the two directions across the patch: both small = flat, one small = ruled, both large = curved both ways
    ev = np.linalg.eigvalsh(S)
    l3, l2 = np.maximum(ev[:, 1], 0.0), np.maximum(ev[:, 2], 0.0)
    flat = (ev[:, 2] < FLAT_SPREAD)                       # every normal within a fraction of a degree
    ruled = ~flat & (l3 < RULED_RATIO * np.maximum(l2, 1e-300) + FLAT_SPREAD / 10)
    developable = 100.0 * float((flat | ruled).mean())
    left = np.ones(m, bool)
    got = 0
    c8 = np.cos(np.radians(DOMINANT_DEG))
    for _ in range(6):
        if not left.any():
            break
        q = np.round(n[left] * 12).astype(np.int64)      # the heaviest cell of the sphere of normals
        key = (q[:, 0] + 12) * 625 + (q[:, 1] + 12) * 25 + (q[:, 2] + 12)
        _u, inv = np.unique(key, return_inverse=True)
        inv = inv.reshape(-1)
        d = n[left][inv == int(np.argmax(np.bincount(inv)))].mean(axis=0)
        d /= max(float(np.linalg.norm(d)), 1e-12)
        take = left & (n @ d >= c8)
        got += int(take.sum())
        left &= ~take
    dominant = 100.0 * got / m
    return {"developable_pct": round(developable, 1), "flat_pct": round(100.0 * float(flat.mean()), 1),
            "dominant_pct": round(dominant, 1), "mechanical_pct": round(max(developable, dominant), 1),
            "crease_pct": round(crease, 2)}


def units_guess(size, stated: str | None = None, source: str | None = None) -> dict:
    """A guess at a mesh's units from its size. STL and OBJ carry none, so millimetres are assumed; a part under
    UNIT_SMALL_MM or over UNIT_LARGE_MM in its largest dimension makes that assumption unlikely. A format that states
    its units (3MF, AMF, Collada) or has them by rule (glTF, LAS, E57: metres) was converted to millimetres on read."""
    L = float(max(size))
    if stated and "assumed" not in stated:
        out = {"units": stated, "source": source or "the file", "plausible": True}
        if stated != "mm":
            out["converted"] = "to millimetres on read"
        return out
    out = {"units": "mm", "source": "assumed (the format carries no units)", "largest_mm_if_mm": round(L, 4)}
    if L < UNIT_SMALL_MM:
        out.update({"plausible": False, "likely": "metres" if L < 3.0 else "centimetres",
                    "why": f"The largest dimension is {L:g}: {L:g} mm would be a speck, {L:g} m is a plausible object."})
    elif L > UNIT_LARGE_MM:
        out.update({"plausible": False, "likely": "micrometres or a scene in another scale",
                    "why": f"The largest dimension is {L:,.0f}: as millimetres that is {L / 1000:,.1f} m."})
    else:
        out["plausible"] = True
    return out


def _pieces(V, F, top) -> list:
    """Each connected piece: triangles, area, signed volume, closed or not, genus when closed."""
    from .recon import mesh as meshmod
    lab = top["_piece_of"]
    k = int(top["pieces"])
    _N, area = meshmod.tri_normals(V, F)
    A = np.bincount(lab, weights=area, minlength=k)
    a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    vol = np.bincount(lab, weights=np.einsum("ij,ij->i", a, np.cross(b, c)) / 6.0, minlength=k)
    ntri = np.bincount(lab, minlength=k)
    E, tri, eo, _he = meshmod.edges(F)
    cnt = np.bincount(eo, minlength=len(E))
    e_piece = np.zeros(len(E), np.int64)
    e_piece[eo] = lab[tri]
    nE = np.bincount(e_piece, minlength=k)
    openE = np.bincount(e_piece, weights=(cnt != 2), minlength=k)
    v_piece = np.zeros(len(V), np.int64)
    v_piece[F.reshape(-1)] = np.repeat(lab, 3)
    nV = np.bincount(v_piece[np.unique(F)], minlength=k)
    out = []
    for i in np.argsort(-A)[:50]:
        closed = openE[i] == 0
        rec = {"triangles": int(ntri[i]), "area_mm2": round(float(A[i]), 3), "volume_mm3": round(float(vol[i]), 3),
               "closed": bool(closed), "outward": bool(vol[i] > 0), "share_pct": round(100.0 * float(A[i]) / max(float(A.sum()), 1e-300), 2)}
        if closed:
            rec["genus"] = int(round((2 - (int(nV[i]) - int(nE[i]) + int(ntri[i]))) / 2))
        out.append(rec)
    return out


def assess_mesh(path: Path, tolerance: float = 0.02) -> dict:
    """Facts, class and route for one mesh file. Reads the file; changes nothing."""
    from . import meshprep, meshrepair
    from .recon import mesh as meshmod
    t0 = time.perf_counter()
    T, info = meshmod.read_triangles(path)
    V, F, w = meshmod.weld(T, 1e-6)
    del T
    if not len(F):
        raise ValueError("The mesh has no triangles with area.")
    top0 = meshmod.topology(V, F)
    Vr, Fr, repairs, top = meshrepair.repair(V, F, cap_planar=True, drop_debris=True, top=top0)
    size = (V.max(axis=0) - V.min(axis=0))
    diag = float(np.linalg.norm(size))
    n = int(len(F))
    share = mechanical_share(Vr, Fr)
    pieces = _pieces(Vr, Fr, top)
    parts = [p for p in pieces if p["share_pct"] >= 100 * PART_AREA_FRAC and p["closed"] and p["outward"]]
    cavities = [p for p in pieces if p["closed"] and not p["outward"]]
    genus = sum(p.get("genus", 0) for p in pieces if p["closed"])
    units = units_guess(size, info.get("units"), info.get("units_source"))
    if info.get("units_source") and "assumed" in info["units_source"]:
        units["source"] = info["units_source"]
    mech = share["mechanical_pct"]
    cls = "mechanical" if mech >= MECHANICAL_PCT else "organic" if mech < ORGANIC_PCT else "mixed"
    thick = 2.0 * abs(top["volume_mm3"]) / max(top["area_mm2"], 1e-9) if top["closed"] else None
    facts = {"file": path.name, "format": info.get("format"), "bytes": info.get("bytes"),
             "triangles": int(info.get("triangles_in", n)), "vertices": int(len(V)),
             "size_mm": [round(float(x), 4) for x in size], "bbox": [V.min(axis=0).round(4).tolist(), V.max(axis=0).round(4).tolist()],
             "weight": meshprep.kind(n), "units": units,
             "as_given": {"closed": bool(top0["closed"]), "open_edges": int(top0["boundary_edges"]),
                          "holes": int(top0["boundary_loops"]), "non_manifold_edges": int(top0["non_manifold_edges"]),
                          "flipped_edges": int(top0["flipped_edges"]), "pieces": int(top0["pieces"]),
                          "dropped_at_weld": {k: w[k] for k in ("dropped_collapsed", "dropped_zero_area", "dropped_duplicate")
                                              if w.get(k)}},
             "after_repair": {"closed": bool(top["closed"]), "open_edges": int(top["boundary_edges"]),
                              "non_manifold_edges": int(top["non_manifold_edges"]), "pieces": int(top["pieces"]),
                              "triangles": int(len(Fr)), "repairs": [_brief(r) for r in repairs],
                              "large_openings": len(top.get("large_holes") or [])},
             "bodies": len(parts), "cavities": len(cavities), "genus": int(genus) if top["closed"] else None,
             "mean_thickness_mm": round(float(thick), 3) if thick is not None else None,
             **share, "evidence": "computed from the file"}
    for k in ("axes", "notes"):
        if info.get(k):
            facts[k] = info[k]
    kind = "mesh"
    if info.get("pointcloud"):
        kind = "pointcloud"
        pc = info["pointcloud"]
        facts["points"] = pc["points_in_file"]
        facts["surface_from_points"] = pc
        facts["evidence"] = "computed from the surface reconstructed from the file's points"
    out = {"input": {"kind": kind, "path": str(path)}, "facts": facts, "class": cls}
    out.update(_mesh_route(facts, cls, top, tolerance, diag))
    if kind == "pointcloud":
        out["prepare"].insert(0, {"step": "surface_from_points", "grid_mm": pc["grid_mm"], "seconds": pc["seconds"],
                                  "note": pc["note"]})
        out["cannot"].append(f"Detail finer than about {pc['grid_mm']:g} mm: the surface is made from the points on a "
                             "grid of that size.")
    out["seconds"] = round(time.perf_counter() - t0, 2)
    return out


def _brief(r: dict) -> dict:
    return {k: r[k] for k in ("repair", "count", "edges", "pieces", "triangles", "area_mm2", "span_mm", "filled", "fixed")
            if k in r}


def _mesh_route(f: dict, cls: str, top: dict, tol: float, diag: float) -> dict:
    path = f["file"]
    n = f["after_repair"]["triangles"]
    rep = f["after_repair"]
    prepare, cannot, alternates, ask = [], [], [], None
    if rep["repairs"]:
        prepare.append({"step": "repair", "what": [r["repair"] for r in rep["repairs"]],
                        "note": "Runs automatically; every repair is listed in the result."})
    u = f["units"]
    if not u.get("plausible", True):
        ask = {"question": f"{path} is {max(f['size_mm']):g} units in its largest dimension. Are its units {u['likely']}, "
                           "or really millimetres?",
               "choices": [u["likely"].split(" or ")[0].capitalize(), "Millimetres"],
               "why": "The file format carries no units, and the size decides every dimension of the result.",
               "then": "reconstruct(path, units=\"m\") (or \"cm\", \"in\"; \"mm\" when they confirm millimetres)."}
    if not rep["closed"]:
        big = top.get("large_holes") or []
        why = (f"After the safe repairs it still does not close ({_open(rep)}"
               + (f"; {len(big)} opening(s) too large to fill without guessing, the largest "
                  f"{max(b['span_mm'] for b in big):g} mm across" if big else "") + "), so it does not bound a body.")
        cannot.append("A solid body: the surface is open, and closing a large opening would be a guess.")
        return {"route": "reference_only", "why": why, "prepare": prepare, "alternates": [], "ask": ask, "cannot": cannot,
                "steps": [f"create_design(...) or an existing project, then import_reference(project, path) to keep {path} "
                          "as a reference", "design around it with self.reference(name); measure with compare_to_reference"]}
    if f["bodies"] > 1:
        if f["bodies"] > MAX_PARTS:
            cannot.append(f"A part per body: the file holds {f['bodies']} bodies and one design takes {MAX_PARTS}.")
            alternates.append("assembly")
        else:
            return {"route": "assembly", "prepare": prepare, "alternates": ["mesh_body", "reference_only"], "ask": ask,
                    "cannot": cannot,
                    "why": f"The file holds {f['bodies']} separate closed bodies (each at least "
                           f"{100 * PART_AREA_FRAC:g}% of the surface): the parts of one product.",
                    "steps": ["reconstruct(project_or_file=path): it splits the bodies and makes ONE design with one "
                              "part per body", "get_project: the parts, each with its own verification"]}
    if cls == "organic":
        smooth = f["crease_pct"] <= SURFACE_MAX_CREASE_PCT
        if f["genus"] is not None and f["genus"] <= SURFACE_MAX_GENUS and smooth and f["bodies"] <= 1:
            cannot.append("Dimensions to type in: a sculpted surface has none. It is edited through its cage.")
            return {"route": "surface_body", "prepare": prepare + _work(n), "alternates": ["mesh_body", "parametric"],
                    "ask": ask, "cannot": cannot,
                    "why": f"Organic ({f['mechanical_pct']:g}% of the surface is flat or ruled), one closed body "
                           "without handles and without sharp detail: a smooth surface can follow it.",
                    "steps": ["reconstruct(project_or_file=path): fits the cage within a time limit and says the "
                              "measured distance; when the fit is not within tolerance it keeps the mesh body instead",
                              "edit_design to add exact features (holes, a flat base, a split)"]}
        reasons = []
        if f["genus"]:
            reasons.append(f"it has {f['genus']} handle(s) (genus {f['genus']}), which a single closed cage cannot follow")
        if not smooth:
            reasons.append(f"{f['crease_pct']:g}% of its edges are sharp detail a smooth surface would erase")
        cannot += ["Dimensions to type in: a sculpted surface has none.",
                   "A STEP file: the body is a mesh; exports are STL and 3MF."]
        return {"route": "mesh_body", "prepare": prepare + _work(n), "alternates": ["reference_only", "parametric"],
                "ask": ask, "cannot": cannot,
                "why": f"Organic ({f['mechanical_pct']:g}% of the surface is flat or ruled)"
                       + ("; " + "; ".join(reasons) if reasons else "") + ". It stays a mesh, repaired and closed, "
                       "that exact CAD features are cut into.",
                "steps": ["reconstruct(project_or_file=path): makes the design (a mesh body with a Scale parameter)",
                          "edit_design to add exact features: MeshBody.cut(shape), .add(shape), .split(origin, normal)"]}
    if n > PARAMETRIC_TRIANGLES:
        prepare.append({"step": "working_copy", "tolerance_mm": round(tol / 4, 5),
                        "note": f"{n:,} triangles: simplified within a quarter of the tolerance first (flat and ruled "
                                "faces lose nothing); the deviation from the file is measured and reported."})
    if cls == "mixed":
        cannot.append("Dimensions for the sculpted regions: they stay fitted surfaces or the mesh's own facets.")
    return {"route": "parametric", "prepare": prepare, "alternates": ["mesh_body", "reference_only"], "ask": ask,
            "cannot": cannot,
            "why": f"{cls.capitalize()} ({f['mechanical_pct']:g}% of the surface is flat or ruled) and closed: its "
                   "sketches, holes and fillets can be read off it and verified against it.",
            "steps": ["reconstruct(project_or_file=path)", "get_project: editable share and the Hausdorff distance first"]}


def _work(n: int) -> list:
    from . import meshrepair
    if n <= meshrepair.WORK_TRIANGLES:
        return []
    return [{"step": "working_copy", "target_triangles": meshrepair.WORK_TRIANGLES,
             "note": f"{n:,} triangles: the body is a lighter working copy; the file stays the reference and the "
                     "measured distance between them is reported."}]


def _open(rep: dict) -> str:
    from . import meshrepair
    return meshrepair.open_text({"boundary_edges": rep["open_edges"], "non_manifold_edges": rep["non_manifold_edges"]})


# ---- everything else --------------------------------------------------------------------------------------------------

def assess_cad(path: Path) -> dict:
    """STEP, IGES or OCCT BREP, read as text (no kernel)."""
    ext = path.suffix.lower()
    if ext in (".iges", ".igs"):
        return assess_iges(path)
    if ext in (".brep", ".brp"):
        return assess_brep(path)
    return assess_step(path)


def _cad_out(path: Path, facts: dict, solids: int, faces: int, what: str, unit: str | None) -> dict:
    return {"input": {"kind": "cad", "path": str(path)}, "facts": facts, "class": "mechanical",
            "route": "cad_reference", "prepare": [], "alternates": [], "ask": None,
            "why": f"{what} is already exact CAD (" + (f"{solids} solids" if solids else "surfaces only: no solid")
                   + f", {faces} faces" + (f", units {unit}" if unit else "") + "): nothing to reconstruct. "
                   "Its units are converted on import.",
            "cannot": [f"Its feature history: {what} carries the final shape, not the sketches and dimensions that made "
                       "it. Features are added on top, or the part is rebuilt with Params where it must change."]
                      + ([] if solids else ["A body: the file has no solid, so volume and cuts need a closed model."]),
            "steps": ["create_design(..., references=[path]) or import_reference(project, path)",
                      "use it in the design: self.reference(name) (cut around it, add to it)"]
                     + (["analyze_assembly(project, references=[...]) for how the solids fit and move"] if solids > 1 else [])}


_IGES_UNITS = {1: "inch", 2: "mm", 3: "unknown", 4: "foot", 5: "mile", 6: "m", 7: "km", 8: "mil", 9: "micron",
               10: "cm", 11: "microinch"}


def _iges_fields(g: str) -> list:
    """The global section's parameters, Hollerith strings (nH...) kept whole even when they hold the delimiter."""
    delim, end = ",", ";"
    if g[:2] == "1H":
        delim = g[2]
    out, i, cur = [], 0, ""
    while i < len(g):
        m = re.match(r"\s*(\d+)H", g[i:])
        if m and not cur.strip():
            n = int(m.group(1))
            start = i + m.end()
            cur = g[start:start + n]
            i = start + n
            continue
        c = g[i]
        if c in (delim, end):
            out.append(cur)
            cur = ""
            if c == end:
                break
        else:
            cur += c
        i += 1
    return out


def assess_iges(path: Path) -> dict:
    """An IGES file from its fixed 80-column records: the global section's units, the directory's entity types."""
    text = path.read_text(encoding="latin-1", errors="replace")
    lines = text.splitlines()
    glob = "".join(ln[:72] for ln in lines if len(ln) >= 73 and ln[72] == "G")
    d = [ln for ln in lines if len(ln) >= 73 and ln[72] == "D"]
    types = {}
    for ln in d[::2]:
        try:
            t = int(ln[:8])
        except ValueError:
            continue
        types[t] = types.get(t, 0) + 1
    unit = None
    if glob:
        fields = _iges_fields(glob)
        try:
            unit = _IGES_UNITS.get(int(float(fields[13].strip() or 0)))
        except (IndexError, ValueError):
            unit = None
    if not d:
        raise ValueError("Not an IGES file: it has no directory entries.")
    solids = types.get(186, 0)
    faces = types.get(510, 0) + types.get(144, 0) + types.get(143, 0)
    facts = {"file": path.name, "format": "iges", "bytes": path.stat().st_size, "solids": solids, "faces": faces,
             "entities": sum(types.values()), "units": {"units": unit or "unknown", "source": "the file" if unit else "not stated"},
             "evidence": "read from the file's directory; the kernel measures it on import"}
    return _cad_out(path, facts, solids, faces, "An IGES file", unit)


def assess_brep(path: Path) -> dict:
    """An OpenCASCADE BREP file from its text: solids and faces in its topology section."""
    head = path.read_bytes()[:64]
    if not head.lstrip().startswith((b"DBRep_DrawableShape", b"CASCADE Topology")):
        raise ValueError("Not an OpenCASCADE BREP file (binary BREP is not read).")
    text = path.read_text(encoding="latin-1", errors="replace")
    solids = len(re.findall(r"^\s*so\b", text, re.M | re.I))
    faces = len(re.findall(r"^\s*fa\b", text, re.M | re.I))
    facts = {"file": path.name, "format": "brep", "bytes": path.stat().st_size, "solids": solids, "faces": faces,
             "units": {"units": "mm", "source": "assumed (BREP carries no units)"},
             "evidence": "read from the file's text; the kernel measures it on import"}
    return _cad_out(path, facts, solids, faces, "An OpenCASCADE BREP file", None)


def assess_step(path: Path) -> dict:
    """A STEP file, read as text (no kernel): solids, faces, units, product names."""
    head = b""
    counts = {"MANIFOLD_SOLID_BREP": 0, "ADVANCED_FACE": 0, "PRODUCT(": 0, "BREP_WITH_VOIDS": 0}
    unit = None
    size = path.stat().st_size
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(4_000_000)
            if not chunk:
                break
            blob = head + chunk
            for k in counts:
                counts[k] += blob.count(k.encode()) - head.count(k.encode())
            if unit is None:
                m = re.search(rb"SI_UNIT\(\s*(\.MILLI\.|\.CENTI\.|\$)?\s*,?\s*\.METRE\.\s*\)", blob)
                if m:
                    unit = {b".MILLI.": "mm", b".CENTI.": "cm"}.get(m.group(1) or b"", "m")
                elif re.search(rb"CONVERSION_BASED_UNIT\(\s*'INCH'", blob, re.I):
                    unit = "inch"
            head = chunk[-64:]
    solids = counts["MANIFOLD_SOLID_BREP"] + counts["BREP_WITH_VOIDS"]
    facts = {"file": path.name, "format": "step", "bytes": size, "solids": solids, "faces": counts["ADVANCED_FACE"],
             "products": counts["PRODUCT("], "units": {"units": unit or "unknown", "source": "the file" if unit else "not stated"},
             "evidence": "read from the file's text; the kernel measures it on import"}
    several = solids > 1
    return {"input": {"kind": "cad", "path": str(path)}, "facts": facts, "class": "mechanical",
            "route": "cad_reference", "prepare": [], "alternates": [], "ask": None,
            "why": "A STEP file is already exact CAD (" + (f"{solids} solids" if solids else "surfaces only: no solid") + f", {counts['ADVANCED_FACE']} faces"
                   + (f", units {unit}" if unit else "") + "): nothing to reconstruct. STEP converts its units on import.",
            "cannot": ["Its feature history: STEP carries the final shape, not the sketches and dimensions that made it. "
                       "Features are added on top, or the part is rebuilt with Params where it must change."]
                      + ([] if solids else ["A body: the file has no solid, so volume and cuts need a closed model."]),
            "steps": ["create_design(..., references=[path]) or import_reference(project, path)",
                      "use it in the design: self.reference(name) (cut around it, add to it)"]
                     + (["analyze_assembly(project, references=[...]) for how the solids fit and move"] if several else [])}


_DXF_UNITS = {0: None, 1: "in", 2: "ft", 4: "mm", 5: "cm", 6: "m", 8: "microinch", 9: "mil", 10: "yd", 13: "micron",
              14: "dm"}
_MM = {"in": 25.4, "ft": 304.8, "mm": 1.0, "cm": 10.0, "m": 1000.0, "microinch": 25.4e-6, "mil": 0.0254,
       "yd": 914.4, "micron": 0.001, "dm": 100.0, "pt": 25.4 / 72, "pc": 25.4 / 6, "px": 25.4 / 96, "q": 0.25}


def assess_drawing(path: Path) -> dict:
    """A DXF or SVG: how many outlines, which are closed, their overall size in millimetres, the units."""
    ext = path.suffix.lower()
    facts = {"file": path.name, "format": ext[1:], "bytes": path.stat().st_size}
    if ext == ".dxf":
        import ezdxf
        from ezdxf import bbox as dxf_bbox
        try:
            doc = ezdxf.readfile(str(path))
        except (OSError, ezdxf.DXFError) as e:
            raise ValueError(f"not a readable DXF: {e}") from e
        msp = doc.modelspace()
        code = int(doc.header.get("$INSUNITS", 0) or 0)
        unit = _DXF_UNITS.get(code)
        k = _MM.get(unit or "mm", 1.0)
        kinds = {}
        closed = 0
        for e in msp:
            t = e.dxftype()
            kinds[t] = kinds.get(t, 0) + 1
            if t in ("CIRCLE", "ELLIPSE") or (t in ("LWPOLYLINE", "POLYLINE") and e.is_closed) or (
                    t == "SPLINE" and e.closed):
                closed += 1
        ext_box = dxf_bbox.extents(msp)
        size = [round((ext_box.extmax[i] - ext_box.extmin[i]) * k, 4) for i in (0, 1)] if ext_box.has_data else [0, 0]
        facts.update(entities=kinds, closed_outlines=closed, size_mm=size,
                     units={"units": unit or "mm", "source": "the file ($INSUNITS)" if unit else
                            "assumed (the drawing does not say: $INSUNITS is unset)"})
    else:
        import svgelements
        try:
            svg = svgelements.SVG.parse(str(path))
        except Exception as e:                       # noqa: BLE001 - svgelements raises many kinds on a bad file
            raise ValueError(f"not a readable SVG: {e}") from e
        shapes = [e for e in svg.elements() if isinstance(e, svgelements.Shape)]
        closed = 0
        for e in shapes:
            try:
                p = svgelements.Path(e)
                closed += sum(1 for sp in p.as_subpaths() if svgelements.Path(sp).segments() and
                              isinstance(svgelements.Path(sp).segments()[-1], svgelements.Close))
            except Exception:                        # noqa: BLE001 - an element without a path (text, an image)
                continue
        raw = path.read_text(encoding="utf-8", errors="replace")[:4000]
        m = re.search(r"<svg[^>]*\bwidth\s*=\s*\"([\d.]+)\s*(mm|cm|in|pt|pc|px|q)?\"", raw, re.I)
        unit = (m.group(2) or "").lower() if m else ""
        box = svg.bbox()
        # svgelements works in pixels (96 per inch), the physical units of width/height already applied
        size = [round((box[2] - box[0]) * _MM["px"], 4), round((box[3] - box[1]) * _MM["px"], 4)] if box else [0, 0]
        facts.update(shapes=len(shapes), closed_outlines=closed, size_mm=size,
                     units={"units": unit or "px", "source": "the file (width and height)" if unit in ("mm", "cm", "in", "q", "pt", "pc")
                            else "the SVG rule (96 px per inch), since the file gives no physical unit"})
    facts["evidence"] = "read from the file"
    return {"input": {"kind": "drawing", "path": str(path)}, "facts": facts, "class": None, "route": "profile",
            "prepare": [], "alternates": ["sketch"], "ask": None,
            "why": f"A 2D drawing with {facts['closed_outlines']} closed outline(s), "
                   + " x ".join(f"{x:g}" for x in facts["size_mm"]) + " mm overall: a profile at its own sizes.",
            "cannot": ["The depth or height: a drawing is flat. Ask for it, or read it from a dimension in the drawing."],
            "steps": ["create_design: the profile from the drawing (build123d import_svg for SVG; for DXF the outlines "
                      "with the sizes above), extruded, revolved or cut to the depth the person gives",
                      "ask_measurement for the depth when the drawing does not state it"]}


def assess_archive(path: Path, tolerance: float = 0.02) -> dict:
    """A zip: unpacked safely into a folder of its own (formats.unpack), each file it holds triaged."""
    got = formats.unpack(path)
    members = []
    for i, f in enumerate(got["files"]):
        rec = {"name": f["name"], "path": f["path"], "kind": f["kind"], "bytes": f["bytes"]}
        if i < MAX_ARCHIVE_TRIAGE:
            t = triage(f["path"], tolerance=tolerance)
            rec.update(route=t["route"], line=line(t), ask=t.get("ask"))
        members.append(rec)
    parts = [m for m in members if m["kind"] in formats.PART_KINDS]
    facts = {"file": path.name, "format": "zip", "bytes": path.stat().st_size, "folder": got["folder"],
             "files": len(members), "parts": len(parts), "skipped": got["skipped"][:20],
             "evidence": "read from the archive"}
    steps = ["Follow each file's own route, with its path below"]
    if len(parts) > 1:
        steps.insert(0, "Several parts of one product: reconstruct(files=[their paths]) makes ONE design with one part "
                        "each; import_reference each one to design around them")
    return {"input": {"kind": "archive", "path": str(path)}, "facts": facts, "class": None, "route": "archive",
            "members": members, "prepare": [{"step": "unpack", "folder": got["folder"],
                                             "note": "Unpacked safely: no file outside its folder, sizes bounded."}],
            "alternates": [], "ask": None, "cannot": [] if members else ["Anything: the zip holds no file Form Studio reads."],
            "why": f"A zip of {len(members)} file(s) Form Studio reads ({len(parts)} 3D part(s))"
                   + (f"; {len(got['skipped'])} other file(s) skipped" if got["skipped"] else "") + ".",
            "steps": steps}


def _word_route(text: str, intent: str = "") -> dict:
    t = text.strip()
    nums = re.findall(r"\d+(?:[.,]\d+)?\s*(?:mm|cm|m\b|in\b|inch|\"|°|deg|M\d)", t, re.I) + re.findall(r"\bM\d{1,2}\b", t)
    precise = len(nums) >= 2
    facts = {"words": len(t.split()), "dimensions_stated": len(nums)}
    if precise:
        return {"input": {"kind": "text"}, "facts": facts, "class": None, "route": "describe", "prepare": [],
                "alternates": ["concepts"], "ask": None, "cannot": [],
                "why": f"The words give {len(nums)} dimensions: a specification to build, not an open idea.",
                "steps": ["design_brief (the numbers become a checked contract)", "design_guide -> create_design",
                          "get_project: the proof sheet"]}
    return {"input": {"kind": "text"}, "facts": facts, "class": None, "route": "concepts", "prepare": [],
            "alternates": ["describe"], "ask": None, "cannot": [],
            "why": "An idea without sizes: several real designs to choose from say more than a question would.",
            "steps": ["propose_concepts: 3-4 structurally different designs, one line each", "stop: the person picks"]}


def triage(source, intent: str = "", tolerance: float = 0.02) -> dict:
    """Assess anything the person brings and choose the route. source: a file path, a link, or their words."""
    t0 = time.perf_counter()
    s = str(source or "").strip()
    out = None
    if re.match(r"^https?://", s, re.I):
        out = {"input": {"kind": "link", "url": s}, "facts": {}, "class": None, "route": "link", "prepare": [],
               "alternates": [], "ask": None, "cannot": [],
               "why": "A link: what it holds decides the route.",
               "steps": ["fetch_link(url): downloads only this link, never through a shell",
                         "triage(the file it saved) and follow that route"]}
    else:
        p = Path(s).expanduser() if s and "\n" not in s and len(s) < 1024 else None
        if p is not None and p.is_file():
            ext = p.suffix.lower()
            if ext in MESH:
                try:
                    out = assess_mesh(p, tolerance)
                except (ValueError, OSError) as e:
                    out = _unreadable(p, e, "Export it again as a binary STL, OBJ, 3MF or PLY.")
            elif ext in CAD:
                try:
                    out = assess_cad(p)
                except (OSError, ValueError) as e:
                    out = _unreadable(p, e, "Export it again as STEP (AP214 or AP242).")
            elif ext in ARCHIVE:
                try:
                    out = assess_archive(p, tolerance)
                except (OSError, ValueError) as e:
                    out = _unreadable(p, e, "Unpack it and send the files, or zip them again.")
            elif ext in PHOTO:
                out = {"input": {"kind": "photo", "path": str(p)}, "facts": {"file": p.name, "bytes": p.stat().st_size},
                       "class": None, "route": "photo_reference", "prepare": [], "alternates": [],
                       "why": "A picture has no scale of its own: one known length in it sets every size.",
                       "ask": {"question": "What in the photo has a size you know (a bank card, a coin, a ruler), or which "
                                           "one dimension can you measure for me?",
                               "choices": ["A bank card is in the photo", "I will measure one dimension"],
                               "why": "Without one real length every size read from the photo is a guess."},
                       "cannot": ["Fit-critical or hidden dimensions: a photo gives rough outer sizes (assumed, not "
                                  "measured) and nothing behind what it shows."],
                       "steps": ["look at the photo; scale from the reference object (bank card 85.60 x 53.98 mm)",
                                 "ask_measurement for any dimension that decides a fit", "design_guide -> create_design"]}
            elif ext in DOCUMENT:
                out = {"input": {"kind": "document", "path": str(p)}, "facts": {"file": p.name, "bytes": p.stat().st_size},
                       "class": None, "route": "document", "prepare": [], "alternates": [], "ask": None,
                       "why": "A PDF: a drawing or a datasheet, read page by page.",
                       "cannot": ["Dimensions the drawing does not state: they are asked for or stay assumed."],
                       "steps": ["read_document(path): pages as images", "design_brief with the stated dimensions "
                                 "(source: specified)", "create_design"]}
            elif ext in VECTOR:
                try:
                    out = assess_drawing(p)
                except (OSError, ValueError) as e:
                    out = _unreadable(p, e, "Export the drawing again as DXF (R2010 or later) or SVG.")
            elif ext == ".json":
                out = {"input": {"kind": "sketch", "path": str(p)}, "facts": {"file": p.name, "bytes": p.stat().st_size},
                       "class": None, "route": "sketch", "prepare": [], "alternates": [], "ask": None,
                       "why": "A drawn outline: its own numbers are authoritative over how it looks.",
                       "cannot": [], "steps": ["read the outline and its dimensions", "create_design from it"]}
            else:
                out = {"input": {"kind": "unknown", "path": str(p)}, "facts": {"file": p.name, "bytes": p.stat().st_size},
                       "class": None, "route": "unknown", "prepare": [], "alternates": [], "ask": None,
                       "why": formats.unsupported(p),
                       "cannot": ["Reading this file."],
                       "steps": ["Ask for the part as " + formats.supported_text("mesh", "brep") + "; a scan as "
                                 + formats.supported_text("pointcloud") + "; PNG or JPG for a photo; PDF for a drawing."]}
        elif p is not None and formats.kind_of(p) is not None and ("/" in s or "\\" in s):
            out = {"input": {"kind": "unknown", "path": s}, "facts": {}, "class": None, "route": "unknown", "prepare": [],
                   "alternates": [], "ask": None, "why": f"There is no file at {s}.", "cannot": ["Reading a file that is not there."],
                   "steps": ["Give the absolute path of the file the person attached."]}
        else:
            out = _word_route(s, intent)
    out["route_means"] = ROUTES.get(out["route"], "")
    out.setdefault("seconds", round(time.perf_counter() - t0, 2))
    return out


def _unreadable(p: Path, e: Exception, hint: str) -> dict:
    return {"input": {"kind": "unknown", "path": str(p)}, "facts": {"file": p.name, "bytes": p.stat().st_size},
            "class": None, "route": "unknown", "prepare": [], "alternates": [], "ask": None,
            "why": f"{p.name} could not be read: {e}", "cannot": ["Reading this file as it is."], "steps": [hint]}


def line(t: dict) -> str:
    """One sentence for a log or a chat: what it is and what happens to it."""
    f = t.get("facts") or {}
    what = t["input"]["kind"]
    if what in ("mesh", "pointcloud"):
        what = (f"{t.get('class')} {'surface from points' if what == 'pointcloud' else 'mesh'}, {f.get('triangles', 0):,} triangles, "
                + " x ".join(f"{x:g}" for x in f.get("size_mm", [])) + " mm")
    return f"{what}: route {t['route']} ({t.get('why', '')})"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help"):
        print("usage: form triage FILE|LINK|WORDS   (what it is, and the route Form Studio takes)")
        return 0 if argv else 2
    print(json.dumps(triage(" ".join(argv)), indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
