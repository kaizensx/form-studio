"""The documents a maker needs, generated from the revision's real geometry, checks and slice.

BOM.csv, ASSEMBLY.md (with an exploded image per step), PRINT_REPORT.md, MEASUREMENT_PLAN.md and, when the design
has joints, MOTION_CHECKS.csv. Structure follows the original studio templates (templates/bom.csv, print_report.md,
measurement_plan.md, motion_checks.csv). Nothing here is invented: a value FORM does not have is left blank or
marked NOT RUN, and every number says how it is known.
"""
from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import time
import zipfile
from pathlib import Path

import numpy as np
from . import fsutil

DOCS_VERSION = 1
NAMES = ("BOM.csv", "ASSEMBLY.md", "PRINT_REPORT.md", "MEASUREMENT_PLAN.md", "MOTION_CHECKS.csv")
RENDER_TOL = 0.2          # coarse tessellation: the step images are diagrams, not measurements


# ---- inputs ----------------------------------------------------------------------------------------------
def _inputs(st, p) -> dict:
    from .studio import H
    rev, keys, recipe = st.rev(p), st.keys(p), st.recipe(p)
    status = st.status(p)
    cur = lambda n: st.read(p, n, keys[n]) if status[n]["state"] == "current" else None
    view = st._k("view", key=keys["geometry"], recipe_id=st.rid(p), values=rev["values"], tol=RENDER_TOL, edges=True)
    return {"p": p, "rev": rev, "keys": keys, "recipe": recipe, "status": status, "checks": cur("checks"),
            "slice": cur("slice"), "exports": cur("exports"), "view": view, "asm": view.get("assembly"),
            "kernel": st.kernel_id(), "recipe_sha": st.recipe_sha(st.rid(p)), "rid": st.rid(p),
            "key": H("maker-docs", DOCS_VERSION, keys, status["checks"]["state"], status["slice"]["state"])}


def _stamp(d, release):
    rel = f"release {release}" if release else "working files, not a release"
    return f"{d['p']['name']} · r{d['rev']['n']:02d} · {rel}"


def _prov(d, key):
    return (d["rev"]["provenance"].get(key) or {}).get("source", "assumed")


# ---- BOM -----------------------------------------------------------------------------------------------
def bom(d) -> str:
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["item", "kind", "quantity", "description", "standard_or_supplier_reference", "material", "grams",
                "grams_evidence", "source_url", "verified_dimensions", "notes"])
    sl, name = d["slice"], f"{d['p']['id']}_r{d['rev']['n']:02d}"
    material = (sl or {}).get("presets", {}).get("filament", {}).get("name") if sl else None
    total_g = sl.get("filament_g") if sl else None
    asm = d["asm"] if d["asm"] and not d["asm"].get("error") else None
    parts = asm["parts"] if asm else [{"label": d["p"]["name"], "solid": 0, "volume_mm3": d["view"]["volume_mm3"],
                                       "print_bbox": d["view"]["bbox"], "material": ""}]
    vol = sum(x["volume_mm3"] for x in parts) or 1.0
    for x in parts:
        size = np.subtract(x["print_bbox"][1], x["print_bbox"][0])
        g = f"{total_g * x['volume_mm3'] / vol:.1f}" if total_g else ""
        ev = ("simulated plate total, split by part volume (computed)" if len(parts) > 1 else "simulated (slicer)") if total_g \
            else "not sliced"
        w.writerow([x["label"], "printed", 1, f"{size[0]:.1f} x {size[1]:.1f} x {size[2]:.1f} mm as printed",
                    f"{name}.stl" + (f", solid {x['solid'] + 1} of {len(parts)}" if len(parts) > 1 else ""),
                    x.get("material") or material or "not set: no current slice", g, ev, "", "no", ""])
    for h in (asm["hardware"] if asm else []):
        w.writerow([h["name"], "purchased", h["qty"], h["size"], h["source"], "", "", "", h.get("url", ""),
                    "no: check against the printed part", h["note"]])
    return out.getvalue()


