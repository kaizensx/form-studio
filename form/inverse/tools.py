"""The MCP tools of inverse design: inverse_design (search, or keep a point) and get_inverse_design (read, wait,
cancel). Registered by form/mcp_server.py; the same calls serve `form optimize pareto` (form/inverse/cli.py).
"""
from __future__ import annotations

import time

from mcp.server.mcpserver import Context

from . import design


def digest(r: dict | None, full: bool = False) -> dict | None:
    """What an agent reads of a stored search: the front in full, the other points by their state. full: everything."""
    if r is None or full:
        return r
    out = {k: r[k] for k in ("id", "rev", "headline", "evidence", "objectives", "constraints", "vary", "vary_chosen_by",
                             "study", "modal_study", "density", "rates", "budget", "method", "approximate", "stale",
                             "stale_why", "none_why", "current") if k in r}
    pts = {pt["index"]: pt for pt in r["points"]}
    keys = [x["metric"] for x in r["objectives"]] + [c["metric"] for c in r["constraints"]]

    def brief(pt):
        return {"index": pt["index"], "values": pt["values"], **{k: pt["metrics"].get(k) for k in dict.fromkeys(keys)},
                **({"evidence": pt["fea"].get("evidence")} if pt.get("fea") else {}),
                **({"close": pt["close"]} if pt.get("close") else {})}
    out["front"] = [{**brief(pts[i]), "keep": pts[i].get("keep")} for i in r["front"]]
    if r.get("current") is not None:
        cur = pts[r["current"]]
        out["current_design"] = {**brief(cur), "feasible": cur.get("feasible"), "on_front": cur.get("on_front"),
                                 "violations": cur.get("violations")}
    rest = [pt for pt in r["points"] if not pt.get("on_front")]
    out["other_points"] = {"feasible_but_dominated": sum(1 for pt in rest if pt.get("feasible")),
                           "missed_a_requirement": sum(1 for pt in rest if pt.get("ok") and not pt.get("feasible")),
                           "did_not_build": sum(1 for pt in rest if not pt.get("ok")),
                           "close": [brief(pt) for pt in rest if pt.get("close")][:6],
                           "reasons": sorted({v.split(" (is")[0] for pt in rest for v in pt.get("violations") or []})[:6]}
    out["chart"] = "full=True returns every point and the chart data (axes, points with their state, progress)."
    return out


def search_call(st, project: str, body: dict | None, run_now: bool = True, wait: bool = False) -> dict:
    p = st.load(project)
    if body is None:
        return {"runs": design.runs(st, p), "knobs": design.knobs(st.recipe(p), st.rev(p)["values"]),
                "next": "Give minimize / maximize and require to search; get_inverse_design reads a run."}
    spec = design.clean(st, p, body)
    if not run_now:
        return {"request": spec, "note": "Checked, not run."}
    if wait:
        return {"result": digest(design.run(st, project, body))}
    job = design.start(st, project, body)
    return {"job": job["id"], "state": "running", "request": {k: spec[k] for k in ("objectives", "constraints", "vary", "budget")},
            "next": f"get_inverse_design(project='{project}', wait_s=60)"}


def read_call(st, project: str, run: str = "", wait_s: float = 0, full: bool = False, cancel: bool = False) -> dict:
    p = st.load(project)
    job = design.running_job(st, project)
    if cancel:
        if job is None:
            return {"cancelled": False, "note": "No search is running."}
        st.jobs.request_cancel(job["id"])
        wait_s = max(wait_s, 5)
    t0 = time.time()
    while job is not None and time.time() - t0 < wait_s:
        if st.jobs[job["id"]]["state"] != "running":
            break
        time.sleep(0.2)
    out = {}
    if job is not None:
        j = st.jobs[job["id"]]
        out["job"] = {"id": j["id"], "state": j["state"], "error": j.get("error"),
                      "progress": (j.get("steps") or [{}])[0].get("progress")}
        if cancel:
            out["cancelled"] = j["state"] == "cancelled"
        if j["state"] == "running":
            out["state"] = "running"
            return out
    r = design.get(st, st.load(project), run)
    out["state"] = "never" if r is None else "stale" if r.get("stale") else "current"
    out["result"] = digest(r, full)
    out["runs"] = design.runs(st, p)
    return out


