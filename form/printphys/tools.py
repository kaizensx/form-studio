"""The MCP tools of print physics: print_orient, print_strength, print_warp.

Registered by form/mcp_server.py with register_tools(...). The same calls serve `form print ...` (cli.py).
"""
from __future__ import annotations

from mcp.server.mcpserver import Context

from . import layers as layers_mod
from . import orient as orient_mod
from . import warp as warp_mod


def _printing(st, p: dict) -> None:
    from .. import purpose
    from ..studio import StudioError
    if not purpose.printing(st.cfg):
        raise StudioError("3D printing is off, so the print tools do not apply.",
                          "Enable it in Settings (Set up for, 3D printing).", status=409)
    if purpose.is_model(p):
        raise StudioError("This design is a 3D model, not made for printing: print orientation, layers and warping do "
                          "not apply to it.", "set_print_setup(project, purpose=\"print\") if it is to be printed.", status=409)


def orient_call(st, project: str, cosmetic=None, study: str = "", load_direction=None, weights=None, level: int = 2,
                calibrate="auto", verify: int = 0, critical_deg=None, pick: str = "", top: int = 8, free: bool = False) -> dict:
    p = st.load(project)
    _printing(st, p)
    if pick:
        return {"picked": orient_mod.pick(st, p, pick)}
    strict = True
    if cosmetic is None and not study and load_direction is None:        # a bare call repeats the last search's inputs
        o = orient_mod.stored_options(p)
        cosmetic, study, load_direction = o.get("cosmetic"), o.get("study") or "", o.get("load_direction")
        strict = False
    return orient_mod.run(st, p, cosmetic=cosmetic, study=study, load_direction=load_direction, weights=weights,
                          level=level, calibrate=calibrate, verify=verify, critical_deg=critical_deg, top=top, free=free, strict=strict)


def strength_call(st, project: str, study: str = "", definition: dict | None = None, orientation: str = "setup",
                  sweep="auto", assume: dict | None = None, name: str = "", run: bool = True, force: bool = False,
                  by: str = "agent") -> dict:
    _printing(st, st.load(project))
    return layers_mod.study_call(st, project, study, definition, orientation, sweep, assume, name, run, force, by)


def warp_call(st, project: str, orientation=None, material=None, chamber_C=None, alpha_per_K=None, tg_C=None,
              layer_height_mm=None, source: str = "") -> dict:
    p = st.load(project)
    _printing(st, p)
    return warp_mod.run(st, p, orientation, material, chamber_C, alpha_per_K, tg_C, layer_height_mm, source)


