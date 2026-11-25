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
