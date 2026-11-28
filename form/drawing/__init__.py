"""Engineering drawings, GD&T and PMI from the B-rep (wave F).

    from form import drawing
    out = drawing.build(st, p, sheet="A3", projection="first")   # PDF, SVG, DXF, PNG, the sheet scene, a report
    drawing.export_pmi(st, p)                                     # STEP AP242 with semantic PMI, read back
    drawing.set_spec(st, pid, {"datums": [...], "gdt": [...], "fits": [...], "surface": [...]})
    drawing.set_dimension(st, p, "dim_lin_z_0_1", 8.0)            # a dimension is its parameter: edit it

What a drawing says and where it comes from:

- Views: OCCT hidden-line removal on the solid (form/drawing/views.py), first or third angle (ISO 5456-2), a full
  section through the bores when the part has any, an isometric; the largest ISO 5455 scale that fits the sheet.
- Dimensions: sizes measured on the B-rep; each size parameter of the design is bound to the size it equals (proved
  by building the design again with the parameter nudged, when the drawing may), so the drawing reports "N of N size
  parameters dimensioned, 0 twice", lists the ones it cannot show and what they drive, and editing a dimension
  commits a new value for its parameter. Placement is the layout algorithm in form/drawing/sheet.py.
- Tolerances: fits by ISO 286 classes the design or the person states (limits computed: form/drawing/iso286.py), the
  rest by the general tolerance in the title block (ISO 2768, a default the report says was not stated).
- GD&T, datums, surface texture: only what the design (a `drawing(v)` method returning a spec) or the person
  (`set_spec`) declares, checked against ISO 1101 / ISO 5459 / ISO 21920-1.
- The spec's face selectors: {"face": i}, {"feature": id, "normal": [x, y, z]}, {"feature": id, "cylinder": True,
  "d": mm}, {"param": key} (the faces of the size bound to that parameter).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

VERSION = 1
SPEC_FILE = "drawing.json"


class DrawingError(ValueError):
    def __init__(self, message, hint=""):
        super().__init__(message)
        self.hint = hint


# ── the spec: what the design and the person declare ───────────────────────

def stored_spec(st, pid: str) -> dict:
    f = st.dir(pid) / SPEC_FILE
    if f.is_file():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
    return {}


def design_spec(recipe, values: dict) -> dict:
    fn = getattr(recipe, "drawing", None)
    if not callable(fn):
        return {}
    try:
        out = fn(recipe.validate(values))
    except Exception as e:  # noqa: BLE001  (a design's drawing() that raises declares nothing; the report says so)
        return {"_error": f"drawing() raised {type(e).__name__}: {e}"}
    return out if isinstance(out, dict) else {}


def merged_spec(st, p: dict, n: int | None = None) -> dict:
    r = st.rev(p, n)
    d = design_spec(st.recipe(p, r["n"]), r["values"])
    s = stored_spec(st, p["id"])
    out = {"from_design": bool(d), "from_person": bool(s)}
    for k in ("datums", "gdt", "fits", "surface", "notes"):
        out[k] = list(d.get(k) or []) + list(s.get(k) or [])
    for k in ("general", "geometric", "holes", "sheet", "projection", "section"):
        out[k] = s.get(k, d.get(k))
    if d.get("_error"):
        out["design_error"] = d["_error"]
    return out


def validate_spec(spec: dict) -> list[str]:
    from . import gdt as G
    from . import iso286
    out = []
    for g in spec.get("gdt") or []:
        out += [f"gdt {g.get('type')}: {x}" for x in G.validate(g)]
        if "at" not in g:
            out.append(f"gdt {g.get('type')}: say which face it is on (at)")
    letters = [d.get("letter") for d in spec.get("datums") or []]
    for d in spec.get("datums") or []:
        if d.get("letter") not in G.LETTERS:
            out.append(f"datum {d.get('letter')!r} is not a datum letter (A-Z without I, O, Q)")
    if len(set(letters)) != len(letters):
        out.append("a datum letter is declared twice")
    for g in spec.get("gdt") or []:
        for dl in g.get("datums") or []:
            if str(dl).rstrip("MLP") not in letters:
                out.append(f"gdt {g.get('type')} refers to datum {dl}, which is not declared")
    for f in spec.get("fits") or []:
        try:
            iso286.parse(f.get("class", ""))
        except iso286.FitError as e:
            out.append(str(e))
    for s in spec.get("surface") or []:
        out += [f"surface: {x}" for x in G.surface_problems(s)]
    if spec.get("general") and spec["general"] not in ("f", "m", "c", "v"):
        out.append("general tolerance class must be f, m, c or v (ISO 2768-1)")
    if spec.get("holes") and spec["holes"] not in ("baseline", "chain"):
        out.append("holes must be baseline or chain (ISO 129-1)")
    return out


def set_spec(st, pid: str, spec: dict, replace: bool = False) -> dict:
    """Store what the person declares for the drawing (datums, GD&T, fits, surface, notes, general tolerance)."""
    with st.lock(pid):
        cur = {} if replace else stored_spec(st, pid)
        for k, v in (spec or {}).items():
            if k in ("datums", "gdt", "fits", "surface", "notes"):
                cur[k] = list(v or []) if replace else list(cur.get(k) or []) + list(v or [])
            elif k in ("general", "geometric", "holes", "sheet", "projection", "section", "placement"):
                cur[k] = v
            else:
                raise DrawingError(f"unknown drawing spec key {k!r}",
                                   "Use datums, gdt, fits, surface, notes, general, geometric, holes, sheet, projection.")
        problems = validate_spec(cur)
        if problems:
            raise DrawingError("The drawing spec cannot be used: " + "; ".join(problems))
        (st.dir(pid) / SPEC_FILE).write_text(json.dumps(cur, indent=1), encoding="utf-8")
    return cur


# ── resolving face selectors on the measured B-rep ─────────────────────────

def resolve(sel: dict, m: dict, binding: dict | None = None, cands=None) -> list[dict]:
    """Faces a selector names, each with the geometry an annotation needs."""
    import numpy as np
    from . import views as V
    out = []
    if not isinstance(sel, dict):
        raise DrawingError(f"a face selector is a dict, got {sel!r}")
    if "param" in sel:
        row = (binding or {}).get(sel["param"])
        if not row or not row.get("candidate"):
            raise DrawingError(f"parameter {sel['param']!r} is not bound to a size on the drawing")
        c = next(c for c in cands if c["id"] == row["candidate"])
        faces = c.get("faces") or []
        return [g for i in faces for g in resolve({"face": i}, m)]
    if "face" in sel:
        i = int(sel["face"])
        for pl in m["planes"]:
            if pl["face"] == i:
                return [{"face": i, "type": "plane", "normal": list(V.AXES[pl["axis"]] * pl["sense"]), "box": pl["box"],
                         "feature": pl["feature"]}]
        for c in m["cylinders"]:
            if c["face"] == i and c["axis"]:
                return [{"face": i, "type": "cylinder", "axis": c["axis"], "at": c["at"], "along": c["along"],
                         "r": c["r"], "feature": c["feature"]}]
        raise DrawingError(f"face {i} is not an axis-aligned plane or cylinder of the part, so it cannot be annotated")
    feat = sel.get("feature")
    if sel.get("cylinder"):
        cs = [c for c in m["cylinders"] if c["axis"] and c["full"] and (feat is None or c["feature"] == feat)]
        if sel.get("d") is not None:
            cs = [c for c in cs if abs(2 * c["r"] - float(sel["d"])) < 1e-3]
        else:
            big = max((c["r"] for c in cs), default=None)
            cs = [c for c in cs if c["r"] == big]
        for c in cs:
            out += resolve({"face": c["face"]}, m)
    elif sel.get("normal") is not None:
        n = np.asarray(sel["normal"], float)
        n /= np.linalg.norm(n)
        ps = [pl for pl in m["planes"] if (feat is None or pl["feature"] == feat)
              and float(V.AXES[pl["axis"]] @ n) * pl["sense"] > 0.999]
        if sel.get("largest", True) and ps:
            ps = [max(ps, key=lambda q: q["area"])]
        for pl in ps:
            out += resolve({"face": pl["face"]}, m)
    if not out:
        raise DrawingError(f"no face matches {sel}", "Name a feature and a normal, a cylinder (d=...), or a face index.")
    return out


# ── the drawing from what the kernel measured ──────────────────────────────

def make(raw: dict, params: list, values: dict, spec: dict, title: dict, sheet: str = "A3", projection: str = "first",
         theme: str = "night") -> dict:
    """Compose the sheet and its report from the kernel's views and measurements (pure Python)."""
    from . import dims as D
    from . import iso286
    from . import sheet as SH
    from . import standards as STD
    m = raw["measure"]
    cands = D.candidates(m)
    rows = D.bind(params, values, cands, raw.get("perturbed"))
    binding = {r["param"]: r for r in rows}
    plan = D.choose(cands, rows, spec.get("holes") or "baseline")
    gen = spec.get("general") or "m"
    geo = spec.get("geometric") or "K"
    problems = validate_spec(spec)
    if problems:
        raise DrawingError("The drawing spec cannot be used: " + "; ".join(problems))
    fits_by_dim, fits_report = {}, []
    for f in spec.get("fits") or []:
        faces = {g["face"] for g in resolve(f["at"], m, binding, cands)}
        c = next((c for c in cands if c["kind"] in ("diameter", "linear", "radius") and faces & set(c.get("faces") or [])
                  and c["kind"] == "diameter"), None) or next((c for c in cands if faces & set(c.get("faces") or [])), None)
        if c is None:
            raise DrawingError(f"fit {f['class']}: no dimensioned size on those faces")
        lim = iso286.limits(f["class"], c["value"])
        fits_by_dim[c["id"]] = lim
        fits_report.append({"class": lim["class"], "nominal": c["value"], "min": lim["min"], "max": lim["max"],
                            "upper_um": lim["upper_um"], "lower_um": lim["lower_um"], "how": lim["how"],
                            "candidate": c["id"], "source": lim["source"]})
        if not any(p["id"] == c["id"] for p in plan):
            plan.append({**c, "param": None, "binding": "model"})
    ann = {"fits_by_dim": fits_by_dim, "datum": [], "gdt": [], "surface": []}
    for d in spec.get("datums") or []:
        geo_f = resolve(d["at"], m, binding, cands)
        ann["datum"].append({"letter": d["letter"], "faces": [g["face"] for g in geo_f], "_faces_geo": geo_f})
    for i, g in enumerate(spec.get("gdt") or []):
        geo_f = resolve(g["at"], m, binding, cands)
        ann["gdt"].append({**{k: v for k, v in g.items() if k != "at"}, "id": g.get("id") or f"g{i + 1}",
                           "faces": [x["face"] for x in geo_f], "_faces_geo": geo_f})
    for i, s in enumerate(spec.get("surface") or []):
        geo_f = resolve(s["at"], m, binding, cands)
        ann["surface"].append({**{k: v for k, v in s.items() if k != "at"}, "id": s.get("id") or f"s{i + 1}",
                               "faces": [x["face"] for x in geo_f], "_faces_geo": geo_f})
    notes = [f"General tolerances ISO 2768-{gen}{geo}"] + [str(n) for n in spec.get("notes") or []]
    ann["notes"] = notes
    title = {**title, "tolerance": STD.tolerance_note(gen, geo)}
    sc = SH.compose(raw, plan, ann, title, sheet, projection, theme, cands=cands)
    sc["title"] = title.get("title", "Drawing")
    comp = D.completeness(rows)
    placed = [g["meta"] for g in _groups(sc, "dimension")]
    dims_report = []
    for g in _groups(sc, "dimension"):
        mt = g["meta"]
        dims_report.append({"id": g["id"], "text": mt["text"], "value": mt["value"], "kind": mt["kind"], "view": mt["view"],
                            "param": mt["param"], "binding": mt["binding"], "feature": mt["feature"],
                            "tolerance": _tol_of(mt, gen)})
    report = {"completeness": comp, "bindings": rows, "dimensions": dims_report, "fits": fits_report,
              "overlaps": SH.overlaps(sc), "unplaced": sc["unplaced"], "scale": sc["scale"], "sheet": sheet,
              "projection": projection, "general_tolerance": {"class": f"{gen}{geo}", "stated": bool(spec.get("general")),
                                                              "standard": "ISO 2768-1/-2"},
              "annotations": {"datums": len(ann["datum"]), "gdt": len(ann["gdt"]), "surface": len(ann["surface"])},
              "fits_sheet": sc["fits_sheet"], "placed": len(placed)}
    return {"sheet": sc, "report": report, "annotations": ann, "plan": plan, "cands": cands}


