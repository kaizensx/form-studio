"""The Bench entries of print physics (the Bench is form/studies.py; this module is named in studies.PROVIDERS).

Check (studies):

    print.orient     the Pareto front of print orientations: support, time, strength, surface, tip-over
    print.strength   the design's layer-aware strength studies (kept and keyed by form/fea/study.py)
    print.warp       the warp-risk indicator in the print orientation

Make (routes):

    print.orientation   the orientation the person picked, written to the print setup; it says whether that
                        orientation is on the current front

Each is keyed like every other entry: by the geometry, and by what else it reads (the print setup's orientation, the
material, the slicer preset), so a commit or a new setup makes it stale by construction.
"""
from __future__ import annotations


def _orient_key(ctx):
    from . import orient
    return orient.result_key(ctx.st, ctx.p)


def _orient_result(r: dict) -> dict:
    from . import orient
    return {"headline": orient.headline(r), "evidence": "computed, modelled" + (", simulated" if (r.get("verification") or {}).get("ran") else ""),
            "detail": orient.SCORE_NOTE, "data": orient.digest(r)}


def _orient_run(ctx):
    from . import orient
    o = orient.stored_options(ctx.p)
    return _orient_result(orient.run(ctx.st, ctx.p, cosmetic=o.get("cosmetic"), study=o.get("study") or "",
                                     load_direction=o.get("load_direction"), level=o.get("level") or 2,
                                     critical_deg=o.get("critical_deg"), settings=o.get("settings"), free=bool(o.get("free")),
                                     remember=False, strict=False))


def _orient_probe(ctx):
    from . import orient
    if orient.cached(ctx.st, ctx.p) is None:
        return None
    return _orient_run(ctx)                              # the search is cached: this only ranks it


def _warp_key(ctx):
    from ..studio import H
    from .. import materials
    from . import VERSION
    s = ctx.st.slicer_info(p=ctx.p)
    proc = ((s.get("presets") or {}).get("process") or {}) if s.get("available") else {}
    return H("print-warp", VERSION, ctx.keys["geometry"], ctx.p["orientation"], materials.resolved(ctx.p).get("material"),
             proc.get("sha"))


def _warp_run(ctx):
    from . import warp
    r = warp.run(ctx.st, ctx.p)
    return {"headline": warp.headline(r), "evidence": r.get("evidence") or "modelled",
            "detail": r.get("not") or r.get("note") or "",
            "data": {k: r.get(k) for k in ("index", "band", "raised_by", "orientation", "material", "by_orientation", "inputs")}}


def _strength_state(ctx) -> dict:
    from ..fea import HOW_TO_GET, python
    from ..fea import bench as fbench
    from ..fea import study
    rows = [study.state(ctx.st, ctx.p, d["id"]) for d in study.definitions(ctx.p) if d.get("layers")]
    if not rows:
        out = {"state": "never", "headline": "", "studies": [],
               "why": "No layer-aware strength study is defined for this design yet (print_strength: the loads of a "
                      "static strength study, solved for the printed, layered material)."}
        if python(ctx.st.cfg) is None:
            out.update({"state": "unavailable", "state_before": "never", "why": HOW_TO_GET})
        return out
    worst = min(rows, key=lambda r: fbench.ORDER.index(r["state"]) if r["state"] in fbench.ORDER else 0)
    out = {"state": worst["state"], "studies": rows, "rev": worst.get("rev") or worst.get("last_rev"), "headline": ""}
    best = None
    for r in rows:
        if r["state"] != "current":
            continue
        res = study.result(ctx.st, ctx.p, r["id"]).get("result") or {}
        sf = (res.get("safety_factor") or {}).get("value")
        if best is None or (sf is not None and (best[0] is None or sf < best[0])):
            best = (sf, res)
    if best:
        out.update({"headline": best[1].get("headline") or "", "evidence": (best[1].get("layers") or {}).get("evidence") or best[1].get("evidence")})
    else:
        first = next((r for r in rows if r.get("headline")), None)
        if first:
            out.update({"headline": first["headline"], "evidence": first.get("evidence") or ""})
    if worst["state"] in ("stale", "failed", "unavailable"):
        out["why"] = worst.get("why") or (worst.get("error") or {}).get("message") or ""
    if worst["state"] == "running":
        out["job"] = worst.get("job")
    return out


