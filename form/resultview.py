"""What the window draws of a result: one description per Bench entry, made only from what an engine stored.

A result lives on the part (direction I, decision 7). The engines already write what a viewport needs: the strength
field (form.fea.field/1), the manufacturability overlay (form-dfm-overlay/1), the CNC view (form-cam-view/1), the
unfolded sheet, the drawing's scene graph (sheet.json) and the motion study. `describe` reads the one that belongs to
a Bench entry and returns what the window needs beside the arrays: where the peak is, what was left out, where the
loads and the supports sit, the scale with its unit, the stated error, the evidence, and what the result does not
tell. The arrays themselves stay in their files: the window's geometry reads them from disk (form/app/resultgeo.py),
so a 10 MB overlay never travels through the interface as text.

Nothing here computes a result or marks one current. An entry that is not current for the head returns
{"kind", "state", "why"} and the window says "not run" (or what it needs); a study that did not converge is returned
with converged false and its reason, and the window never plays the "a result develops" moment for it.

Kernel-free: importable without OCCT. numpy is imported where a mesh is read.
"""
from __future__ import annotations

import base64
import json
import math
from pathlib import Path

KINDS = {"strength": "field", "cam": "cam", "dfm": "dfm", "sheet": "flat", "drawing": "drawing", "motion": "motion",
         "stack": "stack", "topology": "topology", "inverse": "front", "printOrient": "front", "lattice": "lattice"}
# Hooks of engines that are not on this branch yet: their Bench entries will name these apps. Until then `describe`
# answers {"kind": "none", "state": "unavailable"} for them and the window draws nothing.
LATER: dict = {}

NOT_TOLD = {
    "static": "Not told here: fatigue, yielding and what happens after it, buckling, impact, creep, how the bolts and "
              "the welds hold, and anything the loads you defined leave out.",
    "modal": "Not told here: how large the motion is (a mode shape has no amplitude), damping, and the response to a "
             "real excitation.",
    "buckling": "Not told here: the collapse after buckling, the effect of imperfections (a real part buckles "
                "earlier), and material yielding before it.",
    "thermal": "Not told here: transients, radiation, contact resistance and convection beyond the coefficients you gave.",
    "thermal_stress": "Not told here: fatigue, yielding, creep at temperature, and transients.",
}


def _read(path) -> dict | None:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _np(text: str, dtype):
    import numpy as np
    return np.frombuffer(base64.b64decode(text), dtype=dtype) if text else np.zeros(0, dtype=dtype)


def _entry(st, p, sid: str) -> dict:
    from . import studies
    return studies.show(st, p, sid)


def _sentence(t: str) -> str:
    """A clause from an engine, ended as a sentence."""
    t = (t or "").strip()
    return t + "." if t and t[-1] not in ".!?)" else t


def _none(e: dict | None, kind: str, why: str = "") -> dict:
    e = e or {}
    return {"kind": kind, "id": e.get("id", ""), "state": e.get("state", "never"), "title": e.get("label", ""),
            "why": why or e.get("why") or "", "rev": e.get("rev"), "head": e.get("head")}


def describe(st, p: dict, sid: str, opts: dict | None = None) -> dict:
    """The description of entry `sid` for the window. opts: study (a strength study's id), setup (CNC setup n)."""
    from . import studies
    opts = opts or {}
    try:
        s = studies.get(sid)
    except Exception:                                       # noqa: BLE001 - an entry of an engine that is not here
        return {"kind": "none", "id": sid, "state": "unavailable", "why": "This engine is not part of this build."}
    app = s.app or ""
    if app in LATER:
        return {"kind": "none", "id": sid, "state": "unavailable", "why": "Drawn when " + LATER[app] + " is built."}
    kind = KINDS.get(app)
    if kind is None:
        return {"kind": "none", "id": sid, "state": "n/a", "why": "This entry draws nothing on the part."}
    e = _entry(st, p, sid)
    if kind == "front":
        out = (_inverse if app == "inverse" else _orient)(st, p, e, opts)
    else:
        out = {"field": _strength, "dfm": _dfm, "cam": _cam, "flat": _flat, "drawing": _drawing, "motion": _motion,
               "stack": _stack, "topology": _topology, "lattice": _lattice}[kind](st, p, e, opts)
    out.setdefault("kind", kind)
    out.setdefault("id", sid)
    out.setdefault("head", p.get("head"))
    out.setdefault("title", e.get("label", ""))
    return out


# ---- strength: the field on the part ------------------------------------------------------------------------------

def _pct(x) -> str:
    return ("%.1f" % (100 * float(x))).rstrip("0").rstrip(".") + " %"


def _num(x, digits=3) -> str:
    x = float(x)
    if x == 0:
        return "0"
    d = max(0, digits - 1 - int(math.floor(math.log10(abs(x)))))
    return ("%.*f" % (min(d, 6), x))