def _tol_of(meta: dict, gen: str) -> dict:
    from . import standards as STD
    if meta.get("fit"):
        f = meta["fit"]
        return {"kind": "fit", "class": f["class"], "upper": f["upper_um"] / 1000, "lower": f["lower_um"] / 1000}
    try:
        if meta["kind"] == "radius":
            t = STD.general_break(meta["value"], gen)
        else:
            t = STD.general_linear(meta["value"], gen)
        return {"kind": "general", "class": gen, "upper": t, "lower": -t}
    except STD.StandardError as e:
        return {"kind": "none", "why": str(e)}


def _groups(sc, role):
    from . import scene as S
    return S.groups(sc, role)


def pmi_annotations(made: dict) -> list:
    """The drawing's semantic content as PMI: every dimension with its tolerance on its faces, the datums and the
    geometric tolerances."""
    out = []
    by = {c["id"]: c for c in made["cands"]}
    for d in made["report"]["dimensions"]:
        cid = d["id"][4:]
        c = by.get(cid)
        if c is None or not c.get("faces"):
            continue
        tol = d["tolerance"]
        row = {"kind": "dimension", "id": d["id"], "value": c["value"]}
        if c["kind"] == "diameter":
            row.update(type="diameter", faces=list(c["faces"]))
        elif c["kind"] == "radius":
            row.update(type="radius", faces=list(c["faces"]))
        elif c["kind"] == "linear" and c.get("planes"):
            a, b = c["planes"]
            row.update(type="linear", faces=[a["face"]], faces2=[b["face"]])
        else:
            continue
        if tol.get("kind") in ("fit", "general"):
            row.update(upper=round(tol["upper"], 6), lower=round(tol["lower"], 6))
        if tol.get("kind") == "fit":
            row["fit"] = tol["class"]
        out.append(row)
    for a in made["annotations"]["datum"]:
        out.append({"kind": "datum", "letter": a["letter"], "faces": a["faces"]})
    for a in made["annotations"]["gdt"]:
        out.append({"kind": "gdt", **{k: v for k, v in a.items() if not k.startswith("_")}})
    return out