# ---- assembly steps and images ------------------------------------------------------------------------
def _xf(P, m, off):
    M = np.asarray(m, float)
    return P @ M[:, :3].T + M[:, 3] + np.asarray(off, float)


def _scene(d, placed: dict, highlight: str):
    """Meshes for render.render_png: placed = {part_id: offset}, parts in the assembled frame plus offset."""
    asm, out, edges = d["asm"], [], []
    by_id = {x["id"]: x for x in asm["parts"]}
    for m in d["view"]["mesh"]:
        if m.get("part") not in placed:
            continue
        x = by_id[m["part"]]
        P = np.frombuffer(base64.b64decode(m["positions"]), np.float32).reshape(-1, 3).astype(float)
        P = _xf(P, x["placement"]["m"], placed[m["part"]]).astype(np.float32)
        out.append({"feature": "new" if m["part"] == highlight else "placed",
                    "positions": base64.b64encode(P.tobytes()).decode(), "indices": m["indices"]})
    for pid, off in placed.items():
        E = np.frombuffer(base64.b64decode(by_id[pid]["edges"]), np.float32).reshape(-1, 3).astype(float)
        if len(E):
            edges.append(_xf(E, by_id[pid]["placement"]["m"], off).astype(np.float32))
    e = base64.b64encode(np.concatenate(edges).tobytes()).decode() if edges else ""
    return {"mesh": out, "edges": e}


def _steps(asm) -> list:
    steps, hw = [], asm["hardware"]
    for i, x in enumerate(asm["parts"]):
        steps.append({"kind": "part", "part": x, "upto": i})
        steps += [{"kind": "hardware", "hw": h, "upto": i} for h in hw if h.get("after") == x["id"]]
    steps += [{"kind": "hardware", "hw": h, "upto": len(asm["parts"]) - 1} for h in hw if not h.get("after")]
    return steps


def _dir_text(v):
    v = np.asarray(v, float)
    n = float(np.linalg.norm(v))
    if n < 1e-9:
        return "in place (no separation set)"
    names = [("+X", "-X"), ("+Y (back)", "-Y (front)"), ("+Z (up)", "-Z (down)")]
    parts = [names[i][0 if v[i] > 0 else 1] for i in range(3) if abs(v[i]) > 1e-6 * n]
    return f"{n:.0f} mm along " + " and ".join(parts)


