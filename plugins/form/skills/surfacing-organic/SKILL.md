---
name: surfacing-organic
description: Build smooth, styled and organic bodies in Form Studio with form.craft (sections, lofts, sweeps, revolves, shells, superellipses, organic bodies and blends). Use when a design is curved, sculpted or product-like rather than prismatic, such as a mouse, a kettle, a helmet, a vase, a creature or a handle.
---

# Surfacing and organic forms

FORM tools: `design_guide()`, `design_examples()`, `plan_design()`, `create_design()`, `add_feature()`,
`build_candidates()`, `render_photo()`, `critique()`.

1. Decide the sections before any code: a designed object is sections and transitions, not boxes. Read
   `references/surfacing.md` (lofts, sweeps, revolves, shells, safe fillets, seam rules) and, for bodies that grow,
   bend or blend like living forms, `references/organic.md`. `design_guide(topic="surfacing")` and
   `design_guide(topic="organic")` return the same texts.
2. Find a close exemplar with `design_examples()` and read its source for the construction.
3. Give each feature a route in `plan_design()`: smooth styled skins are kernel lofts or a subd cage, fine sculpted
   detail is a mesh tier (see remodel-from-mesh, `references/hybrid.md`). Interfaces such as holes, bosses and pockets
   always stay in the kernel.
4. Build the main skin as the skeleton feature, look at it from three angles with `render_photo()`, then add features
   one at a time. A loft that folds or a fillet that fails: apply the diagnosis' first fix, or try two constructions
   with `build_candidates()`.
5. Judge the outline first: if any view reads as a primitive (a box, a puck, an egg), it is not done. Score it with
   `critique()` and fix the lowest item. For the design language and radius hierarchy see industrial-design.

The automatic refinement after each build adds fillet tiers and parting lines without touching interface faces.