# ── studio glue ────────────────────────────────────────────────────────────

def _params(recipe) -> list:
    return [p.public() if hasattr(p, "public") else dict(p) for p in recipe.params]


def _title(st, p, r, volume) -> dict:
    from . import standards as STD  # noqa: F401
    mass = None
    try:
        from .. import materials
        mass = materials.mass(p, volume)
    except Exception:  # noqa: BLE001
        mass = None
    gk = st.keys(p, r["n"])["geometry"]
    rel = _release_of(st, p, r["n"])
    return {"title": p["name"], "number": p["id"], "revision": f"r{r['n']:02d}",
            "date": time.strftime("%Y-%m-%d", time.localtime(r.get("ts") or time.time())), "sheet": "1/1",
            "type": "Detail drawing", "creator": "", "owner": "", "approved": rel.get("approved", ""),
            "material": (mass or {}).get("label", ""), "mass": f"{mass['grams']:g} g" if mass else "",
            "release": rel.get("hash") or f"unreleased · {gk[:12]}", "language": "en", "_geometry": gk,
            "_volume_mm3": volume}


def _release_of(st, p, n) -> dict:
    for rel in p.get("releases") or []:
        if rel.get("rev") == n:
            return {"hash": str(rel.get("sha256") or rel.get("hash") or rel.get("name") or "")[:16],
                    "approved": rel.get("approved_by") or ""}
    return {}