def assembly_md(d, out_dir: Path, release=None) -> tuple[str, list]:
    from .render import render_png
    asm = d["asm"]
    steps = _steps(asm)
    ids = [x["id"] for x in asm["parts"]]
    images = []
    lines = [f"# Assembly: {d['p']['name']}", "", f"{_stamp(d, release)}. Units: mm.", "",
             "Steps follow the part order the design declares. Images are drawn from the revision's solids, placed as "
             "the design's assembly declares, with the new part lifted along its separation direction (exploded). "
             "They are diagrams; Form Studio has not seen the parts go together.", ""]
    ov = f"assembly-00.png"
    feats = [{"id": "placed", "label": "Assembled"}, {"id": "new", "label": "This step"}]
    png = render_png(_scene(d, {x["id"]: x["explode"] for x in asm["parts"]}, ""), feats[:1], "iso", None, size=(880, 600),
                     title="Exploded view", caption="Each part offset along its separation direction")
    (out_dir / ov).write_bytes(png)
    images.append(ov)
    lines += [f"![Exploded view]({ov})", "", "## Parts and hardware", ""]
    lines += [f"- {x['label']} (printed)" for x in asm["parts"]]
    lines += [f"- {h['qty']} x {h['name']}, {h['size']} ({h['source'] or 'source not given'})" for h in asm["hardware"]]
    lines += ["", "## Steps", ""]
    for k, s in enumerate(steps, 1):
        placed = {ids[i]: [0, 0, 0] for i in range(s["upto"] + 1)}
        if s["kind"] == "part":
            x = s["part"]
            placed[x["id"]] = x["explode"]
            title, text = f"Step {k}: {x['label']}", x["note"] or f"Place the {x['label'].lower()}."
            how = "Separation direction: " + _dir_text(x["explode"]) + "."
            hl = x["id"]
        else:
            h = s["hw"]
            title, text = f"Step {k}: {h['name']} x {h['qty']}", h["note"] or f"Fit the {h['name'].lower()}."
            how = f"{h['size']}. " + (f"Tool access checked: {len(h['access'])} straight path(s), see PRINT_REPORT.md." if h["access"] else "")
            hl = ""
        img = f"assembly-{k:02d}.png"
        (out_dir / img).write_bytes(render_png(_scene(d, placed, hl), feats if hl else feats[:1], "iso", "new" if hl else None,
                                               size=(880, 600), title=title, caption=how))
        images.append(img)
        lines += [f"### {k}. {title.split(': ', 1)[1]}", "", text, "", how, "", f"![{title}]({img})", ""]
    if asm["joints"]:
        lines += ["## Moving parts", ""]
        for j in asm["joints"]:
            u = "°" if j["kind"] == "hinge" else " mm"
            lines.append(f"- {j['label']}: {j['part']} {j['kind']}, {j['range'][0]:g}–{j['range'][1]:g}{u}, "
                         f"checked at {j['samples']} positions (see MOTION_CHECKS.csv). Sampled positions only.")
        lines.append("")
    lines += ["## Limits", "", "- Placements come from the design's assembly declaration; the checks test that geometry, not the printed parts.",
              "- Printed parts differ from the model by the printer's accuracy; see the fit and clearance checks.", ""]
    return "\n".join(lines), images


# ---- reports --------------------------------------------------------------------------------------------
def _check_row(checks, *ids):
    got = [c for c in checks if c["id"] in ids] if checks else []
    if not got:
        return None
    st = "FAIL" if any(c["status"] == "FAIL" for c in got) else ("WARN" if any(c["status"] == "WARN" for c in got) else "PASS")
    return st, "; ".join(f"{c['label']}: {c['value']} ({c['evidence']})" for c in got)


