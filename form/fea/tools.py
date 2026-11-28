"""The MCP tools of the strength studies: strength_study (define and run) and get_strength_study (read, wait, cancel).

Registered by form/mcp_server.py with register_tools(...). The same calls serve `form strength` (form/fea/cli.py).
"""
from __future__ import annotations

import time

from mcp.server.mcpserver import Context

from . import study as study_mod


def digest(r: dict, full: bool = False) -> dict:
    """What an agent reads of a stored result: the verdict, how it is known and what limits it. full adds the
    convergence levels and the whole record."""
    if r is None:
        return None
    if full:
        return r
    keep = ("id", "name", "kind", "rev", "headline", "evidence", "how_known", "converged", "not_converged_because",
            "stopped_because", "stale", "model", "assumptions", "frame", "seconds",
            "max_displacement_mm", "max_displacement_at", "peak_von_mises_MPa", "peak_at", "safety_factor",
            "safety_factor_withheld", "discretisation_error", "singularities", "equilibrium", "loads", "hand_estimate",
            "frequencies_Hz", "modes", "free_body", "mass_g", "load_factor", "load_factor_extrapolated", "load_factors",
            "thermal", "t_max_C", "t_min_C", "t_max_at", "t_min_at", "heat_through_W", "conditions", "heat_balance",
            "meaning", "mesh", "materials", "material_notes", "units", "faces", "versions")
    out = {k: r[k] for k in keep if k in r}
    conv = r.get("convergence") or {}
    out["convergence"] = {"method": conv.get("method"), "tolerance": conv.get("tolerance"),
                          "levels": [{k: lv.get(k) for k in ("level", "unknowns", "h_mean_mm", "max_displacement_mm",
                                                               "peak_von_mises_MPa", "strain_energy_mJ", "error_indicator",
                                                               "frequencies_Hz", "load_factors", "t_max_C", "t_min_C",
                                                               "heat_through_W", "seconds") if k in lv}
                                     for lv in conv.get("levels") or []]}
    return out


def study_call(st, project: str, definition: dict | None, study: str = "", run: bool = True, force: bool = False,
               remove: bool = False, by: str = "agent") -> dict:
    """Define and/or start; returns {"study", "state", "job"?} or the listing."""
    p = st.load(project)
    if remove:
        return study_mod.remove(st, p, study)
    if definition is None and not study:
        return {"studies": study_mod.listing(st, p), "engine_installed": study_mod.python(st.cfg) is not None,
                "next": "Give fixtures and loads to define a study; study=\"<id>\" runs one again."}
    if definition is not None:
        d = study_mod.define(st, p, definition, by=by, sid=study or None)
        p = st.load(project)
    else:
        d = study_mod.get(p, study)
    out = {"study": d, "state": study_mod.state(st, p, d["id"])}
    if not run:
        return out
    if out["state"]["state"] == "current" and not force:
        out["result"] = digest(study_mod.result(st, p, d["id"]).get("result"))
        out["note"] = "A current result is stored for this revision and these inputs; force=True solves it again."
        return out
    job = study_mod.start(st, project, d["id"], force=force)
    out["job"] = job["id"]
    out["state"] = {**out["state"], "state": "running", "job": job["id"]}
    out["next"] = f"get_strength_study(project='{project}', study='{d['id']}', wait_s=60)"
    return out


def read_call(st, project: str, study: str, wait_s: float = 0, field: bool = False, full: bool = False,
              cancel: bool = False) -> dict:
    p = st.load(project)
    study_mod.get(p, study)
    job = study_mod._running_job(st, project, study)
    if cancel:
        if job is None:
            return {"cancelled": False, "note": "The study is not running."}
        st.jobs.request_cancel(job["id"])
        wait_s = max(wait_s, 5)
    t0 = time.time()
    while job is not None and time.time() - t0 < wait_s:
        if st.jobs[job["id"]]["state"] != "running":
            break
        time.sleep(0.2)
    p = st.load(project)
    r = study_mod.result(st, p, study)
    out = {"study": r["study"], "state": r["state"], "result": digest(r.get("result"), full)}
    if job is not None:
        j = st.jobs[job["id"]]
        out["job"] = {"id": j["id"], "state": j["state"], "error": j.get("error"),
                      "progress": (j.get("steps") or [{}])[0].get("progress")}
        if cancel:
            out["cancelled"] = j["state"] == "cancelled"
    path = study_mod.field_path(st, p, study)
    if path is not None:
        out["field_file"] = str(path)
        if field:
            out["field"] = study_mod.field(st, p, study)
    return out