def raw_views(st, p: dict, r: dict, spec: dict, prove: bool = True) -> dict:
    """The kernel's part: views, a section when the part has bores, measurements, nudged builds."""
    gk = st.keys(p, r["n"])["geometry"]
    recipe = st.recipe(p, r["n"])
    perturb = {}
    if prove:
        for q in recipe.params:
            if q.unit == "mm" and isinstance(r["values"].get(q.key), (int, float)):
                v = r["values"][q.key]
                d = q.step if q.step and q.step >= 0.01 else max(0.05 * (q.max - q.min), 1e-3)
                perturb[q.key] = d if v + d <= q.max else -d if v - d >= q.min else (q.max - v) / 2 or (q.min - v) / 2
    sections = spec.get("_sections") or []
    raw = st._k("drawing_views", timeout=300, key=gk, recipe_id=st.rid(p, r["n"]), values=r["values"], p=p, rev=r["n"],
                views=["front", "top", "right", "iso"], sections=sections, perturb=perturb)
    return raw


def auto_section(m: dict) -> list:
    """A full section A-A through the bores along z (the plane through their axes, seen from the front) when the
    part has holes; none otherwise."""
    holes = [c for c in m["cylinders"] if c["full"] and c["inner"] and c["axis"] == "z"]
    if not holes:
        return []
    big = max(holes, key=lambda c: c["r"])
    y = big["at"][1]
    return [{"id": "A", "origin": [0.0, y, 0.0], "normal": [0.0, -1.0, 0.0], "right": [1.0, 0.0, 0.0]}]


