---
name: texture
description: Put grip, knurl, ribs, cells, grain or a woven pattern on a Form Studio design, choosing between a B-rep texture (in the CAD solid and STEP) and a mesh texture (in STL, GLB and renders only). Use when a design needs a textured, knurled, ribbed or patterned surface.
---

# Texture

FORM tools: `design_guide()`, `add_feature()`, `update_design()`, `render_photo()`, `get_project()`.

1. Read `references/texture.md` (also `design_guide(topic="texture")`): the B-rep helpers (knurls, spiral ribs,
   wrapped ribs, embossed cells, `form.patterns`) and the mesh texture kinds with their amplitude, scale, regions and
   exclusions.
2. Choose the tier. Seen from a metre away or doing work (grip, alignment): B-rep. Felt or seen up close: a mesh
   texture, and say "mesh texture; STEP carries the smooth body".
3. Add the texture as its own feature after the body is right, so it can be removed or retried without touching the
   rest. Keep logo fields, seal faces and mating faces smooth.
4. Look at it in `render_photo()` close-ups; the six-view sheet is too coarse for fine texture. Do not deepen it past
   what the material could hold just to make it visible.
5. For a print, texture survives only above about two nozzle widths in plan and 0.3 mm in depth.

The automatic refinement can add a grip texture on its own; `refine_design()` reports each change and can undo it.
