# Game bench

Six original game-asset briefs (tests/design_bench/game_briefs.json) made end to end by a scripted agent (`python scripts/game_bench.py`), run 2026-11-24 on Darwin arm64 with Blender 5.2.3. Textures 1024 px, the fast bake. Every number below is from that run; failures are published as they came out. Budgets and thresholds are proposed values, not engine rules.

How it is measured:

- **Route**: form/router.py reads each feature's words (a heuristic, and labelled one); the main route is the most common one, compared with the route the brief was written for.
- **Build**: the design created with the purpose "game" and built by the kernel, with STEP exported.
- **SubD to CAD**: per connected cage part, the CAD patches against the Catmull-Clark limit surface (form/craft/subd_report.py); the worst part's max deviation per 100 mm of its size. Exact only where every patch is a regular B-spline patch; ACC elsewhere.
- **STEP**: the exported STEP read back with OCCT: valid, solids.
- **Game asset**: form/game (Blender bakes, the GLB is written and checked here): every validation check, LOD triangles against budgets (2% over passes), bake seconds.
- **Aesthetic**: form/critique.py's rubric (heuristic). Scores come from tests/design_bench/game_scores.json (the bench's AI agent, from the renders of the first run (not a person), 2026-11-24), capped by what the geometry supports. Gate: mean ≥ 4.0 and none under 3 (proposed).

| Brief | Route (expected) | Build | SubD→CAD max / 100 mm | STEP | Validation | LOD0..LOD3 tris / budget | Bake s | Aesthetic |
|---|---|---|---|---|---|---|---|---|
| Sci-fi helmet prop | subd_cage (subd_cage) | ok 2.2 s | 0.141 mm (1/4 parts exact) | valid, 1 solid(s) | PASS | 5184/8000 · 3980/4000 · 1296/1600 · 324/500 | 1.8 | 2.25 below gate |
| Stylised treasure chest | subd_cage (subd_cage) | ok 1.5 s | 0.277 mm (4/8 parts exact) | valid, 1 solid(s) | PASS | 11940/12000 · 4016/6000 · 2486/2500 · 796/800 | 1.7 | 2.38 below gate |
| Fantasy sword | subd_cage (subd_cage) | ok 0.7 s | 0.174 mm (1/4 parts exact) | valid, 1 solid(s) | PASS | 2984/3000 · 1136/1500 · 696/700 · 248/250 | 1.0 | 2.00 below gate |
| Modular wall kit piece | kernel (procedural) ✗ | ok 1.5 s | 7.66e-13 mm (31/32 parts exact) | valid, 1 solid(s) | PASS | 5970/6000 · 2928/3000 · 732/1200 · 398/400 | 1.9 | 1.62 below gate |
| Vehicle wheel | subd_cage (subd_cage) | ok 2.8 s | 0.171 mm (6/8 parts exact) | valid, 1 solid(s) | PASS | 4974/5000 · 2486/2500 · 736/1000 · 298/300 | 2.2 | 2.25 below gate |
| Remote control, CAD plus asset | kernel (kernel) | ok 0.6 s | n/a (kernel) | valid, 1 solid(s) | FAIL: normal_map | 2984/3000 · 1492/1500 · 596/600 · 198/200 | 1.4 | 2.62 below gate |

## Per brief

### Sci-fi helmet prop

- Routes: shell → subd_cage (cage, rounded, shell); visor → subd_cage (cage, curved, shell); pods → subd_cage (cage, rounded, smooth); crest → subd_cage (cage, smooth)
- Cage: 170 points, 162 quads, 36 sharp crease edges, regions crest, pod, visor.
- SubD→CAD: 4 part(s), worst max 0.0882 mm, RMS 0.0375 mm, 0.141 mm per 100 mm; 24 irregular point(s).
- STEP: valid, 1 solid(s), 89 faces, 651 kB
- Game asset (unreal): built in 5.8 s, bake 1.8 s, UVs smart, collision 4 hull(s) (UCX_Sci_fi_helmet_prop_LOD0_00, UCX_Sci_fi_helmet_prop_LOD0_01, …).
- Checks: all PASS
  - LOD0: 5184 / 8000 triangles, cage level 2 (clean quads)
  - LOD1: 3980 / 4000 triangles, cage level 2, decimated to the budget (automatic retopology)
  - LOD2: 1296 / 1600 triangles, cage level 1 (clean quads)
  - LOD3: 324 / 500 triangles, cage level 0 (clean quads)