def build(st, p: dict, n: int | None = None, sheet: str | None = None, projection: str | None = None,
          theme: str = "night", prove: bool = True, formats=("pdf", "svg", "dxf", "png")) -> dict:
    """Make the drawing of revision n (default the head): files, the sheet scene, the report. Cached by geometry,
    spec and options."""
    from ..studio import H
    from . import render
    from . import standards as STD
    r = st.rev(p, n)
    spec = merged_spec(st, p, r["n"])
    sheet = sheet or spec.get("sheet") or "A3"
    projection = projection or spec.get("projection") or "first"
    if sheet not in STD.SHEETS:
        raise DrawingError(f"sheet must be one of {', '.join(STD.SHEETS)}")
    if projection not in STD.PROJECTIONS:
        raise DrawingError("projection must be first or third")
    gk = st.keys(p, r["n"])["geometry"]
    key = H("drawing", VERSION, gk, spec, sheet, projection, theme, prove, p["name"], _release_of(st, p, r["n"]))[:16]
    out_dir = st.dir(p["id"]) / "artifacts" / "side" / f"drawing-{key}"
    meta = out_dir / "drawing.json"
    if meta.is_file():
        return json.loads(meta.read_text(encoding="utf-8"))
    # sections need the measurements first: one call measures, a second (cached B-rep) cuts
    if spec.get("section") is not False:
        probe = st._k("drawing_views", timeout=300, key=gk, recipe_id=st.rid(p, r["n"]), values=r["values"], p=p,
                      rev=r["n"], views=[], sections=[], perturb=None)
        spec["_sections"] = auto_section(probe["measure"])
    raw = raw_views(st, p, r, spec, prove)
    recipe = st.recipe(p, r["n"])
    title = _title(st, p, r, raw["measure"].get("volume"))
    made = make(raw, _params(recipe), r["values"], spec, {k: v for k, v in title.items() if not k.startswith("_")},
                sheet, projection, theme)
    out_dir.mkdir(parents=True, exist_ok=True)
    base = f"{p['id']}_r{r['n']:02d}_{sheet.replace(' ', '')}"
    files = {}
    sc = made["sheet"]
    (out_dir / "sheet.json").write_text(json.dumps(sc), encoding="utf-8")
    (out_dir / "raw.json").write_text(json.dumps({"raw": raw, "params": _params(recipe), "values": r["values"], "spec": {k: v for k, v in spec.items() if k != "_sections"}, "title": {k: v for k, v in title.items() if not k.startswith("_")}}), encoding="utf-8")
    files["scene"] = "sheet.json"
    if "svg" in formats:
        (out_dir / f"{base}.svg").write_text(render.svg(sc), encoding="utf-8")
        files["svg"] = f"{base}.svg"
    if "dxf" in formats:
        render.dxf(sc, str(out_dir / f"{base}.dxf"))
        files["dxf"] = f"{base}.dxf"
    if "pdf" in formats or "png" in formats:
        paper = render.themed(sc, "paper")
        render.qt(paper, pdf=str(out_dir / f"{base}.pdf") if "pdf" in formats else None,
                  png=str(out_dir / f"{base}-paper.png") if "png" in formats else None)
        if "pdf" in formats:
            files["pdf"] = f"{base}.pdf"
        if "png" in formats:
            render.qt(render.themed(sc, "night"), png=str(out_dir / f"{base}-night.png"))
            files["png"] = f"{base}-paper.png"
            files["png_night"] = f"{base}-night.png"
    res = {"rev": r["n"], "key": key, "dir": str(out_dir), "files": files,
           "paths": {k: str(out_dir / v) for k, v in files.items()}, "report": made["report"],
           "geometry": gk, "spec": {k: v for k, v in spec.items() if not k.startswith("_")},
           "title": {k: v for k, v in title.items() if not k.startswith("_")}}
    (out_dir / "pmi_annotations.json").write_text(json.dumps(pmi_annotations(made)), encoding="utf-8")
    meta.write_text(json.dumps(res, indent=1), encoding="utf-8")
    return res


