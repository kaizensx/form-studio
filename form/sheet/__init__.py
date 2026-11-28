"""Sheet metal and cut parts: design bent parts, unfold them with a sourced bend table and prove the unfold by
folding it back, write the flat pattern as a DXF, check any DXF a shop will cut, find a bend order a press brake
can form, export flat parts for laser, waterjet or router, and preflight against a service's published limits.

    form/sheet/build.py      Sheet: base flange, edge flanges, hems, jogs, reliefs, louvres (a design's code)
    form/sheet/tables.py     K-factor (generic table, DIN 6935 or the shop's value) and default radius, with sources
    form/sheet/unfold.py     the B-rep unfold and its fold-back verification (kernel worker)
    form/sheet/fold.py       folding a flat pattern back from its own numbers
    form/sheet/dxf.py        DXF out (CUT, BEND_UP, BEND_DOWN, ETCH, NOTES) and in (layers by intent)
    form/sheet/cutcheck.py   the cut-file check (laser, waterjet, router), rules in form/sheet/rules
    form/sheet/brake.py      bend order with a V-die and gooseneck punch model
    form/sheet/preflight.py  a service's materials, thicknesses and limits (form/sheet/services)
    form/sheet/analysis.py   the measures of the sheet-metal manufacturability rules
    form/sheet/ops.py        kernel ops: sheet_unfold, sheet_profile

Studio level (this module):

    flat_pattern(st, p, options)          the flat pattern of a design, its DXF and a picture
    profile(st, p, kerf=0.2)              the cut profile of a flat design (kerf compensated on request)
    cut_check(path, "cut_laser", {"t": 2})
    bend_order(st, p)                     a feasible sequence, or the collisions that rule it out
    service_preflight(st, p, "sendcutsend", material="al_5052_h32")
    dfm_check(st, p, options)             the sheet_metal process of manufacturability (form/dfm)

Results are stored under artifacts/sheet/, keyed by the geometry, the bend table's hash and the options, so a new
revision or an edited table makes them stale. Nothing here uploads or orders anything.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

from . import geom2d, tables

VERSION = 1
OPTION_KEYS = ("k", "method", "material", "forming", "label", "label_at")


def _err(msg, hint="", status=400):
    from ..studio import StudioError
    return StudioError(msg, hint, status=status)


def H(*a) -> str:
    from ..studio import H as _h
    return _h(*a)


def _dir(st, p) -> Path:
    return st.dir(p["id"]) / "artifacts" / "sheet"


def _write(path: Path, data) -> None:
    from .. import fsutil
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    fsutil.replace(tmp, path)


def _read(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def clean_options(options: dict | None) -> dict:
    o = {k: v for k, v in (options or {}).items() if v not in (None, "", [])}
    bad = sorted(set(o) - set(OPTION_KEYS) - {"punch", "die_v", "kerf", "service", "t", "process", "units"})
    if bad:
        raise _err(f"Unknown sheet option(s): {', '.join(bad)}.",
                   "k (a K-factor), method (table | din6935), material, forming (air | bottoming | coining), label.")
    if "k" in o:
        o["k"] = float(o["k"])
        if not 0 <= o["k"] <= 1:
            raise _err("A K-factor is between 0 and 1.")
    if o.get("method") and o["method"] not in ("table", "din6935", "value"):
        raise _err("method is table, din6935 or value.")
    if o.get("forming") and o["forming"] not in ("air", "bottoming", "coining"):
        raise _err("forming is air, bottoming or coining.")
    if o.get("material") and tables.material(o["material"]) is None:
        raise _err(f"Unknown material “{o['material']}”.", "Materials: " + ", ".join(tables.bend_table()["materials"]) + ".")
    return o


def _kspec(o: dict) -> dict:
    return {k: o[k] for k in ("k", "method", "material", "forming") if k in o}


# ---- the flat pattern --------------------------------------------------------------------------------------------

def unfolded(st, p: dict, options: dict | None = None, rev: int | None = None, force: bool = False) -> dict:
    """The unfold of a revision (head by default), from the kernel, cached under artifacts/sheet/."""
    o = clean_options(options)
    r = st.rev(p, rev)
    rid, values = st.rid(p, r["n"]), r["values"]
    gk = st.keys(p, r["n"])["geometry"]
    key = H("sheet-unfold", VERSION, gk, tables.digest(), _kspec(o), o.get("label"), o.get("label_at"))
    path = _dir(st, p) / f"unfold-{key}.json"
    if not force:
        got = _read(path)
        if got is not None:
            got["cached"] = True
            return got
    res = st._k("sheet_unfold", timeout=600, key=gk, recipe_id=rid, values=values, k=_kspec(o),
                label=o.get("label"), label_at=o.get("label_at"), p=p)
    res.update({"project": p["id"], "rev": r["n"], "key": key, "geometry_key": gk, "options": o,
                "k_spec": _kspec(o), "computed_at": time.time()})
    _write(path, res)
    return res


def summary(res: dict) -> dict:
    """The unfold without its bulky parts, for MCP and the CLI."""
    out = {k: res.get(k) for k in ("project", "rev", "ok", "reasons", "t", "size_mm", "area_mm2", "outline_mm",
                                   "volume_mm3", "volume_expected_mm3", "volume_rel_err", "dxf", "png", "key",
                                   "cached", "seconds") if k in res}
    out["bends"] = [{"bend": f"B{i + 1}", "angle": round(b["angle"], 4), "direction": b["direction"],
                     "r": round(b["r"], 4), "K": b["K"], "allowance_mm": round(b["allowance"], 4),
                     "length_mm": round(b["length"], 4), "line": [[round(x, 4) for x in pt] for pt in b["line"]],
                     "k_source": {k: v for k, v in b["k_source"].items() if k in ("method", "source", "evidence", "class",
                                                                                  "class_evidence", "band", "forming", "note")}}
                    for i, b in enumerate(res.get("bends", []))]
    v = res.get("verify") or {}
    out["verify"] = {k: v.get(k) for k in ("max_mm", "tolerance_mm", "samples", "pass", "method", "worst")}
    out["contours"] = len(res.get("loops") or [])
    out["holes"] = sum(1 for lp in res.get("loops") or [] if lp["depth"] % 2 == 1)
    if res.get("open_ends"):
        out["open_ends"] = res["open_ends"][:10]
    out["evidence"] = "computed (B-rep unfold, folded back)" if res.get("ok") else "not unfolded"
    return out


def flat_pattern(st, p: dict, options: dict | None = None, rev: int | None = None, dxf: bool = True,
                 png: bool = True, out: str | None = None, force: bool = False) -> dict:
    """The flat pattern of a design: unfold, fold-back proof, DXF (CUT, BEND_UP/DOWN, ETCH, NOTES) and a picture."""
    from . import dxf as dxfmod
    res = unfolded(st, p, options, rev, force)
    d = _dir(st, p)
    if res.get("entities") and dxf:
        path = Path(out) if out else d / f"flat-{res['key']}.dxf"
        if out or not path.is_file():
            dxfmod.write(path, res["entities"], res["bends"], res.get("etch"), title=p.get("name", ""))
        res["dxf"] = str(path)
    if res.get("entities") and png:
        pp = d / f"flat-{res['key']}.png"
        if not pp.is_file():
            render_flat(res, pp, title=f"{p.get('name', '')} · flat pattern")
        res["png"] = str(pp)
    return res


def profile(st, p: dict, kerf: float = 0.0, label: str | None = None, rev: int | None = None, out: str | None = None,
            force: bool = False) -> dict:
    """The cut profile of a flat design (a prism through its largest flat face) for laser, waterjet or router, with
    the cutter's path offset half the kerf away from the material when kerf is given."""
    from . import dxf as dxfmod
    if kerf < 0 or kerf > 10:
        raise _err("kerf is between 0 and 10 mm.")
    r = st.rev(p, rev)
    rid, values = st.rid(p, r["n"]), r["values"]
    gk = st.keys(p, r["n"])["geometry"]
    key = H("sheet-profile", VERSION, gk, round(float(kerf), 6), label)
    path = _dir(st, p) / f"profile-{key}.json"
    res = None if force else _read(path)
    if res is None:
        res = st._k("sheet_profile", timeout=300, key=gk, recipe_id=rid, values=values, kerf=float(kerf), label=label, p=p)
        res.update({"project": p["id"], "rev": r["n"], "key": key, "geometry_key": gk})
        _write(path, res)
    if res.get("entities"):
        dp = Path(out) if out else _dir(st, p) / f"profile-{key}.dxf"
        if out or not dp.is_file():
            dxfmod.write(dp, res["entities"], [], res.get("etch"), title=p.get("name", ""))
        res["dxf"] = str(dp)
        pp = _dir(st, p) / f"profile-{key}.png"
        if not pp.is_file():
            render_flat({**res, "bends": []}, pp, title=f"{p.get('name', '')} · cut profile"
                        + (f" · kerf {kerf:g} mm" if kerf else ""), ghost=res.get("exact") if kerf else None)
        res["png"] = str(pp)
    return res


