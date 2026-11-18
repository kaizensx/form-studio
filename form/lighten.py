"""Make it lighter: search real changes that reduce a design's mass while every check that passed still passes.

    from form import lighten
    r = lighten.search(st, p)            # {"baseline": {...}, "candidates": [{...}], ...}
    lighten.apply(st, p, r["candidates"][0])

Two kinds of change are tried, and nothing is estimated:

* Geometry: the design's own wall, thickness and lightening-pocket parameters (never an interface parameter). A
  ladder of values toward the lighter end is built by the kernel in one batch (the optimizer's `evaluate` call,
  form/optimize.py); candidates that move an interface dimension are dropped. The lightest few are then taken
  through the real pipeline (solid, exports, checks, slice) under their own artifact keys, so their checks are the
  checks and their grams are the slicer's. A candidate is kept only when every check that passed on the head
  revision still passes.
* Print settings: a lower infill and one wall fewer over the slicer's process preset, sliced for real on the
  design. The solid does not change, so the computed checks are the head's own.

Nothing is committed by search. apply() commits a geometry candidate as a new revision (its artifacts are already
built under the keys the new revision will have) and/or sets the design's print settings.
"""
from __future__ import annotations

import copy
import json
import re

THIN = re.compile(r"(wall|thick|shell|floor|skin|rib|web|plate|_t$|^t_|_t_)", re.I)
POCKET = re.compile(r"(pocket|lighten|cutout|window|hollow|relief)", re.I)
FRACTIONS = (0.25, 0.5, 0.75, 1.0)
DENSITY_ASSUMED = 1.24          # g/cm³, the same as the optimizer's solid_mass_g, when the slicer states none
NOTE = ("Every candidate was built by the kernel, and the ones shown went through the real checks; slicer grams are each "
        "slice's simulation. Computed mass is the solid's volume × the filament density. Search is a ladder toward the "
        "lighter end of each parameter's range, not a proof of the lightest possible design.")


def _err(msg, hint="", status=409):
    from .studio import StudioError
    return StudioError(msg, hint, status=status)


def knobs(recipe, values: dict) -> list:
    """The parameters that can make the part lighter: [{key, label, unit, from, to, direction}]."""
    out = []
    for k, v in values.items():
        try:
            sp = recipe.spec(k)
        except Exception:
            continue
        if sp.group in ("interface", "brief") or sp.unit not in ("mm", ""):
            continue
        name = f"{k} {sp.label}"
        if POCKET.search(name) and sp.max > v:
            out.append({"key": k, "label": sp.label, "unit": sp.unit, "from": v, "to": sp.max, "step": sp.step or 0.1})
        elif THIN.search(name) and sp.min < v:
            out.append({"key": k, "label": sp.label, "unit": sp.unit, "from": v, "to": sp.min, "step": sp.step or 0.1})
    return out[:4]


def _snap(k, x):
    st = k["step"]
    lo, hi = sorted((k["from"], k["to"]))
    x = min(hi, max(lo, x))
    return round(round(x / st) * st, 6)


def ladder(ks: list) -> list:
    """Each parameter alone at a quarter, half, three quarters and all the way toward its lighter end, then all of
    them together at each step."""
    pts, seen = [], set()
    def add(ch):
        key = tuple(sorted(ch.items()))
        if ch and key not in seen:
            seen.add(key)
            pts.append(ch)
    for f in FRACTIONS:
        for k in ks:
            v = _snap(k, k["from"] + (k["to"] - k["from"]) * f)
            if abs(v - k["from"]) > 1e-9:
                add({k["key"]: v})
    if len(ks) > 1:
        for f in FRACTIONS:
            ch = {k["key"]: _snap(k, k["from"] + (k["to"] - k["from"]) * f) for k in ks}
            add({a: b for a, b in ch.items() if abs(b - next(k["from"] for k in ks if k["key"] == a)) > 1e-9})
    return pts


def _checks(st, p, keys) -> list:
    ch = st.read(p, "checks", keys["checks"])
    return ch["checks"] if ch else []


def _density(s: dict) -> tuple:
    d = (s.get("summary") or {}).get("density") if s.get("available") else None
    return (float(d), "the filament preset") if d else (DENSITY_ASSUMED, "assumed (PLA)")


