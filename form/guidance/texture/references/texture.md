TEXTURE, two honest tiers
  B-rep (the CAD solid carries it; STEP, STL, checks and slices all include it). Capped at about 2000 elements:
    craft.knurl(diameter, height, pitch, depth, kind="diamond"|"straight")      exact faceted knurl, chamfered ends
    craft.spiral_ribbed_body([(r, z), ...], ribs, rib_depth, twist, fade=(0.1, 0.2))   one skin with spiral ribs;
        fade eases the ribs into a plain foot and collar; past 80 deg of twist it lofts in runs (noted)
    craft.wrapped_ribs(radius, height, count, rib_w, rib_h, twist)             ribs to fuse onto a cylinder
    craft.emboss_cells(w, d, cell, height, kind="hex"|"diamond"|"dots"|"pyramids", base=0)   raised tiles for a flat face
    form.patterns: hex_vents, perforation_grid, slot_array, knurl, grip_ribs (cutters / adds with computed webs)
  Mesh texture (fine surface: leather grain, stone, carbon-like cells, sand-cast): declare it on the design; the STL,
  OBJ, GLB and the renders carry it, the STEP keeps the smooth body. Say so: "mesh texture; STEP carries the smooth body".
    from form.craft import MeshTexture
    def mesh_texture(self, v):
        return [MeshTexture("cells", amplitude=0.4, scale=5, features=["shell"])]
    kinds: noise, cells, grain, hex, weave (carbon-like twill), knurl, ribs, heightmap (image=, projection=planar|
    cylindrical|spherical). amplitude mm (negative presses in), scale mm, features = which feature ids,
    facing="out" = only the outside of a shell, edge_falloff mm at borders and creases.
    region=((x0, y0, z0), (x1, y1, z1)) keeps it to a box (the flanks of a mouse, a band on a lofted face that is one
    feature), exclude=(box, ...) keeps areas smooth (a logo field, a seal face).
    Seeing it: the six-view sheet draws a 270 mm helmet at about 0.5 mm a pixel, so a 0.25 mm weave is invisible
    there; it shows in render_photo close-ups and in the app. Do not deepen it past what the material would have
    to make it show in the sheet.
Choose: if a person sees it from a metre away or it does work (grip, alignment), make it B-rep. If it is felt or seen
up close, make it a mesh texture. Printed texture needs >= 2 nozzle widths in plan and >= 0.3 mm depth to survive.
