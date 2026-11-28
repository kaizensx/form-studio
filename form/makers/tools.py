"""The makers' generators over MCP: one tool per generator (form/mcp_server.py registers them from here).

Every tool takes preset (one of the generator's presets), values ({parameter: number}, applied over the preset),
name and purpose, and returns {project, name, head, generator, preset, parameters, make, next}. The design is built
in the kernel before it is saved."""
from __future__ import annotations

from mcp.server.mcpserver import Context


def register_tools(mcp, studio, run_async, RW, made=None) -> None:

    from ..studio import StudioError
    from . import MakeError, make

    async def go(gid, preset, values, text=None, image=None, name="", purpose=None, ctx=None):
        st = studio()

        def call():
            try:
                return make(st, gid, values, text, image, preset or "", name, purpose)
            except MakeError as e:
                raise StudioError(str(e), e.hint, status=422, params=e.params) from None
        out = await run_async(call)
        if made is not None:
            made(out["project"], f"make_{gid}", ctx)
        return out


    @mcp.tool(annotations=RW)
    async def make_name_tag(text: str, preset: str = "keychain", values: dict[str, float] | None = None, name: str = "",
                            purpose: str | None = None, ctx: Context = None) -> dict:
        """Make a name tag or keychain: the text in real font outlines, raised (or engraved, sunk=1) on a rounded
        plate that grows with it, with a keyring hole (ring=1). Presets: keychain, name_tag, engraved. Parameters:
        cap_h, depth, sunk, plate_t, margin, corner_r, ring, ring_d, ring_wall."""
        return await go("name_tag", preset, values, text=text, name=name, purpose=purpose, ctx=ctx)

    @mcp.tool(annotations=RW)
    async def make_lithophane(image: str, preset: str = "lithophane", values: dict[str, float] | None = None, name: str = "",
                              purpose: str | None = None, ctx: Context = None) -> dict:
        """Make a lithophane or relief from a picture the person gave (an absolute path; read locally, never sent):
        thick where dark (lithophane) or high where bright (relief), on a frame. The picture becomes a grid of grey
        levels in the design; the surface is a B-spline B-rep, or a mesh body when the picture is too sharp-edged
        (derived surface_bspline says which). Presets: lithophane, relief. Parameters: width, min_t, max_t, invert,
        frame, frame_t."""
        return await go("lithophane", preset, values, image=image, name=name, purpose=purpose, ctx=ctx)

    @mcp.tool(annotations=RW)
    async def make_gridfinity(preset: str = "bin", values: dict[str, float] | None = None, name: str = "", purpose: str | None = None,
                              ctx: Context = None) -> dict:
        """Make a Gridfinity bin, tray or baseplate from the built-in recipes. Presets: bin, tray, parts_tray,
        baseplate. describe_recipe gridfinity_bin (or gridfinity_baseplate) lists the parameters."""
        return await go("gridfinity", preset, values, name=name, purpose=purpose, ctx=ctx)

    @mcp.tool(annotations=RW)
    async def make_knob(preset: str = "knurled", values: dict[str, float] | None = None, name: str = "", purpose: str | None = None,
                        ctx: Context = None) -> dict:
        """Make a knob for a D-shaft: knurled or smooth grip, dished cap, pointer, set screw. Presets: knurled, smooth,
        large. Parameters: knob_d, height, knurl, pitch, knurl_depth, shaft_d, flat, fit, bore_depth, dish, set_screw."""
        return await go("knob", preset, values, name=name, purpose=purpose, ctx=ctx)

    @mcp.tool(annotations=RW)
    async def make_cable_clip(preset: str = "single", values: dict[str, float] | None = None, name: str = "", purpose: str | None = None,
                              ctx: Context = None) -> dict:
        """Make a cable clip: one to four snap-in rings on a strip with countersunk screw holes. Presets: single,
        double, thick. Parameters: cable_d, count, fit, opening, wall, width, strip_t, screw_d."""
        return await go("cable_clip", preset, values, name=name, purpose=purpose, ctx=ctx)

    @mcp.tool(annotations=RW)
    async def make_hook(preset: str = "coat", values: dict[str, float] | None = None, name: str = "", purpose: str | None = None,
                        ctx: Context = None) -> dict:
        """Make a wall hook: a J arm on a back plate with two countersunk screw holes, printed on its side. Presets:
        coat, small, heavy. Parameters: plate_h, t, width, opening, tip_h, screw_d."""
        return await go("hook", preset, values, name=name, purpose=purpose, ctx=ctx)

    @mcp.tool(annotations=RW)
    async def make_stand(preset: str = "phone", values: dict[str, float] | None = None, name: str = "", purpose: str | None = None,
                         ctx: Context = None) -> dict:
        """Make a phone or tablet stand (the device_stand recipe): seat, lip, backrest, charging cut-out. Presets:
        phone, tablet. describe_recipe device_stand lists the parameters."""
        return await go("stand", preset, values, name=name, purpose=purpose, ctx=ctx)

    @mcp.tool(annotations=RW)
    async def make_drawer_divider(preset: str = "cutlery", values: dict[str, float] | None = None, name: str = "",
                                  purpose: str | None = None, ctx: Context = None) -> dict:
        """Make a drawer divider: an insert sized to the drawer, divided into rows and columns of rounded
        compartments. Presets: cutlery, desk, small. Parameters: width, depth, height, clearance, cols, rows, wall,
        floor, radius."""
        return await go("drawer_divider", preset, values, name=name, purpose=purpose, ctx=ctx)

    @mcp.tool(annotations=RW)
    async def make_hinge_box(preset: str = "box", values: dict[str, float] | None = None, name: str = "", purpose: str | None = None,
                             ctx: Context = None) -> dict:
        """Make a hinged box printed in one piece: base and lid joined by a print-in-place pin hinge whose clearance
        comes from the fit model (the printer's calibration when there is one), closed by a snap latch. Presets: box,
        slim, deep. Parameters: inner_w, inner_d, half_h, wall, corner_r, clearance, latch_undercut."""
        return await go("hinge_box", preset, values, name=name, purpose=purpose, ctx=ctx)

    @mcp.tool(annotations=RW)
    async def make_threaded_jar(preset: str = "printing", values: dict[str, float] | None = None, name: str = "",
                                purpose: str | None = None, ctx: Context = None) -> dict:
        """Make a threaded jar and its screw lid, side by side: a 45-degree printing thread at any pitch (iso=0) or
        ISO metric (iso=1: ISO 68-1 profile, ISO 261 coarse pitch). Presets: printing, iso, spice. Parameters:
        inner_d, height, wall, floor, iso, pitch, turns, clearance, lid_wall, lid_top."""
        return await go("threaded_jar", preset, values, name=name, purpose=purpose, ctx=ctx)

    @mcp.tool(annotations=RW)
    async def make_spur_gears(preset: str = "1:2", values: dict[str, float] | None = None, name: str = "", purpose: str | None = None,
                              ctx: Context = None) -> dict:
        """Make a spur gear pair in mesh with the gear calculator (ISO 21771 geometry, Lewis bending; every revision
        runs the calculation again). Presets: 1:2, 1:3, 1:1. values are the calculator's inputs: module, z1, z2,
        face, bore1, bore2, backlash, pressure_angle, x1, x2, torque (calculate lists them)."""
        return await go("spur_gears", preset, values, name=name, purpose=purpose, ctx=ctx)
