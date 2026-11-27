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
 SCULPTED MESHES (a scan, a sculpt, a downloaded figure): reconstruct(path) does this for you
  Do not write this by hand first. reconstruct(path) runs the triage, repairs the mesh and makes the design: a
  surface body or a mesh body. Read its headline (the measured distance from the file) and edit the design it made
  with edit_design. Write the code below only to add features to that design.
  Mesh body (from form.meshbody import MeshBody): the mesh stays a mesh; features are exact booleans. The whole API:
   body = MeshBody.load("scan.stl")     a reference part of this design by name, or an absolute path (STL, OBJ, 3MF).
                                        Welded and repaired; a heavy mesh becomes a lighter working copy; what was
                                        done is in body.source and noted on the build. There is no other loader.
   MeshBody(V, F)                       from arrays: vertices (n, 3) and triangles (m, 3) of a closed mesh
   MeshBody.from_shape(shape, tol=0.02) a build123d shape's tessellation
   body.cut(shape, "hole")              a build123d shape (or another MeshBody) cut out, exactly
   body.add(shape, "boss")              a shape joined to it
   body.trim(origin, normal, "base")    keep the side the normal points to; the cut is closed flat
   front, back = body.split(origin, normal)
   body.scale(factor, about=(x, y, z))  body.move(x, y, z)  body.bounds()  body.volume()  body.report()
   body.solid()                         the kernel solid a feature returns (one planar face per triangle)
  A mesh design declares `mesh = True` on its class (no STEP, no B-rep checks; STL and 3MF export) and keeps the
  mesh in ONE feature: every stage of a mesh is rebuilt and compared triangle by triangle, so cut everything on the
  MeshBody first and return body.solid() once. A complete one:
   class Design(Recipe):
       mesh = True
       params = [Param("pin_d", "Pin hole", 6, 2, 20, 0.1, "mm", "form", "body")]
       features = [Feature("body", "Body", "structure")]
       def build(self, v):
           body = MeshBody.load("scan_body.stl")
           body.cut(Pos(0, 0, -1) * Cylinder(v["pin_d"] / 2, 30), "pin hole")
           return [Stage("body", body.solid())]
  Surface body: solid, report = form.meshbody.organic_solid(triangles_or_(V, F), tol=0.3, kind="auto", cage=None)
   kind "shell" (a thick skin with an open rim: a helmet, a mask) or "closed" (one smooth body without handles).
   cage: the closed route's cage size; 3, 5, 8 and 12 take about 6, 10, 26 and 62 s on 45,000 triangles and the time
   grows with the square of it: never loop over cages or pass one above 12 in a design (the kernel stops a build at
   its time limit). A mesh with handles (genus above 0) or sharp detail cannot be a surface body: use a mesh body.
   report has the measured distance both ways (max_mm), faces, valid, closed; it is data, not an error: never raise
   it. reconstruct(path, route="surface_body") does the fit within a time limit and writes the cage into the design.
  Say which tier the result is ("surface body", "mesh body") and its measured distance from the file.