def _face_glyphs(picks: list, P, T, F) -> list:
    """Where a picked face is, for a glyph: its centroid on the surface, its mean outward normal and its size, read
    off the field's own surface mesh (each triangle names its B-rep face)."""
    import numpy as np
    out = []
    if not len(T):
        return out
    C = (P[T[:, 0]] + P[T[:, 1]] + P[T[:, 2]]) / 3
    N = np.cross(P[T[:, 1]] - P[T[:, 0]], P[T[:, 2]] - P[T[:, 0]])
    A = np.linalg.norm(N, axis=1) / 2
    for pk in picks:
        at = pk.get("at") if isinstance(pk, dict) else pk
        if at is None or len(at) != 3:
            continue
        q = np.asarray(at, dtype=float)
        near = int(np.argmin(np.linalg.norm(C - q, axis=1)))
        m = F == F[near]
        w = A[m]
        if w.sum() <= 0:
            continue
        c = (C[m] * w[:, None]).sum(axis=0) / w.sum()
        n = N[m].sum(axis=0)
        ln = float(np.linalg.norm(n))
        # a hole's wall has no mean normal: the glyph then stands along the hole's axis side that faces outward least
        flat = ln > 0.35 * 2 * float(w.sum())
        n = n / ln if ln > 1e-9 else np.array([0.0, 0.0, 1.0])
        # the glyph sits on the surface: the triangle of that face nearest its centroid
        on = C[m][int(np.argmin(np.linalg.norm(C[m] - c, axis=1)))]
        out.append({"at": [round(float(v), 4) for v in (c if flat else on)], "normal": [round(float(v), 5) for v in n],
                    "flat": bool(flat), "area_mm2": round(float(w.sum()), 3), "face": int(F[near]),
                    "size_mm": round(float(math.sqrt(w.sum())), 3)})
    return out