# ---- checks --------------------------------------------------------------------------------------------------

def cut_check(path: str | None = None, process: str = "cut_laser", options: dict | None = None, st=None, p=None,
              rev: int | None = None, kind: str = "auto") -> dict:
    """The cut-file check of a DXF file, or of a design's own flat pattern or profile (written to DXF and read
    back, so the file a shop would get is the thing checked)."""
    from . import cutcheck
    o = dict(options or {})
    if path:
        return cutcheck.check_file(path, process, o)
    if st is None or p is None:
        raise _err("Give a DXF file or a project.")
    res = _part_flat(st, p, kind, rev, o)
    if not res.get("dxf"):
        raise _err("The design has no flat pattern or profile to check.", "; ".join(r["why"] for r in res.get("reasons", [])[:3]))
    o.setdefault("t", res.get("t"))
    out = cutcheck.check_file(res["dxf"], process, o)
    out["project"] = p["id"]
    out["from"] = res.get("kind")
    return out


def _part_flat(st, p, kind, rev, o) -> dict:
    if kind in ("auto", "flat"):
        res = flat_pattern(st, p, {k: v for k, v in o.items() if k in OPTION_KEYS}, rev)
        if res.get("entities") and (res.get("bends") or kind == "flat"):
            res["kind"] = "flat pattern"
            return res
    res = profile(st, p, float(o.get("kerf") or 0.0), rev=rev)
    res["kind"] = "profile"
    return res


