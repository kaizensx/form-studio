---
name: modular-storage
description: Design Gridfinity bins, drawer organizers and custom tool inserts in FORM. Use when the user wants to organise a drawer, toolbox or desk with bins or pockets.
---

# Modular storage

FORM tools: `brief_presets()`, `describe_recipe()`, `create_project()`, `preview_change()`, `commit_change()`,
`slice_test_piece()`, `render()`.

1. Read the real drawer: inner width, depth and usable height to the lowest obstruction. `brief_presets(preset="organizer")`
   lists the questions. Check what base or bins already exist.
2. Gridfinity: `describe_recipe(recipe="gridfinity_bin")`, then `create_project(recipe="gridfinity_bin", values=...)`; the grid
   it sits in is `gridfinity_baseplate`. Small boxes: `storage_box`; batteries and cards: `battery_holder`. Keep the
   reusable base interface separate from the object pockets; do not change the grid interface to fit a pocket.
3. Pockets: measured tool sizes plus a stated per-side clearance; finger access for every tool; walls thick enough
   between pockets (check `min_wall_mm`). The drawer must still close with the tallest tool in place.
4. Print one cell or `slice_test_piece()` first and check it seats on the user's base before printing the set.

Ecosystem names are not fit guarantees: verify against the user's real base and tools.
