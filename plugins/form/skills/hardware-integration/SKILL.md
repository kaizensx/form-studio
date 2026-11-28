---
name: hardware-integration
description: Design purchased hardware into a FORM part — screws, nuts, heat-set inserts, magnets, bearings, threads. Use when a part is fastened, carries an insert or a bearing, or needs a bill of purchased parts.
---

# Hardware integration

FORM tools: `read_document()`, `design_guide()`, `update_design()`, `slice_test_piece()`, `render()`.

1. Identify the exact standard and size (e.g. ISO 4762 M3×10, a named insert part number). Read the supplier's drawing
   with `read_document()` and record head envelope, hole recommendation and engagement as **specified** parameters
   with the source in the parameter doc.
2. Inserts: use the insert maker's hole size, then test with the real insert and installation method on a small piece.
   Size the boss for the load path around it, not just the hole.
3. Screws: check engagement length, head and driver clearance from the real direction of approach, and nut capture.
4. Printed threads suit larger sizes only; verify a short pair before a long assembly. Real fasteners beat tiny printed
   replicas for repeated service. Keep cosmetic threads separate from fit tests.
5. Magnets and bearings: press fits need a coupon (see fit-calibration); state per-side clearance.
6. Assembly access: every fastener reachable with a real tool, in an order that works. Render the assembled state.
7. List purchased parts with quantity and specification (standard, size, length, material). Never invent SKUs or links.

Build with `form.parts` (the cad-core contract lists every call): `parts.bolted_joint(size, clamp, into=...)` cuts the
clearance and counterbore, the insert pocket, nut trap or tap hole, and picks a stock screw length with enough
engagement; `joint.hardware(qty, after=...)` and `parts.bearing("608").bom()` give BOM rows that carry the standard
and a computed mass. Lead screws (`trapezoidal_thread`), bottle caps (`bottle_thread`), sprockets and chain
(`sprocket`, `chain_drive`) and stock pipe (`pipe_socket`) come from published standards too. Exemplars:
`lead_screw_axis`, `chain_drive`, `bottle_pipe_adapter`.

On a design that already exists, `standard_part` does it in one action: `standard_part(action="search", query="m3
socket")` finds the part in the standards' tables, and `standard_part(action="place", project=..., spec=...,
at=[x, y, z])` snaps to the hole or face at that point, cuts the matching hole, counterbore, pocket or seat as a
feature of the source, records the part as purchased and checks its fit on the B-rep. `bom(project)` is the parts list
by designation with quantity, material and mass; add a supplier's part number only when the person gives it, or from a
page at a link they gave (`bom(action="add_supplier", url=...)`).