def _slice_meta(st, p, keys) -> dict | None:
    try:
        return st.read(p, "slice", keys["slice"])
    except Exception:
        return None


def build(st, p, changes: dict | None = None, overrides: dict | None = None, rev_note: str = "") -> dict:
    """Take a candidate through the real pipeline without committing it: a copy of the design in memory whose head is
    the candidate, with every step written under its own key (so a later commit finds them already made)."""
    from .studio import NODES, StudioError
    from . import slicer as slicer_mod
    q = copy.deepcopy(p)
    head = st.rev(q)
    if changes:
        from .studio import H
        n = max(r["n"] for r in q["revisions"]) + 1
        vals = {**head["values"], **{k: float(v) for k, v in changes.items()}}
        # the values as the kernel returns them, exactly as commit() stores them, so the keys match after a commit
        vals = st._k("summary", key="pv-" + H(st.rid(q), vals), recipe_id=st.rid(q), values=vals, tol=0.06, p=q)["values"]
        q["revisions"].append({**copy.deepcopy(head), "n": n, "parent": head["n"], "values": vals,
                               "note": rev_note or "candidate", "origin": "lighten"})
        q["head"] = n
    if overrides is not None:
        if overrides:
            q["print_overrides"] = {**(q.get("print_overrides") or {}), **overrides}
        else:
            q.pop("print_overrides", None)
    rev, keys = st.rev(q), st.keys(q)
    name = f"{q['id']}_r{rev['n']:02d}"
    want = list(NODES)
    if not st.slice_mode(q)["on"]:
        want.remove("slice")
    out = {"slice_error": None}
    for node in want:
        if st.read(q, node, keys[node]) is not None:
            continue
        try:
            getattr(st, f"_make_{node}")(q, rev, keys, name)
        except (slicer_mod.SlicerBlocked, slicer_mod.SlicerFailed) as e:
            out["slice_error"] = str(e)
            break
        except StudioError as e:
            if node == "slice":
                out["slice_error"] = str(e)
                break
            raise
    geo = st.read(q, "geometry", keys["geometry"]) or {}
    s = st.slicer_info(p=q)
    dens, dsrc = _density(s)
    sm = _slice_meta(st, q, keys) if "slice" in want else None
    out.update(values=rev["values"], keys=keys, checks=_checks(st, q, keys),
               volume_cm3=round(geo.get("volume_mm3", 0) / 1000, 3) if geo else None,
               mass_g=round(geo["volume_mm3"] / 1000 * dens, 2) if geo else None, density=dens, density_source=dsrc,
               slice_g=sm.get("filament_g") if sm else None, slice_time_s=sm.get("time_s") if sm else None,
               sliced="slice" in want, print_overrides=q.get("print_overrides") or {}, process=(s.get("presets") or {}).get("process", {}).get("name", ""))
    return out


def _compare(base_checks: list, cand_checks: list) -> tuple:
    by = {c["id"]: c for c in cand_checks}
    rows, broken = [], []
    for c in base_checks:
        n = by.get(c["id"])
        row = {"id": c["id"], "label": c["label"], "before": c["status"], "before_value": c["value"],
               "after": n["status"] if n else "MISSING", "after_value": n["value"] if n else "", "evidence": c.get("evidence", "")}
        rows.append(row)
        if c["status"] == "PASS" and row["after"] != "PASS":
            broken.append(f"{c['label']}: {row['after_value'] or row['after']}")
    return rows, broken


def _interfaces(st, p) -> dict:
    try:
        return {d["key"]: d["value"] for d in st.head_summary(p)["derived"] if d.get("interface")}
    except Exception:
        return {}