def register_tools(mcp, studio, run, RO, RW, origin) -> None:
    """Add inverse_design and get_inverse_design to the MCP server."""
    runner = run                                         # the tools below take an argument named run (a stored run's id)
    @mcp.tool(annotations=RW)
    async def inverse_design(project: str, minimize: list[str] | None = None, maximize: list[str] | None = None,
                             require: list[str] | None = None, vary: list[dict] | None = None, study: str = "",
                             modal_study: str = "", budget: dict | None = None, rates: dict | None = None,
                             costing: dict | None = None, run_now: bool = True, save_point: int | None = None, name: str = "", run: str = "",
                             ctx: Context = None) -> dict:
        """Inverse design: state what the part must do and get the variants that do it, each built by the kernel and
        studied by the real solver. "Survive 250 N at this face with a safety factor of 3, as light as possible" is a
        static strength_study on the design (the faces, the force, the material) plus
        minimize=["mass_g"], require=["fea.safety_factor >= 3"]. Two or three objectives (minimize=["mass_g",
        "fea.max_displacement_mm"]) give a Pareto front: variants among which one count only improves at the cost of
        another.
        vary: [{"key": "t", "min": 3, "max": 10}] (1-6 parameters; left out: the design's lengths that are not
        interfaces, at most four, named in the result).
        Metrics: mass_g (volume x the material's density, source stated), volume_cm3, width, depth, height,
        overhang_mm2 and contact_mm2 (support the best orientation needs), min_wall_mm, derived.<key>, statics.<key>;
        fea.safety_factor (the lower value: the stated error applied), fea.peak_von_mises_MPa,
        fea.max_displacement_mm from the static study (study="<id>" when the design has several);
        modal.frequency_Hz from a modal study (modal_study=); cost = mass x rates={"per_kg": x} (labelled assumed; no
        price is made up); cost.per_part = the cost per part to make it, from the sourced rates (estimate_cost's
        models on each candidate's volume and bounding box), costing={"process": "auto"|"fdm"|"sla"|"sls"|"mjf"|
        "lpbf"|"cnc", "quantity": 1000, "shop": ""}, labelled as its rates are (sourced, specified, assumed).
        budget: {"solves": 24, "seconds": 900, "evaluations": n}; the search stops at the first limit and says which.
        The search is surrogate-assisted (Gaussian processes, NSGA-II, hypervolume infill), and the surrogate only
        chooses what to evaluate: every reported point was built and, for a strength metric, solved. The front is
        approximate and the result says so. It runs in the background: read it with get_inverse_design(project,
        wait_s). Nothing in the design changes. Keep a point as a named variant with save_point=<index> (and name=,
        run= for an older search); save_variant with a point's values does the same. No arguments but project: the
        stored searches and the parameters that can be varied."""
        st = studio()
        by = origin(ctx).replace("agent:", "") or "agent"
        if save_point is not None:
            return await runner(design.save_point, st, project, run, int(save_point), name, by)
        body = None
        if minimize or maximize or require or vary:
            body = {"minimize": minimize or [], "maximize": maximize or [], "require": require or [], "vary": vary or [],
                    "study": study, "modal_study": modal_study, "budget": budget or {}, "rates": rates}
            if costing:
                body["costing"] = costing
        return await runner(search_call, st, project, body, run_now)

    @mcp.tool(annotations=RO)
    async def get_inverse_design(project: str, run: str = "", wait_s: float = 30, full: bool = False,
                                 cancel: bool = False) -> dict:
        """Read an inverse design search: running with its progress, or the stored result. Waits up to wait_s seconds
        for a running search. The result gives the front (each variant's parameter values, its objectives and
        requirements as measured, the evidence class of its study, and how to keep it), the design as it is for
        comparison, what the other candidates were (dominated, missed a requirement and which, did not build, "close":
        passing only at the central value of the safety factor), the budget used against its limits (strength solves,
        builds, seconds, why it stopped) and the statement that the front is approximate. full=True returns every
        evaluated point with all its metrics and the chart data: axes, one entry per point with its state (front,
        feasible, misses, close, failed) and the hypervolume after each round. A search made on other design source
        is stale. cancel=True stops a running search; nothing is stored for a cancelled one."""
        st = studio()
        return await runner(read_call, st, project, run, max(0.0, min(float(wait_s), 300.0)), full, cancel)