def bend_order(st, p: dict, options: dict | None = None, rev: int | None = None) -> dict:
    from . import brake
    o = dict(options or {})
    res = unfolded(st, p, {k: v for k, v in o.items() if k in OPTION_KEYS}, rev)
    if not res.get("entities"):
        raise _err("The part does not unfold, so it has no bends to order.",
                   "; ".join(r["why"] for r in res.get("reasons", [])[:3]))
    key = H("sheet-brake", VERSION, res["key"], o.get("punch", "gooseneck"), o.get("die_v"))
    path = _dir(st, p) / f"brake-{key}.json"
    got = _read(path)
    if got is not None:
        got["cached"] = True
        return got
    out = brake.bend_order(res, o.get("punch", "gooseneck"), o.get("die_v"))
    out.update({"project": p["id"], "rev": res["rev"], "key": key})
    _write(path, out)
    return out


def service_preflight(st=None, p=None, service: str = "sendcutsend", material: str | None = None,
                      t: float | None = None, path: str | None = None, rev: int | None = None,
                      options: dict | None = None) -> dict:
    from . import cutcheck, preflight
    o = dict(options or {})
    if service not in tables.services():
        raise _err(f"No table for service “{service}”.", "Services: " + ", ".join(tables.services()) + ".")
    if path:
        cc = cutcheck.check_file(path, "cut_laser", {**o, **({"t": t} if t else {})})
        flat = {"t": t, "bends": [], "size_mm": (cc["data"]["part_sizes_mm"] or [None])[0], "holes": []}
        hole_row = next((r for r in cc["rows"] if r["id"] == "laser.hole"), None)
        if hole_row and hole_row.get("value") is not None:
            flat["holes"] = [hole_row["value"]]
        out = preflight.preflight(flat, service, material or o.get("material"), t, cc["rows"])
        out["file"] = str(path)
        return out
    if st is None or p is None:
        raise _err("Give a project or a DXF file.")
    res = _part_flat(st, p, "auto", rev, o)
    if not res.get("dxf"):
        raise _err("The design has no flat pattern or profile.", "; ".join(r["why"] for r in res.get("reasons", [])[:3]))
    cc = cutcheck.check_file(res["dxf"], "cut_laser", {"t": t or res.get("t")})
    hole_row = next((r for r in cc["rows"] if r["id"] == "laser.hole"), None)
    flat = {"t": res.get("t"), "bends": res.get("bends") or [], "size_mm": res.get("size_mm"),
            "holes": [hole_row["value"]] if hole_row and hole_row.get("value") is not None else []}
    out = preflight.preflight(flat, service, material or o.get("material"), t, cc["rows"])
    out.update({"project": p["id"], "rev": res.get("rev"), "dxf": res["dxf"], "from": res.get("kind")})
    return out