def search(st, p, builds: int = 4, ladder_max: int = 24, settings: bool = True) -> dict:
    """Candidates that are lighter than the head revision and keep every passing check passing."""
    from .studio import NODES
    if st.read(p, "checks", st.keys(p)["checks"]) is None:          # the baseline is the head's real checks
        job = st.run_sync(p["id"])
        p = st.load(p["id"])
        if st.read(p, "checks", st.keys(p)["checks"]) is None:
            bad = next((s.get("error", {}).get("message") for s in job.get("steps", []) if s.get("state") == "failed"), "")
            raise _err("The checks for this revision could not be made, so there is nothing to keep passing.", bad or "Run the pipeline first.")
    base = build(st, p)
    base.update(rev=p["head"])
    passed = [c["id"] for c in base["checks"] if c["status"] == "PASS"]
    recipe = st.recipe(p)
    head = st.rev(p)["values"]
    ks = knobs(recipe, head)
    iface = _interfaces(st, p)
    tried, rejected, cands = 0, [], []

    # 1. geometry: a ladder built by the kernel in one batch, then the lightest few through the real checks
    if ks:
        pts = ladder(ks)[:ladder_max]
        rows = st._k("evaluate", timeout=240, recipe_id=st.rid(p), base=head, candidates=pts, p=p)
        tried = len(rows)
        lighter = []
        for r in rows:
            if not r["ok"]:
                rejected.append({"values": r["changes"], "why": r["error"]["message"]})
                continue
            m = r["metrics"]
            moved = [k for k, v in iface.items() if m.get("derived." + k) is not None and abs(m["derived." + k] - v) > 1e-6]
            if moved:
                rejected.append({"values": r["changes"], "why": "moves an interface: " + ", ".join(moved)})
                continue
            if base["volume_cm3"] is not None and m["volume_cm3"] < base["volume_cm3"] - 1e-6:
                lighter.append(r)
        lighter.sort(key=lambda r: r["metrics"]["volume_cm3"])
        kept = 0
        for r in lighter:
            if builds <= 0 or kept >= 2:
                break
            builds -= 1
            c = build(st, p, r["changes"])
            rows_, broken = _compare(base["checks"], c["checks"])
            entry = {"kind": "geometry", "changes": r["changes"], "labels": {k["key"]: k["label"] for k in ks},
                     "mass_g": c["mass_g"], "volume_cm3": c["volume_cm3"], "slice_g": c["slice_g"], "slice_time_s": c["slice_time_s"],
                     "slice_error": c["slice_error"], "checks": rows_, "keeps_checks": not broken, "broken": broken}
            if broken:
                rejected.append({"values": r["changes"], "why": "; ".join(broken), "mass_g": c["mass_g"]})
                continue
            kept += 1
            cands.append(entry)

    # 2. print settings: lower infill, one wall fewer, sliced for real; the solid (and so the checks) is the head's
    s = st.slicer_info(p=p)
    summ = s.get("summary") or {}
    if settings and base["sliced"] and s.get("available") and base["slice_g"] is not None:
        def num(x):
            try:
                return float(str(x[0] if isinstance(x, list) else x).strip().rstrip("%"))
            except (TypeError, ValueError):
                return None
        inf, walls = num(summ.get("infill")), num(summ.get("walls"))
        trials = []
        if inf is not None and inf > 5:
            trials.append({"infill": max(5.0, float(round(inf / 2)))})
        if walls is not None and walls >= 3:
            trials.append({"walls": walls - 1})
        for ov in trials:
            c = build(st, p, None, ov)
            if c["slice_g"] is None:
                rejected.append({"settings": ov, "why": c["slice_error"] or "the slicer gave no weight"})
                continue
            if c["slice_g"] >= base["slice_g"]:
                rejected.append({"settings": ov, "why": f"not lighter in the slicer ({c['slice_g']:g} g)"})
                continue
            rows_, _ = _compare(base["checks"], c["checks"])
            cands.append({"kind": "settings", "settings": ov, "was": {k: (inf if k == "infill" else walls) for k in ov},
                          "mass_g": c["mass_g"], "volume_cm3": c["volume_cm3"], "slice_g": c["slice_g"], "slice_time_s": c["slice_time_s"],
                          "slice_error": None, "checks": rows_, "keeps_checks": True, "broken": [], "process": c["process"]})

    # 3. both: the lightest geometry that kept its checks, sliced with the lightest print settings
    geo = [c for c in cands if c["kind"] == "geometry"]
    sets = [c for c in cands if c["kind"] == "settings"]
    if geo and sets:
        g, sv = min(geo, key=lambda c: (c["slice_g"] if c["slice_g"] is not None else 1e18, c["mass_g"])), min(sets, key=lambda c: c["slice_g"])
        c = build(st, p, g["changes"], sv["settings"])
        rows_, broken = _compare(base["checks"], c["checks"])
        if not broken and c["slice_g"] is not None:
            cands.append({"kind": "both", "changes": g["changes"], "labels": g["labels"], "settings": sv["settings"], "was": sv["was"],
                          "mass_g": c["mass_g"], "volume_cm3": c["volume_cm3"], "slice_g": c["slice_g"], "slice_time_s": c["slice_time_s"],
                          "slice_error": None, "checks": rows_, "keeps_checks": True, "broken": [], "process": c["process"]})

    for i, c in enumerate(cands):
        c["id"] = f"c{i + 1}"
        c["saves_mass_g"] = round(base["mass_g"] - c["mass_g"], 2) if base["mass_g"] is not None and c["mass_g"] is not None else None
        c["saves_slice_g"] = round(base["slice_g"] - c["slice_g"], 2) if base["slice_g"] is not None and c["slice_g"] is not None else None
    cands.sort(key=lambda c: -(c["saves_slice_g"] if c["saves_slice_g"] is not None else (c["saves_mass_g"] or 0)))
    out = {"project": p["id"], "rev": p["head"],
            "baseline": {"mass_g": base["mass_g"], "volume_cm3": base["volume_cm3"], "slice_g": base["slice_g"],
                         "slice_time_s": base["slice_time_s"], "sliced": base["sliced"], "slice_error": base["slice_error"],
                         "checks": [{"id": c["id"], "label": c["label"], "status": c["status"], "value": c["value"]} for c in base["checks"]],
                         "passed": len(passed), "density": base["density"], "density_source": base["density_source"],
                         "settings": {k: summ.get(k) for k in ("infill", "walls")} if s.get("available") else {}},
            "knobs": [{k: x[k] for k in ("key", "label", "unit", "from", "to")} for x in ks],
            "built": tried, "candidates": cands, "rejected": rejected[:8],
            "none_why": "" if cands else ("This design exposes no wall, thickness or pocket parameter, and no slicer is set up to try "
                                          "print settings." if not ks and not base["sliced"] else
                                          "Every lighter candidate broke a check that passes now, or was not lighter."),
            "evidence": "computed geometry and checks; slicer weights are simulated", "note": NOTE}
    f = _cache_path(st, p)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out | {"cached": False}


