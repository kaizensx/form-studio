"""The calculators over MCP and for the command line: one call that lists, calculates, builds, places and re-reads.

    call(st, "")                                    the calculators, with every input
    call(st, "snapfit", {...})                      a sheet: numbers, checks, equations, sources (nothing saved)
    call(st, "snapfit", {...}, build=True)          the sheet, and a new design written from it
    call(st, "snapfit", {...}, project=P, at=, normal=)   the hook (or an insert boss) put on a face of design P
    call(st, "", project=P)                         the sheet of a design a calculator wrote, for its head revision

form/mcp_server.py registers `calculate` from here; `form calc` (form/calc/cli.py) prints the same JSON.
"""
from __future__ import annotations

from mcp.server.mcpserver import Context

from . import CALCULATORS, CalcError, catalogue, run
from . import design


def _err(e: CalcError):
    from ..studio import StudioError
    return StudioError(str(e), e.hint, status=422, params=e.params)


def sheet_of(st, project: str) -> dict:
    """The calculation of a design a calculator wrote, run again on the head revision's values."""
    from ..studio import StudioError
    p = st.load(project)
    c = design.record(st.source_text(p))
    if c is None:
        raise StudioError("This design was not written by a calculator.",
                          "calculate(calculator, inputs, build=True) writes one; `form calc list` names the calculators.", status=404)
    r = design.recompute(c, {**st.rev(p)["values"], **c["const"]})
    return {**r, "project": p["id"], "head": p["head"], "written_from": c["headline"],
            "note": "Computed now for the head revision's parameter values; written_from is the headline at the time it was written."}


def call(st, calculator: str = "", inputs: dict | None = None, build: bool = False, name: str = "", project: str = "",
         at=None, normal=None, expect_head: int | None = None, purpose: str | None = None, fea: bool = False,
         by: str = "agent") -> dict:
    if not calculator:
        if project:
            return sheet_of(st, project)
        return {"calculators": catalogue(),
                "how": "calculate(calculator, inputs) returns a sheet and saves nothing; build=True writes the design; "
                       "project= with at= and normal= puts a snap hook or an insert boss on a face. Every number is "
                       "labelled computed, specified or assumed, with its equation and source."}
    try:
        r = run(calculator, inputs)
    except CalcError as e:
        raise _err(e) from None
    out = dict(r)
    if project and at is not None:
        from ..studio import StudioError
        if normal is None:
            raise StudioError("A point needs the face's normal.", "Pass normal=[x, y, z] (analyze_selection gives it for a picked point).")
        try:
            res = design.place(st, st.load(project), r, at, normal, expect_head=expect_head, origin=by)
        except CalcError as e:
            raise _err(e) from None
        out.update({"project": project, "head": res["head"], "placed": res["features"][-1] if res.get("features") else None,
                    "next": "render(project) to look; the feature is in the design's source and can be removed (remove_feature)."})
        return out
    if build:
        try:
            p = design.create(st, r, name=name, purpose=purpose)
        except CalcError as e:
            raise _err(e) from None
        out.update({"project": p["id"], "name": p["name"], "head": p["head"],
                    "parameters": sorted(k for k in st.rev(p)["values"]),
                    "next": "render(project, view='sheet') to look; preview_change/commit_change edit its parameters, and "
                            "every revision runs the calculation again (get_project derived; list_studies 'calc')."})
        if fea:
            out["fea"] = _fea(st, p, r, inputs or {}, by)
    return out


def _fea(st, p: dict, r: dict, inputs: dict, by: str) -> dict:
    """Define (and start, where the engine is installed) the strength study that checks the hook by finite elements."""
    d = design.fea_definition(r)
    if d is None:
        return {"available": False, "why": "A finite-element check is defined for the cantilever snap hook only (it needs the deflection force)."}
    from ..fea import HOW_TO_GET, python
    from ..fea import study
    from ..studio import StudioError
    expect = d.pop("expect")
    body = {**d, "material": inputs.get("material") or None}
    try:
        sd = study.define(st, st.load(p["id"]), body, by=by)
    except StudioError as e:
        return {"available": False, "why": str(e), "hint": getattr(e, "hint", ""), "expect": expect}
    out = {"study": sd["id"], "expect": expect, "read": f"get_strength_study(project='{p['id']}', study='{sd['id']}')"}
    if python(st.cfg) is None:
        return {**out, "state": "unavailable", "why": HOW_TO_GET}
    job = study.start(st, p["id"], sd["id"])
    return {**out, "state": "running", "job": job.get("id") if isinstance(job, dict) else job}


def register_tools(mcp, studio, run_async, RO, RW, origin) -> None:
    """Add `calculate` to the MCP server."""
    @mcp.tool(annotations=RW)
    async def calculate(calculator: str = "", inputs: dict | None = None, build: bool = False, name: str = "",
                        project: str = "", at: list[float] | None = None, normal: list[float] | None = None,
                        expect_head: int | None = None, purpose: str | None = None, fea: bool = False,
                        ctx: Context = None) -> dict:
        """Size a part from requirements with a standard's equations, and write it as a design. calculator: "snapfit"
        (cantilever or annular snap joints by permissible strain; Bayer's snap-fit guide), "hinge" (living hinge:
        elastic by strain, or moulded PP/PE from cited practice), "spring" (compression, extension, torsion; EN
        13906-1/-2/-3, with a printed-spring mode), "fastener" (screw size from the load, preload, tightening torque,
        thread stripping, or a boss with a heat-set insert; VDI 2230 Part 1 simplified), "gear" (involute spur and
        helical pairs with profile shift, internal pairs, rack and pinion; contact ratio, backlash, Lewis bending),
        "cam" (plate cam from a motion law; pressure angle, undercut), "fit" (an ISO 286 fit over a temperature span
        from the materials' sourced expansion). No calculator: the list, with every input and its unit.
        inputs: plain numbers and words in mm, N, N·mm, degrees, MPa, °C; materials are keys of the materials library
        (mass_properties library=True lists them). The result is a sheet: values (each with unit, evidence = computed,
        specified or assumed, its equation and its source), checks (PASS, WARN, FAIL with why), equations (text and
        source), sources (title, url), caveats, and not_computed (what was left out because an input has no source,
        and what to give). Nothing is assumed silently: a missing material value leaves its result out.
        build=True writes the geometry as a new design with a parameter per sized dimension (name= names it); every
        later revision runs the calculation again on its values. project= with at=[x, y, z] and normal=[x, y, z] puts
        a snap hook or an insert boss on that face of an existing design instead. project= alone (no calculator):
        the sheet of a design a calculator wrote, for its head revision. fea=True with build=True also defines a
        strength study that checks a cantilever hook's deflection by finite elements (needs the strength engine)."""
        st = studio()
        by = origin(ctx).replace("agent:", "") or "agent"
        return await run_async(call, st, calculator, inputs, build, name, project, at, normal, expect_head, purpose, fea, by)


__all__ = ["call", "sheet_of", "register_tools", "CALCULATORS"]