def export_pmi(st, p: dict, n: int | None = None, sheet: str | None = None) -> dict:
    """STEP AP242 with the drawing's dimensions, tolerances, datums and GD&T attached to faces, read back and
    compared annotation by annotation."""
    from . import pmi
    d = build(st, p, n, sheet=sheet, formats=())
    r = st.rev(p, n)
    ann = json.loads((Path(d["dir"]) / "pmi_annotations.json").read_text(encoding="utf-8"))
    path = Path(d["dir"]) / f"{p['id']}_r{r['n']:02d}_AP242.step"
    gk = st.keys(p, r["n"])["geometry"]
    out = st._k("drawing_pmi", timeout=300, key=gk, recipe_id=st.rid(p, r["n"]), values=r["values"], p=p, rev=r["n"],
                path=str(path), annotations=ann)
    written = _sig_written(st, p, r, gk, ann, out)
    rows = pmi.compare(written, out["read_back"])
    res = {"path": str(path), "schema": out["read_back"]["schema"], "rows": rows,
           "written": len(ann), "passed": sum(x["status"] == "PASS" for x in rows),
           "read_back": {k: len(v) for k, v in out["read_back"].items() if isinstance(v, list)},
           "note": "Fit classes travel as their limits (a size range); OCCT's AP242 writer does not keep the class "
                   "name, so it is listed in the drawing, not read from the file."}
    (Path(d["dir"]) / "pmi_check.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    return res


def _sig_written(st, p, r, gk, ann, out):
    return out.get("written") or ann


def set_dimension(st, p: dict, dim_id: str, value: float, expect_head: int | None = None, rev: int | None = None) -> dict:
    """Change a dimension: commits the new value of the parameter it is bound to. A model size without a
    parameter cannot be edited (it follows from the others)."""
    d = build(st, p, rev, formats=())
    row = next((x for x in d["report"]["dimensions"] if x["id"] == dim_id), None)
    if row is None:
        raise DrawingError(f"no dimension {dim_id!r} on the drawing", "Read the drawing's report for dimension ids.")
    if not row.get("param"):
        raise DrawingError(f"{row['text']} is a size of the model, not a parameter",
                           "Change the parameters it follows from; the report lists what each parameter drives.")
    b = next(x for x in d["report"]["bindings"] if x["param"] == row["param"])
    val = float(value) / float(b.get("factor") or 1.0)
    return {"param": row["param"], "value": val, "dimension": dim_id, "binding": b["status"],
            "commit": st.commit(p, {row["param"]: val}, expect_head=expect_head,
                                note=f"Drawing: {row['text']} → {value:g}")}
