---
name: assemblies-and-mechanisms
description: Design multi-part FORM assemblies and moving parts — hinges, sliders, gears, lids, clips — and document them (parts list, assembly order, motion). Use when a design has more than one printed body or anything moves.
---

# Assemblies and mechanisms

FORM tools: `design_guide()`, `create_design()`, `update_design()`, `render()`, `animate()`, `explore_alternatives()`,
`slice_test_piece()`.

Modelling
- Multiple printed bodies go side by side on the bed, at least 5 mm apart, with `solids = N` in the design. Each body
  gets its own features so renders name them.
- Define motion first: travel, range of angle, speed, load, ratio. Then shafts, bearing surfaces, axial retention,
  backlash convention and fastener access.
- Print the smallest mechanism first (one hinge knuckle, one gear pair) before the full assembly.

Motion: be exact about what was evaluated
- `animate(kind="morph", from_rev=..., to_rev=...)` builds every in-between revision for real; it shows a design change,
  not a mechanism moving.
- FORM does not simulate motion or collisions. If you check interference, do it at sampled positions you model
  explicitly (one parameter for the joint angle, `explore_alternatives()` over a few angles) and report the samples.
  Never present static clearance as a completed motion simulation or a collision-free verdict.

Documentation
- Parts list: printed bodies with material and orientation; purchased parts with standard and size (no invented SKUs).
- Assembly steps in order, with tool access and the removal or service path.
- `render(view="sheet")` of the assembled layout; describe an exploded order in words if no exploded model exists.