def dfm_check(st, p: dict, options: dict | None = None, rev: int | None = None) -> dict:
    """The sheet_metal process of manufacturability: the unfold's measures judged by form/dfm/rules/sheet_metal.toml."""
    from ..dfm import rules
    from . import analysis
    o = dict(options or {})
    if "k_method" in o:
        o["method"] = o.pop("k_method")
    res = unfolded(st, p, {k: v for k, v in o.items() if k in OPTION_KEYS}, rev)
    meas, data = analysis.measures(res)
    t = res.get("t")
    ropts = {**o, "t": t, "t_band": ("thin" if t and t <= 0.914 + 1e-9 else "thick") if t else None}
    ev = rules.evaluate("sheet_metal", {"measures": meas}, ropts)
    tab = rules.table("sheet_metal")
    out = {"project": p["id"], "rev": res.get("rev"), "process": "sheet_metal", "label": tab["process"]["label"],
           "verdict": ev["verdict"], "rows": ev["rows"], "findings": ev["findings"], "data": data, "fixes": [],
           "evidence": tab["process"]["evidence"], "not_judged": tab["process"].get("not_judged", ""),
           "geometry_key": res.get("geometry_key"), "key": H("sheet-dfm", VERSION, res.get("key"), rules.digest("sheet_metal")),
           "options": o, "sources": [{**s, "text": rules.source_text(s)} for s in tab["sources"].values()],
           "unfold": summary(res)}
    n = {s: sum(r["status"] == s for r in ev["rows"]) for s in ("fail", "warn", "not_checked", "pass")}
    bits = [f"{n[k]} {k.replace('_', ' ')}" for k in ("fail", "warn", "not_checked") if n[k]]
    out["headline"] = f"{out['label']}: {ev['verdict']}" + (f" ({', '.join(bits)})" if bits else f" ({n['pass']} rules pass)")
    return out


# ---- a picture of the flat ---------------------------------------------------------------------------------------

