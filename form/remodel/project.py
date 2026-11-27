"""The remodel tools on a project's imported meshes: analysis, assembly analysis and comparison, cached and saved.

Engine side, no OCCT: the mesh analyses run here; comparing a design asks the kernel for the design's tessellation
(Studio.view). Results and pictures are kept in the project's `references/.remodel` folder, named by the mesh's
SHA-256 and the method version, so asking again is instant and a changed mesh is analysed again.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from . import VERSION

REMODEL_TOLERANCE = 0.1      # mm: the default limit for a remodel (clean CAD that reads like the original)


def _ref(st, p: dict, reference: str) -> tuple[dict, Path]:
    from ..recon.mesh import FORMATS
    from ..studio import StudioError
    refs = st.references(p)
    rec = next((r for r in refs if r["file"] == reference), None)
    if rec is None:                                     # "Base" for Base.stl, any case
        want = Path(str(reference)).stem.lower()
        rec = next((r for r in refs if Path(r["file"]).stem.lower() == want), None)
    if rec is None:
        names = ", ".join(r["file"] for r in refs) or "none"
        raise StudioError(f"There is no reference part “{reference}” in this project.",
                          f"Imported: {names}. Import the mesh first (import_reference).")
    if Path(rec["file"]).suffix.lower() not in FORMATS:
        raise StudioError(f"{rec['file']} is already CAD (STEP, IGES or BREP).",
                          "Read it in a design with self.reference(...) and measure it with measure; the remodel tools "
                          "are for meshes and scans.")
    path = st.dir(p["id"]) / "references" / rec["file"]
    return rec, path


def _h(s: str) -> str:
    import hashlib
    return hashlib.sha1(s.encode()).hexdigest()[:10]


def _cache(st, p) -> Path:
    d = st.dir(p["id"]) / "references" / ".remodel"
    d.mkdir(parents=True, exist_ok=True)
    return d


def analyze_reference(st, p: dict, reference: str, tolerance: float = 0.05, levels: dict | None = None) -> dict:
    """Analyse one imported mesh. Returns the brief (JSON) plus "images": [{"axis", "path"}] and "saved": the full
    analysis JSON (outlines included)."""
    from ..studio import StudioError
    from . import analyze as an
    rec, path = _ref(st, p, reference)
    if not (0.005 <= float(tolerance) <= 1.0):
        raise StudioError("The tolerance must be between 0.005 and 1 mm.")
    lv = {str(k): [float(x) for x in v] for k, v in (levels or {}).items()}
    if any(k not in ("x", "y", "z") for k in lv):
        raise StudioError("levels: give section levels per axis, for example {\"z\": [1.5, 4], \"y\": [-40, 0]}.")
    key = f"{(rec.get('sha256') or 'x')[:16]}-t{tolerance:g}-v{VERSION}" + (f"-{_h(json.dumps(lv, sort_keys=True))}" if lv else "")
    stem = Path(rec["file"]).stem
    d = _cache(st, p)
    jf = d / f"{stem}-{key}.json"
    if jf.exists():
        out = json.loads(jf.read_text(encoding="utf-8"))
        return out
    V, F, info = an.load(path)
    if not info.get("closed"):
        raise StudioError(f"{rec['file']} is not closed (it has open edges), so it does not bound a solid.",
                          "Close it in the program that made it, or reconstruct it (reconstruct fills holes and lists it).")
    res = an.analyse(V, F, tol=float(tolerance), name=stem, section_levels=lv or None)
    imgs = []
    for ax, png in an.images(res):
        f = d / f"{stem}-{key}-sections-{ax}.png"
        f.write_bytes(png)
        imgs.append({"axis": ax, "path": str(f)})
    full = an.public(res)
    (d / f"{stem}-{key}-full.json").write_text(json.dumps(full, default=float), encoding="utf-8")
    np.savez_compressed(d / f"{stem}-{key}-tris.npz",
                        **{f"f{i}": f["_tris"] for i, f in enumerate(res["features"]) if f.get("_tris") is not None})
    out = an.brief(res)
    out.update({"reference": rec["file"], "images": imgs, "saved": str(d / f"{stem}-{key}-full.json"),
                "next": "Plan the features named after what they are (base plate, rails, card slot, ramp…), write "
                        "build123d code with Params (create_design), then compare_to_reference and refine."})
    jf.write_text(json.dumps(out, default=float), encoding="utf-8")
    return out


def _analysis_with_tris(st, p, rec) -> dict | None:
    """The latest saved analysis of a reference with its features' triangles (for per-feature comparison)."""
    d = _cache(st, p)
    stem = Path(rec["file"]).stem
    sha = (rec.get("sha256") or "x")[:16]
    fulls = sorted(d.glob(f"{stem}-{sha}-*-v{VERSION}-full.json"), key=lambda f: f.stat().st_mtime)
    if not fulls:
        return None
    full = json.loads(fulls[-1].read_text(encoding="utf-8"))
    tf = Path(str(fulls[-1]).replace("-full.json", "-tris.npz"))
    if tf.exists():
        z = np.load(tf)
        for i, f in enumerate(full["features"]):
            if f"f{i}" in z:
                f["_tris"] = z[f"f{i}"]
    return full