def _strength_run(ctx):
    from ..fea import study
    pid = ctx.p["id"]
    for d in study.definitions(ctx.p):
        if d.get("layers") and study.state(ctx.st, ctx.p, d["id"])["state"] in ("never", "stale", "failed"):
            study.run(ctx.st, pid, d["id"])
    s = _strength_state(type(ctx)(ctx.st, ctx.st.load(pid)))
    return {"headline": s.get("headline") or "", "evidence": s.get("evidence") or "simulated (FEA, layered material)",
            "detail": f"{len(s.get('studies') or [])} layer-aware studies", "data": {"studies": s.get("studies")}}


def _orientation_live(ctx) -> dict:
    """Make: the orientation in the print setup, and whether it is on the current front. Read when listed: the
    setup is always known, the front only after a search of this revision."""
    from .. import analysis
    from . import orient
    o = ctx.p["orientation"]
    picked = ((ctx.p.get("print") or {}).get("orient") or {}).get("picked") or {}
    head = analysis.orientation_label(o)
    raw = orient.cached(ctx.st, ctx.p)
    detail = "No orientation search has been run for this revision yet (Orientation front, or print_orient)."
    if raw is not None:
        row = next((r for r in raw.get("rows") or [] if r.get("current")), None)
        n = sum(1 for r in raw.get("rows") or [] if r.get("on_front"))
        if row is not None:
            on = bool(row.get("on_front"))
            head += " · on the front" if on else " · not on the front"
            detail = (f"One of {n} orientations no other beats on every objective." if on else
                      f"Another orientation is at least as good on every objective and better on one ({n} on the front).")
    if picked.get("orientation") == o:
        head += " · picked"
    return {"headline": head, "evidence": "a person's pick" if picked.get("orientation") == o else "the print setup",
            "detail": detail, "data": {"orientation": o, "picked": picked or None}}


def register_studies(register) -> None:
    from ..studies import Study
    register(Study(
        id="print.orient", group="study", label="Orientation front",
        doc="The print orientations no other one beats: support volume and contact, print time, strength along the "
            "load, stairs on cosmetic faces and tip-over, searched over the whole sphere of directions.",
        evidence="computed, modelled", run=_orient_run, probe=_orient_probe, key=_orient_key, needs=("print", "step"),
        inputs=("geometry", "printer bed", "slicer preset", "orientation", "cosmetic faces", "strength study"),
        app="printOrient", tool="print_orient", heavy=True, order=45))
    register(Study(
        id="print.strength", group="study", label="Strength as printed",
        doc="A strength study with a layered material in the print orientation: the safety factor across the layers "
            "and in them, and how it changes with the orientation.",
        evidence="simulated (FEA, linear static, layered material)", run=_strength_run, state_fn=_strength_state,
        needs=("print", "step"), inputs=("geometry", "material", "orientation", "supports and loads", "engine"),
        app="strength", tool="print_strength", heavy=True, order=25))
    register(Study(
        id="print.warp", group="study", label="Warp risk",
        doc="A first-order indicator from the material's shrinkage on cooling, the first layer, the longest span, the "
            "height and the corners. An indicator, not a predicted lift.",
        evidence="modelled (Wang, Xi and Jin 2007; uncalibrated)", run=_warp_run, key=_warp_key, needs=("print", "step"),
        inputs=("geometry", "orientation", "material", "layer height"), app="printWarp", tool="print_warp", order=47))
    register(Study(
        id="print.orientation", group="route", label="Print orientation",
        doc="The orientation written to the print setup, and whether it is on the front of the last search. The pick is "
            "a person's.",
        evidence="the print setup", run=_orientation_live, live=True, needs=("print",),
        inputs=("geometry", "orientation"), app="printOrient", tool="print_orient", order=8))