def _strength(st, p: dict, e: dict, opts: dict) -> dict:
    from .fea import KIND_LABEL, study
    rows = study.listing(st, p)
    if not rows:
        return _none(e, "field", "No strength study is defined for this design yet.")
    pick = opts.get("study") or ""
    row = next((r for r in rows if r["id"] == pick), None) or next((r for r in rows if r["state"] == "current"), rows[0])
    studies_ = [{"id": r["id"], "name": r.get("name") or KIND_LABEL.get(r["kind"], r["kind"]), "kind": r["kind"],
                 "state": r["state"], "headline": r.get("headline") or ""} for r in rows]
    base = {"kind": "field", "state": row["state"], "study": row["id"], "studies": studies_, "study_kind": row["kind"],
            "name": row.get("name") or "", "rev": row.get("rev") or row.get("last_rev")}
    if row["state"] != "current":
        base["why"] = row.get("why") or row.get("unavailable") or (
            "Describes revision %s; a stale field is not drawn." % row.get("last_rev") if row["state"] == "stale" else "Not run.")
        return base
    got = study.result(st, p, row["id"], stale_ok=False)
    r = got.get("result") or {}
    fp = study.field_path(st, p, row["id"])
    if not r or fp is None:
        return {**base, "state": "never", "why": "The result has no field data. Run it again."}
    kind = r.get("kind") or row["kind"]
    conv = r.get("convergence") or {}
    levels = conv.get("levels") or []
    err = r.get("discretisation_error") or {}
    out = {**base, "rev": r.get("rev"), "evidence": r.get("evidence") or "", "headline": r.get("headline") or "",
           "converged": bool(r.get("converged")), "frame": r.get("frame") or "as built",
           "why": "" if r.get("converged") else (r.get("not_converged_because") or r.get("stopped_because") or
                                                 "It did not converge within its budget."),
           "not": NOT_TOLD.get(kind, NOT_TOLD["static"]), "mesh": {"file": str(fp), "key": r.get("key")},
           "method": (conv.get("method") or ""), "assumptions": r.get("assumptions") or []}
    f = _read(fp) or {}
    import numpy as np
    P = _np(f.get("positions"), "<f4").reshape(-1, 3).astype(float)
    T = _np(f.get("indices"), "<u4").reshape(-1, 3).astype(np.int64)
    F = _np(f.get("face"), "<u4")
    diag = float(np.linalg.norm(P.max(axis=0) - P.min(axis=0))) if len(P) else 1.0
    out["mesh"].update({"vertices": int(len(P)), "triangles": int(len(T)), "diag_mm": round(diag, 3)})
    d = r.get("definition") or (got.get("study") or {})
    glyphs = []
    for fx in d.get("fixtures") or []:
        for g in _face_glyphs(fx.get("faces") or [], P, T, F):
            glyphs.append({**g, "role": "fixture", "type": fx.get("type") or "fixed",
                           "label": {"fixed": "held", "hold": "held in a direction"}.get(fx.get("type") or "fixed", fx.get("type"))})
    for ld in d.get("loads") or []:
        v = ld.get("vector")
        mag = float(np.linalg.norm(v)) if v is not None else None
        word = ("%s N" % _num(mag)) if ld.get("type") == "force" and mag is not None else \
            ("%s MPa" % _num(ld.get("value"))) if ld.get("type") == "pressure" and ld.get("value") is not None else \
            (ld.get("type") or "load")
        for g in _face_glyphs(ld.get("faces") or [], P, T, F):
            dirn = (np.asarray(v, float) / mag).tolist() if v is not None and mag else [-x for x in g["normal"]]
            glyphs.append({**g, "role": "load", "type": ld.get("type") or "force", "vector": [round(float(x), 5) for x in dirn],
                           "label": word})
        if ld.get("type") == "gravity" and len(P):
            c = (P.min(axis=0) + P.max(axis=0)) / 2
            g = np.asarray(v if v is not None else [0, 0, -1], float)
            glyphs.append({"role": "load", "type": "gravity", "at": [round(float(x), 3) for x in c], "flat": True,
                           "normal": [0, 0, 1], "vector": (g / (np.linalg.norm(g) or 1)).round(5).tolist(),
                           "label": "gravity", "size_mm": round(diag * 0.12, 3), "area_mm2": 0, "face": -1})
    out["glyphs"] = glyphs
    lines = []
    if kind in ("static", "thermal_stress"):
        rng = (f.get("ranges") or {}).get("von_mises") or [0, r.get("peak_von_mises_MPa") or 1]
        peak = float(r.get("peak_von_mises_MPa") or rng[1])
        dmax = float(r.get("max_displacement_mm") or 0)
        sf = r.get("safety_factor") or {}
        out.update({"field": "von_mises", "unit": "MPa", "quantity": "von Mises stress",
                    "range": [0.0, peak], "range_anywhere": [float(rng[0]), float(rng[1])],
                    "peak": {"at": r.get("peak_at"), "value": peak, "text": "%s MPa" % _num(peak)},
                    "stated": {"stress": err.get("stress"), "displacement": err.get("displacement"),
                              "text": "± " + _pct(err["stress"]) if err.get("stress") is not None else ""},
                    "max_displacement": {"at": r.get("max_displacement_at"), "value": dmax},
                    # the deformed shape drawn so its largest movement is 6 % of the part's diagonal, as a round factor
                    "deform": {"max_mm": dmax, "auto": _round_factor(0.06 * diag / dmax) if dmax > 0 else 0},
                    "singular": [{"at": s.get("at"), "label": s.get("label"), "why": s.get("why"),
                                  "radius_mm": s.get("left_out_within_mm"), "nodes": s.get("nodes_left_out"),
                                  "by_refinement": s.get("stress_there_MPa_by_refinement")} for s in r.get("singularities") or []]})
        if sf.get("value") is not None:
            lines.append({"k": "Safety factor", "v": "%.2f" % sf["value"], "ev": "simulated",
                          "note": ("at least %.2f with the stated error, against %s" % (sf.get("low") or sf["value"], sf.get("against") or "the strength"))})
        lines.append({"k": "Peak von Mises", "v": "%s MPa" % _num(peak), "ev": "simulated", "note": out["stated"]["text"]})
        lines.append({"k": "Largest displacement", "v": "%s mm" % _num(dmax), "ev": "simulated",
                      "note": "± " + _pct(err["displacement"]) if err.get("displacement") is not None else ""})
        eq = r.get("equilibrium") or {}
        if eq:
            lines.append({"k": "Equilibrium", "v": "balanced" if eq.get("balanced") else "not balanced", "ev": "computed",
                          "note": "reactions against the loads, residual %.1e" % float(eq.get("force_residual") or 0)})
        he = r.get("hand_estimate") or {}
        if he.get("applies"):
            lines.append({"k": "Hand estimate", "v": "%s MPa" % _num(he.get("stress_MPa") or 0), "ev": "computed",
                          "note": he.get("formula") or "beam theory at the fixed end"})
        elif he.get("why"):
            lines.append({"k": "Hand estimate", "v": "none", "ev": "", "note": he["why"]})
        for s in r.get("singularities") or []:
            lines.append({"k": "Left out", "v": "%d nodes" % int(s.get("nodes_left_out") or 0), "ev": "",
                          "note": "%s, within %s mm: the stress there grows with every refinement" % (s.get("label") or "a singular zone", _num(s.get("left_out_within_mm") or 0))})
        series = "peak_von_mises"
    elif kind in ("modal", "buckling"):
        vals = f.get("mode_frequencies_Hz") if kind == "modal" else f.get("mode_load_factors")
        vals = vals or r.get("frequencies_Hz") or []
        unit = "Hz" if kind == "modal" else "×"
        out.update({"field": "modes", "unit": "", "quantity": "mode shape, largest movement 1",
                    "range": [0.0, 1.0], "modes": [{"n": i + 1, "value": float(v), "text": ("%s Hz" % _num(v, 4)) if kind == "modal" else ("%s × the load" % _num(v, 3))}
                                                   for i, v in enumerate(vals)],
                    "deform": {"max_mm": 1.0, "auto": round(0.05 * diag, 3)}, "singular": [], "peak": None,
                    "stated": {"text": ("± " + _pct(err.get("frequency") if err.get("frequency") is not None else next(iter([v for v in err.values() if isinstance(v, (int, float))]), 0)))
                              if err else ""}})
        for m in out["modes"]:
            lines.append({"k": ("Mode %d" % m["n"]) if kind == "modal" else ("Buckling mode %d" % m["n"]), "v": m["text"], "ev": "simulated", "note": ""})
        if r.get("meaning"):
            lines.append({"k": "Meaning", "v": "", "ev": "", "note": r["meaning"]})
        series = "frequency" if kind == "modal" else "load_factor"
    else:                                                   # steady heat
        rng = (f.get("ranges") or {}).get("temperature") or [r.get("t_min_C") or 0, r.get("t_max_C") or 1]
        out.update({"field": "temperature", "unit": "°C", "quantity": "temperature", "range": [float(rng[0]), float(rng[1])],
                    "peak": None, "singular": [], "deform": {"max_mm": 0, "auto": 0}, "stated": {"text": ""}})
        lines.append({"k": "Temperature", "v": "%s to %s °C" % (_num(rng[0]), _num(rng[1])), "ev": "simulated", "note": ""})
        series = "temperature"
    out["lines"] = lines
    # the convergence plot: the quantity that decides, per refinement level, against the unknowns solved
    pts = []
    key = {"peak_von_mises": "peak_von_mises_MPa"}.get(series, series)
    blk = conv.get(series) or {}
    if not blk:                                             # modal and buckling name their deciding series themselves
        series = next((k for k, v in conv.items() if isinstance(v, dict) and v.get("values")), series)
        blk = conv.get(series) or {}
    vals = blk.get("values") or [lv.get(key) for lv in levels]
    for lv, v in zip(levels, vals):
        if v is not None and lv.get("unknowns"):
            pts.append({"unknowns": int(lv["unknowns"]), "value": float(v), "level": lv.get("level")})
    out["convergence"] = {"points": pts, "quantity": {"peak_von_mises": "peak von Mises, MPa"}.get(series, series.replace("_", " ")),
                          "extrapolated": blk.get("extrapolated"), "error": blk.get("error"),
                          "tolerance": (conv.get("tolerance") or {}).get("stress" if series == "peak_von_mises" else "displacement"),
                          "unknowns": (r.get("mesh") or {}).get("unknowns"), "seconds": r.get("seconds")}
    return out