def register_tools(mcp, studio, run, RO, RW, origin) -> None:
    """Add print_orient, print_strength and print_warp to the MCP server."""
    @mcp.tool(annotations=RW)
    async def print_orient(project: str, cosmetic: list[list[float]] | None = None, study: str = "",
                           load_direction: list[float] | None = None, weights: dict | None = None, level: int = 2,
                           calibrate: bool | str = "auto", verify: int = 0, critical_deg: float | None = None,
                           pick: str = "", top: int = 8, free: bool = False) -> dict:
        """Find the print orientation over several objectives at once. Returns the Pareto front: the orientations no
        other one beats on everything. Objectives: support volume (mm3) and support contact on the part (mm2), both
        computed from the facets that overhang past the critical angle, with each support column going down to the
        plate or to the part below; print time by a layer-time model; strength along the load; surface quality on
        the faces marked cosmetic; and the tilt at which the part tips off its plate contact.
        cosmetic: points on the faces that show, [[x, y, z], ...] in design millimetres (stair height and support
        marks on them become objectives). study: a static strength study whose stress field gives the tension across
        the layers in every orientation, against the material's Z strength from its datasheet (left out: the design's
        one current static study); or load_direction=[x, y, z] when only the direction of the load is known. Without
        either, strength is not an objective and the result says so.
        The search is the six axis orientations, every flat face the part can lie on, and a geodesic grid over all
        directions (level 2: 162, about 16 degrees apart; 1: 42; 3: 642), then a local refinement down to 1 degree.
        The front is taken over the orientations in which the part stands on the plate on its own (a flat face on it,
        the centre of mass over it); free=True also admits orientations that rest on supports.
        The front is ranked by weights you can change (weights={"support_mm3": 0.4, "time_s": 0.1, ...}); the ranking
        is a convention, the front is not. Each row says how every number is known: computed, modelled, simulated.
        Print time is uncalibrated unless a real slice exists: calibrate=True slices the current orientation once
        (supports on) and scales the model by it, stating the factor; "auto" uses such a slice only if it is already
        there. verify=N slices the N best-ranked candidates with the real slicer and reports the model's error in time
        and in support filament per candidate (a slice each: about a minute).
        Nothing is written to the print setup by a search. The person picks: pick="<id>" writes that orientation to
        the design's print setup (ask before picking for them). A call with only the project repeats the last
        search's inputs. critical_deg: the steepest overhang printed without support, from vertical (default: the
        slicer preset's threshold, else 45). Not a print-success prediction: slice the pick to confirm."""
        st = studio()
        return await run(orient_call, st, project, cosmetic, study, load_direction, weights, level, calibrate, verify,
                         critical_deg, pick, top, free)

    @mcp.tool(annotations=RW)
    async def print_strength(project: str, study: str = "", fixtures: list[dict] | None = None,
                             loads: list[dict] | None = None, material: str | dict | None = None,
                             orientation: str = "setup", sweep: list[str] | str = "auto", assume: dict | None = None,
                             mesh: dict | None = None, name: str = "", run_now: bool = True, force: bool = False,
                             ctx: Context = None) -> dict:
        """Strength of the part as printed, layer by layer. A static strength study with a layered (transversely
        isotropic) material, stiff and strong in the layers, weaker across them, turned to the print orientation. Gives the safety factor
        in the weak direction (tension across the layers against the datasheet's Z strength, with its own stated
        discretisation error), the in-plane one (von Mises against the X-Y strength), the lower of the two as the
        verdict, and how they change with the orientation: the same mesh and loads solved for each other build
        direction.
        study: an existing static strength study whose supports, loads and material are reused (strength_study defines
        them); or give fixtures, loads and material as for strength_study. orientation: "setup" (the design's print
        setup; the result goes stale when the setup changes) or an orientation id (as_modelled, on_back, ..., or a
        "down:x,y,z" id from print_orient). sweep: "auto" (the six axis orientations), a list of up to eight ids, or
        [] for none.
        The material: in-plane modulus and strength and the Z modulus and strength are the filament datasheet's
        (X-Y and Z specimens, each with its document). Poisson's ratio is in no filament datasheet: a value measured
        on printed specimens of the same polymer is used where a paper gives one, and named; otherwise give it
        (material={"key": "PETG", "poisson": 0.38, "source": "..."}). Two constants no source has are assumed by a
        stated rule unless you give them in assume: {"poisson_z": ..., "G_z_MPa": ..., "E_z_GPa": ..., "uts_z_MPa":
        ..., "uts_xy_MPa": ..., "shear_strength_MPa": ..., "source": "..."}; every assumed value is listed in
        result.layers.material.assumed, and a study with assumed values says so in its evidence. Without a Z strength
        there is no safety factor in the weak direction. No arguments but project: the design's layered studies.
        It runs in the background like any strength study: read it with get_strength_study(project, study, wait_s);
        the layered part is result.layers. Infill, walls, raster direction and voids are not modelled: the part is a
        homogeneous solid with the datasheet's 100 % infill values. Needs the optional strength engine."""
        st = studio()
        body = None
        if fixtures is not None or loads is not None:
            body = {"fixtures": fixtures or [], "loads": loads or [], "material": material, "mesh": mesh or {}, "name": name}
        by = origin(ctx).replace("agent:", "") or "agent"
        return await run(strength_call, st, project, study, body, orientation, sweep, assume, name, run_now, force, by)

    @mcp.tool(annotations=RO)
    async def print_warp(project: str, orientation: str | None = None, material: str | None = None,
                         chamber_C: float | None = None, alpha_per_K: float | None = None, tg_C: float | None = None,
                         layer_height_mm: float | None = None, source: str = "") -> dict:
        """Warp risk of the part as printed: an indicator, never a predicted lift in millimetres. It is the layer-
        shrinkage model of Wang, Xi and Jin (2007): every layer shortens by alpha x (Tg - chamber temperature) on the
        stack below it, which bends a part of n layers over its longest span on the plate; the index is that model's
        end lift over one layer height. Inputs, each with how it is known: the material's thermal expansion and glass
        transition (sourced from a paper or a resin datasheet of the same polymer, named; or given with alpha_per_K,
        tg_C and source), the chamber temperature (given, else assumed 25 C for an open printer), and from the
        geometry in the print orientation the first-layer area, the longest span, the footprint's aspect ratio, the
        height in layers and the sharp corners at its ends. The band (low, moderate, high) is a stated convention on
        the index, raised by sharp corners and by a footprint that touches the plate on little of its extent.
        Returns the index, the band and what raised it, every input, the footprint's corners (where it lifts first),
        and the same index for the six axis orientations so they can be compared. orientation: default the design's
        print setup. Without a sourced expansion coefficient or glass transition for the material the call is
        refused, naming what to give. It does not know the plate, its temperature, the adhesive, a brim, infill or
        drafts, and the model is not calibrated to any print."""
        st = studio()
        return await run(warp_call, st, project, orientation, material, chamber_C, alpha_per_K, tg_C, layer_height_mm, source)
