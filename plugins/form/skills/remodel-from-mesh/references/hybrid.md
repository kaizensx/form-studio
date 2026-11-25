HYBRID: one design, a construction route per feature
A real object mixes kinds of geometry: a sculpted creature head with a magnet pocket, a smooth mouse shell with screw
bosses, a modular wall with repeated bricks. plan_design gives every feature a route, read from its words (form/router.py,
English and Portuguese, heuristic: it returns the words that chose it and never claims to detect everything) or stated
by you as route= on the feature. A feature it cannot read is built in the kernel by default and listed in the brief's
unknowns: settle it instead of guessing.

THE FOUR ROUTES
  kernel        build123d / OCCT with form.craft. For every mechanical interface: holes, threads, bosses, inserts,
                magnet pockets (craft.magnet_pocket), snaps (craft.cantilever_snap), bearing seats (craft.bearing_fit),
                mating faces, rails. Exact, and editable through Params. A feature that names an interface is routed
                here whatever it sits on.
  subd_cage     smooth styled surfaces: a mouse shell, a fairing, a helmet crown, a kettle body. A quad cage
                (craft.subd.Cage: vertices and quad faces as data in the design source) shaped by moving cage points
                and named Handles (craft.subd.Handle, craft.subd.apply_handles); model_mesh edits the cage in Blender
                when available. Blender is an editor, never the authority: the cage is written back into the source.
  sculpt_recon  high-frequency organic detail: creatures, faces, wrinkles, scales, weathering, rock. Sculpted as a
                mesh (model_mesh sculpt ops, when available), then brought back as a surface: craft.subd.fit_cage
                onto a cage, or the spline patches of form/recon/freeform.py (recon.freeform.fit_patch).
  procedural    repeated or generated detail. Kernel tier (B-rep, in STEP): form.patterns (patterns.hex_vents,
                patterns.perforation_grid, patterns.slot_array, patterns.grip_ribs, patterns.knurl) and craft.knurl,
                craft.emboss_cells, craft.wrapped_ribs, craft.lattice. Mesh tier (STL, GLB and renders only):
                craft.MeshTexture, or Geometry Nodes arrays and scatters through model_mesh when available.

HOW A SUBD CAGE BECOMES EXACT CAD
  Where the cage is a regular grid, its limit surface is a bicubic B-spline and the CAD face is that surface exactly.
  Around an extraordinary vertex (not four edges) craft.subd builds approximating Bezier patches (ACC) that meet with
  G1 continuity; craft.subd.seam_angles measures how well, and the deviation from the true limit surface is reported,
  never hidden. craft.subd.patches_solid sews the patches into a solid that booleans, shells and holes work on. So a
  subd body can take kernel interfaces (a hole, a magnet pocket) after it is a solid.

EDITABILITY PER ROUTE
  kernel        every Param; the best route for anything that must fit.
  subd_cage     cage points and named Handles (bulge the crown 3 mm, pull the nose 5 mm); interfaces cut after it
                stay Params.
  sculpt_recon  the fitted cage or patches only; sculpted detail is changed by sculpting again, not by a number.
  procedural    the pattern's Params (cell size, pitch, depth, count, seed).

HONEST LIMITS
  * The route is a keyword heuristic. Say "heuristic" when you report it, and correct it with route= when you know
    better.
  * sculpt_recon is approximate: give the measured deviation of the fit, never call it exact.
  * A mechanical interface on a mesh-only route (sculpt_recon without a fit back to a surface, procedural on the
    mesh tier) cannot be exact; plan_design warns and you move it to the kernel.
  * Mesh-tier detail is not in STEP. Say so when the design leaves as CAD.
  * model_mesh needs Blender; without it, use the craft helpers above. Nothing here downloads or installs anything.
