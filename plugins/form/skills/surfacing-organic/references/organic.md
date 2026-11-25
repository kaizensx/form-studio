ORGANIC FORMS (form.craft.organic)
  craft.section_body([dict(z, a, b, n, cx, cy, squash), ...], tip=(x, y, z))   loft of superellipse sections
  craft.dome_sections(length, width, height, crown_back=, squash_front=)       sections of a smooth dome
  craft.section_shell(sections, wall, tip=, open_top=)                         hollow by inset sections (never fails
                                                                               where an offset of a crown point does)
  craft.inset_body(sections, wall, tip=)                                       the inner body section_shell removes
  craft.inflate(sections, amount, tip)                                         near-offset sections, for pads/ridges
  craft.helmet_shell(length, width, height, wall, skirt)                       outer form + hollow shell
  craft.helmet_sections(length, width, height, skirt)                          its sections, for visors, pads, liners
  craft.grip(length, d_max, d_min, flat, finger_grooves)                       revolved spline, oval section
  craft.handle(span, rise, section_w, section_h)                               swept D-handle with feet
 Silhouette-driven forms (draw three views, get sections):
  craft.profile_sections(front, back, half_width, z_eq=, crown=(x, z), n=, squash=, cy=)   sections from guide
      curves: front/back = the side silhouette as (z, x) knots, half_width = the front silhouette as (z, y) knots,
      a superellipse dome above z_eq to the crown; n, squash, cy constants or (z, v) knots. C2 splines throughout.
  craft.checked_body(secs, tip, label=)    section_body + check_sections (order, seams, steep steps) + loft_report
      (the skin's normals: a fold is a crease inside a face that should be smooth); leaves a note when it folds
  craft.loft_report(shape)                 {faces_checked, folds, worst_deg, where}: run it on any lofted solid
  craft.two_view_cutter(side, front, x_range)   a cutter drawn in two views (eye ports, visor windows, wrapped vents)
  craft.grow_outline(points, mm)           an outline moved outward (rims and gaskets round an opening)
  craft.surface_band(secs, tip, amount, region, depth)   the surface grown by amount, clipped to region, rooted
      depth inside the wall: pads, scoops, trim, spoilers, raised graphic panels; the region's walls are crisp lines
  craft.slot_grille(center, normal, count, length, width, pitch, taper=)   B-rep vent grille cutter
  craft.cut(body, tool) / craft.fuse(body, part)   booleans through the engine (craft.boolean); they refuse a result
      that lost the body. Parts that must stay separate (a visor, a faceplate) go in craft.parts, not a fuse
 Product families from named proportions (each returns the sections plus the outlines of its openings):
  craft.head_form("J")                      EN 960 / ECE 22.05 headform (A 500, E 540, J 570, M 600, O 620 mm
                                            circumference) scaled from the ANSUR II mean head: length, breadth, eye, chin
  craft.helmet_fullface(size, chin=, tail=) full-face helmet: head + comfort 10 + EPS 34 + shell 3.5 mm a side;
                                            keys sections, tip, edge, port_side/port_front, visor_side, pivot
  craft.helmet_open(size, kind="cycling"|"open")   half-shell and open-face helmets
  craft.mouse_form(length=, width=, height=, hand=, hump=, tilt=, flare=)   palm-grip mouse from the hand (ANSUR II:
                                            0.65 x hand length long); hump behind centre, tilt toward the thumb
  craft.grip_sections(length, hand_breadth) power grip (31-38 mm best for force), palm swell, flat across
  craft.bottle_profile(volume_ml)           revolve profile with a PCO 1881 neck, height solved from the volume
Method: start from the object's real measurements (a head is about 200 x 160 mm, a helmet adds 25-35 mm a side; a
power grip is 30-38 mm across), draw the side silhouette and the top silhouette as curves, and derive the sections
from them. Asymmetry front to back is what makes organic things read as designed (a helmet's crown sits behind
centre; a grip swells at the palm, not the middle). Cut openings with smooth cutters (lofted or swept), not boxes,
and round their edges.
Shape the OUTSIDE first, then hollow: a scoop or a flat cut into a shell leaves a fillet the wall cannot take.
    outer = craft.section_body(secs, tip); inner = craft.inset_body(secs, wall, tip)
    outer = craft.safe_fillet(outer - scoop, scoop_edges, 4)      # round the outside
    shell = outer - (inner - grown_scoop)                         # the inside follows, the wall stays even
Layers that follow the surface (a visor 1.2 mm off a helmet, a pad, a spoiler) are inflate() bodies subtracted from
each other and intersected with a window: skin = body(inflate(secs, g + 3)) - body(inflate(secs, g)). Shape the
window as a side profile extruded across (spline_profile on Plane.XZ, extrude(..., both=True)), not a box: the
outline is what reads. A visor reaches back to its pivots; a band that stops short leaves the pivot tabs floating.
Product shapes read from their silhouettes: a helmet's chin bar juts forward and its lower edge sweeps up behind the
jaw to the neck; a mouse's hump sits behind centre and its thumb side is fuller. Shift and pinch sections (cx, b) to
get there, a little at a time: large sideways shifts between close sections fold the loft.
What makes a styled product read as the real thing is its BREAK-UP, not its dome: a smoked visor as its own body on
pivots, rubber trim on the edges, intakes with grilles, a spoiler, split lines between buttons, a wheel. Every one is
a surface_band or a two_view_cutter that follows the main form. A smooth body with one cut reads as a pebble.
Face the product +X with Z up: critique compares its side, front and top silhouettes with the product class
(helmet_fullface, helmet_open, mouse, bottle), and render_photo's views and appearance() zones assume it.
 Sculpted forms (masks, cowls, character props) as subdivision cages, exact NURBS (from form.craft import subd):
  C = subd.dome_cage(L, W, H, n=14, rim=fn(theta), tuck=0.28)   a head-like skin cage (x forward, z up)
  C = subd.apply_handles(C, HANDLES, v)     subd.Handle(name, label, centre, radius, direction | "normal", ...) moves
      cage points smoothly; h.param(feature) makes each handle a Param ("stronger brow" is a number)
  shell = subd.sculpted_shell(C, wall)      skin + inside + ruled rim: three faces, C2 inside, fast booleans after
  subd.Cage(V, quads, levels=1).solid()     a closed Catmull-Clark cage as bicubic patches (G1 at odd vertices)
 Exact CAD on a sculpted skin (hybrid):
  craft.organic.magnet_boss(body, at, axis, magnet_d, magnet_t)   a boss from the inside with the pocket in it
  craft.organic.split_with_magnets(body, x, organic.split_spots(body, x, heights, d), d, t)   front/back halves
  openings from a constrained sketch: from form.sketch2d import Sketch (lines, arcs, constraints, named dimensions
  that are Params; Sketch.face(v, plane=Plane.YZ)), never hand-typed coordinates for a shape that must keep intent.
 A sculpted MESH (a download, a scan): form.meshbody.organic_solid(triangles) gives a closed NURBS solid within a
 stated tolerance with its cage, or MeshBody keeps the mesh and cuts exact features into it. Say which tier it is.