def analyze_assembly(st, p: dict, references: list, fixed: str | None = None, near: float = 1.0) -> dict:
    from ..studio import StudioError
    from . import analyze as an
    from . import mechanism
    if not references or len(references) < 2:
        raise StudioError("Give two or more imported meshes.", "references: the file names, the part that stays still first.")
    recs = [_ref(st, p, r) for r in references]
    key = "-".join((r.get("sha256") or "x")[:10] for r, _ in recs) + f"-n{near:g}-f{fixed or ''}-v{VERSION}"
    f = _cache(st, p) / f"assembly-{_h(key)}.json"
    if f.exists():
        cached = json.loads(f.read_text(encoding="utf-8"))
        if cached.get("_key") == key:
            cached.pop("_key", None)
            return cached
    parts = []
    for rec, path in recs:
        V, F, _ = an.load(path)
        parts.append((Path(rec["file"]).stem, V, F))
    fx = Path(fixed).stem if fixed else None
    out = mechanism.analyse(parts, fixed=fx, near=float(near))
    out["references"] = [r["file"] for r, _ in recs]
    out["next"] = ("Model each part (analyze_reference on each), then declare the assembly: one Part per mesh in the same "
                   "coordinates, and the joints found here (slide or hinge with their axes and ranges); name couplings "
                   "in the design's notes. Check each part with compare_to_reference(part=...).")
    f.write_text(json.dumps({**out, "_key": key}, default=float), encoding="utf-8")
    return out


def compare_to_reference(st, p: dict, reference: str, part: str | None = None, tolerance: float = REMODEL_TOLERANCE,
                         rev: int | None = None) -> dict:
    """The design (or one part) against an imported mesh. Returns the numbers plus "image": the deviation picture."""
    from ..studio import StudioError
    from . import analyze as an
    from . import compare as cmp
    rec, path = _ref(st, p, reference)
    view = st.view(p, rev, tol=min(0.02, float(tolerance) / 4), timeout=300)
    try:
        P, T = cmp.design_mesh(view, part)
    except ValueError as e:
        raise StudioError(str(e), "Name the part as the design's assembly does (get_project lists the parts), "
                                  "or leave part out to compare the whole design.") from None
    V, F, _ = an.load(path)
    ana = _analysis_with_tris(st, p, rec)
    res = cmp.compare(V, F, P, T, tol=float(tolerance), analysis=ana, name=Path(rec["file"]).stem)
    n = st.rev(p, rev)["n"]
    d = st.dir(p["id"]) / "artifacts" / "remodel"
    d.mkdir(parents=True, exist_ok=True)
    img = d / f"compare-r{n:02d}-{Path(rec['file']).stem}-{part or 'all'}.png"
    img.write_bytes(cmp.picture(res, f"{p['name']} r{n:02d} vs {rec['file']}"))
    out = cmp.public(res)
    out.update({"reference": rec["file"], "part": part, "rev": n, "image": str(img),
                "verdict": (f"Within {tolerance:g} mm of the mesh everywhere (two-sided Hausdorff {res['hausdorff_mm']:.3f} mm)."
                            if res["within_tolerance"] else
                            f"Not yet: {res['regions_over_tolerance']} region(s) are more than {tolerance:g} mm from the mesh "
                            f"(Hausdorff {res['hausdorff_mm']:.3f} mm). Fix the worst first; they are listed with where they are.")})
    if ana is None:
        out["note"] = "Run analyze_reference on this mesh first to get per-feature differences and feature names."
    return out


def rebuild_brief(st, p: dict, files: list | None = None) -> dict:
    """The message that starts "Rebuild as editable CAD": the agent remodel of this project's meshes, staged
    (design_guide topic "reference_parts"). Returns {"message", "files"}."""
    from ..recon.mesh import FORMATS
    from ..studio import StudioError
    meshes = [r["file"] for r in st.references(p) if Path(r["file"]).suffix.lower() in FORMATS]
    files = [f for f in (files or meshes) if f in meshes]
    if not files:
        raise StudioError("This project has no imported mesh to rebuild.", "Import an STL, OBJ or 3MF first (Brief > Import part).")
    names = ", ".join(files[:-1]) + (" and " if len(files) > 1 else "") + files[-1]
    lines = [f"Rebuild {names} as clean, fully editable CAD, like a part designed from scratch: named features, "
             "Params for the dimensions that matter, sharp edges only where the part has edges. They are imported in "
             f"this project ({p['id']}) as reference parts. Follow design_guide topic \"reference_parts\":"]
    lines.append("1. Never embed the meshes as the design; keep them as blueprint references only.")
    lines.append("2. analyze_reference on " + ("each mesh" if len(files) > 1 else "the mesh") + " and look at the section pictures.")
    if len(files) > 1:
        lines.append(f"3. analyze_assembly(references={json.dumps(files)}) (the first stays still), then tell me in one "
                     "sentence how the parts go together and move.")
    else:
        lines.append("3. Tell me in one sentence what the part is and how it is made.")
    lines.append("4. Plan the features in build order, named after what they are, with their Params.")
    lines.append("5. Write it in build123d with create_design" + (" (one Part per mesh in the same coordinates, joints for "
                 "the motion analyze_assembly found)" if len(files) > 1 else "") + ".")
    lines.append(f"6. compare_to_reference{' for each part' if len(files) > 1 else ''} and refine until the two-sided "
                 f"Hausdorff is within {REMODEL_TOLERANCE:g} mm; then tell me where it still differs from the mesh and by how much.")
    rec = p.get("reconstruction") or {}
    s = rec.get("summary") or {}
    if s:
        edit = s.get("editable_pct", s.get("driven_by_params_pct")) or 0
        lines.append(f"Make editable (the deterministic route) reached Layer {s.get('layer')}: {edit:g}% of the surface "
                     f"driven by Params, {s.get('hausdorff_mm')} mm from the mesh ({s.get('frozen_area_pct')}% the mesh's "
                     "own facets)" + ("" if s.get("recipe_verified") else
                                                                  ", with no verified feature recipe") + ".")
    return {"message": "\n".join(lines), "files": files}