- Aesthetic rubric (heuristic): silhouette 3.0, proportion 3.0, continuity 4.0, radius_hierarchy 1 (cap 1: No blend radii and sharp edges: rounding was dropped. Use craft.safe_fillet with smaller radii; never ship without them.), break_up 2 (cap 2: One feature in one material: no surface break.), detail_rhythm 2.0, material 1 (cap 1: One material over everything: declare appearance() zones (two or three, by function).), would_sell 2.0; mean 2.25
- Looked at (the bench's AI agent, from the renders of the first run (not a person)): Reads as a rounded helmet with a wide visor; the ear pods are plain spheres and the crest floats a little high. No blend radii between parts.
- Wall time 15.6 s.

### Stylised treasure chest

- Routes: body → subd_cage (cage, soft, subdivision); lid → subd_cage (cage, smooth, subdivision); bands → procedural (repeated); lock → subd_cage (cage, smooth)
- Cage: 518 points, 502 quads, 366 sharp crease edges, regions gold, iron.
- SubD→CAD: 8 part(s), worst max 1.12 mm, RMS 0.0919 mm, 0.277 mm per 100 mm; 92 irregular point(s).
- STEP: valid, 1 solid(s), 79 faces, 1049 kB
- Game asset (unreal): built in 8.3 s, bake 1.7 s, UVs smart, collision 8 hull(s) (UCX_Stylised_treasure_chest_LOD0_00, UCX_Stylised_treasure_chest_LOD0_01, …).
- Checks: all PASS
  - LOD0: 11940 / 12000 triangles, cage level 2, decimated to the budget (automatic retopology)
  - LOD1: 4016 / 6000 triangles, cage level 1 (clean quads)
  - LOD2: 2486 / 2500 triangles, cage level 1, decimated to the budget (automatic retopology)
  - LOD3: 796 / 800 triangles, cage level 0, decimated to the budget (automatic retopology)
- Aesthetic rubric (heuristic): silhouette 4.0, proportion 4.0, continuity 2 (cap 2: 95 % of edge length is a sharp crease.), radius_hierarchy 1 (cap 1: No blend radii and sharp edges: rounding was dropped. Use craft.safe_fillet with smaller radii; never ship without them.), break_up 2 (cap 2: One feature in one material: no surface break.), detail_rhythm 3.0, material 1 (cap 1: One material over everything: declare appearance() zones (two or three, by function).), would_sell 2 (cap 2: Nothing sells better than its weakest item allows.); mean 2.38
- Looked at (the bench's AI agent, from the renders of the first run (not a person)): The strongest: clear masses, banded lid, wood and iron read at LOD3. Edges are hard creases with no bevel.
- Wall time 22.8 s.

### Fantasy sword

- Routes: blade → subd_cage (cage, subdivision); guard → subd_cage (cage, smooth); grip → subd_cage (cage, grip, smooth); pommel → subd_cage (cage, smooth, subdivision)
- Cage: 150 points, 142 quads, 96 sharp crease edges, regions blade, grip, guard.
- SubD→CAD: 4 part(s), worst max 0.228 mm, RMS 0.0651 mm, 0.174 mm per 100 mm; 48 irregular point(s).
- STEP: valid, 1 solid(s), 79 faces, 499 kB
- Game asset (gltf): built in 2.8 s, bake 1.0 s, UVs smart, collision 4 hull(s) (Fantasy_sword_collision_00, Fantasy_sword_collision_01, …).
- Checks: all PASS
  - LOD0: 2984 / 3000 triangles, cage level 2, decimated to the budget (automatic retopology)
  - LOD1: 1136 / 1500 triangles, cage level 1 (clean quads)
  - LOD2: 696 / 700 triangles, cage level 1, decimated to the budget (automatic retopology)
  - LOD3: 248 / 250 triangles, cage level 0, decimated to the budget (automatic retopology)
- Aesthetic rubric (heuristic): silhouette 3.0, proportion 3.0 (cap 4: Bounding ratios are not near a classic ratio: long:mid 4.235, mid:short 4.557.), continuity 2 (cap 2: 68 % of edge length is a sharp crease.), radius_hierarchy 1 (cap 1: No blend radii and sharp edges: rounding was dropped. Use craft.safe_fillet with smaller radii; never ship without them.), break_up 2 (cap 2: One feature in one material: no surface break.), detail_rhythm 2.0, material 1 (cap 1: One material over everything: declare appearance() zones (two or three, by function).), would_sell 2.0; mean 2.00
- Looked at (the bench's AI agent, from the renders of the first run (not a person)): A clean but generic silhouette; the blade is thin for its length and the guard and pommel are plain.
- Wall time 9.0 s.

### Modular wall kit piece

- Routes: wall → kernel (wall); plinth → kernel, not confident; bricks → procedural (array, brick, pattern)
- Cage: 430 points, 366 quads, 684 sharp crease edges, regions brick.
- SubD→CAD: 32 part(s), worst max 2.34e-12 mm, RMS 2.15e-13 mm, 7.66e-13 mm per 100 mm; 24 irregular point(s).
- STEP: valid, 1 solid(s), 161 faces, 761 kB
- Game asset (godot): built in 11.4 s, bake 1.9 s, UVs smart, collision 14 hull(s) (Modular_wall_kit_piece_00-convcolonly, Modular_wall_kit_piece_01-convcolonly, …).
- Checks: all PASS
  - LOD0: 5970 / 6000 triangles, cage level 2, decimated to the budget (automatic retopology)
  - LOD1: 2928 / 3000 triangles, cage level 1 (clean quads)
  - LOD2: 732 / 1200 triangles, cage level 0 (clean quads)
  - LOD3: 398 / 400 triangles, cage level 0, decimated to the budget (automatic retopology)
- Aesthetic rubric (heuristic): silhouette 1 (cap 1: Mostly flat faces and no rounds: the views read as a primitive.), proportion 3.0 (cap 4: Bounding ratios are not near a classic ratio: mid:short 6.733.), continuity 2 (cap 2: 100 % of edge length is a sharp crease.), radius_hierarchy 1.0 (cap 1: No blend radii and sharp edges: rounding was dropped. Use craft.safe_fillet with smaller radii; never ship without them.), break_up 2 (cap 2: One feature in one material: no surface break.), detail_rhythm 2.0, material 1 (cap 1: One material over everything: declare appearance() zones (two or three, by function).), would_sell 1.0; mean 1.62
- Looked at (the bench's AI agent, from the renders of the first run (not a person)): The bricks cover only the lower part of the face, so the piece reads unfinished; the slab is a plain box.
- Wall time 23.5 s.

### Vehicle wheel

- Routes: tyre → subd_cage (cage, rounded, smooth); rim → subd_cage (cage, smooth, subdivision); spokes → procedural (array, procedural, repeated); hub → subd_cage (cage, rounded)
- Cage: 382 points, 368 quads, 100 sharp crease edges, regions rim, tyre.
- SubD→CAD: 8 part(s), worst max 0.175 mm, RMS 0.0802 mm, 0.171 mm per 100 mm; 16 irregular point(s).
- STEP: valid, 1 solid(s), 91 faces, 1174 kB
- Game asset (unity): built in 10.3 s, bake 2.2 s, UVs smart, collision 1 hull(s) (Vehicle_wheel_00_collider).
- Checks: all PASS
  - LOD0: 4974 / 5000 triangles, cage level 2, decimated to the budget (automatic retopology)
  - LOD1: 2486 / 2500 triangles, cage level 1, decimated to the budget (automatic retopology)
  - LOD2: 736 / 1000 triangles, cage level 0 (clean quads)
  - LOD3: 298 / 300 triangles, cage level 0, decimated to the budget (automatic retopology)
- Aesthetic rubric (heuristic): silhouette 3.0, proportion 3.0 (cap 4: Bounding ratios are not near a classic ratio: mid:short 4.325.), continuity 3.0 (cap 4: 25 % of edge length is a sharp crease.), radius_hierarchy 1 (cap 1: No blend radii and sharp edges: rounding was dropped. Use craft.safe_fillet with smaller radii; never ship without them.), break_up 2 (cap 2: One feature in one material: no surface break.), detail_rhythm 3.0, material 1 (cap 1: One material over everything: declare appearance() zones (two or three, by function).), would_sell 2.0; mean 2.25
- Looked at (the bench's AI agent, from the renders of the first run (not a person)): The tyre reads; the rim disc and spokes are crude, and LOD1 turns the tyre visibly polygonal.
- Wall time 29.2 s.

### Remote control, CAD plus asset

- Routes: body → subd_cage (rounded); buttons → kernel (hole); battery_cover → kernel (latch)
- STEP: valid, 1 solid(s), 69 faces, 187 kB
- Game asset (gltf): built in 6.4 s, bake 1.4 s, UVs smart, collision 1 hull(s) (Remote_control__CAD_plus_asset_collision_00).
- Checks: normal_map LOD0 FAIL (1.613% of LOD0's UV area points inward (20 triangles))
  - LOD0: 2984 / 3000 triangles, decimated to the budget (automatic retopology)
  - LOD1: 1492 / 1500 triangles, decimated to the budget (automatic retopology)
  - LOD2: 596 / 600 triangles, decimated to the budget (automatic retopology)
  - LOD3: 198 / 200 triangles, decimated to the budget (automatic retopology)
- Aesthetic rubric (heuristic): silhouette 3.0, proportion 3.0 (cap 4: Bounding ratios are not near a classic ratio: long:mid 3.75, mid:short 2.4.), continuity 3 (cap 3: 44 % of edge length is a sharp crease.), radius_hierarchy 4.0, break_up 2.0, detail_rhythm 3.0, material 1.0 (cap 1: One material over everything: declare appearance() zones (two or three, by function).), would_sell 2.0; mean 2.62
- Looked at (the bench's AI agent, from the renders of the first run (not a person)): A tidy CAD body, but at game scale the button holes vanish and the baked normal map has an inverted patch (the normal_map check fails).
- Wall time 10.2 s.

## What failed

Published as they came out: Remote control, CAD plus asset. See each brief above for the measured reason.
