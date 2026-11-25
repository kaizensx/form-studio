---
name: assemblies-and-mechanisms
description: Design multi-part FORM assemblies and moving parts — hinges, sliders, gears, lids, clips — and document them (parts list, assembly order, motion). Use when a design has more than one printed body or anything moves.
---

# Assemblies and mechanisms

FORM tools: `design_guide()`, `create_design()`, `update_design()`, `render()`, `animate()`, `explore_alternatives()`,
`slice_test_piece()`.

Read `references/mechanisms.md` (the same text as `design_guide(topic="mechanisms")`): the form.craft helpers for
hinges, snaps, sliders, gears, cams, linkages and fits, with their clearances.

Modelling
- Multiple printed bodies go side by side on the bed, at least 5 mm apart, with `solids = N` in the design. Each body
  gets its own features so renders name them.
- Define motion first: travel, range of angle, speed, load, ratio. Then shafts, bearing surfaces, axial retention,
  backlash convention and fastener access.
- Print the smallest mechanism first (one hinge knuckle, one gear pair) before the full assembly.

Declaring the assembly (`design_guide()`, section ASSEMBLIES)
- Parts form a tree. Give every part at most one parent: a part with `attach="arm"` for a part fixed to another (a bolt,
  a cap), or one joint that moves it: a hinge on the cup with `parent="arm"`. A joint moves its part and
  everything attached below it, so the cup and its bolt swing with the arm. Axes and origins are written with every
  joint at 0; a child joint's axis rides with its parent.
- Ratchets and detents: `step=15` checks only the positions the joint can rest at. Say so when you report.
- Declare a Mate (kind pin, thread, slip, press, snap or contact, with its `clearance`) for every pair that touches
  or interlocks by design. Threads also take `axis=` and `origin=` so their arbitrary phase is searched. Undeclared
  pairs are checked for overlap at rest and through every joint.
- Check your placement before anything else: a fit row that says "no surfaces within N mm" means a part is not where
  its mate is. build123d Rot with angles (x, y, z) is the matrix Rx·Ry·Rz; verify where an axis lands instead of reasoning it out.
- Explode offsets are relative to the parent part.

Motion: be exact about what was evaluated
- Form Studio sweeps each joint with its chain on the mesh (stated tolerance), refines near contact, and reports the
  first contact angle and the worst overlap (volume from the B-rep). Between positions it proves freedom only where the
  clearance exceeds how far any point can travel; elsewhere the row says "sampled only". Quote that wording.
- The checks run in a time budget (`[assembly].budget_s`, or `budget_s` on the Assembly). A partial row says which range
  was checked ("checked -60 to 15°, not beyond"); never report the unchecked part as clear.
- `animate(kind="morph", from_rev=..., to_rev=...)` builds every in-between revision for real; it shows a design change,
  not a mechanism moving.

Documentation
- Parts list: printed bodies with material and orientation; purchased parts with standard and size (no invented SKUs).
- Assembly steps in order, with tool access and the removal or service path.
- `render(view="sheet")` of the assembled layout; describe an exploded order in words if no exploded model exists.