def print_report(d, release=None) -> str:
    p, rev, ch, sl, ex = d["p"], d["rev"], d["checks"], d["slice"], d["exports"]
    checks = ch["checks"] if ch else None
    asm_ids = [c["id"] for c in checks or [] if c["id"].startswith("asm_")]
    hashes = ", ".join(f"{v['name']} `{v['sha256'][:16]}…`" for v in (ex or {}).get("files", {}).values()) or "exports not current"
    lines = ["# Print report", "", f"Part / revision: {p['name']} r{rev['n']:02d}",
             f"Release stage: {'released as ' + release if release else 'working files, not released'}",
             f"Source of truth: recipe `{d['rid']}` @ `{d['recipe_sha']}` (design source in the project)",
             f"Source / STEP / mesh hashes: {hashes}",
             f"Tool and dependency versions: {d['kernel']}" + (f"; Bambu Studio {sl.get('slicer_version')}" if sl else "; slicer: not run"),
             f"Generated: {time.strftime('%Y-%m-%d %H:%M')}", "",
             "| Check | PASS / FAIL / NOT RUN | Evidence / result |", "|---|---|---|"]
    geo = d["status"]["geometry"]["state"] == "current"
    rows = [("Clean regeneration", ("PASS", "solid rebuilt from source by the kernel for this revision (computed)") if geo else None),
            ("Parametric variation", None),
            ("BREP validity and solid count", _check_row(checks, "solid")),
            ("Envelope and critical interface measurements", _check_row(checks, "envelope", "interfaces")),
            ("STEP round-trip", None),
            ("Mesh screening and documented limits", _check_row(checks, "mesh", "conversion")),
            ("Thickness / intersections where required", _check_row(checks, "wall", "asm_interference", "asm_clearance")),
            ("Assembly motion and tool access", _check_row(checks, *[i for i in asm_ids if i.startswith(("asm_motion", "asm_access"))])),
            ("Actual visual review, including underside / sections", None),
            ("Correct machine/nozzle/material/plate", ("PASS", "sliced with " + " · ".join(v["name"] for v in sl["presets"].values()) + " (simulated)")
             if sl and sl.get("presets") else None),
            ("Slice and layer inspection", ("PASS", f"sliced: {sl.get('layers')} layers (simulated); layer-by-layer review by a person not recorded")
             if sl else None),
            ("Physical fit / functional tests", None)]
    phys = [e for e in p["evidence"] if e["rev"] == rev["n"]]
    if phys:
        rows[-1] = ("Physical fit / functional tests", ("PASS" if all(e.get("result", "good") == "good" for e in phys) else "FAIL",
                                                        f"{len(phys)} physical record(s) for this revision"))
    for label, r in rows:
        if label == "Assembly motion and tool access" and r is None and not d["asm"]:
            continue
        lines.append(f"| {label} | {r[0] if r else 'NOT RUN'} | {r[1] if r else ''} |")
    lines += ["", "## All checks", "", "| Check | Result | Value | Evidence | Detail |", "|---|---|---|---|---|"]
    lines += [f"| {c['label']} | {c['status']} | {c['value']} | {c['evidence']} | {c['detail'].replace('|', '/')} |" for c in checks or []]
    if not checks:
        lines.append("| Checks | NOT RUN | | | The checks for this revision are not current. Run the pipeline. |")
    lines += ["", "Evidence classes: computed = measured on the solid or mesh by the kernel; heuristic = rule of thumb; "
              "model = statistical or rigid-body model; simulated = slicer; physical = recorded from a real print.", ""]
    motion = [c for c in checks or [] if c["id"].startswith("asm_motion")]
    if motion:
        lines += ["## Motion checks (sampled)", "", "| Joint | Result | Worst | Samples | Method |", "|---|---|---|---|---|"]
        lines += [f"| {c['label']} | {c['status']} | {c['value']} | {len(c.get('samples', []))} | boolean overlap + B-rep distance (computed); "
                  "does not prove continuous freedom |" for c in motion]
        lines += ["", "Per-position results: MOTION_CHECKS.csv.", ""]
    s = sl or {}
    lines += ["## Process", "",
              "Configured layer height / widths / walls / infill / top-bottom: " + (" · ".join(v["name"] for v in s.get("presets", {}).values())
                                                                                     + " (slicer presets)" if s else "not sliced"),
              f"Orientation, seams, brim, supports and removal: {p['orientation']}; supports "
              + ("used" if s.get("support_used") else "not used" if s else "unknown (not sliced)") + "; seams and brim: see the slicer project",
              "Slicer-estimated time and material: " + (f"{s['time_s'] / 60:.0f} min, {s['filament_g']:.1f} g (simulated)" if s.get("time_s") and s.get("filament_g") is not None else ("sliced; the slicer gave no estimate" if s else "not sliced")),
              ""]
    lines += ["## Measured results (fill in after printing)", "",
              "Actual physical measurements and test conditions:", "", "| Feature | Intended (mm) | Measured (mm) | Tool | By / date |",
              "|---|---|---|---|---|"]
    for x in [x for x in d["view"]["derived"] if x.get("interface")][:8]:
        lines.append(f"| {x['label']} | {x['value']:.2f} | ______ | ______ | ______ |")
    lines += ["| ______ | ______ | ______ | ______ | ______ |", "", "Printer, filament, room temperature: ______________________", "",
              "Assembly steps: " + ("see ASSEMBLY.md" if d["asm"] else "single part"), ""]
    assumed = [sp for sp in d["recipe"].params if _prov(d, sp.key) == "assumed" and sp.group in ("brief", "interface", "process")]
    lines += ["## Residual uncertainty", ""]
    lines += [f"- {sp.label} = {rev['values'][sp.key]:g} {sp.unit} is assumed." for sp in assumed] or ["- No brief or interface value is marked assumed."]
    lines += ["- No structural analysis was performed.", "- Slicer output is a simulation, not a print.", ""]
    brief_assumed = [sp for sp in assumed if sp.group == "brief"]
    nxt = (f"measure {', '.join(sp.label.lower() for sp in brief_assumed[:3])} (MEASUREMENT_PLAN.md)" if brief_assumed else
           "print the fit test piece, or the part, and record the result in Form Studio")
    lines += ["Next smallest useful test: " + nxt + ".", ""]
    return "\n".join(lines)


