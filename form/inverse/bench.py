"""The Bench entries of inverse design and topology optimisation (the Bench is form/studies.py).

Two entries among the studies of the Design chapter:

    inverse    "Inverse design"          the newest stored search: how many variants are on the front, the best one
    topology   "Topology optimisation"   the newest stored run: pockets, how much lighter, the studied safety factor

Each keeps its own record (`state_fn`): current when its newest run describes the design as it is, stale when the
design moved on, running with the job, never when nothing was run, unavailable without the strength engine. Both
need a static strength study to say what the part must carry; without one the entry says so and names the tool
that defines it. Running them from the Bench uses the defaults: lightest design that keeps a safety factor of 2,
and half the volume. The tools (inverse_design, topology_optimise) take the real requirement.
"""
from __future__ import annotations

INVERSE, TOPOLOGY = "inverse", "topology"
SF_DEFAULT = 2.0


def _static(ctx) -> tuple:
    """(study id or "", why not)."""
    from ..fea import study as fea_study
    try:
        return fea_study.pick_static(ctx.p, ""), ""
    except Exception as e:                               # noqa: BLE001 - no study, or several: said in the entry
        return "", f"{e} {getattr(e, 'hint', '')}".strip()


def _engine_missing(ctx) -> str:
    from ..fea import HOW_TO_GET, python
    return "" if python(ctx.st.cfg) is not None else HOW_TO_GET


def inverse_state(ctx) -> dict:
    from . import design
    job = design.running_job(ctx.st, ctx.p["id"])
    if job is not None:
        return {"state": "running", "job": job["id"], "progress": (job.get("steps") or [{}])[0].get("progress")}
    r = design.get(ctx.st, ctx.p)
    if r is None:
        sid, why = _static(ctx)
        out = {"state": "never", "headline": "",
               "why": "No search yet. inverse_design takes what the part must do (objectives and requirements) and "
                      "returns the variants that do it, each built and studied." + ("" if sid else " " + why)}
        if _engine_missing(ctx):
            out.update({"state": "unavailable", "state_before": "never", "why": _engine_missing(ctx)})
        return out
    out = {"state": "stale" if r.get("stale") else "current", "rev": r.get("rev"), "headline": r.get("headline"),
           "evidence": r.get("evidence"), "detail": r.get("approximate"),
           "data": {"run": r["id"], "chart": r.get("chart"), "budget": r.get("budget"), "objectives": r.get("objectives"),
                    "constraints": r.get("constraints")}}
    if r.get("stale"):
        out["why"] = r.get("stale_why")
    return out


def inverse_run(ctx) -> dict:
    from . import design
    sid, why = _static(ctx)
    if not sid:
        from ..studio import StudioError
        raise StudioError("Inverse design from the Bench needs the design's static strength study: " + why,
                          "Define one with strength_study, or call inverse_design with objectives that need none.", status=409)
    r = design.run(ctx.st, ctx.p["id"], {"minimize": ["mass_g"], "require": [f"fea.safety_factor >= {SF_DEFAULT:g}"], "study": sid})
    return {"headline": r["headline"], "evidence": r["evidence"], "detail": r["approximate"],
            "data": {"run": r["id"], "chart": r["chart"], "budget": r["budget"]}}


def topology_state(ctx) -> dict:
    from ..topo import study as topo
    job = topo.running_job(ctx.st, ctx.p["id"])
    if job is not None:
        return {"state": "running", "job": job["id"], "progress": (job.get("steps") or [{}])[0].get("progress")}
    r = topo.get(ctx.st, ctx.p)
    if r is None:
        sid, why = _static(ctx)
        out = {"state": "never", "headline": "",
               "why": "No run yet. topology_optimise finds where material carries the load and writes the rest as "
                      "lightening pockets, features of the design." + ("" if sid else " " + why)}
        if _engine_missing(ctx):
            out.update({"state": "unavailable", "state_before": "never", "why": _engine_missing(ctx)})
        return out
    out = {"state": "stale" if r.get("stale") else "current", "rev": r.get("rev"), "headline": r.get("headline"),
           "evidence": r.get("evidence"), "detail": r.get("resolution"),
           "data": {"run": r["id"], "outcome": r.get("outcome"), "comparison": r.get("comparison"), "budget": r.get("budget"),
                    "frames_file": r.get("frames_file"), "fallback": r.get("fallback")}}
    if r.get("stale"):
        out["why"] = r.get("stale_why")
    return out


def topology_run(ctx) -> dict:
    from ..topo import study as topo
    r = topo.run(ctx.st, ctx.p["id"], {})
    return {"headline": r["headline"], "evidence": r["evidence"], "detail": r["resolution"],
            "data": {"run": r["id"], "outcome": r["outcome"], "comparison": r["comparison"], "budget": r["budget"],
                     "frames_file": r["frames_file"]}}


def register_studies(register) -> None:
    """The Bench's hook for later waves (form/studies.py PROVIDERS)."""
    from ..studies import Study
    register(Study(
        id=INVERSE, group="study", label="Inverse design",
        doc="What the part must do, and the variants that do it: a search of the design's own parameters, every "
            "reported variant built by the kernel and studied by the real solver, on a Pareto front.",
        evidence="simulated (FEA) on every point", run=inverse_run, state_fn=inverse_state,
        needs=("step",), inputs=("the design's source", "its parameters' ranges", "the strength study", "the budget"),
        by="engine", app="inverse", tool="inverse_design", heavy=True, order=26, extra={"chapter": "design"}))
    register(Study(
        id=TOPOLOGY, group="study", label="Topology optimisation",
        doc="Where material carries the load, found on the strength study's mesh and written back as lightening "
            "pockets: named features with parameters, studied again as real CAD.",
        evidence="simulated (FEA) on the rebuilt CAD", run=topology_run, state_fn=topology_state,
        needs=("step",), inputs=("geometry", "the strength study", "the material", "engine"),
        by="engine", app="topology", tool="topology_optimise", heavy=True, order=27, extra={"chapter": "design"}))
