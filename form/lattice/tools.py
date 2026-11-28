"""Lattices over MCP and for the command line: `lattice_properties` (what a cell is worth; reads only) and
`lattice_fill` (put one in a design, change it, remove it, read it back).

    props(kind="gyroid", cell=8, density=0.2, material="PA12", process="sls")     a sheet of numbers, nothing saved
    fill(st, P, kind="octet", cell=8, strut_d=1.0, skin=1.2)                      a new revision with the lattice
    fill(st, P)                                                                   the lattice the design carries
    fill(st, P, remove=True)                                                      the body back
"""
from __future__ import annotations

from mcp.server.mcpserver import Context

from . import LatticeError, _serr, apply, current, normalise, properties, read, remove as _remove, stress_grid
from . import cells as C

SPEC_KEYS = ("kind", "cell", "form", "wall", "strut_d", "density", "skin", "node", "region", "grading", "output", "resolution")


def catalogue() -> dict:
    return {"tpms": [{"kind": k, "label": C.LABEL[k], "forms": list(C.FORMS)} for k in C.TPMS],
            "struts": [{"kind": k, "label": C.LABEL[k], "struts_per_cell": len(C.struts(k)),
                        "length_per_cell_a": round(C.STRUT_LENGTH[k], 4)} for k in C.STRUT],
            "aliases": {"diamond": "schwarz_d"},
            "how": "lattice_properties(kind, cell, density | wall | strut_d) returns the cell's numbers and saves "
                   "nothing; lattice_fill(project, ...) puts it in a design with a skin."}


def props(kind: str = "", cell: float = 8.0, material=None, process: str | None = None, nozzle: float | None = None,
          verify: bool = False, **spec) -> dict:
    if not kind:
        return catalogue()
    try:
        s = normalise(kind, cell, **{k: v for k, v in spec.items() if k in SPEC_KEYS and v is not None})
        return properties(s, material, process, nozzle, verify)
    except LatticeError as e:
        raise _serr(e) from None


def fill(st, project: str, kind: str = "", cell: float | None = None, remove: bool = False, study: str = "",
         expect_head: int | None = None, material=None, process: str | None = None, nozzle: float | None = None,
         verify: bool = False, by: str = "agent", **spec) -> dict:
    try:
        p = st.load(project)
        if remove:
            return _remove(st, p, expect_head, by)
        if not kind:
            return read(st, p, material, process, nozzle, verify)
        spec = {k: v for k, v in spec.items() if k in SPEC_KEYS and v is not None}
        g = spec.get("grading")
        if isinstance(g, dict) and g.get("mode") == "stress" and "grid" not in g:
            if not (study or g.get("study")):
                raise LatticeError("A stress grading needs the strength study to read: study=.",
                                   "strength_study defines and runs one; its von Mises field sets the density.")
            base = current(st, p)
            if base:
                raise LatticeError("The strength study must describe the body, and this design already carries a "
                                   "lattice.", "Remove the lattice (remove=True), run the study on the body, then fill "
                                   "again with study=.")
            spec["grading"] = {**g, **stress_grid(st, p, study or g["study"])}
        s = normalise(kind, 8.0 if cell is None else cell, **spec)
        return apply(st, p, s, expect_head, by, material, process, nozzle, verify)
    except LatticeError as e:
        raise _serr(e) from None


def register_tools(mcp, studio, run_async, RO, RW, origin) -> None:
    @mcp.tool(annotations=RO)
    async def lattice_properties(kind: str = "", cell: float = 8.0, form: str = "sheet", density: float | None = None,
                                 wall: float | None = None, strut_d: float | None = None, node: float = 1.25,
                                 skin: float = 0.0, grading: dict | None = None, material: str | dict | None = None,
                                 process: str = "", nozzle: float | None = None, verify: bool = False) -> dict:
        """What a lattice or TPMS cell is worth, before anything is built. kind: gyroid, schwarz_p, schwarz_d
        (diamond), neovius (TPMS; form "sheet" = a wall about the surface, "network" = one channel system filled) or
        bcc, fcc, octet, kelvin (struts). cell: its size in mm. One of density (relative, 0.02 to 0.8), wall (mm, a
        sheet TPMS) or strut_d (mm). No kind: the list. Returns relative_density ("computed (unit cell)", with the
        first-order strut formula or the thin-wall estimate from the published surface area beside it), features
        (thinnest wall or strut, largest pore), stiffness and strength by Gibson-Ashby scaling, labelled "computed
        (scaling law)" with the class of the cell, its basis and source (E in MPa when material= names one from the
        library or gives E), and printability against process= (fdm, sla, sls, mjf, lpbf): thinnest feature against
        the table's sourced limit and the nozzle, and for resin and powder whether a skin traps it and whether the
        pores let it out. verify=True also solves one periodic cell by finite elements (a frame for struts, voxels
        for a TPMS, which needs SciPy) and reports the estimate's difference from it. Saves nothing."""
        return await run_async(props, kind, cell, material, process or None, nozzle, verify, form=form, density=density,
                               wall=wall, strut_d=strut_d, node=node, skin=skin, grading=grading)

    @mcp.tool(annotations=RW)
    async def lattice_fill(project: str, kind: str = "", cell: float | None = None, form: str = "sheet",
                           density: float | None = None, wall: float | None = None, strut_d: float | None = None,
                           skin: float = 0.0, node: float = 1.25, region: dict | None = None, grading: dict | None = None,
                           study: str = "", output: str = "auto", resolution: int = 14, remove: bool = False,
                           expect_head: int | None = None, material: str | dict | None = None, process: str = "",
                           nozzle: float | None = None, verify: bool = False, ctx: Context = None) -> dict:
        """Fill a design (or a box inside it) with a lattice or TPMS, leaving a skin: one feature in the design's
        source, a new revision. kind, cell, form, density | wall | strut_d as lattice_properties. skin: the solid
        wall left round the region, in mm (0: the lattice is open to the outside). region: {"min": [x, y, z], "max":
        [x, y, z]} to fill only that box of the body. grading: {"mode": "distance", "from": "boundary" | {"point":
        [...]} | {"plane": {"origin", "normal"}}, "over": mm, "density": [at the reference, far from it]} or {"mode":
        "stress", "density": [where there is no stress, at the peak], "exponent": 1} with study= a current static
        strength study of the body (its von Mises field, resampled to a grid kept in the source). output: "auto"
        decides and says why: struts are exact B-rep cylinders and node spheres up to about 900 struts, a mesh body
        above; a TPMS has no exact B-rep, so it is a faceted B-rep (planar triangles cut into the exact body) while
        small and a mesh body when large; "brep" or "mesh" forces one. A mesh body is not written to STEP. Returns
        the specification, plan (output and why), built (representation, relative density measured on the solid,
        facet deviation, closed voids), the cell's properties and printability as lattice_properties. No kind: reads
        the lattice the design carries. remove=True takes it out. Pass expect_head."""
        st = studio()
        return await run_async(fill, st, project, kind, cell, remove, study, expect_head, material, process or None,
                               nozzle, verify, origin(ctx), form=form, density=density, wall=wall, strut_d=strut_d,
                               skin=skin, node=node, region=region, grading=grading, output=output, resolution=resolution)


__all__ = ["props", "fill", "catalogue", "register_tools"]