def _technique(sp) -> str:
    lab = sp.label.lower()
    if sp.unit in ("deg", "°"):
        return "Protractor or angle gauge against the reference face; two readings."
    if sp.unit != "mm":
        return "Count or read it from the object or its documentation."
    if any(k in lab for k in ("height", "deep")):
        return "Calipers, depth rod, from the reference face down; three readings at different places, record the median."
    if any(k in lab for k in ("inner", "inside", "opening", "hole", "slot", "gap")):
        return "Calipers, inside jaws; three readings at different places, record the median."
    if "depth" in lab:
        return "Calipers, depth rod or outside jaws front to back; three readings at different places, record the median."
    if "diameter" in lab:
        return "Calipers, outside jaws across the widest point; turn 90° and repeat; record both."
    return "Calipers, outside jaws, square to the faces; three readings at different places, record the median."


def measurement_plan(d, release=None) -> str:
    rev, recipe = d["rev"], d["recipe"]
    brief = [sp for sp in recipe.params if sp.group == "brief"]
    fit = recipe.fit or {}
    lines = ["# Measurement plan", "", f"Part/revision: {_stamp(d, release)}", "",
             "Only the dimensions below come from the world rather than from the design. Values marked assumed have not been "
             "measured; Form Studio keeps them, labels every check that depends on them, and design work can continue. "
             "Never write a value here that was not measured.", "",
             "| Feature | Parameter | Value now | Known as | Source |", "|---|---|---|---|---|"]
    for sp in brief:
        pv = rev["provenance"].get(sp.key) or {}
        lines.append(f"| {sp.feature or '-'} | {sp.label} | {rev['values'][sp.key]:g} {sp.unit} | {pv.get('source', 'assumed')} | "
                     f"{pv.get('note') or sp.doc or ''} |")
    todo = [sp for sp in brief if _prov(d, sp.key) == "assumed"]
    lines += ["", f"## To measure ({len(todo)})", ""]
    if not todo:
        lines += ["Nothing: every brief dimension is measured or specified.", ""]
    for i, sp in enumerate(todo, 1):
        prec = "±0.1 mm"
        if fit.get("mating") == sp.key:
            w = fit.get("window") or [0, 0.4]
            prec = f"±{max(0.02, (w[1] - w[0]) / 4):.2f} mm (a quarter of the fit window {w[0]:g}–{w[1]:g} mm)"
        lines += [f"### {chr(64 + i) if i <= 26 else i}. {sp.label}", "",
                  f"Question that this measurement resolves: is {sp.label.lower()} really {rev['values'][sp.key]:g} {sp.unit}? "
                  f"It drives the {sp.feature or 'design'} feature" + (" and the fit model." if fit.get("mating") == sp.key else "."),
                  "Reference datum: the object's own faces (the part's design origin is the centre of its base); state which faces you used.",
                  f"Tool and measurement technique: {_technique(sp)}",
                  f"Required precision / acceptable uncertainty: {prec}",
                  "Photo or sketch with marked locations: attach a photo of the object with the measured faces marked.",
                  "Can independent form development continue?: yes; the value stays assumed until a measurement is recorded.",
                  "", "Measured value: ______ mm   Tool: ______   By / date: ______", ""]
    lines += ["Record results in Form Studio (Brief: set the value and choose 'measured'), so the next revision and its checks use them.", ""]
    return "\n".join(lines)


