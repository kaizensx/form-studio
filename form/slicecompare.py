"""Print time and cost on every printer you have: the design's exported STL sliced for real on each printer set up in
each installed slicer (form/printers.py), with the slicer's own time and filament estimate and the cost from your
prices (form/cost.py).

    from form import slicecompare
    r = slicecompare.compare(st, p)        # {"rows": [{printer, slicer, time_s, filament_g, cost, status, ...}], ...}

Every number in a row is read from that slicer's G-code (a simulation, not a print) or is your own price; a printer
whose bed is smaller than the part is reported as too small without slicing, and a slice that fails says why.
Each slice is kept under the design's side artifacts, keyed by the exported model and that printer's presets, so
asking again costs nothing until the design or the presets change. A design of several parts is sliced as exported
(all parts on one plate), and the result says so.
"""
from __future__ import annotations

import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

LIMIT = 8
WORKERS = 3
NOTE = ("Times and grams are each slicer's simulation of its own slice with that printer's process and filament; costs use "
        "your prices (or the filament preset's). Not a print, not a quote.")


def _err(msg, hint="", status=409):
    from .studio import StudioError
    return StudioError(msg, hint, status=status)


def _summary_path(st, p) -> Path:
    return st.dir(p["id"]) / "artifacts" / "side" / f"slicecompare-{st.keys(p)['exports']}.json"


def cached(st, p) -> dict | None:
    f = _summary_path(st, p)
    if f.is_file():
        return json.loads(f.read_text(encoding="utf-8")) | {"cached": True}
    return None


def candidates(cfg, limit: int = LIMIT, ids=None) -> list:
    """The printers to compare: the ones named, else the selected printer of each slicer first, then the rest."""
    from . import printers
    inv = printers.inventory(cfg)["printers"]
    if ids:
        want = list(ids)
        got = [x for x in inv if x["id"] in want]
        missing = [i for i in want if i not in {x["id"] for x in got}]
        if missing:
            raise _err("No such printer: " + ", ".join(missing) + ".", "Run `form printers` to see them.", 404)
        return got
    inv = sorted(inv, key=lambda x: (not x.get("selected"), x.get("source") != "user"))
    return inv[:max(1, int(limit))]


def _fits(bbox, env) -> bool:
    if not bbox or not env:
        return True
    a, b = sorted(bbox[:2]), sorted(env[:2])
    return a[0] <= b[0] and a[1] <= b[1] and bbox[2] <= env[2]


def _one(st, p, keys, stl: Path, pr: dict, prefs: dict) -> dict:
    from . import cost, printers, slicer, toolpath
    from .studio import H, _slicer_tag
    row = {"id": pr["id"], "printer": pr["name"], "model": pr.get("model") or "", "slicer": pr["slicer"], "kind": pr["kind"],
           "nozzle_mm": pr.get("nozzle_mm"), "envelope_mm": pr.get("envelope_mm"), "process": "", "filament": "",
           "time_s": None, "filament_g": None, "cost": None, "currency": prefs.get("currency", ""), "not_counted": [],
           "status": "ok", "reason": ""}
    try:
        choice = printers.complete(st.cfg, {"kind": pr["kind"], "machine": pr["name"], "process": pr.get("process") or "",
                                            "filament": pr.get("filament") or ""})
        row.update(process=choice["process"], filament=choice["filament"])
        r = printers.resolve(st.cfg, choice)
        if not r.get("available"):
            return row | {"status": "unavailable", "reason": r.get("reason") or "This printer cannot slice here."}
        presets = {k: v.get("sha") for k, v in (r.get("presets") or {}).items()}
        key = H("slicecompare", keys["exports"], presets, choice, *_slicer_tag(r))
        out = st.dir(p["id"]) / "artifacts" / "side" / ("compare-" + key)
        meta_f = out / "meta.json"
        if meta_f.is_file():
            meta = json.loads(meta_f.read_text(encoding="utf-8"))
        else:
            tmp = out.with_name(out.name + ".tmp")
            shutil.rmtree(tmp, ignore_errors=True)
            meta = slicer.slice_stl(r, stl, tmp, timeout=st.cfg["slicer"]["timeout_s"])
            (tmp / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
            shutil.rmtree(out, ignore_errors=True)
            tmp.rename(out)
        e = cost.estimate(meta, toolpath.gcode_settings(out / meta["gcode"]), prefs)
        row.update(time_s=meta.get("time_s"), filament_g=meta.get("filament_g"), layers=meta.get("layers"),
                   cost=e["per_plate_as_sliced"]["cost"], not_counted=e["per_plate_as_sliced"]["not_counted"],
                   slicer_version=meta.get("slicer_version") or "", gcode=str(out / meta["gcode"]))
    except Exception as ex:                      # one printer's failure never hides the others
        row.update(status="failed", reason=str(ex) or type(ex).__name__)
        hint = getattr(ex, "hint", "")
        if hint:
            row["hint"] = hint
    return row


def compare(st, p, limit: int = LIMIT, ids=None) -> dict:
    """Slice the head revision's exported STL on each candidate printer (cached per printer and presets)."""
    from . import cost, purpose
    if purpose.of(p) == "model":
        raise _err("This design is just a 3D model, so it is not sliced.", "Set its purpose to 3D printing to compare printers.")
    keys = st.keys(p)
    ex = st.read(p, "exports", keys["exports"])
    if not ex:
        raise _err("There is no current exported model to slice.", "Run the pipeline first (form run <project>).")
    stl = st.apath(p, "exports", keys["exports"]) / ex["files"]["stl"]["name"]
    prs = candidates(st.cfg, limit, ids)
    if not prs:
        raise _err("No printers are set up in any installed slicer.", "Open your slicer once and add a printer, then try again.", 404)
    prefs = cost.load_prefs(st.cfg)
    bbox = ex.get("print_bbox")
    todo = [x for x in prs if _fits(bbox, x.get("envelope_mm"))]
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        done = dict(zip([x["id"] for x in todo], pool.map(lambda x: _one(st, p, keys, stl, x, prefs), todo)))
    rows = []
    for x in prs:
        if x["id"] in done:
            rows.append(done[x["id"]])
        else:
            env = x.get("envelope_mm") or []
            rows.append({"id": x["id"], "printer": x["name"], "model": x.get("model") or "", "slicer": x["slicer"], "kind": x["kind"],
                         "nozzle_mm": x.get("nozzle_mm"), "envelope_mm": env, "time_s": None, "filament_g": None, "cost": None,
                         "status": "too_big", "reason": "The part (" + " × ".join(f"{v:.0f}" for v in bbox) + " mm) is larger than its bed ("
                         + " × ".join(f"{v:.0f}" for v in env) + " mm)."})
    ok = [r for r in rows if r["status"] == "ok" and r["time_s"] is not None]
    best = {}
    if ok:
        best["fastest"] = min(ok, key=lambda r: r["time_s"])["id"]
        g = [r for r in ok if r["filament_g"] is not None]
        if g:
            best["least_filament"] = min(g, key=lambda r: r["filament_g"])["id"]
        c = [r for r in ok if r["cost"] is not None]
        if c:
            best["cheapest"] = min(c, key=lambda r: r["cost"])["id"]
    out = {"project": p["id"], "rev": p["head"], "rows": rows, "best": best, "currency": prefs.get("currency", ""),
           "parts_note": "The design's parts are sliced together, as exported." if getattr(st.recipe(p), "solids", 1) > 1 else "",
           "evidence": "simulated", "note": NOTE}
    f = _summary_path(st, p)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out | {"cached": False}