def _cache_path(st, p):
    k = st.keys(p)
    return st.dir(p["id"]) / "artifacts" / "side" / f"lighten-{k['checks']}-{k['slice']}.json"


def cached(st, p) -> dict | None:
    """The last search for exactly this revision and these presets, if there is one."""
    f = _cache_path(st, p)
    return json.loads(f.read_text(encoding="utf-8")) | {"cached": True} if f.is_file() else None


def apply(st, p, cand: dict, expect_head: int | None = None, origin: str = "user") -> dict:
    """Keep a candidate: geometry changes become a new revision; print settings become the design's own."""
    out = {"head": p["head"]}
    if cand.get("changes"):
        labels = cand.get("labels") or {}
        note = "Lighter: " + ", ".join(f"{labels.get(k, k)} → {v:g}" for k, v in cand["changes"].items())
        p = st.commit(p, {k: float(v) for k, v in cand["changes"].items()}, note=note, origin=origin, expect_head=expect_head)
        out["head"] = p["head"]
    if cand.get("settings"):
        st.settings(p, {"print_overrides": {**(p.get("print_overrides") or {}), **cand["settings"]}})
        out["print_overrides"] = st.load(p["id"]).get("print_overrides")
    return out


def apply_values(st, p, changes: dict | None, settings: dict | None, expect_head=None, origin="user") -> dict:
    """apply() from the bare values a person or an agent picked (no search result in hand)."""
    if not changes and not settings:
        raise _err("Nothing to apply.", "Pick a candidate from the search first.")
    return apply(st, p, {"changes": changes or {}, "settings": settings or {}}, expect_head, origin)