def motion_csv(d) -> str:
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["revision", "configuration", "angle_or_travel", "collision_check_method", "minimum_measured_clearance_mm",
                "interference", "artifact", "limitations"])
    for c in (d["checks"] or {}).get("checks", []):
        if not c["id"].startswith("asm_motion"):
            continue
        for s in c.get("samples", []):
            w.writerow([f"r{d['rev']['n']:02d}", c["label"], s["value"], "B-rep boolean intersection and distance (computed)",
                        "" if s["clearance_mm"] is None else s["clearance_mm"],
                        f"{s['overlap_mm3']} mm3 with {s['with']}" if s["overlap_mm3"] > 0.01 else "none",
                        f"checks/{d['keys']['checks'][:12]}", "computed from the model, not measured; sampled positions only"])
    return out.getvalue()


# ---- writing ------------------------------------------------------------------------------------------------
def write(st, p, out_dir: Path, release: str | None = None, d: dict | None = None) -> dict:
    """Write every document for the head revision into out_dir. Returns {file name: sha256}."""
    d = d or _inputs(st, p)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    texts = {"BOM.csv": bom(d), "PRINT_REPORT.md": print_report(d, release), "MEASUREMENT_PLAN.md": measurement_plan(d, release)}
    images = []
    if d["asm"] and not d["asm"].get("error") and not d["asm"].get("derived"):
        texts["ASSEMBLY.md"], images = assembly_md(d, out_dir, release)
        if d["asm"]["joints"]:
            texts["MOTION_CHECKS.csv"] = motion_csv(d)
    for name, t in texts.items():
        (out_dir / name).write_text(t, encoding="utf-8")
    files = list(texts) + images
    return {f: hashlib.sha256((out_dir / f).read_bytes()).hexdigest() for f in files}


def working(st, p, name: str) -> Path:
    """A document for the head revision's working files (regenerated when its inputs change). name may be docs.zip."""
    d = _inputs(st, p)
    base = st.dir(p["id"]) / "artifacts" / "docs" / d["key"]
    if not (base / "index.json").exists():
        tmp = base.with_name(base.name + ".tmp")
        files = write(st, p, tmp, None, d)
        (tmp / "index.json").write_text(json.dumps(files, indent=1), encoding="utf-8")
        fsutil.replace_dir(tmp, base)
    files = json.loads((base / "index.json").read_text(encoding="utf-8"))
    if name == "docs.zip":
        z = base / f"{p['id']}_r{d['rev']['n']:02d}_docs.zip"
        if not z.exists():
            with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
                for f in files:
                    zf.write(base / f, f)
        return z
    if name not in files:
        from .studio import StudioError
        raise StudioError(f"{name} is not generated for this design.", "ASSEMBLY.md and MOTION_CHECKS.csv need an assembly with joints.", status=404)
    return base / name


def release_zip(st, p, release: str) -> Path:
    from .studio import StudioError
    rel = st.dir(p["id"]) / "releases" / release
    if not (rel / "MANIFEST.json").is_file():
        raise StudioError("Unknown release.", status=404)
    m = json.loads((rel / "MANIFEST.json").read_text(encoding="utf-8"))
    docs = [f for f in m.get("documents", []) if (rel / f).is_file()]
    if not docs:
        from .studio import StudioError
        raise StudioError("This release has no maker documents.", "Releases made before Form Studio generated them have only REPORT.md.", status=404)
    z = st.root / f".{p['id']}-{release}-docs.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in docs:
            zf.write(rel / f, f)
    return z


def available(st, p) -> list:
    """Names of the working documents this design gets (cheap: no generation)."""
    try:
        recipe, v = st.recipe(p), st.rev(p)["values"]
        spec = recipe.assembly(v)
    except Exception:
        spec = None
    out = ["BOM.csv", "PRINT_REPORT.md", "MEASUREMENT_PLAN.md"]
    if spec is not None:
        out.insert(1, "ASSEMBLY.md")
        if spec.joints:
            out.append("MOTION_CHECKS.csv")
    return out
