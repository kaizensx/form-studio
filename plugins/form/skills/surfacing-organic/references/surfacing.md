SURFACING (form.craft.surfaces)  from form import craft
A designed object is made of sections and transitions, not of boxes. Decide the sections first, then skin them.
  craft.superellipse(a, b, n)                 points; n = 2 ellipse, 2.5-4 product "soft square", >= 6 rounded rectangle
  craft.superellipse_face(a, b, n, z=, center=, squash_front=)    a section Face at height z
  craft.spline_profile(points, plane=Plane.XZ, closed=True)       smooth Face (or Wire) through points
  craft.loft_sections([face, face, ..., Vertex(tip)])             smooth B-spline skin; ruled loft as fallback (noted)
  craft.sweep_spline(profile_face, path_points)                   profile placed normal to the path start
  craft.revolve_profile([(r, z), ...], spline=True)               vases, knobs, lamp bodies, wheels
  craft.shell(solid, t, openings=craft.faces_at(solid, "top"))    hollow it; keeps the outside
  craft.safe_fillet(solid, edges, r)          tries r, 75 %, 50 %, 25 % on all edges, then edge by edge, then leaves
                                              them (all noted); never crashes
  craft.variable_fillet(solid, edges, r0, r1) a blend that grows along the edge
  craft.thicken(face, t)                      a solid from a surface
  craft.notes()                               what fell back; get_project shows them as craft_fallbacks
Rules:
  * 5-12 sections for a body; the same point count and start angle (seam) on every section, or the loft twists.
  * Make sections follow a law (an ellipse in elevation, a power curve) rather than hand-picked numbers: the
    surface then flows. craft.dome_sections() does this.
  * A loft has a seam line where its sections start (seam=0: +X, the nose). Fillets and booleans fail first where
    they cross it; keep pockets, vents and spoilers off it, or move it (section dicts take seam=180 for the back).
  * Fillet BEFORE shelling where you can (a shell follows the rounds), and big radii first, small ones last.
  * A pocket cut into a curved dome (a hex for a bolt head) leaves an edge OCCT will not round: cut a flat land
    (a shallow cylinder) first, then the pocket, then fillet the land's circle and the pocket mouth.
  * Profiles: spline_profile / polygon_profile faces always face the plane's normal, so extrude(face, d) goes along
    it whichever way the points run; extrude(face, d, both=True) for a cutter through a whole body.
  * Tangent and coincident faces break booleans: overlap cutters by 0.2 mm and avoid exactly touching surfaces.