def _round_factor(x: float) -> float:
    """A factor a person reads: 1, 2, 5 times a power of ten, at or under x."""
    if x <= 0 or not math.isfinite(x):
        return 0
    e = math.floor(math.log10(x))
    m = x / 10 ** e
    return float((5 if m >= 5 else 2 if m >= 2 else 1) * 10 ** e)


# ---- manufacturability ---------------------------------------------------------------------------------------------

def _dfm(st, p: dict, e: dict, opts: dict) -> dict:
    if e.get("state") != "current":
        return _none(e, "dfm")
    process = (e.get("id") or "").replace("dfm_", "", 1)
    ov_file = next((f for f in e.get("files") or [] if "overlay-" in str(f)), None)
    res = None
    if ov_file:
        key = Path(ov_file).stem.replace("overlay-", "", 1)
        res = _read(Path(ov_file).parent / f"{process}-{key}.json")
    if res is None or not ov_file or not Path(ov_file).is_file():
        return _none({**e, "state": "never"}, "dfm", "The check's overlay is not on disk. Run it again.")
    ov = _read(ov_file) or {}
    data = res.get("data") or {}
    rows = [{"id": r["id"], "title": r.get("title"), "status": r.get("status"), "value": r.get("value"), "unit": r.get("unit") or "",
             "limit": r.get("fail") if r.get("fail") is not None else r.get("warn"), "op": r.get("op") or "", "fix": r.get("fix"),
             "why": r.get("why") or "", "reason": r.get("reason") or "", "evidence": r.get("evidence") or "",
             "faces": sorted({int(fc) for f in res.get("findings") or [] if f.get("rule") == r["id"] for fc in f.get("faces") or []}),
             "findings": sum(1 for f in res.get("findings") or [] if f.get("rule") == r["id"])}
            for r in res.get("rows") or []]
    pull = data.get("pull")
    centre = None
    try:
        import numpy as np
        P = _np(ov.get("positions"), "<f4").reshape(-1, 3)
        if len(P):
            lo, hi = P.min(axis=0), P.max(axis=0)
            centre = {"lo": lo.round(3).tolist(), "hi": hi.round(3).tolist()}
    except Exception:                                       # noqa: BLE001
        pass
    lg = ov.get("legend") or {}
    return {"kind": "dfm", "state": "current", "rev": res.get("rev"), "process": process, "label": res.get("label"),
            "verdict": res.get("verdict"), "headline": res.get("headline"), "options": res.get("options") or {}, "evidence": res.get("evidence") or lg.get("evidence") or "",
            "not": "Not told here: " + (res.get("not_judged") or lg.get("not") or ""), "what": lg.get("what") or "",
            "mesh": {"file": str(ov_file), "has_face": bool(ov.get("face")), "triangles": len(ov.get("status") or "") * 3 // 4 // 3},
            "map": ov.get("map"), "stops": lg.get("stops") or [], "rows": rows, "box": centre,
            "faces": ov.get("faces") or [], "markers": ov.get("markers") or [],
            "parting": {"segments": (data.get("parting_line") or {}).get("segments") or 0, "lines": ov.get("lines"),
                        "note": (data.get("parting_line") or {}).get("note") or ""} if ov.get("lines") else None,
            "pull": {"dir": pull, "name": data.get("pull_name") or ""} if pull else None,
            "side_actions": [{"at": s.get("at"), "dir": s.get("direction"), "label": s.get("action"), "area_mm2": s.get("area_mm2")}
                             for s in data.get("side_actions") or []],
            "fixes": [{"id": f["id"], "kind": f.get("kind"), "rules": f.get("rules") or [], "summary": f.get("summary") or "",
                       "can": bool(f.get("attempts"))} for f in res.get("fixes") or []],
            "sources": [{"title": s.get("title"), "publisher": s.get("publisher")} for s in res.get("sources") or []]}


def fix_preview(st, p: dict, process: str, fix: str, options: dict | None = None) -> dict:
    """A manufacturability fix built and checked without saving it, with the candidate's own geometry so the window
    can draw it as a ghost over the part. Nothing is written to the design."""
    from .dfm import fixes
    out = fixes.apply_fix(st, p, process, fix or None, options or None, apply=False)
    if out.get("previewed") and out.get("ops"):
        rid, vals, _mode = fixes._candidate(st, p, out["ops"])
        v = st._k("view", key=st.geometry_key(p, rid, vals), recipe_id=rid, values=vals, tol=0.05, p=p)
        out["view"] = {k: v.get(k) for k in ("mesh", "edges", "bbox")}
    return out


# ---- CNC ----------------------------------------------------------------------------------------------------------

def _cam(st, p: dict, e: dict, opts: dict) -> dict:
    if e.get("state") != "current":
        return _none(e, "cam")
    vf = next((f for f in e.get("files") or [] if Path(str(f)).name.startswith("view-")), None)
    v = _read(vf) if vf else None
    if not v:
        return _none({**e, "state": "never"}, "cam", "The simulation's view file is not on disk. Run it again.")
    summ = ((e.get("data") or {}).get("summary")) or {}
    setups = []
    for i, s in enumerate(v.get("setups") or []):
        tmax = 0.0
        ops = []
        for tp in s.get("toolpaths") or []:
            t = _np(tp.get("t"), "<f4")
            t1 = float(t.max()) if len(t) else 0.0
            t0 = float(t.min()) if len(t) else 0.0
            tmax = max(tmax, t1)
            ops.append({"op": tp.get("op"), "kind": tp.get("kind"), "operation": tp.get("operation"), "label": tp.get("label"),
                        "tool": tp.get("tool"), "color": tp.get("color"), "count": tp.get("count"), "t0": round(t0, 3), "t1": round(t1, 3)})
        stock = s.get("stock") or {}
        setups.append({"index": i, "n": s.get("n"), "name": s.get("name"), "frame": (s.get("frame") or {}).get("text") or "",
                       "axis": ((s.get("frame") or {}).get("R") or [[1, 0, 0], [0, 1, 0], [0, 0, 1]])[2],
                       "ops": ops, "duration_s": round(tmax, 3), "marks": s.get("marks") or [],
                       "stock": {"cell_mm": stock.get("cell_mm"), "grid": stock.get("grid"), "what": stock.get("what") or ""} if stock else None})
    lg = v.get("legend") or {}
    return {"kind": "cam", "state": "current", "rev": e.get("rev"), "label": v.get("label") or "", "evidence": v.get("evidence") or "simulated",
            "headline": e.get("headline") or "", "mesh": {"file": str(vf)}, "setups": setups, "summary": summ,
            "ops_legend": lg.get("ops") or [], "stock_legend": lg.get("stock") or [],
            "not": "Not told here: workholding, deflection, chatter, chip evacuation, surface finish, tool wear and the "
                   "machine's own travel. The stock drawn is the end of each setup, not a moment along it."}


# ---- sheet metal: the flat pattern --------------------------------------------------------------------------------

def _flat(st, p: dict, e: dict, opts: dict) -> dict:
    if (e.get("id") or "") != "sheet_flat":
        e = _entry(st, p, "sheet_flat")
    if e.get("state") != "current":
        return _none(e, "flat")
    d = st.dir(p["id"]) / "artifacts" / "sheet"
    res = None
    key = (e.get("data") or {}).get("key")
    for cand in ([d / f"unfold-{key}.json"] if d is not None and key else []) + (sorted(d.glob("unfold-*.json"), key=lambda x: -x.stat().st_mtime) if d is not None and d.is_dir() else []):
        r = _read(cand)
        if r and r.get("rev") == e.get("rev") and (not key or r.get("key") == key):
            res = r
            break
    if res is None or not res.get("ok"):
        return _none({**e, "state": "never" if res is None else "failed"}, "flat",
                     "The flat pattern is not on disk. Run it again." if res is None else
                     "It does not unfold: " + "; ".join(x.get("why", "") for x in res.get("reasons") or []))
    regions = res.get("regions") or {}
    ents = []
    for en in res.get("entities") or []:
        rg = regions.get(str(en.get("face"))) or {}
        item = {"t": en.get("t"), "face": en.get("face"), "path": rg.get("path") or [], "zone": rg.get("zone")}
        for k in ("a", "b", "c", "r", "a0", "a1", "pts"):
            if k in en:
                item[k] = en[k]
        ents.append(item)
    bends = [{"id": b["id"], "angle": b.get("angle"), "direction": b.get("direction"), "r": b.get("r"), "K": b.get("K"),
              "line": b.get("line"), "start": b.get("start"), "end": b.get("end"), "length": b.get("length"),
              "q": b.get("q"), "u": b.get("u"), "d": b.get("d"), "allowance": b.get("allowance"), "s": b.get("s"),
              "k_source": ((b.get("k_source") or {}).get("source") or (b.get("k_source") or {}).get("title") or "")}
             for b in res.get("bends") or []]
    ver = res.get("verify") or {}
    return {"kind": "flat", "state": "current", "rev": res.get("rev"), "evidence": e.get("evidence") or "computed (B-rep unfold, folded back)",
            "headline": e.get("headline") or "", "t": res.get("t"), "size_mm": res.get("size_mm"), "frame": res.get("frame"),
            "entities": ents, "bends": bends, "regions": {k: {"path": v.get("path") or [], "zone": v.get("zone")} for k, v in regions.items()},
            "verify": {"max_mm": ver.get("max_mm"), "samples": ver.get("samples"), "pass": ver.get("pass"), "tolerance_mm": ver.get("tolerance_mm")},
            "area_mm2": res.get("area_mm2"), "outline_mm": res.get("outline_mm"),
            "not": "Not told here: springback, the tooling's marks, grain direction and whether your shop's brake reaches every bend "
                   "(see Bend order)."}


# ---- the drawing sheet ----------------------------------------------------------------------------------------------

def _drawing(st, p: dict, e: dict, opts: dict) -> dict:
    if e.get("state") != "current":
        return _none(e, "drawing")
    from . import drawing
    d = drawing.cached(st, p)
    sc = _read(Path(d["dir"]) / "sheet.json") if d else None
    if not sc:
        return _none({**e, "state": "never"}, "drawing", "The sheet's scene is not on disk. Make the drawing again.")
    from .drawing import scene
    dims = []

    def walk(g):
        for c in g.get("children") or []:
            if c.get("kind") == "group":
                if c.get("role") == "dimension":
                    m = c.get("meta") or {}
                    dims.append({"id": c.get("id"), "bbox": c.get("bbox"), "param": m.get("param"), "feature": m.get("feature"),
                                 "value": m.get("value"), "binding": m.get("binding"), "text": m.get("text"),
                                 "editable": bool(m.get("param"))})
                walk(c)
    walk(sc)
    rep = d.get("report") or {}
    return {"kind": "drawing", "state": "current", "rev": d.get("rev"), "evidence": e.get("evidence") or "computed",
            "headline": e.get("headline") or "", "sheet": sc, "themes": scene.THEMES, "dims": dims, "size": sc.get("size"),
            "name": sc.get("name"), "scale": rep.get("scale"), "projection": rep.get("projection"),
            "files": d.get("paths") or {},
            "not": "Not told here: tolerances you did not declare, surface finish, and anything a shop adds by convention."}


# ---- motion -------------------------------------------------------------------------------------------------------

def _motion(st, p: dict, e: dict, opts: dict) -> dict:
    if e.get("state") != "current":
        return _none(e, "motion")
    key = (e.get("data") or {}).get("key")
    d = st.dir(p["id"]) / "artifacts" / "motion"
    r = _read(d / f"study-{key}.json") if d is not None and key else None
    if not r:
        return _none({**e, "state": "never"}, "motion", "The motion study is not on disk. Run it again.")
    c = r.get("clearance") or {}
    per = c.get("per_frame") or []
    frames = r.get("frames") or []
    return {"kind": "motion", "state": "current", "rev": r.get("rev"), "evidence": r.get("evidence") or "", "headline": e.get("headline") or "",
            "duration_s": r.get("duration_s"), "times": r.get("times") or [f.get("t") for f in frames],
            "poses": [f.get("pose") or {} for f in frames], "closed": [bool(f.get("closed")) for f in frames],
            "drivers": r.get("drivers") or [],
            "joints": [{"joint": j.get("joint"), "label": j.get("label"), "role": j.get("role"), "unit": j.get("unit"),
                        "range": j.get("range"), "value": j.get("value") or []} for j in r.get("joints") or []],
            "traces": [{"label": t.get("label"), "part": t.get("part"), "points": t.get("positions_mm") or [],
                        "length_mm": t.get("path_length_mm")} for t in r.get("traces") or []],
            "clearance": {"status": c.get("status"), "value": c.get("value"), "evidence": c.get("evidence") or "",
                          "tolerance_mm": c.get("tolerance_mm"), "min": c.get("min"), "first_contact_t": c.get("first_contact_t"),
                          "series": [{"t": x.get("t"), "mm": x.get("clearance_mm"), "state": x.get("state"), "at": x.get("at"), "to": x.get("to"),
                                      "pair": x.get("pair")} for x in per], "partial": bool(c.get("partial")),
                          "detail": c.get("detail") or ""} if c else None,
            "torque": [{"joint": j.get("joint"), "unit": j.get("unit"), "max_abs": j.get("max_abs"), "values": j.get("values") or []}
                       for j in (r.get("torque") or {}).get("joints") or []],
            "notes": r.get("notes") or [],
            "not": "Not told here: forces between the parts, friction, inertia loads and play in the joints. The parts are rigid."}


# ---- tolerance stack-up: the loop on the parts (docs/TOLERANCES.md, `draw`) -----------------------------------------

def _stack(st, p: dict, e: dict, opts: dict) -> dict:
    """The stack with the lowest Cpk among the current ones (the Bench entry's headline), or the one asked for: its
    loop as the engine drew it (faces with their roles, segments along the gap's direction), the gap's numbers and
    each contributor's share. Points are in the assembled frame at rest."""
    from . import stack as S
    rows = S.listing(st, p)
    if not rows:
        return _none(e, "stack", "No stack is defined yet: pick the two faces of a gap (tolerance_stack).")
    pick = opts.get("study") or ""
    cur = [r for r in rows if r["state"] == "current"]
    if not cur:
        return _none(e, "stack", rows[0].get("why") or "")
    best = None
    for r in cur:
        res = S.stored(st, p, r["id"])[0] or {}
        c = ((res.get("capability") or {}).get("rss") or {}).get("cpk")
        k = c if isinstance(c, (int, float)) and math.isfinite(c) else math.inf
        if r["id"] == pick:
            best = (-math.inf, r, res)
            break
        if best is None or k < best[0]:
            best = (k, r, res)
    _, row, res = best
    if not res.get("draw"):
        return _none(e, "stack", "This stack was stored without its loop: run it again.")
    g, wc, rs = res["gap"], res["worst_case"], res["rss"]
    cap = (res.get("capability") or {}).get("rss") or {}
    return {"kind": "stack", "state": "current", "rev": res.get("rev") or e.get("rev"), "study": row["id"],
            "studies": [{"id": r["id"], "name": r.get("name") or r["id"], "state": r["state"]} for r in rows],
            "name": res.get("name") or row.get("name") or "", "evidence": res.get("evidence") or e.get("evidence") or "computed",
            "headline": res.get("headline") or "", "draw": res["draw"],
            "gap": {"nominal": g["nominal"], "direction": g["direction"]},
            "worst_case": [wc["min"], wc["max"]], "rss": [rs["min"], rs["max"]],
            "spec": res.get("spec") or {}, "cpk": cap.get("cpk") if isinstance(cap.get("cpk"), (int, float)) and math.isfinite(cap["cpk"]) else None,
            "chart": (res.get("chart") or [])[:6],
            "not": "Not told here: tolerances on angles beyond the linear range, form errors not declared as GD&T, "
                        "wear, load and assembly forces. " + _sentence((res.get("caveats") or [""])[0])}


# ---- topology optimisation: the density of every iteration (docs/OPTIMISATION.md, frames) --------------------------

def _topology(st, p: dict, e: dict, opts: dict) -> dict:
    """The newest run for the head: its frames file (the density at the part's surface vertices, one picture per
    iteration from the even start) for the window to play, with each iteration's compliance and volume."""
    from .topo import study as T
    r = T.get(st, p)
    if r is None:
        return _none(e, "topology", "Not run yet.")
    if r.get("stale"):
        return {**_none(e, "topology", r.get("stale_why") or ""), "state": "stale"}
    f = r.get("frames_file") or ""
    meta, hist = {}, []
    if f and Path(f).is_file():
        d = _read(f) or {}
        surf = d.get("surface") or {}
        meta = {"frames": len(surf.get("frames") or []), "vertices": surf.get("vertices"), "triangles": surf.get("triangles")}
        hist = [{k: x.get(k) for k in ("iteration", "compliance", "volume")} for x in d.get("frames") or []]
    if not meta.get("frames"):
        return {**_none(e, "topology", "This run kept no frames to play: run it again."), "state": "stale"}
    st_ = r.get("settings") or {}
    return {"kind": "topology", "state": "current", "rev": r.get("rev"), "run": r.get("id"), "file": f, **meta,
            "headline": r.get("headline") or "", "evidence": r.get("evidence") or e.get("evidence") or "simulated",
            "converged": bool(r.get("converged")), "volfrac": st_.get("volfrac"), "resolution": r.get("resolution") or "",
            "history": hist,
            "not": "Not told here: the density field is a layout, not a part; the pockets built from it are studied "
                        "again, and their own study is what the safety factor is. " + _sentence(r.get("resolution") or "")}


# ---- lattice infill: the lattice alone, clipped to its region (docs/LATTICES.md) ------------------------------------

def _lattice(st, p: dict, e: dict, opts: dict) -> dict:
    """The lattice the head carries, drawn inside the part: its struts or level set kept where the material is, inside
    the skin (a mesh the kernel writes once per geometry, form/lattice/geom.py view), with the relative density per
    vertex (asked, for a graded lattice; measured on the drawn lattice, for a uniform one) and the build's numbers."""
    from . import lattice as LT
    from .studio import H
    spec = LT.current(st, p)
    if not spec:
        return _none(e, "lattice", "No lattice in this design: lattice_fill puts one in a region, with a skin.")
    if e.get("state") != "current":
        return {**_none(e, "lattice", e.get("why") or ""), "state": e.get("state") or "never"}
    try:
        r = LT.read(st, p)
    except Exception as ex:                             # noqa: BLE001 - say why, draw nothing
        return {**_none(e, "lattice", str(ex)), "state": "failed"}
    f = LT._dir(st, p) / ("view-" + H("lattice-view", 1, st.keys(p)["geometry"], spec)[:20] + ".json")
    info = None
    if f.is_file():
        d = _read(f) or {}
        info = {k: d.get(k) for k in ("region", "clipped", "graded", "triangles", "volume_mm3", "inner_volume_mm3")} if d else None
    if info is None:
        rev = st.rev(p)
        f.parent.mkdir(parents=True, exist_ok=True)
        info = st._k("lattice_view", timeout=900, key=st.keys(p)["geometry"], recipe_id=st.rid(p), values=rev["values"], p=p, out=str(f))
        if info.get("error"):
            return {**_none(e, "lattice", info["error"] + (" " + info["hint"] if info.get("hint") else "")), "state": "failed"}
    dens = r.get("relative_density") or {}
    built = r.get("built") or {}
    g = spec.get("grading") or {}
    rng = sorted(float(x) for x in g["density"]) if g.get("density") else None
    drawn = (info.get("volume_mm3") or 0.0) / max(info.get("inner_volume_mm3") or 0.0, 1e-12)
    return {"kind": "lattice", "state": "current", "rev": r.get("rev") or e.get("rev"), "file": str(f),
            "label": r.get("label") or "", "cell": spec.get("cell"), "skin": spec.get("skin"), "grading": g.get("mode") or "uniform",
            "region": info.get("region"), "triangles": info.get("triangles"), "clipped": bool(info.get("clipped")),
            "density": {"computed": dens.get("value"), "measured": built.get("relative_density_measured"), "drawn": drawn,
                        "range": rng or [drawn, drawn]},
            "representation": built.get("representation") or "", "output": built.get("output") or "",
            "headline": r.get("headline") or "", "evidence": e.get("evidence") or "computed; measured on the built solid",
            "not": "Not told here: how the lattice fails, fatigue, and powder or resin left inside."}


# ---- fronts: inverse design and print orientation (a Pareto chart in the card) -----------------------------------

def _inverse(st, p: dict, e: dict, opts: dict) -> dict:
    from .inverse import design as I
    rec = I.get(st, p)
    if rec is None:
        return _none(e, "front", "Not run yet.")
    if rec.get("stale"):
        return {**_none(e, "front", "The design's source changed since this search: search again."), "state": "stale"}
    ch = I.chart(rec)
    axes = ch["axes"][:2]
    pts = [{"index": x["index"], "at": x["at"][:2], "state": x["state"], "why": x.get("why"), "current": x.get("current"),
            "values": x["values"]} for x in ch["points"] if len(x["at"]) >= 2 and None not in x["at"][:2]]
    return {"kind": "front", "app": "inverse", "state": "current", "rev": rec.get("rev"), "run": rec.get("id"),
            "evidence": rec.get("evidence") or e.get("evidence") or "", "headline": rec.get("headline") or "",
            "axes": axes, "points": pts, "front": ch["front"], "note": ch["note"],
            "open": "A point opens its variant as a draft: built and previewed, nothing kept until you commit it."}


def _orient(st, p: dict, e: dict, opts: dict) -> dict:
    from .printphys import orient as O
    if O.cached(st, p) is None:                         # what is stored is the search (its rows), not the ranked front
        return _none(e, "front", "Not run yet.")
    o = O.stored_options(p)
    try:                                                # the search is cached: this only ranks it (as the Bench entry does)
        r = O.run(st, p, cosmetic=o.get("cosmetic"), study=o.get("study") or "", load_direction=o.get("load_direction"),
                  level=o.get("level") or 2, critical_deg=o.get("critical_deg"), settings=o.get("settings"),
                  free=bool(o.get("free")), remember=False, strict=False)
    except Exception as ex:                             # noqa: BLE001 - say why, never draw a front that is not there
        return {**_none(e, "front", str(ex)), "state": "failed"}
    front = r.get("front") or []
    axes = [{"metric": "support_mm3", "label": "Support", "unit": "mm³", "better": "lower"},
            {"metric": "time_s", "label": "Print time", "unit": "min", "better": "lower"}]
    pts = [{"index": i, "id": x.get("id"), "at": [x.get("support_mm3"), (x.get("time_s") or 0) / 60.0], "state": "front", "label": x.get("label"),
            "current": bool(x.get("current")), "tip_over_deg": x.get("tip_over_deg"), "height_mm": x.get("height_mm"),
            "down": x.get("down")} for i, x in enumerate(front) if x.get("support_mm3") is not None and x.get("time_s") is not None]
    cal = (r.get("calibration") or {}).get("factors")
    return {"kind": "front", "app": "printOrient", "state": "current", "rev": r.get("rev") or e.get("rev"),
            "evidence": e.get("evidence") or "computed, modelled", "headline": O.headline(r),
            "axes": axes, "points": pts, "front": [q["index"] for q in pts],
            "note": "The orientations no other one beats on every objective at once; two of them drawn here. "
                    + ("Time calibrated on a real slice." if cal else "Time uncalibrated: it ranks orientations and little more."),
            "open": "A point turns the part on the stage to lie that way, and shows its numbers; Use this writes it to the "
                    "print setup."}