def render_flat(res: dict, path, title: str = "", size: int = 1100, ghost: list | None = None) -> str:
    """A PNG of a flat pattern: cut contours dark, bend lines dashed (up green, down red) with their notes, etch blue,
    a 10 mm scale bar."""
    from PIL import Image, ImageDraw
    ents = res.get("entities") or []
    etch = res.get("etch") or []
    bends = res.get("bends") or []
    allp = [geom2d.polyline(e) for e in ents + etch] + [np.asarray(b["line"], float) for b in bends]
    P = np.vstack(allp) if allp else np.zeros((1, 2))
    lo, hi = P.min(axis=0), P.max(axis=0)
    span = max(float((hi - lo).max()), 1e-6)
    k = 2                                   # drawn at twice the size and scaled down: even lines, smooth arcs
    pad, head = 60 * k, 54 * k
    W = size * k
    s = (W - 2 * pad) / span
    Hh = int((hi[1] - lo[1]) * s + 2 * pad + head + 30 * k)
    img = Image.new("RGB", (W, max(Hh, 300 * k)), (250, 249, 246))
    dr = ImageDraw.Draw(img)
    from ..render import _font
    font, small = _font(15 * k), _font(12 * k)

    def xy(Q):
        Q = np.asarray(Q, float)
        return [(pad + (q[0] - lo[0]) * s, head + pad + (hi[1] - q[1]) * s) for q in Q]
    for e in ghost or []:
        dr.line(xy(geom2d.polyline(e)), fill=(200, 196, 188), width=k)
    for e in ents:
        dr.line(xy(geom2d.polyline(e)), fill=(30, 30, 34), width=2 * k, joint="curve")
    for e in etch:
        dr.line(xy(geom2d.polyline(e)), fill=(52, 104, 210), width=k)
    from .dxf import bend_note
    notes: list = []
    for b in bends:
        col = (32, 150, 90) if b["direction"] == "up" else (210, 70, 50)
        A, B = np.asarray(b["line"], float)
        L = float(np.linalg.norm(B - A))
        n = max(2, int(L * s / (12 * k)))
        for j in range(0, n, 2):
            a = A + (B - A) * (j / n)
            c = A + (B - A) * (min(j + 1, n) / n)
            dr.line(xy([a, c]), fill=col, width=2 * k)
        note = bend_note(b)
        for f in (0.5, 0.3, 0.7, 0.15, 0.85, 0.4, 0.6, 0.5):
            m = xy([A + (B - A) * f])[0]
            box = dr.textbbox((m[0] + 6 * k, m[1] - 16 * k), note, font=small)
            if not any(box[0] < q[2] and q[0] < box[2] and box[1] < q[3] and q[1] < box[3] for q in notes):
                break
        notes.append(box)
        dr.text((m[0] + 6 * k, m[1] - 16 * k), note, fill=col, font=small)
    dr.text((pad, 16 * k), title or "Flat pattern", fill=(30, 30, 34), font=font)
    sub = []
    if res.get("size_mm"):
        sub.append(f"{res['size_mm'][0]:.2f} × {res['size_mm'][1]:.2f} mm")
    if res.get("t"):
        sub.append(f"t {res['t']:g} mm")
    v = res.get("verify") or {}
    if v:
        sub.append(f"folded back to {v.get('max_mm', 0):.1e} mm (tolerance {v.get('tolerance_mm', 0.01):g} mm)")
    if res.get("kerf_mm"):
        sub.append(f"kerf {res['kerf_mm']:g} mm, cutter path drawn; the part in grey")
    dr.text((pad, 34 * k), " · ".join(sub), fill=(110, 106, 98), font=small)
    y0 = img.height - 22 * k
    dr.line([(pad, y0), (pad + 10 * s, y0)], fill=(30, 30, 34), width=2 * k)
    dr.text((pad + 10 * s + 6 * k, y0 - 8 * k), "10 mm", fill=(110, 106, 98), font=small)
    img = img.resize((img.width // k, img.height // k), Image.LANCZOS)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    img.save(str(path))
    return str(path)


# ---- the Bench -------------------------------------------------------------------------------------------------

def register_studies(register) -> None:
    """Three Bench entries: Flat pattern, DXF (a route to Make), Cut-file check and Bend order (studies)."""
    from ..studies import Study

    def flat_run(ctx):
        res = flat_pattern(ctx.st, ctx.p, (getattr(ctx, "opts", None) or {}).get("options") or {})
        sm = summary(res)
        head = (f"Flat {res['size_mm'][0]:.1f} × {res['size_mm'][1]:.1f} mm, {len(res['bends'])} bends, folded back "
                f"to {res['verify']['max_mm']:.1e} mm") if res.get("ok") else \
            "Does not unfold: " + "; ".join(r["why"] for r in res.get("reasons", [])[:2])
        return {"headline": head, "evidence": sm["evidence"], "data": sm,
                "files": [f for f in (res.get("dxf"), res.get("png")) if f]}

    def cut_run(ctx):
        r = cut_check(None, "cut_laser", {}, ctx.st, ctx.p)
        return {"headline": r["headline"], "evidence": r["evidence"],
                "detail": "; ".join(f"{x['id']} {x['status']}" for x in r["rows"]), "data": r}

    def brake_run(ctx):
        r = bend_order(ctx.st, ctx.p)
        return {"headline": r["headline"], "evidence": r["evidence"], "data": r}

    def key(name):
        def k(ctx):
            return H("sheet-study", name, VERSION, ctx.keys["geometry"], tables.digest())
        return k
    register(Study("sheet_flat", "route", "Flat pattern, DXF",
                   "The bent part unfolded with a sourced K-factor, folded back to prove it, written as a DXF with cut, "
                   "bend and etch layers.", "computed (B-rep unfold, folded back)", run=flat_run, key=key("flat"),
                   inputs=("geometry", "bend table", "options"), app="sheet", tool="flat_pattern", order=60))
    register(Study("sheet_cutcheck", "study", "Cut-file check",
                   "The flat pattern's DXF as a laser shop reads it: closed contours, duplicates, crossings, text, "
                   "holes against the thickness, each rule with its source.", "computed (2D), rules with sources",
                   run=cut_run, key=key("cut"), inputs=("geometry", "rule table"), app="sheet", tool="cut_file_check",
                   order=61))
    register(Study("sheet_bend_order", "study", "Bend order",
                   "A sequence a press brake can form with a stated V-die and gooseneck punch, or the collisions that "
                   "rule one out.", "model (2D press-brake cross-section)", run=brake_run, key=key("brake"),
                   inputs=("geometry", "bend table", "tool model"), app="sheet", tool="bend_order", heavy=True, order=62))


__all__ = ["flat_pattern", "profile", "cut_check", "bend_order", "service_preflight", "dfm_check", "render_flat",
           "summary", "unfolded", "register_studies"]
