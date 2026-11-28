"""The MCP tools of topology optimisation: topology_optimise (run), get_topology (read, wait, cancel, the density
frames) and apply_topology (keep the features, or the mesh body). Registered by form/mcp_server.py; the same calls
serve `form optimize topology` (form/inverse/cli.py).
"""
from __future__ import annotations

import time

from mcp.server.mcpserver import Context

from . import study as topo


def digest(r: dict | None, full: bool = False) -> dict | None:
    """What an agent reads of a stored run. full adds every iteration and the edit ops."""
    if r is None or full:
        return r
    keep = ("id", "rev", "study", "headline", "evidence", "outcome", "mode", "settings", "mesh", "resolution", "iterations",
            "converged", "stopped", "grey", "non_design_fraction", "mass_solid_part_g", "density_result", "comparison",
            "tries", "targets", "target_met", "target_why", "fallback", "budget", "method", "assumptions", "material",
            "stale", "stale_why", "frames_file")
    out = {k: r[k] for k in keep if k in r}
    rc = dict(r.get("reconstruction") or {})
    rc.pop("ops", None)
    out["reconstruction"] = rc
    lay = r.get("layout") or {}
    if lay:
        out["layout"] = {**{k: lay.get(k) for k in ("threshold", "grown_mm", "solid_fraction_predicted", "volume_fraction_asked",
                                                    "dropped", "tolerance_mm", "pixel_mm", "thickness_mm")},
                         "pockets": [{k: pk[k] for k in ("area_mm2", "corners", "centre")} for pk in lay.get("pockets") or []],
                         "ribs": {**{k: v for k, v in (lay.get("ribs") or {}).items() if k != "members"},
                                  "members": ((lay.get("ribs") or {}).get("members") or [])[:12]}}
    h = r.get("history") or []
    out["compliance"] = {"first": h[0]["compliance"] if h else None, "last": h[-1]["compliance"] if h else None,
                         "unit": "N mm", "note": "full=True returns every iteration"}
    return out


def run_call(st, project: str, opts: dict | None, wait: bool = False) -> dict:
    p = st.load(project)
    if opts is None:
        return {"runs": topo.runs(st, p), "settings": {k: {"default": v[0], "what": v[3]} for k, v in topo.SETTINGS.items()},
                "next": "Give volfrac (or mass_g, or safety_factor) to run; get_topology reads a run."}
    if wait:
        return {"result": digest(topo.run(st, project, opts))}
    job = topo.start(st, project, opts)
    return {"job": job["id"], "state": "running", "settings": topo.clean(opts),
            "next": f"get_topology(project='{project}', wait_s=120)"}


def read_call(st, project: str, run: str = "", wait_s: float = 0, full: bool = False, cancel: bool = False,
              frames: bool = False) -> dict:
    p = st.load(project)
    job = topo.running_job(st, project)
    if cancel:
        if job is None:
            return {"cancelled": False, "note": "No optimisation is running."}
        st.jobs.request_cancel(job["id"])
        wait_s = max(wait_s, 8)
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
            if frames:
                out["live"] = topo.live(st, p, j)
            return out
    p = st.load(project)
    r = topo.get(st, p, run)
    out["state"] = "never" if r is None else "stale" if r.get("stale") else "current"
    out["result"] = digest(r, full)
    out["runs"] = topo.runs(st, p)
    if r is not None and frames:
        f = topo.frames_path(st, p, r["id"])
        out["frames"] = topo._read(f) if f else None
    return out