def register_tools(mcp, studio, run, RO, RW, origin) -> None:
    """Add strength_study and get_strength_study to the MCP server."""
    @mcp.tool(annotations=RW)
    async def strength_study(project: str, kind: str = "static", fixtures: list[dict] | None = None,
                             loads: list[dict] | None = None, material: str | dict | None = None,
                             materials: dict | None = None, modes: int | None = None, mesh: dict | None = None,
                             name: str = "", study: str = "", run_now: bool = True, force: bool = False,
                             remove: bool = False, thermal: list[dict] | None = None, reference_C: float = 20.0,
                             ctx: Context = None) -> dict:
        """Run a strength study on the design: will it hold? Finite elements on the B-rep (quadratic tetrahedra, Netgen
        mesh), refined until the answer stops changing, with the discretisation error stated. kind: "static" (stress,
        displacement, safety factor against the material's yield), "modal" (natural frequencies; no supports = free
        body; loads ignored), "buckling" (the factor on the loads at which it buckles), "thermal" (steady heat conduction:
        temperatures and the heat through the part) or "thermal_stress" (the stress from that temperature field, with
        any loads; reference_C is the temperature at which the part is stress free).
        thermal: [{"type": "temperature", "faces": [...], "value_C": 80}, {"type": "convection", "faces": [...],
        "h_W_m2K": 10, "ambient_C": 20}, {"type": "heat", "faces": [...], "value_W": 5}, {"type": "heat_flux", "faces":
        [...], "value_W_m2": 2000}]; a face with none is insulated. A heat study needs the material's conductivity
        ("k_W_mK"), thermal stress also its expansion ("cte_per_K").
        Faces are picked as points on the part, [x, y, z] in design millimetres, each part as printed (as for
        analyze_selection, which shows the face a point lands on).
        fixtures: [{"type": "fixed" | "roller" | "pin" | "hold", "faces": [[x, y, z], ...]}]. fixed: no movement. roller: slides
        in the face, cannot leave it (a symmetry plane). pin: a cylindrical face that may turn about its axis. hold:
        no movement along "directions": [[x, y, z], ...], free in the others.
        loads: [{"type": "force", "faces": [...], "vector": [Fx, Fy, Fz]}] newtons, spread over the faces (or
        "magnitude" and "direction"); {"type": "pressure", "faces": [...], "value_MPa": p}; {"type": "preload",
        "faces": [under the head], "faces_b": [under the nut], "force_N": N} a bolt's clamping force as a modelled
        connector; {"type": "gravity", "g": 1, "direction": [0, 0, -1]}.
        material: a key of the materials library ("AL-6061", "PETG": E, Poisson's ratio, yield and density with their
        sources), or values with where they are from: {"name", "E_GPa", "poisson", "yield_MPa", "density_kg_m3",
        "source"}; left out: the design's material (set_appearance). materials: {part id: material} for several parts,
        which are solved assembled and bonded where they touch. Nothing is assumed: without E or Poisson's ratio the
        study is refused; without a yield strength there is no safety factor.
        mesh: optional {"h0" start size mm, "levels_max", "dof_max", "budget_s", "tol_stress" 0.05, "tol_disp" 0.01,
        "singular_radius" mm}. The study is saved in the project and runs in the background: read it with
        get_strength_study(project, study, wait_s). study="<id>" alone runs a saved study again (after a change it is
        stale); with a definition it replaces that study; remove=True deletes it. No arguments but project: the
        design's studies with their states. Evidence class: simulated (FEA, <kind>, converged to N %), or "not
        converged", which gives no safety factor. Stress at a sharp inside corner is named as singular and left out.
        Linear elastic, small strain; a printed part is solved solid and isotropic. Needs the optional strength engine
        (setup_status); without it nothing is computed and the call says so."""
        st = studio()
        body = None
        if fixtures is not None or loads is not None or thermal is not None:
            body = {"kind": kind, "fixtures": fixtures or [], "loads": loads or [], "material": material,
                    "materials": materials or {}, "modes": modes, "mesh": mesh or {}, "name": name,
                    "thermal": thermal or [], "reference_C": reference_C}
        by = origin(ctx).replace("agent:", "") or "agent"
        return await run(study_call, st, project, body, study, run_now, force, remove, by)

    @mcp.tool(annotations=RO)
    async def get_strength_study(project: str, study: str, wait_s: float = 30, full: bool = False, field: bool = False,
                                 cancel: bool = False) -> dict:
        """Read a strength study: its state (never, running with progress, current, stale with the revision the
        stored result describes, failed with why), and the result. Waits up to wait_s seconds for a running study.
        The result gives the headline, the evidence class, the safety factor with its lower value under the stated
        error and the source of the strength it is against, peak von Mises stress and where, largest displacement,
        natural frequencies or the buckling load factor, the discretisation error, every singularity that was left
        out (where, why, how the stress there grew with refinement), the balance of reactions and loads, the mesh, the
        material's numbers with their sources and the assumptions. converged=false means the tolerance was not
        reached: the numbers are reported with why, and no safety factor is given. full=True adds every refinement
        level's record. field_file is the path of the field data for a viewer (per-vertex displacement, von Mises
        stress and safety factor on the surface mesh; docs/STRENGTH.md); field=True returns it inline (large).
        cancel=True stops a running study; nothing is stored for a cancelled run."""
        st = studio()
        return await run(read_call, st, project, study, max(0.0, min(float(wait_s), 300.0)), field, full, cancel)