def register_tools(mcp, studio, run, RO, RW, origin) -> None:
    """Add topology_optimise, get_topology and apply_topology to the MCP server."""
    runner = run                                         # the tools below take an argument named run (a stored run's id)
    @mcp.tool(annotations=RW)
    async def topology_optimise(project: str, volfrac: float | None = None, mass_g: float | None = None,
                                safety_factor: float | None = None, study: str = "", mode: str = "pockets",
                                pull: str | list[float] | None = None, h: float | None = None, rmin: float | None = None,
                                keep: float | None = None, rim: float | None = None, max_iter: int | None = None,
                                budget_s: float | None = None, tries: int | None = None, ctx: Context = None) -> dict:
        """Topology optimisation written back as editable features. The loads, supports and material are the design's
        static strength_study (study="<id>" when it has several). The layout is found by SIMP (density filter,
        optimality criteria) on the study's mesh; the faces that carry supports and loads, and a rim, stay solid.
        Then the density field is rebuilt as CAD: threshold, outlines, ribs measured, and one named feature per
        lightening pocket cut along the pull direction, with the parameters topo_inset (every rib wider by twice
        this), topo_fillet (pocket corner radius) and topo_web (a floor left under the pockets). The rebuilt design
        is built by the kernel and its strength study is solved again with the refining solver; the result sets its
        safety factor, displacement and mass beside the density field's own numbers and beside the part as it was.
        Target, one of: volfrac (the fraction of the volume that stays, 0.08-0.95, default 0.5), mass_g (grams), or
        safety_factor (the run is repeated at a higher fraction, up to `tries` times, until the rebuilt part's
        studied safety factor, lower value, meets it; volfrac is then the first try).
        mode "pockets" (default): a 2.5D layout along pull ("x", "y", "z" or a vector; left out: the part's thinnest
        direction). mode "free": a 3D layout, which is not written as features: it is offered as a mesh body.
        h: element size mm (default: the diagonal / 40, coarsened to at most 60,000 elements). rmin: smallest member
        mm (default 2 h). keep / rim: millimetres kept solid at the loaded and supported faces / along the side
        walls. max_iter (80), budget_s (240): the limits, stated in the result with the solves used.
        Stiffness is what is optimised (minimum compliance, one load case); strength is checked afterwards on the
        rebuilt part. When the features cannot be fitted, built or verified the result says why and offers the
        smoothed dense region as a mesh body, labelled as one. It runs in the background: get_topology(project,
        wait_s); nothing in the design changes until apply_topology. No arguments but project: the stored runs and
        the settings. One solid only. Needs the optional strength engine (setup_status)."""
        st = studio()
        opts = None
        given = {"volfrac": volfrac, "mass_g": mass_g, "safety_factor": safety_factor, "study": study or None,
                 "pull": pull, "h": h, "rmin": rmin, "keep": keep, "rim": rim, "max_iter": max_iter, "budget_s": budget_s,
                 "tries": tries}
        if any(v is not None for k, v in given.items() if k != "study") or mode != "pockets":
            opts = {k: v for k, v in given.items() if v is not None}
            opts["mode"] = mode
        return await runner(run_call, st, project, opts)

    @mcp.tool(annotations=RO)
    async def get_topology(project: str, run: str = "", wait_s: float = 60, full: bool = False, frames: bool = False,
                           cancel: bool = False) -> dict:
        """Read a topology optimisation: running with its progress (iteration, compliance), or the stored result.
        Waits up to wait_s seconds. The result gives the outcome ("features": rebuilt as pockets and verified;
        "features, not verified"; "mesh body"), the reconstruction (the features and parameters, the built solid's
        volume, the strength study of the rebuilt part with its evidence class and stated error, or why it failed),
        the comparison (rebuilt CAD against the density result and against the solid part: safety factor,
        compliance, displacement, mass, and whether the safety factors agree within the stated band), the density
        result's own numbers with how they were read, the layout (pockets, ribs with widths), the settings and mesh
        as used, the budget (seconds, solves, tries) and the resolution. frames=True adds the density field of every
        iteration (a picture across the pull direction, and the density at the vertices of the part's surface), or
        the newest picture while it runs; frames_file is its path. full=True adds every iteration's record and the
        edit ops. A run on an older revision is stale. cancel=True stops a running optimisation; nothing is stored."""
        st = studio()
        return await runner(read_call, st, project, run, max(0.0, min(float(wait_s), 600.0)), full, cancel, frames)

    @mcp.tool(annotations=RW)
    async def apply_topology(project: str, run: str = "", expect_head: int | None = None, as_new: str = "",
                             mesh_body: bool = False, ctx: Context = None) -> dict:
        """Keep a topology optimisation. Default: its lightening pockets become features of the design, as one
        revision (each can be suppressed, deleted or reshaped; topo_inset, topo_fillet and topo_web are parameters).
        as_new="<name>": in a copy of the design instead, the original untouched. mesh_body=True: the smoothed dense
        region is added to the design's references as an STL, labelled a mesh body; the design does not change.
        run: an older run (default: the newest). A run made on another revision is refused: run it again. The
        strength study is stale on the new revision until it is run there."""
        st = studio()
        by = origin(ctx) or "agent"
        return await runner(topo.apply, st, project, run, expect_head, as_new or False, mesh_body, by)
